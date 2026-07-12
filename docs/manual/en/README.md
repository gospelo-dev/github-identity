# gospelo-github-identity manual

User manual for `gospelo-github-identity`, the directory-aware git/gh CLI identity guard.

## About the tool

Juggling several GitHub accounts (personal OSS / employer / client) on one machine invites a specific accident: **a write to the right repository with the wrong account**. gospelo-github-identity resolves the "expected identity (profile)" from the working directory and verifies, applies, or enforces it against the actual `git config`, `gh` CLI, and SSH authentication.

It operates at three levels:

| Level | Commands | What it does |
|---|---|---|
| Visibility | `prompt` / `detect` / `list` / `check` | Make it visible whether the current identity matches the expectation |
| Robustness audit | `doctor` | Audit whether the setup will *stay* correct (inherited config, unpinned keys, ...) |
| Enforcement | `guard` / `commit-msg` hook | Resolve identity from the write's target and inject the token per invocation; refuse unknown targets before execution (fail-closed) — works even for autonomous agents |

## Reading order

| Document | Contents | When to read |
|---|---|---|
| [quick-start.md](quick-start.md) | Install through first check/switch | You want it running now |
| [concepts.md](concepts.md) | Profiles, resolution rules, the three identity layers | You want to understand the model |
| [cli-reference.md](cli-reference.md) | All 13 subcommands, options, exit codes | You need to look up an option |
| [config-format.md](config-format.md) | `config.yml` schema and glob semantics | You are writing the config |
| [enforcement.md](enforcement.md) | The guard (PATH shims) and the commit-msg hook in depth | You want the enforcement layer |
| [agents.md](agents.md) | AI-agent (Claude Code / Copilot) integration | You delegate writes to an agent |
| [shell-integration.md](shell-integration.md) | PS1 / direnv / pre-commit recipes | You want it in your shell |
| [troubleshooting.md](troubleshooting.md) | Fixes by symptom | Something is broken or blocked |

## Design principles

- **No silent fallbacks** — a missing config, an unmatched glob, or a failing external tool stops with an explicit error. There are exactly two deliberate exceptions: `prompt` silently returns an empty string (so it never breaks a shell), and the `guard` passes commands through in situations it does not govern (no config, or — in the ownerless check mode — an ungoverned directory) — see [enforcement.md](enforcement.md#the-fail-open--fail-closed-boundary).
- **Deterministic** — every decision is pure pattern logic. No LLM is involved anywhere.
- **Local** — the only network traffic is `gh api user` (account verification) and the opt-in `ssh -T` login probe.
- **Minimal dependencies** — the only PyPI dependency is `PyYAML`; `git` and `gh` are invoked as external CLIs.

## Version scope

This manual documents the implementation of gospelo-github-identity **0.2.x**. Version 0.2.0 implemented the enforce-style architecture: target-based resolution, the `gh.owners` reverse map, per-invocation token injection, and fail-closed refusal. For the design background, see the [design document](../../architecture/enforce-fail-closed.md).
