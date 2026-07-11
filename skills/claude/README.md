# Claude Code Skill - gospelo-github-identity-check

Drop-in [Agent Skill](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview)
for Claude Code that auto-verifies your git/gh CLI identity before any write
operation (push, PR, release, package publish).

The actual skill body is in [`skill.md`](skill.md). This README explains
**how to install** the skill into your project or global Claude Code config.

## What it does

Before Claude Code executes any of:

- `git push`, `git push --force`
- `gh pr create`, `gh pr merge`, `gh release create`
- `pip publish`, `npm publish`, `cargo publish`, `docker push`, etc.
- Anything you describe as "publish", "release", "push", "deploy", "merge",
  "公開", "マージ", "デプロイ"

…it runs `gospelo-github-identity check` in the current working directory and:

- Exit `0` (match): proceeds silently
- Exit `1` (mismatch): **stops**, shows the expected profile, the mismatched
  fields, and the `gospelo-github-identity switch <profile>` command to fix it
- Exit `2` (tool error): surfaces the error to you instead of assuming a
  default identity (the project policy is no silent fallback)

## Installation

Prerequisite: install the CLI.

```bash
pip install gospelo-github-identity
gospelo-github-identity init   # create ~/.config/gospelo-github-identity/config.yml
```

Then install the skill into Claude Code.

### Per-project (recommended)

```bash
mkdir -p .claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   .claude/skills/gospelo-github-identity-check/skill.md
```

Commit `.claude/skills/gospelo-github-identity-check/skill.md` so all collaborators on
the project benefit.

### Global (every Claude Code session, every project)

```bash
mkdir -p ~/.claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   ~/.claude/skills/gospelo-github-identity-check/skill.md
```

After installing, restart Claude Code (or run `/skills reload` if your version
supports it).

## Verifying installation

In Claude Code, ask:

> Push my changes to GitHub.

Expected:

- If your identity matches: a normal `git push` runs.
- If your identity is mismatched: Claude Code stops, shows the expected
  profile, the actual mismatched fields, and the
  `gospelo-github-identity switch <profile>` fix command.

## Customising

The body of `skill.md` is plain Markdown with YAML frontmatter. You can:

- Tighten the `keywords` list to your team's vocabulary
- Add project-specific write commands to the "When to invoke" section
- Lower `priority` from `high` to `medium` if it conflicts with other skills

Do **not** modify the exit-code handling table or the "no silent fallback"
behavior — those are core to the protective contract.

## See also

- [`../README.md`](../README.md) — overview of all gospelo-github-identity Agent Skills
- [`skill.md`](skill.md) — the skill itself
- [gospelo-github-identity CLI README](../../README.md)
