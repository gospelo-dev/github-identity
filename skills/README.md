# gospelo-github-identity Agent Skills

Auto-protective skills for AI coding agents (Claude Code, GitHub Copilot, etc.).

## What this does

When you ask your AI coding agent to push code, create a PR, publish a package,
or do any "write to remote" operation, this skill automatically runs
`gospelo-github-identity check` in the current working directory and verifies that the
local `git config` and active `gh` CLI account match the expected profile (per
`~/.config/gospelo-github-identity/config.yml`).

If there is a mismatch (for example, you are about to push from your work
account while inside a personal OSS repo), the skill **stops the operation**
and shows the agent exactly which fields differ and which command will fix it.

The skill is designed to be silent on success and loud on mismatch — it should
add zero friction when your identity is already correct.

## Available skills

| Agent | Skill file | Installation target |
|---|---|---|
| Claude Code | [`claude/skill.md`](claude/skill.md) | `.claude/skills/gospelo-github-identity-check/skill.md` (project) or `~/.claude/skills/gospelo-github-identity-check/skill.md` (global) |
| GitHub Copilot | [`copilot/skill.md`](copilot/skill.md) | See `copilot/README.md` (Copilot skill spec is still evolving) |

Both skill files are intentionally similar in body. Only the frontmatter
(metadata, trigger format) differs per agent.

## Manual installation

### Claude Code

```bash
# Per-project (recommended)
mkdir -p .claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   .claude/skills/gospelo-github-identity-check/skill.md

# Global (applies to every project Claude Code opens)
mkdir -p ~/.claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   ~/.claude/skills/gospelo-github-identity-check/skill.md
```

After installing, restart Claude Code (or run `/skills reload` if available)
so the new skill is picked up.

### GitHub Copilot

The Copilot Workspace / Copilot Chat skill specification is still evolving
(as of 2026-04). See [`copilot/README.md`](copilot/README.md) for the current
recommended placement. The body of `copilot/skill.md` is agent-agnostic
Markdown, so it can also be used as a system prompt fragment for other agents.

## Prerequisites

- `gospelo-github-identity` CLI installed and on `PATH`:
  ```bash
  pip install gospelo-github-identity
  ```
- A configured `~/.config/gospelo-github-identity/config.yml` (see project root
  README for examples; or run `gospelo-github-identity init`)
- An AI coding agent that supports Agent Skills:
  - Claude Code 1.x or later
  - GitHub Copilot (Workspace / Chat with skills support)

## Verifying the skill is active

Ask your agent something like:

> Push my changes to GitHub.

Expected behavior:

- **Identity matches**: the agent runs `gospelo-github-identity check`, sees exit
  code `0`, and proceeds with `git push` without further prompting.
- **Identity mismatched**: the agent runs `gospelo-github-identity check`, sees exit
  code `1`, **stops** before `git push`, and displays the expected profile,
  the mismatched fields, and the `gospelo-github-identity switch <profile>` command
  to fix it.
- **No config / tool error**: the agent surfaces the exit-code-`2` error
  message directly to you and asks how to proceed.

## Skill behavior at a glance

| Pre-check exit code | Skill action |
|---|---|
| `0` (match) | Continue silently with the planned write operation |
| `1` (mismatch) | Block the write operation, display fix command, wait for user override |
| `2` (tool error) | Surface the error to the user; do not assume default identity |

Per project policy, the skill **never** falls back to a default identity when
config is missing or unreadable — it must surface the error.

## Related

- [gospelo-github-identity CLI README](../README.md)
- [Shell integration guide](../docs/manual/ja/shell-integration.md)
