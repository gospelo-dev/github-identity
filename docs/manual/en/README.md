# gospelo-github-identity Documentation

Documentation index for `gospelo-github-identity`, the directory-aware git/gh CLI identity guard.

## About This Documentation

gospelo-github-identity is a CLI tool that resolves the "expected profile" from your current working directory and verifies that the local `git config` and the active `gh` CLI account match it (switching them when they do not). It prevents account mix-ups for developers who juggle multiple GitHub accounts (personal OSS, employer, client work).

Intended audience:
- **Users**: developers who want to operate multiple accounts safely -> [Quick Start](quick-start.md)
- **Config maintainers**: people defining a standard profile set for a team or organization -> [Config Format](config-format.md)

## Document Index

| File | Purpose |
|---|---|
| [quick-start.md](quick-start.md) | 5-minute setup walkthrough |
| [cli-reference.md](cli-reference.md) | All subcommands, options, and exit codes |
| [config-format.md](config-format.md) | `config.yml` schema details |
| [shell-integration.md](shell-integration.md) | `PS1` / `direnv` / pre-commit integration recipes |

## Design Principles

- **No fallbacks**: any failure (missing config file, no glob match, external tool error) stops with an explicit error. Two deliberate exceptions: `prompt` silently returns an empty string so it never breaks prompt rendering, and the `guard` shim **fails open** (runs the real command, with a one-line stderr notice on writes) when there is no usable config or the directory is governed by no profile — so installing the shim never breaks unrelated git/gh work.
- **Minimal dependencies**: the only PyPI dependency is `PyYAML`. `git` and `gh` are invoked as external CLIs.
- **Directory-driven**: profile selection is anchored on "where you are working". This prevents unintended account leakage.

## Related Projects

- [gospelo-review](https://github.com/gospelo-dev/review) — PR review automation toolkit. Integrates with this tool via `pip install gospelo-review[identity]`.
