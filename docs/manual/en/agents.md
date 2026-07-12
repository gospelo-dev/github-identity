# AI-agent integration

Setup for delegating GitHub writes — `git push`, `gh pr create`, `gh release` — to autonomous agents such as Claude Code or GitHub Copilot.

## Why agents need dedicated protection

Human-oriented identity management collapses at its premises in an agent's execution environment:

- **Agents run in non-interactive shells** — shell hooks like direnv fire when a prompt is drawn, so `.envrc` is never evaluated under an agent's `bash -c ...` ([direnv/direnv#262](https://github.com/direnv/direnv/issues/262)). Design as if "switches automatically on cd" mechanisms are simply not there.
- **cwd and the operation target diverge** — agents run `gh --repo owner/x pr create` and `git -C /path push` from arbitrary places; cwd-based mechanisms never look at the target.
- **No human is watching** — a `[oss !]` marker in the prompt or a WARNING from check means nothing without a reader.
- **The gh active account is machine-global** — someone can run `gh auth switch` in another terminal while the agent works.

The guard answers all four: as a PATH shim it is always on, non-interactive shells included; identity is resolved **from the operation's target** (reverse-mapped through `gh.owners`); and the token is injected per invocation, so the global active account stops mattering. On top of it you layer a **self-check imposed on the agent** (the skill).

## Defense in depth

| Layer | Mechanism | Coverage |
|---|---|---|
| Enforcement (outer) | [guard](enforcement.md#the-guard-path-shims-for-gh--git) — PATH shims verify and block right before a write | Every name-based gh/git call, regardless of agent configuration |
| Self-check (inner) | Agent skill — runs `check` before write operations and aborts on mismatch | Agents that read skills (Claude Code / Copilot) |
| Foundation | [doctor](cli-reference.md#doctor) — audits the setup's robustness up front | Setup time and periodic review |

The guard is the last line of defense; the skill is redundancy that lets the agent notice and stop *before* getting blocked. An agent can ignore the skill — it cannot ignore the guard.

## Setup

A human runs this once; from then on the machine stays in a state agents can operate safely:

```bash
# 1. Create the config (declare profiles / paths / owners — owners enable enforce mode)
gospelo-github-identity init

# 2. Audit the setup (bare github.com remotes, unpinned aliases, missing logins, lingering GH_TOKEN, ...)
gospelo-github-identity doctor --sweep

# 3. Install the guard (shadow gh; add git to also guard git push)
gospelo-github-identity install-guard --tools gh,git
export PATH="$HOME/.gospelo-github-identity/bin:$PATH"   # add to ~/.zshrc / ~/.bashrc

# 4. Verify — the target's identity is selected from any cwd
command -v gh          # the shim path means the guard is active
gospelo-github-identity check
```

Once the guard is in place, direnv-based `GH_TOKEN` injection (`.envrc`) **can be retired** — in fact it should be: an ambient `GH_TOKEN` overrides the guard's injection and authenticates shim-bypass paths (`doctor` flags it as a WARN).

**Confirm the PATH actually reaches the agent.** Launch methods that do not read the shell rc (launchd, IDEs launched directly, ...) need the PATH set in the agent's launch environment instead. The reliable test is to have the agent itself run `command -v gh` and confirm the shim path comes back.

## Installing the agent skill

The skills ship with the repository under [skills/](https://github.com/gospelo-dev/github-identity/tree/main/skills).

### Claude Code

```bash
# Per project (recommended)
mkdir -p .claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   .claude/skills/gospelo-github-identity-check/skill.md

# Global (applies to every project)
mkdir -p ~/.claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   ~/.claude/skills/gospelo-github-identity-check/skill.md
```

Restart Claude Code (or reload skills) after installing.

### GitHub Copilot

Copilot's skill specification is still evolving; follow the current recommended placement in [skills/copilot/README.md](https://github.com/gospelo-dev/github-identity/blob/main/skills/copilot/README.md). The body of `copilot/skill.md` is agent-agnostic Markdown, so it also works as a system-prompt fragment for other agents.

### What the skill does

The skill instructs the agent to run `gospelo-github-identity check` **before** write operations (git push, PR creation, releases, package publishing):

| check exit code | Action the skill prescribes |
|---|---|
| `0` (match) | Continue silently (zero friction) |
| `1` (mismatch) | **Abort the write**, show the diff and the `switch <profile>` fix, wait for the user's decision |
| `2` (tool error) | Surface the error verbatim; never fall back to a default identity |

## Operational notes

- `GOSPELO_GITHUB_IDENTITY_SKIP=1` is the guard's explicit bypass. **Never bake it into an agent's system prompt or automation scripts** — that would nullify the guard. It is a one-shot escape hatch for a deliberate human decision.
- The guard's block message includes the fix (`switch <profile>`). An agent may run it and retry — that is fine, because it is the correct recovery: what was blocked was "writing under the wrong identity", and the post-switch write happens under the right one.
- Run `doctor --sweep` periodically (or during human review) to catch configuration gaps early when repositories are added.
