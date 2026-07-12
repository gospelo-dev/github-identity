# 設定ファイル仕様

## 場所

```
~/.config/gospelo-github-identity/config.yml
```

パスは固定です (`$XDG_CONFIG_HOME` は参照しません)。別の場所を使う場合は環境変数 `GOSPELO_GITHUB_IDENTITY_CONFIG` で上書きします (テスト・複数設定セットの切替用)。

作成方法は 3 通り:

```bash
gospelo-github-identity init                  # 対話的に作成
gospelo-github-identity init --from-template  # 同梱テンプレートをコピーして $EDITOR で開く
gospelo-github-identity init --show-example   # 同梱テンプレートを stdout へ (リダイレクト用)
```

サンプルは [examples/](https://github.com/gospelo-dev/github-identity/tree/main/examples) に 3 種類あります: `config.yml` (コメント付き基本 2 profile)、`config.minimal.yml` (最小 1 profile)、`config.advanced.yml` (マルチクライアント 3+ profile)。

## スキーマ全体

```yaml
version: "1"

profiles:
  <profile-name>:
    description: <string>       # 任意
    git:
      user.name: <string>       # 必須
      user.email: <string>      # 必須
    gh:
      account: <string>         # 必須
      owners:                   # 任意。宣言すると guard が enforce 型になる
        - <owner>
    ssh:                        # 任意。ブロックを書くと SSH ログイン検証が有効化
      login: <string>           # 任意。省略時は gh.account を期待値にする
      host: <string>            # 任意。省略時は origin remote からホストを導出
    paths:                      # 任意 (空リスト可)
      - <glob>

default_profile: <profile-name> # 任意
```

スキーマにないキーはエラーにならず**黙って無視**されます。タイポに気づきにくいため、書いた設定が意図どおり効いているかは `list` / `detect` / `check` で確認してください。

## フィールド

### version (必須)

スキーマバージョン。現在は `"1"` のみ (文字列でも数値でも可)。

### profiles (必須)

profile 名 → 定義のマッピング。最低 1 つ必須。profile 名は英数字と `_` / `-` を推奨します (`init` はこの形式を強制します)。

#### profiles.\<name\>.description (任意)

説明文字列。`list` の表示に使われます。

#### profiles.\<name\>.git.user.name / user.email (必須)

期待する git 著者。`switch` が `git config` に設定し、`check` / `doctor` / `guard` が照合します。

#### profiles.\<name\>.gh.account (必須)

期待する GitHub login 名。`switch` が `gh auth switch -u <account>` に渡します。事前にそのアカウントで `gh auth login --hostname github.com` を済ませておく必要があります。

#### profiles.\<name\>.gh.owners (任意)

この profile の identity で書き込む GitHub owner (ユーザー / org) のリスト。**target-aware 強制の要**で、1 つでも宣言すると [guard](enforcement.md#gh-の書き込み-enforce-型-owners-宣言時) が enforce 型に切り替わります: 書き込みの操作対象 (`--repo` / 対象 repo の remote) の owner をこのリストから逆引きし、該当 profile のトークンを呼び出しごとに注入します。どの profile にも属さない owner への書き込みは実行前に拒否されます (fail-closed)。

- 照合は大文字小文字を区別しません (GitHub の login 仕様に準拠)。
- 同じ owner を複数の profile に書くことはできません (逆引きが曖昧になるため exit 2)。
- どの profile も `owners` を持たない場合、guard は従来の check 型のままです (後方互換)。

```yaml
gh:
  account: your-oss-login
  owners: [your-oss-login, your-oss-org]
```

#### profiles.\<name\>.ssh (任意)

`ssh` ブロックを書くと、`check` に SSH ログイン検証の行が追加されます。`git config` / `gh` が正しくても、ssh-agent に別アカウントの鍵が載っていると `git push` が**別人として認証される**盲点を塞ぐためのものです。

`check` はリポジトリの `origin` remote が解決する SSH ホストへ `ssh -T` (読み取り専用・接続のみ) を実行し、GitHub が返す `Hi <login>!` の `<login>` を期待値と照合します。

- `login` (任意) — 期待する GitHub ログイン名。省略時は `gh.account` を使用。通常は `ssh: {}` だけで十分です。
- `host` (任意) — 検証ホストを固定。省略時は `origin` の URL から導出します (SSH エイリアスホストもそのまま使われます)。

判定:

| 状況 | 表示 | 影響 |
|---|---|---|
| 認証ログインが期待値と一致 | `OK` | — |
| 不一致 | `NG` | `check` は exit 1。修正手順を表示 |
| origin が SSH でない / ホスト到達不可 / 鍵未設定 / `ssh` 不在 | `--` | スキップ扱い。失敗にしない |

`ssh` ブロックを書かない profile では SSH 検証は行われず、ネットワークアクセスも発生しません。

なお `check` の ssh 検証が「いま誰として認証されるか」を実測するのに対し、`doctor` は「鍵がエイリアスに固定されているか」という構成を (オフラインで) 監査します。両方を併用するのが確実です。

#### profiles.\<name\>.paths (任意)

この profile が支配するディレクトリの glob パターンのリスト。絶対パスまたは `~` 始まりで書きます。空リストも可 (その profile は `default_profile` 経由でのみ選ばれます)。

### default_profile (任意)

どの profile の `paths` にもマッチしないディレクトリで使うフォールバック profile 名。`profiles` に存在する名前でなければなりません。

**省略時、未マッチは「未マッチ」のままです** (自動フォールバックはしません)。`detect` / `check` / `doctor` は exit 1 になり、`guard` はそのディレクトリを統治対象外として素通しします。

## glob 仕様

### 構文

| パターン | 意味 |
|---|---|
| `*` | `/` 以外の任意文字列 |
| `?` | `/` 以外の 1 文字 |
| `[abc]`, `[a-z]` | 文字クラス |
| `[!abc]` | 否定文字クラス |
| `**` | 任意階層 (0 階層以上) |
| `**/` | 任意階層のディレクトリ |
| `~` | `$HOME` に展開 (パス先頭のみ) |

### 例

```yaml
paths:
  - ~/projects/oss/**             # ~/projects/oss 以下すべて
  - ~/work/client-a               # このディレクトリ (完全一致) のみ
  - ~/work/**/forks/**            # ~/work/.../forks/... を再帰
```

### マッチング規則

1. cwd は `Path.resolve()` で絶対化されます (symlink も解決)。
2. 全 profile の全 `paths` を評価し、マッチしたものすべてを候補にします。
3. 複数 profile がマッチした場合、**literal prefix が最長の pattern** を含む profile が選ばれます。literal prefix とは pattern 先頭から最初の glob メタ文字 (`*` / `?` / `[`) までの部分です。
4. どれにもマッチしなければ `default_profile` (設定時のみ)。

ネスト構成の例:

```yaml
profiles:
  work:
    paths:
      - ~/projects/work/**            # literal prefix = ~/projects/work/
  fork:
    paths:
      - ~/projects/work/oss-forks/**  # literal prefix = ~/projects/work/oss-forks/
```

cwd が `~/projects/work/oss-forks/some-repo` のときは両方マッチしますが、literal prefix の長い `fork` が選ばれます。つまり**深い (具体的な) パスの profile が浅い profile に勝ちます**。

## 権限

- ディレクトリ `~/.config/gospelo-github-identity/` は `0700` で作成されます
- `config.yml` は保存後に `0600` を試行します (失敗してもエラーにしません)

## エラーハンドリング

config が次のいずれかの場合、コマンドは exit 2 で停止します (`prompt` は空出力、`guard` は素通しに切り替わります):

- ファイルが存在しない
- YAML パース失敗 / 空ファイル / ルートがマッピングでない
- `version` が `"1"` でない
- `profiles` が空または不在
- profile の必須キー (`git.user.name` / `git.user.email` / `gh.account`) が欠落・空
- `gh.owners` がリストでない、要素が空文字列、または同じ owner が複数 profile に宣言されている
- `ssh` がマッピングでない、または `ssh.login` / `ssh.host` が空文字列
- `paths` がリストでない、または要素が空文字列
- `default_profile` が `profiles` にない名前を指す
