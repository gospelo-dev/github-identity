# 設定ファイル仕様

## サンプル

[examples/](https://github.com/gospelo-dev/gospelo-github-identity/tree/main/examples) に 3 種類のサンプルがあります:

- `config.yml` — コメント付きの基本 2 profile 構成
- `config.minimal.yml` — 1 profile のみの最小例
- `config.advanced.yml` — フリーランス / マルチクライアント向けの 3+ profile 構成

CLI から同梱テンプレートを取り出すこともできます:

```bash
# 同梱テンプレートを ~/.config/gospelo-github-identity/config.yml にコピー + $EDITOR で開く
gospelo-github-identity init --from-template

# 同梱テンプレートを stdout に出力 (パイプ用)
gospelo-github-identity init --show-example > my-config.yml
```

## 場所

```
~/.config/gospelo-github-identity/config.yml
```

`GOSPELO_GITHUB_IDENTITY_CONFIG` 環境変数で別パスを指定できます（テスト・複数プロファイルセットの切替用）。

## スキーマ全体

```yaml
version: "1"

profiles:
  <profile-name>:
    description: <string>
    git:
      user.name: <string>
      user.email: <string>
    gh:
      account: <string>
    ssh:                   # 任意。ブロックを書くと SSH ログイン検証が有効化される
      login: <string>      # 任意。省略時は gh.account を期待値にする
      host: <string>       # 任意。省略時は origin リモートからホストを導出
    paths:
      - <glob>
      - <glob>

default_profile: <profile-name>   # 任意
```

## フィールド

### version (必須)

スキーマバージョン。現在は `"1"` のみ受け付けます（文字列でも数値でも可）。

### profiles (必須)

profile 名 → 定義のマッピング。最低 1 つは必須。

profile 名は英数字 + `_` / `-` のみ推奨（`init` でもこの制約を確認）。

#### profiles.\<name\>.description

任意の説明文字列。空文字でも可。

#### profiles.\<name\>.git.user.name (必須)

`git config user.name` に設定する値。

#### profiles.\<name\>.git.user.email (必須)

`git config user.email` に設定する値。

#### profiles.\<name\>.gh.account (必須)

`gh auth switch -u <account>` で指定する GitHub login 名。`gh auth login --hostname github.com` で事前にこのアカウントに認証済みである必要があります。

#### profiles.\<name\>.ssh (任意)

`ssh` ブロックを書くと、`check` に **SSH ログイン検証** の行が追加されます。これは `git config` / `gh` が正しくても、`ssh-agent` に別アカウントの鍵が載っていると `git push` が別人として認証されてしまう盲点を塞ぐためのものです（`IdentitiesOnly no` で鍵が順に試されるケースなど）。

`check` はそのリポジトリの `origin` リモートが解決する SSH ホストに対して `ssh -T`（読み取り専用・接続のみ）を実行し、GitHub が返す `Hi <login>!` の `<login>` を期待値と照合します。

- `login` (任意) — 期待する GitHub ログイン名。省略時は `gh.account` を使用（通常は同一の GitHub アカウントなので、`ssh: {}` だけで十分）。
- `host` (任意) — 検証するホストを固定する。省略時は `origin` の URL から導出（SSH エイリアスホスト `github.com-xxx` もそのまま使われる）。

判定:

- 認証されたログインが期待値と一致 → `OK`
- 一致しない → `NG`（`check` は exit 1。HTTPS 化 or `~/.ssh/config` のホストエイリアス固定の修正手順を表示）
- `origin` が SSH でない（HTTPS / リモート無し）、またはホストに到達できない・鍵未設定・`ssh` 未インストール → `--`（スキップ扱いで **失敗にはしない**）

> `ssh` ブロックを書かない profile の挙動は従来と完全に同じで、SSH 検証も行われません（ネットワークアクセスも発生しません）。

#### profiles.\<name\>.paths

glob パターンのリスト。絶対パスまたは `~` 始まりで指定。空リスト可。

### default_profile (任意)

どの profile の `paths` にもマッチしない場合のフォールバック profile 名。`profiles` に存在する名前である必要があります。省略時、マッチしないと `detect` / `check` は exit 1。

> **絶対ルール**: `default_profile` は省略した場合、自動でフォールバックされません。明示的に書かない限り、未マッチは「未マッチ」として扱われます。

## glob 仕様

### 構文

| パターン | 意味 |
|---|---|
| `*` | `/` 以外の任意文字列 |
| `?` | `/` 以外の 1 文字 |
| `[abc]`, `[a-z]` | 文字クラス |
| `[!abc]` | 否定文字クラス |
| `**` | 任意階層（0 階層以上）にマッチ |
| `**/` | 任意階層のディレクトリ |
| `~` | `$HOME` に展開（パスの先頭のみ） |

### 例

```yaml
paths:
  - ~/projects/oss/**             # ~/projects/oss 以下すべて
  - ~/work/client-a               # 完全一致のみ
  - ~/work/**/forks/**            # ~/work/.../forks/... を再帰
```

### マッチング規則

1. cwd は `Path.resolve()` で絶対化されます（symlink も解決）。
2. 各 profile の paths を順に評価し、マッチしたものすべてを候補とします。
3. **複数の profile がマッチした場合、最長の literal prefix を持つ pattern を含む profile が優先されます。** ここでいう literal prefix は、pattern の先頭から最初の glob メタ文字 (`*` / `?` / `[`) までの長さです。
4. どれにもマッチしないとき、`default_profile` が設定されていればそれを返します（`MatchResult.via_default = True`）。

### マッチング例

```yaml
profiles:
  work:
    paths:
      - ~/projects/work/**            # literal prefix = "/Users/you/projects/work/"
  fork:
    paths:
      - ~/projects/work/oss-forks/**  # literal prefix = "/Users/you/projects/work/oss-forks/"
```

cwd が `~/projects/work/oss-forks/some-repo` の場合、両方マッチしますが `fork` の方が literal prefix が長いので `fork` が選ばれます。

## 権限

- ディレクトリ `~/.config/gospelo-github-identity/` は `0700` で作成
- ファイル `config.yml` は保存後に `0600` を試行（失敗してもエラーにはしない）

## エラーハンドリング

設定ファイルが以下のいずれかの場合、コマンドは exit 2 で終了します:

- ファイルが存在しない
- YAML パース失敗
- `version` が `"1"` でない
- `profiles` が空 or 不在
- profile 内の必須キー（`git.user.name` / `git.user.email` / `gh.account`）が欠けている
- `ssh` がマッピングでない、または `ssh.login` / `ssh.host` が空文字列
- `default_profile` が `profiles` に存在しない名前を指している
