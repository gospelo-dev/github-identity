# Troubleshooting

Fixes by symptom. For an overall picture, `gospelo-github-identity doctor` is a good first step.

## `Config file not found` (exit 2)

No config yet — create one with `gospelo-github-identity init`. If you migrated from an old version (when the package was named `gospelo-identity`), your config is still at `~/.config/gospelo-identity/` — copy it to the new path `~/.config/gospelo-github-identity/config.yml`.

## A path glob does not match / the wrong profile wins

Ask `detect` what actually resolves:

```bash
gospelo-github-identity detect --cwd ~/projects/oss/foo
```

Checklist:

- `paths` entries are absolute or `~`-prefixed (`~` expands in the leading position only)
- To match everything under a directory, the glob must end in `**` (`~/projects/oss` matches only that exact directory; `~/projects/oss/**` matches the tree)
- Where several profiles match, the **longest literal prefix** wins ([config-format.md](config-format.md#matching-rules))
- The cwd is compared after symlink resolution — if you enter through a symlink, put the real path in `paths`

## `gh auth switch` fails

The target account was never authenticated:

```bash
gh auth status                            # list authenticated accounts
gh auth login --hostname github.com      # log in as the missing account
```

## switch succeeds but check / guard still say NG

`gh auth switch` only flips the active label in `hosts.yml`; it never re-validates the token. When the keyring holds a stale credential (a token that actually belongs to another account stored under `<account>`'s label), the label is right but the identity is not. check / guard compare **what the token actually is** via `gh api user`, so they catch this. Re-login fixes it:

```bash
gh auth logout --hostname github.com --user <account>
gh auth login  --hostname github.com     # re-authenticate in the browser as <account>
gospelo-github-identity check
```

## `git config --local` fails (exit 2)

`switch` defaults to `--local`, which fails outside a git work tree. `cd` into the repository first, or pass `--global` to apply user-wide.

## The guard blocks a write (identity mismatch)

Working as intended — the identity does not match the profile governing the target repository. Run the command from the block message's `fix:` line, then retry:

```bash
gospelo-github-identity switch <profile>
```

For a deliberate one-off write under a different identity, use the explicit bypass:

```bash
GOSPELO_GITHUB_IDENTITY_SKIP=1 gh release create ...
```

## The guard blocks a write (`no profile declares this owner`)

Enforce-mode fail-closed at work — the write's target owner (the `--repo` value, or the target repo's remote owner) is not declared in any profile's `gh.owners`. If you will keep writing to that owner, add it to the intended profile:

```yaml
gh:
  account: your-login
  owners: [existing-org, new-org]   # <- add it
```

For a deliberate one-off, bypass with `GOSPELO_GITHUB_IDENTITY_SKIP=1`.

## The guard blocks a write (`no resolvable target owner`)

A write with no repo target (`gh gist create`, ...) was run from a directory no profile governs. Move into a governed directory, pass `--repo <owner>/<repo>` to make the target explicit, or set a `default_profile`.

## doctor warns `ambient credential in the environment`

A `GH_TOKEN` / `GITHUB_TOKEN` is parked in your shell environment (a direnv `.envrc` or an export in your shell rc, typically). An ambient token **overrides** the guard's per-invocation injection and authenticates paths that bypass the shim, so fail-closed cannot hold. Retire the direnv injection and remove the export — the guard injects the right token per invocation, so nothing needs to be parked.

## Notices appear in ungoverned directories after installing the guard

`directory not governed by any profile; passing through.` on writes is intentional — it makes a paths typo visible (a directory you *think* is governed silently isn't). Suppress informational lines with `GOSPELO_GITHUB_IDENTITY_QUIET=1`; block notices are shown regardless.

## install-guard refuses, citing broken shims

The `gospelo-github-identity` on PATH is a stale build without the `guard` subcommand. Reinstall the current build, then re-run:

```bash
uv tool install --force gospelo-github-identity
gospelo-github-identity install-guard
```

## The guard is not taking effect (calls bypass the shim)

```bash
command -v gh    # should print the shim path (~/.gospelo-github-identity/bin/gh)
```

- Make sure the shim directory is at the **front** of PATH (`export PATH="$HOME/.gospelo-github-identity/bin:$PATH"`)
- Processes that do not read the shell rc (agents, IDEs) need the PATH set in their launch environment ([agents.md](agents.md#setup))
- Absolute-path calls (`/usr/bin/git push`) never hit the shim — a documented limitation ([enforcement.md](enforcement.md#limitations))

## install-commit-hook is refused (exit 1)

A global `core.hooksPath` is already set to something else. Inspect it, and overwrite with `--force` if that is what you want:

```bash
git config --global core.hooksPath      # inspect the current value
gospelo-github-identity install-commit-hook --force
```

## The commit-msg hook does not fire in some repository

That repository sets its **own** `core.hooksPath` (husky et al.), which overrides the global one, so the dispatcher is never invoked. Wire `gospelo-github-identity strip-coauthors` into that repo's hook setup individually.

## check's `[ssh]` row shows `--`

That is a skip, not a failure. It appears when origin is not an SSH remote (HTTPS / no remote), the host is unreachable, or no `ssh` binary exists. To enable the SSH probe, switch origin to an SSH-alias remote; `doctor` audits the remote's shape.
