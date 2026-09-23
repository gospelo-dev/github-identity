# CLI リファレンス

全 13 サブコマンドの仕様です。強制レイヤ (guard / commit-msg フック) の動作原理は [enforcement.md](enforcement.md) に詳細があります。

## 共通規約

- **stdout**: コマンド本来の出力 (テーブル / profile 名 / プロンプト用文字列)
- **stderr**: 進捗・警告・エラー
- **終了コード**:

| コード | 意味 |
|---|---|
| `0` | 成功 / 一致 |
| `1` | 期待条件未達 (不一致・該当 profile なし・ブロック等の予期される失敗) |
| `2` | ツールエラー (config 不在・不正な YAML・外部ツール失敗等) |

`prompt` はシェルを止めないため常に exit 0 です。`strip-coauthors` は禁止トレーラの除去後に exit 1 となり、利用者に内容確認とリトライを求めます。ただし自身の I/O エラー時は exit 0 です。

```
gospelo-github-identity --help        # サブコマンド一覧
gospelo-github-identity --version     # バージョン表示
```

### 環境変数

| 変数 | 効果 |
|---|---|
| `GOSPELO_GITHUB_IDENTITY_CONFIG` | config ファイルのパスを上書き (既定: `~/.config/gospelo-github-identity/config.yml`) |
| `GOSPELO_GITHUB_IDENTITY_SKIP` | `1` で guard のゲートを 1 回バイパス (guard 専用) |
| `GOSPELO_GITHUB_IDENTITY_QUIET` | `1` で guard の情報ステータス行を抑制 (ブロック通知は抑制されない) |

---

## init

```
gospelo-github-identity init [--force] [--from-template] [--show-example]
```

`~/.config/gospelo-github-identity/config.yml` を作成します。オプションなしでは対話的に profile を入力します。既存ファイルがある場合は上書き確認が出ます (`--force` でスキップ)。

- `--from-template` — 同梱テンプレートを config パスにコピーし、`$EDITOR` (未設定時は `vi`) で開きます。コピー後にプレースホルダ (`<your-name>` 等) を実値へ置き換えてください。
- `--show-example` — 同梱テンプレートを stdout に出力します。`> my-config.yml` とリダイレクトして任意の場所に書き出せます。常に exit 0。

`--from-template` と `--show-example` は併用できません (exit 2)。

| 終了コード | 意味 |
|---|---|
| 0 | 保存成功 / 既存ファイルを残して中断 / `--show-example` 成功 |
| 1 | 中断 (Ctrl-C / EOF / 上書き拒否) または profile 未入力 |
| 2 | I/O エラー、テンプレート不在、オプション併用、`$EDITOR` バイナリ不在 |

---

## list

```
gospelo-github-identity list
```

登録済み profile をテーブル表示します。

| 終了コード | 意味 |
|---|---|
| 0 | 1 つ以上の profile を表示 |
| 1 | profile が空 |
| 2 | config 不在・不正 |

---

## detect

```
gospelo-github-identity detect [--cwd PATH]
```

現在のディレクトリ (または `--cwd`) を支配する profile 名を 1 行で出力します。スクリプトから profile 名だけ取りたいときに使います。

| 終了コード | 意味 |
|---|---|
| 0 | profile を解決できた |
| 1 | 未マッチかつ `default_profile` 未設定 |
| 2 | config 不在・不正 |

---

## check

```
gospelo-github-identity check [--cwd PATH]
```

期待 profile と実状態を照合してテーブル表示します。照合対象:

- `[git]` — local `git config` の `user.name` / `user.email`
- `[gh CLI]` — アクティブなトークンが実際に属するアカウント (`gh api user` で検証するため、`hosts.yml` のラベルが古くても実体を見ます)
- `[ssh]` — profile が `ssh` ブロックを宣言している場合のみ。リポジトリの `origin` ホストに `ssh -T` して認証されるログインを照合します。`--` はスキップ (origin が SSH でない / ホスト到達不可) で、失敗にはなりません

出力例と ssh 検証の詳細は [quick-start.md](quick-start.md#3-期待と実状態を照合する) と [config-format.md](config-format.md#profilesnamessh-任意) を参照してください。

| 終了コード | 意味 |
|---|---|
| 0 | すべて一致 |
| 1 | 1 つ以上不一致、または profile 未解決 |
| 2 | config 不在・不正、外部ツール失敗 |

---

## doctor

```
gospelo-github-identity doctor [--cwd PATH] [--sweep]
```

`check` が「いま正しいか」を見るのに対し、`doctor` は「正しさが保たれる構成か」を監査します。設定の解決のみで判定するため高速・オフラインで動作します (`ssh -T` のネットワーク接続はしません)。

**[machine] マシン単位の監査:**

| 判定 | 条件 |
|---|---|
| OK | global git identity が未設定 (identity は各リポジトリに委ねられている) |
| INFO | global git identity が設定済み (local 未設定のリポジトリはこれを継承する) |
| OK / WARN | 期待する gh アカウントがログイン済みか (未ログインだと switch も guard のトークン注入も作動不能) |
| OK / WARN | 環境に `GH_TOKEN` / `GITHUB_TOKEN` が常駐していないか (常駐していると guard の注入を上書きし、シム迂回経路を認証してしまう) |
| OK / INFO / WARN | guard の動作モード: この profile が `gh.owners` を宣言済み (OK) / どの profile も未宣言で check 型 (INFO) / 他 profile だけ宣言済みでこの profile が置き去り (WARN) |

**[repo] リポジトリ単位の監査:**

| 判定 | 条件 |
|---|---|
| FAIL | git identity が未設定 (コミット不能) / 実効値が期待と不一致 |
| WARN | 実効値は正しいが local 固定でなく global 継承 (global 変更で静かに壊れる) |
| OK | git identity が local に固定済み |
| WARN | `origin` remote がない / SSH でない / 素の `github.com` (ssh-agent の鍵順に依存) |
| WARN | SSH エイリアスが `IdentityFile` を固定していない / `IdentitiesOnly` が no |
| FAIL | エイリアスの鍵ファイルが存在しない |
| OK | エイリアスが 1 鍵に固定済み (`IdentitiesOnly yes`) |

`--sweep` を付けると、マッチした profile の `paths` 配下を走査して**その profile が支配する全 git リポジトリ**を一括監査します (`node_modules` / `.venv` / 隠しディレクトリ等はスキップ。別 profile が支配するリポジトリは対象外)。

| 終了コード | 意味 |
|---|---|
| 0 | すべて OK (INFO は OK 扱い) |
| 1 | WARN / FAIL が 1 件以上、または profile 未解決 |
| 2 | config 不在・不正、外部ツール失敗 |

---

## switch

```
gospelo-github-identity switch <profile> [--global] [--dry-run] [--cwd PATH]
```

指定 profile の identity を一括適用します:

1. `git config user.name` / `user.email` を設定 (既定は `--local`、`--global` でユーザー全体)
2. `gh auth switch -u <account>` を実行し、切替後にトークンレベルで実体を検証 (keyring の credential が古い場合は NG を報告)

`--dry-run` は副作用なしで予定だけ表示します。`--local` (既定) で cwd が git work tree の外にある場合は exit 2 で停止します。

| 終了コード | 意味 |
|---|---|
| 0 | git config と gh switch の両方が成功 |
| 1 | 部分成功 (片方だけ失敗) |
| 2 | profile 不在、両方失敗、外部ツール不在 |

---

## prompt

```
gospelo-github-identity prompt [--format {plain,color,ps1}] [--show-mismatch] [--cwd PATH]
```

シェルプロンプト用 helper。マッチした profile 名を `[name]` 形式で出力します。未マッチ・config 不在のときは黙って空文字列を返します。**常に exit 0** です。

- `--format plain` (既定) — `[oss]`
- `--format color` — ANSI エスケープ付き (通常は黄、不一致は赤)
- `--format ps1` — bash の `PS1` 用に非印字マーカー `\[ \]` で囲んだ color 出力
- `--show-mismatch` — git/gh 実状態が profile と不一致のとき `[oss !]` のように `!` を付与

組み込みレシピは [shell-integration.md](shell-integration.md) を参照してください。

---

## guard / install-guard / uninstall-guard

```
gospelo-github-identity install-guard [--dir DIR] [--tools gh,git]
gospelo-github-identity uninstall-guard [--dir DIR] [--tools gh,git]
gospelo-github-identity guard --tool {gh,git} --real <path> -- <args...>
```

`gh` (opt-in で `git`) を PATH シムでシャドウし、書き込みの**操作対象** (`--repo` / `git -C` / 対象 repo の remote) から identity を解決して強制します。profile が `gh.owners` を宣言していれば対象 owner から逆引きした profile のトークンを呼び出しごとに注入し (enforce 型)、未宣言 owner への書き込みは実行前に拒否します (fail-closed)。owners 未宣言の設定では従来どおり cwd の profile と照合する check 型で動きます。`guard` はシムが呼び出すランタイムゲートで、通常は直接実行しません。

- `install-guard --dir` — シム設置先 (既定: `~/.gospelo-github-identity/bin`)
- `install-guard --tools` — シャドウ対象 (既定: `gh` のみ。`git push` もガードするには `--tools gh,git`)

インストール後、シムディレクトリを **PATH の先頭**に追加して有効化します。動作原理・書き込み分類・fail-open/fail-closed の境界・環境変数は [enforcement.md](enforcement.md) を参照してください。

| 終了コード (install-guard) | 意味 |
|---|---|
| 0 | 1 つ以上のシムをインストール |
| 1 | シム未インストール (対象ツールが PATH にない / 解決されたコマンドが `guard` 非対応) |

---

## install-commit-hook / uninstall-commit-hook / strip-coauthors

```
gospelo-github-identity install-commit-hook [--dir DIR] [--force]
gospelo-github-identity uninstall-commit-hook [--dir DIR]
gospelo-github-identity strip-coauthors <commit-msg-file>
```

グローバル `commit-msg` フックとして、全コミットメッセージから `Co-authored-by:` と `Claude-Session:` トレーラを除去してからコミットをブロックします。`strip-coauthors` はフックが呼ぶワーカーで、通常は直接実行しません。

- `install-commit-hook --dir` — フック設置先 (既定: `~/.gospelo-github-identity/git-hooks`)
- `install-commit-hook --force` — 別値の global `core.hooksPath` が既設でも上書き

ディスパッチャは処理後に各リポジトリ自身の `.git/hooks/<name>` へ**チェーン**するため、husky / pre-commit 等の既存フックは動き続けます。詳細は [enforcement.md](enforcement.md#commit-msg-フック-co-authored-by-除去) を参照してください。

| 終了コード (install-commit-hook) | 意味 |
|---|---|
| 0 | インストール完了 |
| 1 | 別の global `core.hooksPath` が既設 (`--force` で再実行) |
| 2 | `core.hooksPath` の設定に失敗 |
