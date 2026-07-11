# CLI リファレンス

すべてのサブコマンドは以下の共通規約に従います:

- **stdout**: コマンド本来の出力（テーブル / profile 名 / プロンプト用エスケープ等）
- **stderr**: 進捗メッセージ・警告・エラー
- **exit code**:
  - `0` 成功 / 一致
  - `1` 期待条件未達（ミスマッチ / 該当 profile なし 等の予期される失敗）
  - `2` ツールエラー（config 不在、不正な YAML、外部ツール失敗 等）

`prompt` のみ例外で、シェル動作を止めないため常に exit 0 を返します。

## 共通

```
gospelo-github-identity --help        # サブコマンド一覧
gospelo-github-identity --version     # バージョン
```

設定ファイルパスは `GOSPELO_GITHUB_IDENTITY_CONFIG` 環境変数で上書きできます（テスト用）。

---

## init

```
gospelo-github-identity init [--force] [--from-template] [--show-example]
```

`~/.config/gospelo-github-identity/config.yml` を作成します。

オプションなしの場合は対話的に profile を入力します。既存ファイルがある場合は上書き確認のプロンプトが出ます。`--force` で確認をスキップ。

非対話モード:

- `--from-template` — 同梱テンプレート (`gospelo_github_identity/templates/config.template.yml`) を `~/.config/gospelo-github-identity/config.yml` にコピーし、`$EDITOR` (未設定時は `vi`) で開きます。対話入力はスキップ。既存ファイルがある場合は `Overwrite? [y/N]` で確認 (`--force` でスキップ)。コピー後にプレースホルダ (`<your-name>` 等) を実値に置き換えてください。
- `--show-example` — 同梱テンプレートの内容を stdout に出力します。`gospelo-github-identity init --show-example > my-config.yml` のようにリダイレクトでカスタムパスへ書き出せます。常に exit 0。

`--from-template` と `--show-example` は同時指定できません (exit 2)。

サンプル設定は [examples/](https://github.com/gospelo-dev/github-identity/tree/main/examples) にも 3 種 (basic / minimal / advanced) 用意しています。

| 終了コード | 意味 |
|---|---|
| 0 | 保存成功、または既存ファイルを残して中断、または `--show-example` 成功 |
| 1 | 中断（Ctrl-C / EOF / 上書き拒否）、または profile 未入力 |
| 2 | 保存時の I/O エラー、テンプレート不在、`--from-template` と `--show-example` の併用、`$EDITOR` バイナリ不在 |

---

## list

```
gospelo-github-identity list
```

登録済み profile をテーブルで表示します。

| 終了コード | 意味 |
|---|---|
| 0 | 1 つ以上の profile が登録済み |
| 1 | profile が空（理論上は init が防ぎますが念のため） |
| 2 | config 不在・不正 |

---

## detect

```
gospelo-github-identity detect [--cwd PATH]
```

現在のディレクトリ（または `--cwd` で指定したディレクトリ）にマッチする profile 名を 1 行で出力します。スクリプトから profile 名だけを取りたい場合に使用。

| 終了コード | 意味 |
|---|---|
| 0 | profile を解決できた |
| 1 | どの profile にもマッチせず、`default_profile` も未設定 |
| 2 | config 不在・不正 |

---

## check

```
gospelo-github-identity check [--cwd PATH]
```

期待 profile と実状態（`git config user.name` / `user.email` / `gh` CLI のアクティブログイン）を比較してテーブル表示します。profile が `ssh` ブロックを宣言している場合、そのリポジトリの `origin` ホストに対して `ssh -T` が認証される GitHub ログインを照合する `[ssh]` 行が追加されます（[設定ファイル仕様 → ssh](config-format.md#profilesnamessh-任意) 参照）。`[ssh]` 行が `--` の場合はスキップ（origin が SSH でない、またはホスト到達不可）で、実行を失敗させることはありません。

出力例:

```
=== Identity Check ===
Working dir: /Users/you/projects/gospelo-dev/review
Matched profile: oss (via pattern: ~/projects/gospelo-dev/**)

[git]
  user.name  : your-oss-login  (expected: your-oss-login )  OK
  user.email : you@example.com (expected: you@example.com)  OK
[gh CLI]
  login      : your-work-login (expected: your-oss-login )  NG

WARNING: gh CLI account does not match expected profile.
Run `gospelo-github-identity switch oss` to fix.
```

| 終了コード | 意味 |
|---|---|
| 0 | すべて一致 |
| 1 | 1 つ以上 mismatch、または profile が解決できず |
| 2 | config 不在・不正、外部ツール失敗 |

---

## doctor

```
gospelo-github-identity doctor [--cwd PATH] [--sweep]
```

`check` が「いま自分は正しい人か？」を見るのに対し、`doctor` は「正しい"状態"が保たれる設定になっているか（設定の堅牢さ）」を監査します。設定解決のみで判定し（`ssh -T` のネットワーク接続はしない）、`check` では見抜けない問題を検出します:

- git identity が「未設定」ではなく「設定済みだが**値が間違っている**」（例: `.com`/`.net` タイポ）
- git identity が global を**継承しているだけ**で正しい（脆い: global が変わると黙って壊れる）
- remote が素の `git@github.com` のまま（`ssh-agent` の先頭鍵で認証 = 今 OK でも鍵順が変わると壊れる）
- SSH エイリアスが実際には1鍵に固定されていない（`IdentitiesOnly no` / 鍵ファイル欠落）
- 期待する `gh` アカウントがそもそも未ログイン

各項目は `OK` / `INFO` / `WARN` / `FAIL` で表示。`--sweep` を付けると、マッチした profile の `paths` 配下の**全 git repo を一括監査**します（「18 repo が鍵順ひとつで別人 push になる」といった俯瞰把握）。

出力例:

```
=== Identity Doctor ===
Working dir: /Users/you/projects/gospelo-dev/review
Matched profile: gospelo (via pattern: ~/projects/gospelo-dev/**)

[machine]
  [OK  ] global git identity is unset (identity is left to each repo)
  [OK  ] gh account 'gorosun' is logged in

[repo] review  (/Users/you/projects/gospelo-dev/review)
  [OK  ] git identity pinned locally: gorosun / you@example.com
  [OK  ] origin uses SSH alias 'gospelo-dev' (git@gospelo-dev:gospelo-dev/review.git)
  [OK  ] alias 'gospelo-dev' pins ~/.ssh/id_gospelo-dev (IdentitiesOnly yes)

OK: setup is healthy for profile 'gospelo'.
```

| 終了コード | 意味 |
|---|---|
| 0 | 監査項目がすべて OK |
| 1 | WARN/FAIL が 1 件以上、または profile が解決できず |
| 2 | config 不在・不正、外部ツール失敗 |

---

## switch

```
gospelo-github-identity switch <profile> [--global] [--dry-run] [--cwd PATH]
```

指定 profile のために `git config user.name` / `user.email` を設定し、`gh auth switch -u <account>` を実行します。

- デフォルトは `git config --local`（カレントリポジトリのみ）
- `--global` でユーザー全体
- `--dry-run` は副作用なしで予定だけ表示

| 終了コード | 意味 |
|---|---|
| 0 | git config と gh switch の両方が成功 |
| 1 | 部分成功（片方だけ失敗） |
| 2 | profile 不在、両方失敗、外部ツール不在 |

`--local`（既定）で `cwd` が git work tree の外にある場合は exit 2 で停止します。`--global` を使うか、リポジトリに移動してください。

---

## prompt

```
gospelo-github-identity prompt [--format {plain,color,ps1}] [--show-mismatch] [--cwd PATH]
```

シェルプロンプト統合用 helper。マッチした profile 名を `[name]` の形式で出力します。マッチしない・config 未作成のときは空文字列を返します。常に exit 0。

`--format`:

- `plain` (既定) — `[oss]`
- `color` — ANSI エスケープ付き（`\033[33m[oss]\033[0m`）
- `ps1` — bash の `PS1` 用に readline 非印字マーカー `\[ \]` で囲む

`--show-mismatch` を付けると、git/gh 状態が profile と不一致の場合に `[oss !]` のように `!` を付与し、`color` / `ps1` では赤色で表示します。

bash の例:

```bash
PS1='$(gospelo-github-identity prompt --format=ps1 --show-mismatch) \w \$ '
```

zsh の例（`PROMPT` で使う場合は `setopt PROMPT_SUBST` が必要）:

```zsh
setopt PROMPT_SUBST
PROMPT='%F{yellow}$(gospelo-github-identity prompt --format=plain --show-mismatch)%f %~ %# '
```

---

## enforcement: guard（gh/git の PATH シム）

guard は `PATH` 上の `gh`（任意で `git`）を小さなシム実行ファイルで**シャドウ**します。各呼び出しは `gospelo-github-identity guard` を経由し、**読み取り専用**コマンドはそのまま通し、**書き込み／外向き**コマンド（`git push`、`gh release/pr/repo/... create`、変更系の `gh api` など）については先にカレントディレクトリの identity チェックを行い、アクティブな git/gh identity がそのディレクトリを支配する profile と一致しない場合は書き込みを**ブロック**します（非ゼロ終了。本物のバイナリは実行されません）。

設計上の制約:

- **決定論的** — 純粋なパターンロジックのみ。LLM は使わない。
- **ローカル完結** — `check` が行う `gh api user` 以上の通信は発生しない。
- **enforcement の外では fail-open** — マッチした profile 下で identity 不一致の書き込みはブロックするが、それ以外（config 不在、config 読み取り不可、どの profile にもマッチしないディレクトリ、`GOSPELO_GITHUB_IDENTITY_SKIP` 設定時）は本物のコマンドをそのまま実行する。無関係な作業を壊さない。

制限: PATH シムは**名前ベース**の呼び出ししか捕捉できません。絶対パス指定（`/usr/bin/git push`）はバイパスされます。シムの役割は自動化／エージェント実行中の**うっかり**誤 identity 書き込みを止めることであり、敵対的プロセスへの防御ではありません。その用途には OS サンドボックスを併用してください。

### install-guard

```
gospelo-github-identity install-guard [--dir DIR] [--tools gh,git]
```

`DIR`（既定 `~/.gospelo-github-identity/bin`）にシム実行ファイルを書き出し、シェル rc に追記すべき行を表示します。

- `--tools`（既定 `gh`）— シャドウ対象をカンマ区切りで指定。`git` をシャドウすると毎回の `git` 呼び出しに Python 起動が乗り影響範囲も大きいため、`git push` をガードしたい場合のみ `--tools gh,git` で明示的に有効化します（コミットメッセージの衛生は `install-commit-hook` が別途担当）。
- インストール前に、解決された `gospelo-github-identity` が実際に `guard` サブコマンドを持つか検証し、壊れたシム（古いビルドが `PATH` 先頭にある場合など）のインストールを拒否します。

シムディレクトリを `PATH` の**先頭**に置いて有効化します:

```bash
export PATH="$HOME/.gospelo-github-identity/bin:$PATH"   # ~/.zshrc や ~/.bashrc に追記
command -v gh   # シムのパスが表示されればOK
```

| 終了コード | 意味 |
|---|---|
| 0 | 1つ以上のシムをインストール |
| 1 | シム未インストール（`PATH` にツールが無い、または解決コマンドが `guard` 非対応） |

### guard

```
gospelo-github-identity guard --tool {gh,git} --real <path> -- <args...>
```

シムが呼び出すランタイムゲート。通常は手動で実行しません。**書き込み**呼び出しでは **stderr** に1行のステータスを出力します（読み取り専用呼び出しは無音）:

| 状況 | stderr | 結果 |
|---|---|---|
| identity 一致 | `identity OK for profile '<name>'; passing through.` | 本物のコマンドを実行 |
| identity 不一致 | `BLOCKED ... fix: gospelo-github-identity switch <name>` | **ブロック**、exit 1 |
| 未ガバナンスのディレクトリ | `directory not governed by any profile; passing through.` | 本物のコマンドを実行 |
| config 不在／読み取り不可 | `no usable config; passing through ...` | 本物のコマンドを実行 |

環境変数:

- `GOSPELO_GITHUB_IDENTITY_SKIP=1` — 1回だけゲートをバイパス: `GOSPELO_GITHUB_IDENTITY_SKIP=1 gh release create ...`。
- `GOSPELO_GITHUB_IDENTITY_QUIET=1` — 上記の情報ステータス行を抑制。**ブロックはこの設定に関係なく必ず表示**されます。

### uninstall-guard

```
gospelo-github-identity uninstall-guard [--dir DIR] [--tools gh,git]
```

シムファイルを削除します。シェル rc に追記した `export PATH=...` の行も忘れずに削除してください。

---

## enforcement: commit-msg フック（Co-Authored-By 除去）

グローバルな `commit-msg` フックが、コミットメッセージから `Co-authored-by:` トレーラ行をすべて除去します（コミットを実行する人間が責任を負う著者であるため）。PATH シムと異なり、`git` が絶対パスや IDE から呼ばれてもフックは発火します（git 自身が実行するため）。また commit 時のみ動くので毎回の呼び出しレイテンシはありません。

### install-commit-hook

```
gospelo-github-identity install-commit-hook [--dir DIR] [--force]
```

`DIR`（既定 `~/.gospelo-github-identity/git-hooks`）にグローバル `core.hooksPath` ディスパッチャをインストールします。`commit-msg` で `Co-Authored-By` を除去した後、**各リポジトリ独自の `.git/hooks/<name>` にチェーン**するため、既存フック（husky, pre-commit など）も動き続けます。

- グローバル `core.hooksPath` が別の値に既設の場合、`--force` なしでは拒否します。
- **独自の** `core.hooksPath` を設定するリポジトリ（husky など）はグローバル設定を上書きします。その場合はリポジトリ単位でインストールしてください。

| 終了コード | 意味 |
|---|---|
| 0 | インストール完了 |
| 1 | 別のグローバル `core.hooksPath` が既設（`--force` で再実行） |
| 2 | `core.hooksPath` の設定に失敗 |

### uninstall-commit-hook

```
gospelo-github-identity uninstall-commit-hook [--dir DIR]
```

グローバル `core.hooksPath`（自分のディスパッチャを指している場合のみ）を解除し、ディスパッチャ関連ファイルを削除します。

### strip-coauthors

```
gospelo-github-identity strip-coauthors <commit-msg-file>
```

フックが呼び出すワーカー。メッセージファイルをその場で書き換え、`Co-authored-by:` 行を除去します。通常は直接呼びません。常に exit 0（自身の I/O エラーでコミットをブロックしない）。
