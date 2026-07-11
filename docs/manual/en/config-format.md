# Config Format

## Samples

Three sample configurations are available under [examples/](https://github.com/gospelo-dev/github-identity/tree/main/examples):

- `config.yml` — basic 2-profile setup with comments
- `config.minimal.yml` — minimal example with a single profile
- `config.advanced.yml` — 3+ profile setup for freelancers / multi-client work

You can also retrieve the bundled template from the CLI:

```bash
# Copy bundled template to ~/.config/gospelo-github-identity/config.yml + open in $EDITOR
gospelo-github-identity init --from-template

# Print bundled template to stdout (for piping)
gospelo-github-identity init --show-example > my-config.yml
```

## Location

```
~/.config/gospelo-github-identity/config.yml
```

The `GOSPELO_GITHUB_IDENTITY_CONFIG` environment variable can point to an alternate path (useful for tests or for switching between multiple profile sets).

## Full Schema

```yaml
version: "1"

profiles:
  <profile-name>:
    description: <string>
    git:
      user.name: <string>
      user.email: <string>
    gh:
      account: <string>
    ssh:                   # optional; declaring the block enables the SSH-login check
      login: <string>      # optional; defaults to gh.account
      host: <string>       # optional; defaults to the host derived from the origin remote
    paths:
      - <glob>
      - <glob>

default_profile: <profile-name>   # optional
```

## Fields

### version (required)

Schema version. Currently only `"1"` is accepted (string or numeric form is fine).

### profiles (required)

Mapping of profile name to definition. At least one profile is required.

Profile names should consist only of alphanumerics plus `_` / `-` (the `init` command also enforces this).

#### profiles.\<name\>.description

Free-form description string. May be empty.

#### profiles.\<name\>.git.user.name (required)

Value applied to `git config user.name`.

#### profiles.\<name\>.git.user.email (required)

Value applied to `git config user.email`.

#### profiles.\<name\>.gh.account (required)

GitHub login passed to `gh auth switch -u <account>`. You must have authenticated this account beforehand with `gh auth login --hostname github.com`.

#### profiles.\<name\>.ssh (optional)

Declaring an `ssh` block adds an **SSH-login verification** row to `check`. It closes the blind spot where `git config` and `gh` look correct but `git push` authenticates as a *different* account because `ssh-agent` offers another account's key first (e.g. with `IdentitiesOnly no`).

`check` runs `ssh -T` (a read-only, connect-only probe) against the SSH host that this repo's `origin` remote resolves to, and compares the `<login>` in GitHub's `Hi <login>!` banner against the expected login.

- `login` (optional) — the expected GitHub login. Defaults to `gh.account` (usually the same GitHub identity, so `ssh: {}` alone is enough).
- `host` (optional) — force the host to probe. Defaults to the host derived from the `origin` URL (an SSH-alias host like `github.com-work` is preserved verbatim).

Outcome:

- Authenticated login matches the expected login → `OK`
- Mismatch → `NG` (`check` exits 1 and prints the fix: switch to HTTPS, or pin the key via an `~/.ssh/config` host alias)
- `origin` is not SSH (HTTPS / no remote), or the host is unreachable / no key set up / `ssh` not installed → `--` (skipped, **never a failure**)

> A profile with no `ssh` block behaves exactly as before — no SSH verification and no network access.

#### profiles.\<name\>.paths

List of glob patterns. Use absolute paths or paths starting with `~`. May be empty.

### default_profile (optional)

Fallback profile name used when no profile's `paths` matches the current directory. Must be one of the names defined in `profiles`. When omitted, an unmatched directory causes `detect` / `check` to exit 1.

> **Strict rule**: when `default_profile` is omitted, no implicit fallback is applied. Unless you write it explicitly, a non-match is treated as a non-match.

## Glob Specification

### Syntax

| Pattern | Meaning |
|---|---|
| `*` | Any sequence of characters except `/` |
| `?` | A single character except `/` |
| `[abc]`, `[a-z]` | Character class |
| `[!abc]` | Negated character class |
| `**` | Any number of intermediate directories (zero or more) |
| `**/` | Any depth of directories |
| `~` | Expanded to `$HOME` (only at the start of the path) |

### Examples

```yaml
paths:
  - ~/projects/oss/**             # everything under ~/projects/oss
  - ~/work/client-a               # exact match only
  - ~/work/**/forks/**            # ~/work/.../forks/... recursively
```

### Matching Rules

1. `cwd` is normalized via `Path.resolve()` (symlinks are resolved as well).
2. Each profile's `paths` are evaluated in order, and every match becomes a candidate.
3. **When multiple profiles match, the profile whose pattern has the longest literal prefix wins.** The literal prefix is the length of the pattern from the start up to the first glob metacharacter (`*` / `?` / `[`).
4. If nothing matches and `default_profile` is set, that profile is returned (`MatchResult.via_default = True`).

### Match Example

```yaml
profiles:
  work:
    paths:
      - ~/projects/work/**            # literal prefix = "/Users/you/projects/work/"
  fork:
    paths:
      - ~/projects/work/oss-forks/**  # literal prefix = "/Users/you/projects/work/oss-forks/"
```

When `cwd` is `~/projects/work/oss-forks/some-repo`, both patterns match, but `fork` has the longer literal prefix, so `fork` is selected.

## Permissions

- Directory `~/.config/gospelo-github-identity/` is created with mode `0700`
- File `config.yml` is set to mode `0600` after saving (failure to chmod is not treated as an error)

## Error Handling

The CLI exits with code 2 when the config is in any of the following states:

- File does not exist
- YAML parse failure
- `version` is not `"1"`
- `profiles` is empty or missing
- A required key inside a profile (`git.user.name` / `git.user.email` / `gh.account`) is missing
- `ssh` is not a mapping, or `ssh.login` / `ssh.host` is an empty string
- `default_profile` references a name not present in `profiles`
