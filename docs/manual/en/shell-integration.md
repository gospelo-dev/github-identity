# Shell integration guide

Recipes for wiring `gospelo-github-identity` into your interactive shell. For the agent-facing enforcement layer, see [enforcement.md](enforcement.md) / [agents.md](agents.md).

## Keep the profile visible in your prompt

The `prompt` subcommand prints the matched profile name as `[name]`. With `--show-mismatch` it appends a warning marker — `[oss !]` — whenever the live state does not match the profile. On no match or missing config it silently prints nothing, so your prompt never breaks.

### bash

```bash
PS1='$(gospelo-github-identity prompt --format=ps1 --show-mismatch) \w \$ '
```

`--format=ps1` wraps the ANSI colors in readline non-printing markers `\[ \]`, so line wrapping stays correct.

### zsh

Enable `PROMPT_SUBST` and color with zsh's own `%F`/`%f`:

```zsh
setopt PROMPT_SUBST

_identity_prompt() {
  local label
  label=$(gospelo-github-identity prompt --format=plain --show-mismatch)
  [[ -z "$label" ]] && return
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

> `prompt` always exits 0 and never prints errors. When you want to see the error, run `check` directly.

## direnv

To see the comparison the moment you enter a repository, in `.envrc`:

```bash
# .envrc
gospelo-github-identity check >&2 || echo "WARNING: identity mismatch (see above)" >&2
```

After `direnv allow`, it prints automatically on every `cd`.

> **Note**: direnv runs from an interactive-shell hook, so it never fires under an AI agent's non-interactive `bash -c ...`. For agents, use the [guard](enforcement.md), not direnv.

## pre-commit

The simplest way to force a check before committing is `.git/hooks/pre-commit`:

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

With the [pre-commit](https://pre-commit.com/) framework, use `repo: local`:

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

> Stripping `Co-Authored-By` trailers is the job of the dedicated [commit-msg hook](enforcement.md#the-commit-msg-hook-stripping-co-authored-by), not pre-commit — it sees the final message on every commit path.

## Do not use in CI

gospelo-github-identity exists to prevent mix-ups **on local development machines**. CI runs under a fixed bot account, so a directory-derived comparison is normally meaningless there. Keep it out of CI scripts.
