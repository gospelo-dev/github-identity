# GitHub Copilot Skill - gospelo-github-identity-check

Agent Skill for [GitHub Copilot](https://github.com/features/copilot) that
auto-verifies your git/gh CLI identity before any write operation (push, PR,
release, package publish).

The actual skill body is in [`skill.md`](skill.md). This README explains
**how to install** the skill into Copilot.

> Note: this directory was previously named `github/` and was scoped to a
> GitHub Action wrapper. As of the Agent Skills rework it is now scoped to
> **GitHub Copilot** (the AI coding agent). The CI / Action use case is no
> longer the primary target — gospelo-github-identity is fundamentally about
> preventing **interactive** local mistakes.

## What it does

Identical behavior to the [Claude Code skill](../claude/README.md). Before
Copilot executes any of:

- `git push`, `git push --force`
- `gh pr create`, `gh pr merge`, `gh release create`
- `pip publish`, `npm publish`, `cargo publish`, `docker push`, etc.
- Anything you describe as "publish", "release", "push", "deploy", "merge",
  "公開", "マージ", "デプロイ"

…it runs `gospelo-github-identity check` in the current working directory and stops
on mismatch (exit `1`) or tool error (exit `2`). See [`skill.md`](skill.md)
for the full contract.

## Installation

Prerequisite: install the CLI.

```bash
pip install gospelo-github-identity
gospelo-github-identity init   # create ~/.config/gospelo-github-identity/config.yml
```

Then install the skill into Copilot. Placement depends on the Copilot variant.

### GitHub Copilot Workspace

The Copilot Workspace skill specification is still evolving (as of 2026-04).
The current best practice is to place skill files under a project-level
`.github/copilot/skills/` directory:

```bash
mkdir -p .github/copilot/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/copilot/skill.md \
   .github/copilot/skills/gospelo-github-identity-check/skill.md
```

> TODO: spec uncertain. Confirm the exact path and frontmatter schema against
> the latest Copilot Workspace release notes before relying on this in
> production. See `skill.md` `trigger:` block for the assumed schema.

### GitHub Copilot Chat (custom instructions)

If your Copilot variant supports only freeform custom instructions (no formal
skills system), paste the body of [`skill.md`](skill.md) (everything **after**
the YAML frontmatter) into your workspace or repository custom instructions.

## Known limitations

- The Copilot skill frontmatter (`trigger`, `priority`, `agent`) is a
  best-effort match for the documented hook points. It may need adjustment as
  Copilot's skill system stabilises.
- Copilot does not (yet) expose a uniform "pre-tool-use" hook the way Claude
  Code skills do. The `keywords` list in the frontmatter is the most reliable
  trigger today.
- Unlike Claude Code, Copilot may not surface the `gospelo-github-identity check`
  command output verbatim. The skill body explicitly tells the agent to relay
  the exit code and stderr.

## Verifying installation

In Copilot Chat, ask:

> Push my changes to GitHub.

Expected:

- If your identity matches: a normal `git push` runs.
- If your identity is mismatched: Copilot stops, shows the expected profile,
  the actual mismatched fields, and the `gospelo-github-identity switch <profile>`
  fix command.

## See also

- [`../README.md`](../README.md) — overview of all gospelo-github-identity Agent Skills
- [`skill.md`](skill.md) — the skill itself
- [`../claude/README.md`](../claude/README.md) — Claude Code variant of the same skill
- [gospelo-github-identity CLI README](../../README.md)
