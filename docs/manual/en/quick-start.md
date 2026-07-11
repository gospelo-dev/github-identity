# Quick Start

## Prerequisites

- Python 3.11 or later
- `git` is installed
- [`gh` CLI](https://cli.github.com/) is installed and you have already run `gh auth login --hostname github.com` for every account you plan to use

## Installation

```bash
pip install gospelo-github-identity
```

Verify:

```bash
gospelo-github-identity --version
```

## 1. Create a Config

Create `~/.config/gospelo-github-identity/config.yml` interactively:

```bash
gospelo-github-identity init
```

If you prefer to skip the interactive prompts, you can copy the bundled template and open it in `$EDITOR`:

```bash
# Copy bundled template + open in $EDITOR (default: vi)
gospelo-github-identity init --from-template

# Print bundled template to stdout (for piping)
gospelo-github-identity init --show-example > ~/.config/gospelo-github-identity/config.yml
```

Sample configurations (basic / minimal / advanced) are available under [examples/](https://github.com/gospelo-dev/gospelo-github-identity/tree/main/examples).

Example session:

```
Welcome to gospelo-github-identity init.
Config file will be saved to: /Users/you/.config/gospelo-github-identity/config.yml

Profile name: oss
Description (optional): Personal OSS work
git user.name: your-oss-login
git user.email: you@example.com
gh CLI account login: your-oss-login
Paths (one per line, empty line to finish):
  > ~/projects/gospelo-dev/**
  > ~/projects/personal/**
  >
Add another profile? [y/N]: y

Profile name: work
Description (optional): Company work
git user.name: your-oss-login
git user.email: you@company.com
gh CLI account login: your-work-login
Paths (one per line, empty line to finish):
  > ~/projects/work/**
  >
Add another profile? [y/N]: n
Default profile (one of: oss, work) [leave blank for none]: oss

Saved: /Users/you/.config/gospelo-github-identity/config.yml
```

## 2. Verify

```bash
gospelo-github-identity list
```

A table of registered profiles is printed.

## 3. Compare the Expected Profile Against Reality

Move into an OSS repository:

```bash
cd ~/projects/gospelo-dev/your-repo
gospelo-github-identity check
```

If `OK: identity matches profile 'oss'.` is printed, your current git/gh state matches the resolved profile. Any `NG` row indicates a mismatch.

## 4. Switch in One Shot

```bash
gospelo-github-identity switch oss
```

This applies local `git config user.name` / `user.email` and `gh auth switch -u <account>` together.

Use `--global` to apply across the whole user, or `--dry-run` to preview the actions without making any changes.

## Next Steps

- [Shell Integration](shell-integration.md): show the active profile in your `PS1`
- [CLI Reference](cli-reference.md): full details for every subcommand
- [Config Format](config-format.md): finer points of `paths` glob behavior
