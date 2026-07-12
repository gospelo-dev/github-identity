# Quick start

From installation to "verify with `check`, apply with `switch`" in five minutes. Add the enforcement layer (guard / commit-msg hook) afterwards, once you understand the behavior — see [enforcement.md](enforcement.md).

## Prerequisites

- Python 3.11+
- `git` installed
- The [`gh` CLI](https://cli.github.com/) installed and authenticated **for every account you want to switch between**:

```bash
gh auth login --hostname github.com    # once per account
gh auth status                         # list authenticated accounts
```

## Installation

```bash
pip install gospelo-github-identity
```

Verify:

```bash
gospelo-github-identity --version
```

## 1. Create the config

Create `~/.config/gospelo-github-identity/config.yml` interactively:

```bash
gospelo-github-identity init
```

Example session:

```
Welcome to gospelo-github-identity init.
Config file will be saved to: /Users/you/.config/gospelo-github-identity/config.yml

Profile name: oss
Description (optional): Personal OSS work
git user.name: your-oss-login
git user.email: you@example.com
gh CLI account login: your-oss-login
GitHub owners this identity writes to, comma-separated (enables target-aware guard enforcement) (optional): your-oss-login, your-oss-org
Paths (one per line, empty line to finish):
  > ~/projects/oss/**
  >
Add another profile? [y/N]: y

Profile name: work
Description (optional): Company work
git user.name: your-work-name
git user.email: you@company.com
gh CLI account login: your-work-login
GitHub owners this identity writes to, comma-separated (enables target-aware guard enforcement) (optional): your-company-org
Paths (one per line, empty line to finish):
  > ~/projects/work/**
  >
Add another profile? [y/N]: n
Default profile (one of: oss, work) [leave blank for none]:

Saved: /Users/you/.config/gospelo-github-identity/config.yml
```

To skip the interactive prompts:

```bash
# Copy the bundled template and open it in $EDITOR (default: vi)
gospelo-github-identity init --from-template

# Print the bundled template to stdout (for redirecting)
gospelo-github-identity init --show-example > my-config.yml
```

Sample configs (basic / minimal / advanced) live in [examples/](https://github.com/gospelo-dev/github-identity/tree/main/examples); the full schema is in [config-format.md](config-format.md).

## 2. Verify profile resolution

```bash
gospelo-github-identity list      # table of registered profiles
gospelo-github-identity detect    # the profile that governs the current directory
```

If `detect` does not print the profile you expected, revisit the `paths` globs (see [troubleshooting.md](troubleshooting.md#a-path-glob-does-not-match--the-wrong-profile-wins)).

## 3. Compare expected vs. actual

Move into a governed repository:

```bash
cd ~/projects/oss/your-repo
gospelo-github-identity check
```

```
=== Identity Check ===
Working dir: /Users/you/projects/oss/your-repo
Matched profile: oss (via pattern: ~/projects/oss/**)

[git]
  user.name  : your-oss-login  (expected: your-oss-login )  OK
  user.email : you@example.com (expected: you@example.com)  OK
[gh CLI]
  login      : your-work-login (expected: your-oss-login )  NG

WARNING: gh CLI account does not match expected profile.
Run `gospelo-github-identity switch oss` to fix.
```

`OK: identity matches profile 'oss'.` means everything matches; any `NG` row is a mix-up.

## 4. Switch in one shot

```bash
gospelo-github-identity switch oss
```

This sets the local `git config user.name` / `user.email` and runs `gh auth switch -u <account>` in one step. Use `--dry-run` to preview, `--global` to apply user-wide.

Run `check` again afterwards and confirm every row is `OK`.

## 5. Audit the robustness of the setup

Even when everything matches *right now*, fragile setups — git identity that merely inherits the global config, a remote that still uses bare `git@github.com` — are invisible to `check`. Audit them with doctor:

```bash
gospelo-github-identity doctor           # audit the current repository
gospelo-github-identity doctor --sweep   # audit every repo under the profile's paths
```

Resolve any `WARN` / `FAIL` findings as instructed. Details in [cli-reference.md](cli-reference.md#doctor).

## Next steps

- [enforcement.md](enforcement.md) — block mismatched writes before they run (guard), and strip `Co-Authored-By` trailers (commit-msg hook)
- [agents.md](agents.md) — setup for delegating GitHub writes to AI agents such as Claude Code / Copilot
- [shell-integration.md](shell-integration.md) — show the active profile in your prompt at all times
