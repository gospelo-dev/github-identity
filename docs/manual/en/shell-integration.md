# Shell Integration Guide

A collection of recipes for wiring `gospelo-github-identity` into your shell and existing development workflow.

## PS1 / Prompt Display

### bash

```bash
PS1='$(gospelo-github-identity prompt --format=ps1 --show-mismatch) \w \$ '
```

With `--show-mismatch`, the prompt turns red and is rendered like `[oss !]` whenever the actual git/gh state does not match the expected profile.

### zsh

Enable `PROMPT_SUBST` and rely on `%F`/`%f` for cleaner colors:

```zsh
setopt PROMPT_SUBST

_identity_prompt() {
  local label
  label=$(gospelo-github-identity prompt --format=plain --show-mismatch)
  if [[ -z "$label" ]]; then
    return
  fi
  if [[ "$label" == *"!"* ]]; then
    print -n "%F{red}${label}%f"
  else
    print -n "%F{yellow}${label}%f"
  fi
}

PROMPT='$(_identity_prompt) %~ %# '
```

### fish

```fish
function fish_right_prompt
  set -l label (gospelo-github-identity prompt --format=plain --show-mismatch)
  if test -n "$label"
    if string match -q "*!*" -- $label
      set_color red
    else
      set_color yellow
    end
    echo -n $label
    set_color normal
  end
end
```

> **Note**: `gospelo-github-identity prompt` silently returns an empty string even when the config is missing, so it never breaks your shell. If you want errors to surface, call `check` separately.

## direnv Integration

To run `check` and warn the moment you enter a repository, add this to `.envrc`:

```bash
# .envrc
gospelo-github-identity check >&2 || echo "WARNING: identity mismatch (see above)" >&2
```

After `direnv allow`, the warning appears automatically every time you `cd` into the directory.

## pre-commit Hook Integration

The simplest way to enforce a check before committing is to write directly to `.git/hooks/pre-commit`:

```bash
#!/usr/bin/env bash
gospelo-github-identity check
status=$?
if [[ $status -ne 0 ]]; then
  echo "" >&2
  echo "Identity check failed. Refusing to commit." >&2
  echo "Run 'gospelo-github-identity switch <profile>' to fix." >&2
  exit 1
fi
```

If you use the `pre-commit` framework, configure it as a `repo: local` hook:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: gospelo-github-identity-check
        name: gospelo-github-identity check
        entry: gospelo-github-identity check
        language: system
        pass_filenames: false
        stages: [commit]
```

## Do Not Use in CI

gospelo-github-identity is meant for **preventing local mix-ups during development**. CI environments are expected to use a fixed bot account for git config / gh CLI, so running `check` there is rarely meaningful. Do not wire it into CI pipelines.

## Troubleshooting

### `gh auth switch` fails

You must have authenticated the target account beforehand with `gh auth login --hostname github.com`. Run `gh auth status` to see the list of accounts that are currently authenticated.

### `git config --local` fails

`switch` defaults to `--local`, so running it outside a git work tree (in a regular directory) returns exit 2. Either pass `--global` or `cd` into a repository before retrying.

### A path glob does not match

Use `detect` to confirm which profile is actually selected:

```bash
gospelo-github-identity detect --cwd ~/projects/oss/foo
```

Make sure your `paths` entries start with `~` and include `**` whenever recursive matching is required.
