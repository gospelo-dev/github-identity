# Config format

## Location

```
~/.config/gospelo-github-identity/config.yml
```

The path is fixed (`$XDG_CONFIG_HOME` is not consulted). To use a different location, set the `GOSPELO_GITHUB_IDENTITY_CONFIG` environment variable (useful for tests or switching between config sets).

Three ways to create it:

```bash
gospelo-github-identity init                  # interactive
gospelo-github-identity init --from-template  # copy the bundled template, open in $EDITOR
gospelo-github-identity init --show-example   # print the bundled template to stdout
```

Three samples live in [examples/](https://github.com/gospelo-dev/github-identity/tree/main/examples): `config.yml` (commented, two profiles), `config.minimal.yml` (single profile), `config.advanced.yml` (multi-client, 3+ profiles).

## Full schema

```yaml
version: "1"

profiles:
  <profile-name>:
    description: <string>       # optional
    git:
      user.name: <string>       # required
      user.email: <string>      # required
    gh:
      account: <string>         # required
      owners:                   # optional; declaring any switches the guard to enforce mode
        - <owner>
    ssh:                        # optional; presence enables the SSH login probe
      login: <string>           # optional; defaults to gh.account
      host: <string>            # optional; defaults to the host derived from origin
    paths:                      # optional (may be empty)
      - <glob>

default_profile: <profile-name> # optional
active_profile: <profile-name>  # optional; manually selected matching profile
```

Keys not in the schema are **silently ignored** rather than rejected — a typo will not error. Verify that the config behaves as intended with `list` / `detect` / `check`.

## Fields

### version (required)

Schema version. Only `"1"` is accepted (string or number).

### profiles (required)

Mapping of profile name → definition. At least one is required. Profile names should use letters, digits, `_`, and `-` (`init` enforces this shape).

#### profiles.\<name\>.description (optional)

Free-text description, shown by `list`.

#### profiles.\<name\>.git.user.name / user.email (required)

The expected git author. `switch` writes these into `git config`; `check` / `doctor` / `guard` verify them.

#### profiles.\<name\>.gh.account (required)

The expected GitHub login. `switch` passes it to `gh auth switch -u <account>`. The account must already be authenticated via `gh auth login --hostname github.com`.

#### profiles.\<name\>.gh.owners (optional)

The GitHub owners (users / orgs) whose repositories this profile's identity writes to. **The linchpin of target-aware enforcement**: declaring any owner switches the [guard](enforcement.md#gh-writes-enforce-mode-owners-declared) to enforce mode — the owner of a write's target (`--repo` / the target repo's remote) is reverse-mapped through these lists and the matching profile's token is injected per invocation. A write targeting an owner no profile declares is refused before execution (fail-closed).

- Matching is case-insensitive, mirroring GitHub login semantics.
- The same owner may not appear in more than one profile (an ambiguous reverse map is rejected with exit 2).
- With no `owners` anywhere, the guard stays in the legacy check mode (backward compatible).

```yaml
gh:
  account: your-oss-login
  owners: [your-oss-login, your-oss-org]
```

#### profiles.\<name\>.ssh (optional)

Declaring an `ssh` block adds an SSH-login row to `check`. It closes a blind spot: even with `git config` and `gh` correct, a stray key in ssh-agent can make `git push` **authenticate as someone else**.

`check` runs `ssh -T` (read-only, connection only) against the SSH host that the repo's `origin` remote resolves to, and compares the `<login>` in GitHub's `Hi <login>!` reply with the expectation.

- `login` (optional) — expected GitHub login. Defaults to `gh.account`; plain `ssh: {}` is usually all you need.
- `host` (optional) — pin the probed host. Defaults to the host derived from origin's URL (alias hosts are used as-is).

Verdicts:

| Situation | Shown as | Effect |
|---|---|---|
| Authenticated login matches | `OK` | — |
| Mismatch | `NG` | `check` exits 1 and prints fix guidance |
| Origin not SSH / host unreachable / no key / no `ssh` binary | `--` | Skipped; never a failure |

Profiles without an `ssh` block behave exactly as before — no SSH probe, no network access.

Note the division of labor: `check`'s ssh probe measures *who you would authenticate as right now*, while `doctor` audits (offline) *whether the key is pinned to the alias*. Use both.

#### profiles.\<name\>.paths (optional)

List of glob patterns for the directories this profile governs. Absolute or `~`-prefixed. May be empty (the profile is then only reachable via `default_profile`).

### default_profile (optional)

Fallback profile for directories that match no profile's `paths`. Must name an existing profile.

**When omitted, unmatched stays unmatched** — there is no automatic fallback. `detect` / `check` / `doctor` exit 1, and the `guard` treats the directory as ungoverned and passes commands through.

### active_profile (optional)

The manually selected profile. When it has a `paths` pattern matching the
current directory, it wins over other matching profiles. `switch <profile>`
updates this value after switching Git and `gh`, allowing accounts that share a
directory tree to be selected explicitly. It must name an existing profile.

## Glob semantics

### Syntax

| Pattern | Meaning |
|---|---|
| `*` | Any run of characters except `/` |
| `?` | One character except `/` |
| `[abc]`, `[a-z]` | Character class |
| `[!abc]` | Negated character class |
| `**` | Any number of path components (including zero) |
| `**/` | Any number of directory levels |
| `~` | Expanded to `$HOME` (leading position only) |

### Examples

```yaml
paths:
  - ~/projects/oss/**             # everything under ~/projects/oss
  - ~/work/client-a               # this exact directory only
  - ~/work/**/forks/**            # ~/work/.../forks/... recursively
```

### Matching rules

1. The cwd is absolutized with `Path.resolve()` (symlinks resolved).
2. Every pattern of every profile is evaluated; all matches become candidates.
3. When `active_profile` is among the matches, it wins.
4. Otherwise, the profile containing the pattern with the **longest literal prefix** wins. The literal prefix is the part of the pattern before its first glob metacharacter (`*` / `?` / `[`).
5. When nothing matches, `default_profile` applies (if set).

Nested-tree example:

```yaml
profiles:
  work:
    paths:
      - ~/projects/work/**            # literal prefix = ~/projects/work/
  fork:
    paths:
      - ~/projects/work/oss-forks/**  # literal prefix = ~/projects/work/oss-forks/
```

For cwd `~/projects/work/oss-forks/some-repo` both match, but `fork` has the longer literal prefix and wins. **Deeper (more specific) paths beat shallower ones.**

## Permissions

- The directory `~/.config/gospelo-github-identity/` is created with mode `0700`
- `config.yml` is set to `0600` after saving (best-effort; failure is not an error)

## Error handling

Commands stop with exit 2 when the config is any of the following (`prompt` prints an empty string instead; the `guard` switches to pass-through):

- File does not exist
- YAML parse failure / empty file / root not a mapping
- `version` is not `"1"`
- `profiles` missing or empty
- A profile's required key (`git.user.name` / `git.user.email` / `gh.account`) missing or blank
- `gh.owners` not a list, an entry blank, or the same owner declared by more than one profile
- `ssh` not a mapping, or `ssh.login` / `ssh.host` blank
- `paths` not a list, or an entry blank
- `default_profile` names a profile that does not exist
