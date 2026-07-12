# The enforce + fail-closed architecture

[日本語版](enforce-fail-closed_ja.md)

> **Status: implemented (v0.2.0)** — this document records the background and reasoning behind promoting the guard from "check mode" to "enforce mode". For the precise reference of the implemented behavior, see [docs/manual/en/enforcement.md](../manual/en/enforcement.md). The scope boundary — identity only, no general-purpose command firewall — is maintained.
>
> Account names (`your-oss-login` / `your-work-login`) and org names (`your-company-org`) in the examples are placeholders.

## 1. Background — two structural defects of relying on direnv

Up to v0.1.x, the standard recipe delegated automatic `gh` account switching to direnv (injecting `GH_TOKEN` from `.envrc`). That approach has two structural defects, both confirmed by primary sources:

1. **It does not fire in non-interactive shells.** direnv runs from a prompt-time shell hook, so `.envrc` is never evaluated under an autonomous agent's `bash -c ...` (no rc files read) ([direnv/direnv#262](https://github.com/direnv/direnv/issues/262), [direnv man](https://direnv.net/man/direnv.1.html)).
2. **It is cwd-based, not target-based.** Operate on a different repo via `gh --repo <owner>/<repo>` or `git -C <path>` and both direnv and a check-mode guard apply the *cwd's* identity.

Moreover, gh itself explicitly scopes out "automatic account switching based on pwd / git remote" ([cli/cli multiple-accounts.md](https://github.com/cli/cli/blob/trunk/docs/multiple-accounts.md)); the active account is one piece of machine-global state. gospelo-github-identity fills this gap.

### The three identity layers

| Layer | Where identity is bound | Behavior when cwd diverges |
|---|---|---|
| ① git author | target repo's local `git config` | ✅ safe (`git -C X` reads X's config — [git docs](https://git-scm.com/docs/git)) |
| ② SSH push auth | host alias in the target repo's remote URL + `IdentitiesOnly` | ✅ safe (key selection reads only the remote URL) |
| ③ gh account | **environment-global** (`GH_TOKEN` env / active account — [gh env manual](https://cli.github.com/manual/gh_help_environment)) | ❌ **the hole** — a write to the right repo with the wrong account |

The goal of this design: bring **③ into the same "identity bound to the target" structure as ① and ②**.

### The pre-0.2.0 hole (cwd-based + direnv-dependent)

```mermaid
flowchart TB
    Agent["fa:fa-robot Autonomous agent<br/>bash -c (non-interactive shell)"]
    Cmd["fa:fa-terminal gh --repo your-company-org/x pr create<br/>cwd = ~/projects/oss/y"]
    subgraph Old["Legacy decision layer (cwd-based)"]
        Direnv["fa:fa-rotate direnv hook<br/>fires only when a prompt is drawn"]
        GuardOld["fa:fa-shield-halved guard (check mode)<br/>compares the cwd's profile — never sees your-company-org/x"]
    end
    GhGlobal["fa:fa-user Global active account<br/>(one per machine)"]
    API["fa:fa-cloud GitHub<br/>fa:fa-triangle-exclamation write to the right repo, wrong account"]

    Agent --> Cmd
    Cmd --> GuardOld
    Direnv -.->|never fires in non-interactive shells| Cmd
    GuardOld --> GhGlobal
    GhGlobal --> API

    classDef node fill:#FFFFFF,stroke:#666666,stroke-width:1.5px,color:#2C2C2C
    class Agent,Cmd,Direnv,GuardOld,GhGlobal,API node
    style Old fill:#F8FAFC,stroke:#94A3B8,color:#2C2C2C

    %% normal flow = solid teal / dormant & non-destructive = dashed grey
    linkStyle 0,1,3,4 stroke:#0D9488,stroke-width:2px
    linkStyle 2 stroke:#9CA3AF,stroke-width:1.5px,stroke-dasharray:4 4
```

## 2. Design principles

1. **target-aware** — identity derives from the **target of the operation** (`--repo` / `git -C` / the target repo's remote), not the cwd.
2. **non-ambient** — no credentials parked in environment variables. Tokens are materialized per invocation and exist only in that single process's environment, for a moment.
3. **fail-closed** — an unresolvable target, an unmappable profile, or a bypassed shim all degrade to "no credentials / refuse to run", never to "succeed under the wrong identity".

Principle 3 is the keystone: a PATH shim can be bypassed (absolute-path execution, direct API calls), but **if no credentials exist on the far side of the bypass**, the bypass falls into "a safe failure" instead of "a success under the wrong account". Instead of chasing exhaustive interception, remove the credentials from the paths that skip inspection.

## 3. Architecture overview

The guard is promoted from "inspect and warn" (check mode) to "inject identity" (enforce mode); direnv becomes retirable (the prompt-hook dependency disappears).

```mermaid
flowchart TB
    Agent["fa:fa-robot Caller<br/>(human / autonomous agent / CI)"]
    subgraph Shim["gospelo-github-identity guard — enforcing PATH shim"]
        Resolve["fa:fa-magnifying-glass Resolve target<br/>--repo / git -C / target remote"]
        Map["fa:fa-sitemap owner → profile lookup"]
        Inject["fa:fa-key Inject token<br/>materialize GH_TOKEN per invocation"]
        Deny["fa:fa-ban fail-closed<br/>unresolvable / unknown profile: refuse to run"]
    end
    Config[("fa:fa-database config.yml<br/>profiles + owners + paths")]
    Store[("fa:fa-lock Credential store<br/>gh keyring")]
    Real["fa:fa-terminal Real gh / git"]
    API["fa:fa-cloud GitHub"]

    Agent --> Resolve
    Resolve --> Map
    Map --> Inject
    Inject --> Real
    Real --> API
    Resolve -->|unresolvable| Deny
    Map -->|unknown profile| Deny
    Config -.->|read| Map
    Store -.->|read| Inject

    classDef node fill:#FFFFFF,stroke:#666666,stroke-width:1.5px,color:#2C2C2C
    class Agent,Resolve,Map,Inject,Deny,Config,Store,Real,API node
    style Shim fill:#F0FDFA,stroke:#0D9488,color:#2C2C2C

    %% normal flow = solid teal / reads = dashed grey
    linkStyle 0,1,2,3,4,5,6 stroke:#0D9488,stroke-width:2px
    linkStyle 7,8 stroke:#9CA3AF,stroke-width:1.5px,stroke-dasharray:4 4
```

## 4. Data flows

### 4.1 A gh write on the happy path (target-aware injection)

How `gh --repo your-company-org/x pr create` runs under the right identity even from an unrelated cwd:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'actorBkg': '#FFFFFF', 'actorBorder': '#666666', 'actorTextColor': '#2C2C2C', 'signalColor': '#0D9488', 'signalTextColor': '#2C2C2C', 'noteBkgColor': '#F0FDFA', 'noteBorderColor': '#0D9488', 'noteTextColor': '#2C2C2C', 'activationBkgColor': '#F8FAFC', 'activationBorderColor': '#94A3B8', 'loopTextColor': '#2C2C2C', 'labelBoxBkgColor': '#F0FDFA', 'labelBoxBorderColor': '#0D9488', 'labelTextColor': '#2C2C2C'}}}%%
sequenceDiagram
    participant A as Caller
    participant S as guard shim (gh)
    participant C as config.yml
    participant K as Credential store
    participant G as Real gh
    participant H as GitHub API

    A->>S: gh --repo your-company-org/x pr create
    S->>S: Resolve target: your-company-org/x<br/>(--repo > git -C > cwd remote)
    S->>C: Reverse-map owner "your-company-org"
    C-->>S: profile "work" / account your-work-login
    S->>K: Fetch token<br/>(gh auth token --user your-work-login)
    K-->>S: token (this invocation only)
    S->>G: exec with GH_TOKEN injected
    G->>H: Create PR (correct identity)
    H-->>G: 201 Created
    Note over S: An undeclared owner / unresolvable target<br/>exits 1 without exec (fail-closed)
```

### 4.2 A bypassed shim (fail-closed)

Even when the shim is bypassed — absolute-path execution, a direct call from a script — no credentials exist in the environment, so "success under the wrong identity" is unreachable:

```mermaid
flowchart LR
    Bypass["fa:fa-terminal Shim-bypassing call<br/>/opt/homebrew/bin/gh ..."]
    RealGh["fa:fa-terminal Real gh"]
    Env["fa:fa-circle-xmark No GH_TOKEN in the environment<br/>(direnv retired)"]
    Auth["fa:fa-circle-xmark doctor audits lingering env tokens"]
    Fail["fa:fa-circle-check Fails safely with an auth error<br/>never reaches the wrong identity"]

    Bypass --> RealGh
    RealGh --> Fail
    Env -.-> RealGh
    Auth -.-> RealGh

    classDef node fill:#FFFFFF,stroke:#666666,stroke-width:1.5px,color:#2C2C2C
    class Bypass,RealGh,Env,Auth,Fail node

    %% normal flow = solid teal / preconditions (non-destructive) = dashed grey
    linkStyle 0,1 stroke:#0D9488,stroke-width:2px
    linkStyle 2,3 stroke:#9CA3AF,stroke-width:1.5px,stroke-dasharray:4 4
```

## 5. Hole inventory — check mode vs. enforce mode

| Path | Check mode (with direnv, ~v0.1.x) | Enforce mode (v0.2.0+) |
|---|---|---|
| `gh` write from a non-interactive shell | ❌ direnv never fires; passes | ✅ the shim always enforces on PATH-based calls |
| cwd divergence (`gh --repo X` / `git -C X`) | ❌ judged by the cwd | ✅ resolved from the target |
| Operation from an ungoverned cwd | ❌ no profile, no guard | ✅ enforced when the target is governed; refused when unknown |
| Shim bypass via absolute path | ❌ goes through under the global account | ⭕ no credentials — auth error (fails safe) |
| Operations with no inferable target (`gh gist create`, `gh api /user`, ...) | — | ✅ falls back to the cwd's profile; refused when ungoverned |
| A process reading the credential store directly | — | ⚠️ residual risk — the territory of OS sandboxes / dedicated users (out of scope) |

Layers ① (git author) and ② (SSH keys) were already target-local; this design leaves them unchanged.

## 6. Components

| Component | Role |
|---|---|
| `guard.py` | Target resolution (`--repo` / `-C` / target remote) + owner→profile lookup + token injection + fail-closed |
| `config.py` | The `owners:` list under a profile's `gh:` (the owner→profile reverse map) |
| `doctor.py` | Fail-closed hygiene checks: no `GH_TOKEN` / `GITHUB_TOKEN` parked in the environment |
| direnv (`.envrc`) | Retired (removed from the recommended setup) |
| `switch` | Unchanged (still the one-shot manual application command) |

### 6.1 Config (the owners map)

```yaml
profiles:
  oss:
    git:
      user.name: your-oss-login
      user.email: you@example.com
    gh:
      account: your-oss-login
      owners: [your-oss-org, your-oss-login]   # writes to these owners use this identity
    paths:
      - ~/projects/oss/**
```

Target resolution order: the `--repo owner/name` argument → the remote of the repo given to `git -C <path>` → the cwd's remote. An owner found in no profile's `owners` is **not executed** (fail-closed).

### 6.2 Materializing the token

`gh auth token --user <account>` extracts the mapped profile's token, injected as `GH_TOKEN` into the real gh's execution environment only ([the mechanism gh's own docs](https://github.com/cli/cli/blob/trunk/docs/multiple-accounts.md) point automated switching solutions at). `GH_TOKEN` outranks stored credentials, so the invocation runs under the right identity regardless of the global active account.

### 6.3 Removing ambient credentials (what makes fail-closed hold)

- Keep no `GH_TOKEN` / `GITHUB_TOKEN` parked in the shell environment (achieved automatically by retiring direnv)
- This establishes "paths that skip the shim find no credentials"
- `doctor` audits the discipline (a lingering env token is a WARN)

### 6.4 Policy for operations with no inferable target

Operations without a repo target (`gh gist create`, `gh api /user`, ...) cannot be reverse-mapped by owner. The default falls back to the cwd's profile; when the cwd is ungoverned too, the write is refused (`GOSPELO_GITHUB_IDENTITY_SKIP=1` remains the explicit bypass).

## 7. Migration path

1. **Phase A — target-aware check**: move the guard's criterion from cwd to the target (non-breaking precision fix)
2. **Phase B — token injection**: check mode → enforce mode; the right identity gets selected without direnv
3. **Phase C — ambient removal**: retire direnv + `doctor`'s fail-closed diagnostics

Phases A/B are backward compatible (the guard stays in check mode until `gh.owners` is declared). Fail-closed holds once Phase C completes.

## 8. Residual risks and limits (an honest line)

- **Direct access to the credential store** cannot be prevented. Defense against adversarial processes is the job of OS sandboxing; this design protects against **accidental** wrong identity.
- HTTPS git authentication through gh's credential helper presumes global auth, so the design holds together with an **SSH push workflow** (aliased remotes + `IdentitiesOnly`).
- `gh auth token --user` presumes the account is logged into the keyring. Missing logins are caught by `doctor`, and the guard refuses writes it cannot inject.
- Logged-in keyring accounts themselves remain (gh always marks one of them active), so doctor's ambient audit is limited to environment variables (`GH_TOKEN` / `GITHUB_TOKEN`).
