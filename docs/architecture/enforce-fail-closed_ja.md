# enforce + fail-closed アーキテクチャ

[English version](enforce-fail-closed.md)

> **Status: 実装済み (v0.2.0)** — 本書は guard を「check 型」から「enforce 型」へ昇格させた設計の背景と理路を記録するものです。実装済みの仕様の正確なリファレンスは [docs/manual/ja/enforcement.md](../manual/ja/enforcement.md) を参照してください。スコープは identity のみ (汎用コマンドガードは作らない) という境界線を維持しています。
>
> 例に登場するアカウント名 (`your-oss-login` / `your-work-login`) と org 名 (`your-company-org`) はプレースホルダです。

## 1. 背景 — direnv 依存の 2 つの欠陥

v0.1.x までの構成では、`gh` アカウントの自動切替を direnv (`.envrc` の `GH_TOKEN` 注入) に委ねるのが定石でした。この方式には構造的な欠陥が 2 つあり、いずれも一次ソースで確認できます:

1. **非対話シェルで発火しない。** direnv はプロンプト表示時のシェルフックで動くため、自律エージェントの `bash -c ...` (rc 非読込) では `.envrc` が評価されません ([direnv/direnv#262](https://github.com/direnv/direnv/issues/262), [direnv man](https://direnv.net/man/direnv.1.html))。
2. **cwd 基準であり、操作対象基準ではない。** `gh --repo <owner>/<repo>` や `git -C <path>` で cwd と別の repo を操作すると、direnv も check 型 guard も cwd 側の identity を適用してしまいます。

さらに `gh` 自身も「pwd / git remote に基づく自動アカウント切替」を明示的にスコープ外としており ([cli/cli multiple-accounts.md](https://github.com/cli/cli/blob/trunk/docs/multiple-accounts.md))、active account はマシン全体で 1 つのグローバル状態です。この空白を gospelo-github-identity が埋めます。

### identity 3 層の整理

| 層 | identity の束縛先 | cwd がズレたときの挙動 |
|---|---|---|
| ① git 著者名 | 対象 repo の local `git config` | ✅ 守られる (`git -C X` は X の config を読む — [git docs](https://git-scm.com/docs/git)) |
| ② SSH push 認証 | 対象 repo の remote URL エイリアス + `IdentitiesOnly` | ✅ 守られる (鍵選択の入力は remote URL のみ) |
| ③ gh アカウント | **環境グローバル** (`GH_TOKEN` env / active account — [gh env manual](https://cli.github.com/manual/gh_help_environment)) | ❌ **穴** — 正しい repo に誤アカウントで write しうる |

本設計の目的は、**③ を ①② と同じ「対象に identity が紐づく」構造に揃える**ことです。

### 従来の穴 (cwd 基準 + direnv 依存)

```mermaid
flowchart TB
    Agent["fa:fa-robot 自律エージェント<br/>bash -c (非対話シェル)"]
    Cmd["fa:fa-terminal gh --repo your-company-org/x pr create<br/>cwd = ~/projects/oss/y"]
    subgraph Old["従来の判定層 (cwd 基準)"]
        Direnv["fa:fa-rotate direnv フック<br/>プロンプト表示時のみ発火"]
        GuardOld["fa:fa-shield-halved guard (check 型)<br/>cwd の profile と照合 — 対象 your-company-org/x を見ない"]
    end
    GhGlobal["fa:fa-user グローバル active account<br/>(マシン全体で 1 つ)"]
    API["fa:fa-cloud GitHub<br/>fa:fa-triangle-exclamation 正しい repo に誤アカウントで write"]

    Agent --> Cmd
    Cmd --> GuardOld
    Direnv -.->|非対話シェルでは発火しない| Cmd
    GuardOld --> GhGlobal
    GhGlobal --> API

    classDef node fill:#FFFFFF,stroke:#666666,stroke-width:1.5px,color:#2C2C2C
    class Agent,Cmd,Direnv,GuardOld,GhGlobal,API node
    style Old fill:#F8FAFC,stroke:#94A3B8,color:#2C2C2C

    %% 通常フロー = ティール実線 / 不発・非破壊 = グレー破線
    linkStyle 0,1,3,4 stroke:#0D9488,stroke-width:2px
    linkStyle 2 stroke:#9CA3AF,stroke-width:1.5px,stroke-dasharray:4 4
```

## 2. 設計原則

1. **target-aware** — identity は cwd ではなく**操作対象** (`--repo` / `git -C` / 対象 repo の remote) から導出する。
2. **非 ambient** — 資格情報を環境変数として常駐させない。トークンは呼び出しごとに materialize し、その 1 プロセスの env にだけ一瞬存在する。
3. **fail-closed** — 対象を解決できない・profile を引けない・シムを迂回された、のいずれでも「誤 identity で通る」のではなく「認証なし / 実行拒否で失敗する」。

原則 3 が要石になります: PATH シムは迂回可能 (絶対パス実行、直接 API 呼び出し) ですが、**迂回した先に資格情報が存在しなければ**、迂回は「誤アカウントでの成功」ではなく「安全な失敗」に落ちます。検査の網羅性を諦める代わりに、検査を通らない経路から資格情報を消します。

## 3. アーキテクチャ全体図

guard は「検査して警告する check 型」から「identity を注入する enforce 型」へ昇格し、direnv は廃止できます (プロンプトフックへの依存が消える)。

```mermaid
flowchart TB
    Agent["fa:fa-robot 呼び出し元<br/>(人間 / 自律エージェント / CI)"]
    subgraph Shim["gospelo-github-identity guard — enforce 型 PATH シム"]
        Resolve["fa:fa-magnifying-glass 対象解決<br/>--repo / git -C / 対象 remote"]
        Map["fa:fa-sitemap owner → profile 逆引き"]
        Inject["fa:fa-key トークン注入<br/>GH_TOKEN を呼び出しごとに materialize"]
        Deny["fa:fa-ban fail-closed<br/>解決不能・profile 不明は実行しない"]
    end
    Config[("fa:fa-database config.yml<br/>profiles + owners + paths")]
    Store[("fa:fa-lock 資格情報ストア<br/>gh keyring")]
    Real["fa:fa-terminal 本物の gh / git"]
    API["fa:fa-cloud GitHub"]

    Agent --> Resolve
    Resolve --> Map
    Map --> Inject
    Inject --> Real
    Real --> API
    Resolve -->|解決不能| Deny
    Map -->|profile 不明| Deny
    Config -.->|読み取り| Map
    Store -.->|読み取り| Inject

    classDef node fill:#FFFFFF,stroke:#666666,stroke-width:1.5px,color:#2C2C2C
    class Agent,Resolve,Map,Inject,Deny,Config,Store,Real,API node
    style Shim fill:#F0FDFA,stroke:#0D9488,color:#2C2C2C

    %% 通常フロー = ティール実線 / 読み取り = グレー破線
    linkStyle 0,1,2,3,4,5,6 stroke:#0D9488,stroke-width:2px
    linkStyle 7,8 stroke:#9CA3AF,stroke-width:1.5px,stroke-dasharray:4 4
```

## 4. データフロー

### 4.1 gh write の正常系 (target-aware 注入)

`gh --repo your-company-org/x pr create` を、無関係な cwd から実行した場合でも正しい identity で通す流れ:

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'actorBkg': '#FFFFFF', 'actorBorder': '#666666', 'actorTextColor': '#2C2C2C', 'signalColor': '#0D9488', 'signalTextColor': '#2C2C2C', 'noteBkgColor': '#F0FDFA', 'noteBorderColor': '#0D9488', 'noteTextColor': '#2C2C2C', 'activationBkgColor': '#F8FAFC', 'activationBorderColor': '#94A3B8', 'loopTextColor': '#2C2C2C', 'labelBoxBkgColor': '#F0FDFA', 'labelBoxBorderColor': '#0D9488', 'labelTextColor': '#2C2C2C'}}}%%
sequenceDiagram
    participant A as 呼び出し元
    participant S as guard シム (gh)
    participant C as config.yml
    participant K as 資格情報ストア
    participant G as 本物の gh
    participant H as GitHub API

    A->>S: gh --repo your-company-org/x pr create
    S->>S: 対象解決: your-company-org/x<br/>(--repo > git -C > cwd remote)
    S->>C: owner "your-company-org" を逆引き
    C-->>S: profile "work" / account your-work-login
    S->>K: トークン取得<br/>(gh auth token --user your-work-login)
    K-->>S: token (この呼び出し限り)
    S->>G: GH_TOKEN を注入して exec
    G->>H: PR 作成 (正しい identity)
    H-->>G: 201 Created
    Note over S: owner が未宣言 / 対象を解決できない場合は<br/>exec せず exit 1 (fail-closed)
```

### 4.2 シム迂回時 (fail-closed)

絶対パス実行やスクリプトからの直接呼び出しでシムを迂回しても、環境に資格情報が存在しないため「誤 identity での成功」には到達できません:

```mermaid
flowchart LR
    Bypass["fa:fa-terminal シム迂回呼び出し<br/>/opt/homebrew/bin/gh ..."]
    RealGh["fa:fa-terminal 本物の gh"]
    Env["fa:fa-circle-xmark 環境に GH_TOKEN なし<br/>(direnv 廃止)"]
    Auth["fa:fa-circle-xmark 環境変数残留を doctor が監査"]
    Fail["fa:fa-circle-check 認証エラーで安全に失敗<br/>誤 identity には到達しない"]

    Bypass --> RealGh
    RealGh --> Fail
    Env -.-> RealGh
    Auth -.-> RealGh

    classDef node fill:#FFFFFF,stroke:#666666,stroke-width:1.5px,color:#2C2C2C
    class Bypass,RealGh,Env,Auth,Fail node

    %% 通常フロー = ティール実線 / 前提状態 (非破壊) = グレー破線
    linkStyle 0,1 stroke:#0D9488,stroke-width:2px
    linkStyle 2,3 stroke:#9CA3AF,stroke-width:1.5px,stroke-dasharray:4 4
```

## 5. 穴の棚卸し — check 型 vs enforce 型

| 経路 | check 型 (direnv 併用, ~v0.1.x) | enforce 型 (v0.2.0+) |
|---|---|---|
| 非対話シェルからの `gh` write | ❌ direnv 非発火で素通り | ✅ PATH 経由なら必ずシムが強制 |
| cwd ズレ (`gh --repo X` / `git -C X`) | ❌ cwd 基準で誤判定 | ✅ 対象基準で解決 |
| 非 governed cwd からの操作 | ❌ profile 不一致でノーガード | ✅ 対象が governed なら強制、不明なら拒否 |
| 絶対パスでのシム迂回 | ❌ グローバル account で通る | ⭕ 資格情報がなく認証エラー (安全側) |
| 対象を推定できない操作 (`gh gist create`, `gh api /user` 等) | — | ✅ cwd の profile にフォールバック、非 governed なら拒否 |
| 資格情報ストアを直接読むプロセス | — | ⚠️ 残余リスク — OS サンドボックス / 専用ユーザーの領域 (スコープ外) |

① git 著者名・② SSH 鍵は既に target-local であり、本設計での変更はありません。

## 6. コンポーネント構成

| コンポーネント | 役割 |
|---|---|
| `guard.py` | 対象解決 (`--repo` / `-C` / 対象 remote) + owner→profile 逆引き + トークン注入 + fail-closed |
| `config.py` | profile の `gh:` の `owners:` (owner→profile の逆引きマップ) |
| `doctor.py` | fail-closed 状態の健全性チェック: `GH_TOKEN` / `GITHUB_TOKEN` が環境に常駐していないか |
| direnv (`.envrc`) | 廃止 (推奨セットアップから除外) |
| `switch` | 現状維持 (手動適用の一発コマンドとしての役割は不変) |

### 6.1 config (owners マップ)

```yaml
profiles:
  oss:
    git:
      user.name: your-oss-login
      user.email: you@example.com
    gh:
      account: your-oss-login
      owners: [your-oss-org, your-oss-login]   # この owner への write はこの profile
    paths:
      - ~/projects/oss/**
```

対象解決の優先順位: `--repo owner/name` 引数 → `git -C <path>` の対象 repo の remote → cwd の remote。owner がどの profile の `owners` にも見つからなければ**実行しません** (fail-closed)。

### 6.2 トークンの materialize

`gh auth token --user <account>` で対象 profile のトークンを取り出し、`GH_TOKEN` として本物の `gh` の実行環境にのみ注入します ([gh docs](https://github.com/cli/cli/blob/trunk/docs/multiple-accounts.md) が automated switching solutions 向けに案内している公式手段)。`GH_TOKEN` は保存済み認証情報より優先されるため、グローバル active account の状態に関わらず正しい identity で実行されます。

### 6.3 ambient credential の除去 (fail-closed の成立条件)

- シェル環境に `GH_TOKEN` / `GITHUB_TOKEN` を常駐させない (direnv 廃止で自動達成)
- 上記により「シムを通らない経路には資格情報がない」が成立する
- この規律は `doctor` が監査する (環境変数の残留を WARN で検出)

### 6.4 対象を推定できない操作のポリシー

`gh gist create` や `gh api /user` のように repo 対象を持たない操作は owner 逆引きができません。デフォルトは cwd の profile にフォールバックし、cwd も非 governed なら拒否します (`GOSPELO_GITHUB_IDENTITY_SKIP=1` で明示バイパス可)。

## 7. 移行パス

1. **Phase A — target-aware check**: guard の判定基準を cwd から対象へ (非破壊、既存挙動の精度向上)
2. **Phase B — トークン注入**: check 型 → enforce 型。direnv なしで正しい identity が選ばれる
3. **Phase C — ambient 除去**: direnv 廃止 + `doctor` の fail-closed 診断

Phase A/B は後方互換です (`gh.owners` を宣言しない限り従来の check 型のまま)。Phase C を完了した時点で fail-closed が成立します。

## 8. 残余リスクと限界 (正直な線引き)

- **資格情報ストア自体へのアクセス**は防げません。敵対的プロセスへの防御は OS サンドボックスの役割です。本設計が守るのは **accidental** な誤 identity です。
- gh の credential helper 経由の HTTPS git 認証はグローバル auth 前提のため、本設計は **SSH push 運用** (remote エイリアス + `IdentitiesOnly`) と組み合わせて成立します。
- `gh auth token --user` はアカウントが keyring にログイン済みであることが前提です。未ログインは `doctor` が検出し、guard は注入できない書き込みを拒否します。
- keyring のログイン済みアカウント自体は残るため (gh はログイン中アカウントのいずれかを常に active とする仕様)、doctor の ambient 監査は環境変数 (`GH_TOKEN` / `GITHUB_TOKEN`) の残留検査に限定しています。
