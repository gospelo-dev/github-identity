# CLI reference

Specification of all 13 subcommands. For how the enforcement layer works (guard / commit-msg hook), see [enforcement.md](enforcement.md).

## Shared conventions

- **stdout**: the command's primary output (tables / profile names / prompt strings)
- **stderr**: progress, warnings, errors
- **Exit codes**:

| Code | Meaning |
|---|---|
| `0` | Success / match |
| `1` | Expected condition not met (mismatch, no matching profile, blocked write — anticipated failures) |
| `2` | Tool error (missing config, malformed YAML, external tool failure, ...) |

The exceptions are `prompt` (always exit 0, so it never breaks a shell) and `strip-coauthors` (always exit 0, so it never blocks a commit).

```
gospelo-github-identity --help        # list subcommands
gospelo-github-identity --version     # print version
```

### Environment variables

| Variable | Effect |
|---|---|
| `GOSPELO_GITHUB_IDENTITY_CONFIG` | Override the config file path (default: `~/.config/gospelo-github-identity/config.yml`) |
| `GOSPELO_GITHUB_IDENTITY_SKIP` | `1` bypasses the guard gate once (guard only) |
| `GOSPELO_GITHUB_IDENTITY_QUIET` | `1` suppresses the guard's informational status lines (block notices are never suppressed) |

---

## init

```
gospelo-github-identity init [--force] [--from-template] [--show-example]
```

Creates `~/.config/gospelo-github-identity/config.yml`. Without options it prompts interactively for profiles. When the file already exists you are asked before overwriting (`--force` skips the prompt).

- `--from-template` — copies the bundled template to the config path and opens it in `$EDITOR` (default `vi`). Replace the placeholders (`<your-name>` etc.) with real values afterwards.
- `--show-example` — prints the bundled template to stdout. Redirect with `> my-config.yml` to write it anywhere. Always exit 0.

`--from-template` and `--show-example` cannot be combined (exit 2).

| Exit code | Meaning |
|---|---|
| 0 | Saved / declined overwrite leaving the file intact / `--show-example` succeeded |
| 1 | Aborted (Ctrl-C / EOF / overwrite declined) or no profile entered |
| 2 | I/O error, missing template, combined options, `$EDITOR` binary not found |

---

## list

```
gospelo-github-identity list
```

Prints the registered profiles as a table.

| Exit code | Meaning |
|---|---|
| 0 | Printed one or more profiles |
| 1 | No profiles |
| 2 | Missing / invalid config |

---

## detect

```
gospelo-github-identity detect [--cwd PATH]
```

Prints the name of the profile that governs the current directory (or `--cwd`) on a single line. Use it when a script needs just the profile name.

| Exit code | Meaning |
|---|---|
| 0 | Profile resolved |
| 1 | No match and no `default_profile` |
| 2 | Missing / invalid config |

---

## check

```
gospelo-github-identity check [--cwd PATH]
```

Compares the expected profile against the actual state and prints a table. What is compared:

- `[git]` — `user.name` / `user.email` from the local `git config`
- `[gh CLI]` — the account the active token actually belongs to (verified via `gh api user`, so a stale `hosts.yml` label cannot fool it)
- `[ssh]` — only when the profile declares an `ssh` block. Probes which login `ssh -T` authenticates as against the repo's `origin` host. A `--` row means skipped (origin not SSH / host unreachable) and never fails the run

See [quick-start.md](quick-start.md#3-compare-expected-vs-actual) for sample output and [config-format.md](config-format.md#profilesnamessh-optional) for the ssh probe details.

| Exit code | Meaning |
|---|---|
| 0 | Everything matches |
| 1 | One or more mismatches, or no profile resolved |
| 2 | Missing / invalid config, external tool failure |

---

## doctor

```
gospelo-github-identity doctor [--cwd PATH] [--sweep]
```

Where `check` verifies "correct right now", `doctor` audits "wired to stay correct". It works from configuration alone — fast and offline (no `ssh -T` network probe).

**[machine] machine-level findings:**

| Verdict | Condition |
|---|---|
| OK | Global git identity unset (identity is left to each repo) |
| INFO | Global git identity set (repos without a local override inherit it) |
| OK / WARN | Whether the expected gh account is logged in (when it is not, neither switch nor the guard's token injection can act as it) |
| OK / WARN | Whether `GH_TOKEN` / `GITHUB_TOKEN` linger in the environment (an ambient token overrides the guard's injection and authenticates shim-bypass paths) |
| OK / INFO / WARN | The guard's mode: this profile declares `gh.owners` (OK) / no profile declares owners, legacy check mode (INFO) / other profiles declare owners but this one was left behind (WARN) |

**[repo] per-repository findings:**

| Verdict | Condition |
|---|---|
| FAIL | git identity unset (commits would fail) / effective values wrong |
| WARN | Effective values correct but only inherited from global, not pinned locally (a global change breaks it silently) |
| OK | git identity pinned locally |
| WARN | No `origin` remote / origin not SSH / bare `github.com` (depends on ssh-agent key order) |
| WARN | SSH alias pins no `IdentityFile` / `IdentitiesOnly` is no |
| FAIL | The alias's key file does not exist |
| OK | Alias pinned to one key (`IdentitiesOnly yes`) |

With `--sweep`, doctor walks the matched profile's `paths` and audits **every git repository governed by that profile** in one pass (skipping `node_modules` / `.venv` / hidden directories; repos governed by a different profile are excluded).

| Exit code | Meaning |
|---|---|
| 0 | Everything OK (INFO counts as OK) |
| 1 | One or more WARN / FAIL findings, or no profile resolved |
| 2 | Missing / invalid config, external tool failure |

---

## switch

```
gospelo-github-identity switch <profile> [--global] [--dry-run] [--cwd PATH]
```

Applies the named profile's identity in one shot:

1. Sets `git config user.name` / `user.email` (local by default; `--global` for user-wide)
2. Runs `gh auth switch -u <account>`, then verifies at the token level that the active identity really is that account (reports NG when the keyring credential is stale)

`--dry-run` prints the planned changes without side effects. With the default `--local`, running outside a git work tree stops with exit 2.

| Exit code | Meaning |
|---|---|
| 0 | Both git config and gh switch succeeded |
| 1 | Partial success (one of the two failed) |
| 2 | Unknown profile, both failed, or external tool missing |

---

## prompt

```
gospelo-github-identity prompt [--format {plain,color,ps1}] [--show-mismatch] [--cwd PATH]
```

Shell-prompt helper. Prints the matched profile name as `[name]`. Prints an empty string silently when nothing matches or the config is missing. **Always exit 0.**

- `--format plain` (default) — `[oss]`
- `--format color` — with ANSI escapes (yellow normally, red on mismatch)
- `--format ps1` — the color output wrapped in readline non-printing markers `\[ \]` for bash `PS1`
- `--show-mismatch` — appends `!` (as in `[oss !]`) when the live git/gh state does not match the profile

Integration recipes: [shell-integration.md](shell-integration.md).

---

## guard / install-guard / uninstall-guard

```
gospelo-github-identity install-guard [--dir DIR] [--tools gh,git]
gospelo-github-identity uninstall-guard [--dir DIR] [--tools gh,git]
gospelo-github-identity guard --tool {gh,git} --real <path> -- <args...>
```

Shadows `gh` (and opt-in `git`) with PATH shims that enforce identity resolved from the **target of the operation** (`--repo` / `git -C` / the target repo's remote). With `gh.owners` declared, the target owner is reverse-mapped to a profile and that profile's token is injected per invocation (enforce mode); writes to undeclared owners are refused before execution (fail-closed). Without owners, the guard stays in the legacy check mode comparing against the cwd's profile. `guard` is the runtime gate the shims invoke; you normally never run it by hand.

- `install-guard --dir` — shim directory (default: `~/.gospelo-github-identity/bin`)
- `install-guard --tools` — what to shadow (default: `gh` only; use `--tools gh,git` to also guard `git push`)

After installing, add the shim directory to the **front** of `PATH`. Mechanics, write classification, the fail-open/fail-closed boundary, and environment variables are documented in [enforcement.md](enforcement.md).

| Exit code (install-guard) | Meaning |
|---|---|
| 0 | Installed one or more shims |
| 1 | Nothing installed (tool not on PATH / resolved command does not support `guard`) |

---

## install-commit-hook / uninstall-commit-hook / strip-coauthors

```
gospelo-github-identity install-commit-hook [--dir DIR] [--force]
gospelo-github-identity uninstall-commit-hook [--dir DIR]
gospelo-github-identity strip-coauthors <commit-msg-file>
```

A global `commit-msg` hook that strips `Co-authored-by:` trailers from every commit message. `strip-coauthors` is the worker the hook invokes; you normally never run it by hand (always exit 0 — its own I/O errors never block a commit).

- `install-commit-hook --dir` — hooks directory (default: `~/.gospelo-github-identity/git-hooks`)
- `install-commit-hook --force` — overwrite a pre-existing global `core.hooksPath` that points elsewhere

The dispatcher **chains** to each repository's own `.git/hooks/<name>` after processing, so existing hooks (husky, pre-commit, ...) keep working. Details in [enforcement.md](enforcement.md#the-commit-msg-hook-stripping-co-authored-by).

| Exit code (install-commit-hook) | Meaning |
|---|---|
| 0 | Installed |
| 1 | A different global `core.hooksPath` already set (re-run with `--force`) |
| 2 | Failed to set `core.hooksPath` |
