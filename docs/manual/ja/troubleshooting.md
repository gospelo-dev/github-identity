# トラブルシューティング

症状別の対処集です。まず全体状況を掴むには `gospelo-github-identity doctor` が便利です。

## `Config file not found` (exit 2)

config がまだありません。`gospelo-github-identity init` で作成してください。旧バージョン (パッケージ名 `gospelo-identity` 時代) から移行した場合、設定は `~/.config/gospelo-identity/` に残っています — 新パス `~/.config/gospelo-github-identity/config.yml` へコピーしてください。

## path glob がマッチしない / 意図しない profile が選ばれる

`detect` で実際の解決結果を確認します:

```bash
gospelo-github-identity detect --cwd ~/projects/oss/foo
```

チェックポイント:

- `paths` は絶対パスまたは `~` 始まりで書けているか (`~` が展開されるのはパス先頭のみ)
- ディレクトリ以下すべてにマッチさせたい場合、glob が `**` で終わっているか (`~/projects/oss` は完全一致のみ、`~/projects/oss/**` が配下すべて)
- 複数 profile がマッチする場所では **literal prefix の最長一致**で勝敗が決まる ([config-format.md](config-format.md#マッチング規則))
- cwd は symlink 解決後の実パスで照合される — symlink 経由で入っている場合は実パス側を `paths` に書く

## `gh auth switch` が失敗する

対象アカウントで事前に認証していない状態です:

```bash
gh auth status                            # 認証済みアカウントの一覧
gh auth login --hostname github.com      # 足りないアカウントでログイン
```

## switch は成功するのに check / guard が NG のまま

`gh auth switch` は `hosts.yml` のアクティブラベルを切り替えるだけで、トークンの実体は再検証しません。keyring に残った credential が古い (別アカウントのトークンが `<account>` のラベルで保存されている) と、ラベル上は正しくても実体は別人です。check / guard は `gh api user` で**トークンの実体**を照合するため、この状態を NG として検出します。再ログインで解消します:

```bash
gh auth logout --hostname github.com --user <account>
gh auth login  --hostname github.com     # <account> としてブラウザで再認証
gospelo-github-identity check
```

## `git config --local` が失敗する (exit 2)

`switch` の既定は `--local` なので、git work tree の外で実行すると失敗します。リポジトリに `cd` してから再実行するか、ユーザー全体に適用したい場合は `--global` を付けてください。

## guard がブロックする (identity 不一致)

これは正常動作です — 対象リポジトリを支配する profile と identity が一致していません。ブロックメッセージの `fix:` 行のコマンドを実行してから再試行してください:

```bash
gospelo-github-identity switch <profile>
```

意図的に別 identity で 1 回だけ書き込みたい場合は明示的バイパスを使います:

```bash
GOSPELO_GITHUB_IDENTITY_SKIP=1 gh release create ...
```

## guard がブロックする (`no profile declares this owner`)

enforce 型の fail-closed が働いています — 書き込み対象の owner (`--repo` の値、または対象リポジトリの remote の owner) がどの profile の `gh.owners` にも宣言されていません。その owner への書き込みを今後も行うなら、意図する profile の `owners` に追加します:

```yaml
gh:
  account: your-login
  owners: [existing-org, new-org]   # ← 追加
```

一度きりの意図的な書き込みなら `GOSPELO_GITHUB_IDENTITY_SKIP=1` でバイパスします。

## guard がブロックする (`no resolvable target owner`)

repo 対象を持たない書き込み (`gh gist create` 等) を、どの profile にも属さないディレクトリから実行しています。統治されたディレクトリに移動するか、`--repo <owner>/<repo>` で対象を明示するか、`default_profile` を設定してください。

## doctor が `ambient credential in the environment` と警告する

シェル環境に `GH_TOKEN` / `GITHUB_TOKEN` が常駐しています (direnv の `.envrc` や shell rc の export が典型)。常駐トークンは guard の呼び出しごとの注入を**上書き**し、シムを迂回した経路も認証してしまうため、fail-closed が成立しません。direnv の注入を廃止し、export を削除してください。guard が対象に応じたトークンを毎回注入するので、常駐は不要です。

## guard を入れたら統治対象外のディレクトリで通知が出る

書き込み時に `directory not governed by any profile; passing through.` が出るのは仕様です (paths のタイポで「統治しているつもり」のディレクトリが素通しになっていることに気づけるように)。抑制したい場合は `GOSPELO_GITHUB_IDENTITY_QUIET=1` を設定します。ブロック通知は QUIET でも表示されます。

## install-guard が「壊れたシム」を理由に拒否する

PATH 上の `gospelo-github-identity` が `guard` サブコマンドを持たない古いビルドです。現行ビルドを再インストールしてから再実行してください:

```bash
pip install -U gospelo-github-identity   # または uv tool install --force .
gospelo-github-identity install-guard
```

## guard が効いていない (シムを経由しない)

```bash
command -v gh    # シムのパス (~/.gospelo-github-identity/bin/gh) が出るか
```

- シムディレクトリが PATH の**先頭**にあるか確認 (`export PATH="$HOME/.gospelo-github-identity/bin:$PATH"`)
- エージェント・IDE などシェル rc を読まないプロセスには、その起動環境側で PATH を設定する必要があります ([agents.md](agents.md#セットアップ手順))
- 絶対パス呼び出し (`/usr/bin/git push`) はシムを通りません — これは既知の限界です ([enforcement.md](enforcement.md#限界))

## install-commit-hook が拒否される (exit 1)

global `core.hooksPath` が別の値に設定済みです。現在の値を確認し、上書きしてよければ `--force` を付けます:

```bash
git config --global core.hooksPath      # 現在の設定を確認
gospelo-github-identity install-commit-hook --force
```

## commit-msg フックが発火しないリポジトリがある

そのリポジトリが**独自の** `core.hooksPath` を設定している場合 (husky 等)、リポジトリ設定が global を上書きするためディスパッチャは呼ばれません。そのリポジトリのフック構成に `gospelo-github-identity strip-coauthors` を個別に組み込んでください。

## check の `[ssh]` 行が `--` になる

スキップ判定です (失敗ではありません)。origin が SSH remote でない (HTTPS / remote なし)、ホストに到達できない、または `ssh` バイナリがない場合に出ます。SSH 検証を有効にしたい場合は origin を SSH エイリアス remote に切り替えてください。`doctor` が remote の形式を監査します。
