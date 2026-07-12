# gospelo-github-identity マニュアル

ディレクトリ連動 git/gh CLI アイデンティティガード `gospelo-github-identity` の利用マニュアルです。

## このツールについて

複数の GitHub アカウント (個人 OSS / 業務 / クライアント) を 1 台のマシンで使い分けると、「正しいリポジトリに、間違ったアカウントで書き込む」事故が起こります。gospelo-github-identity は、作業ディレクトリから「期待される identity (profile)」を解決し、実際の `git config` / `gh` CLI / SSH 認証と照合・切替・強制する CLI ツールです。

役割は 3 段階に分かれます:

| 段階 | コマンド | 何をするか |
|---|---|---|
| 可視化 | `prompt` / `detect` / `list` / `check` | いまの identity が期待と一致しているかを見える化する |
| 堅牢性監査 | `doctor` | 「一致し続ける設定になっているか」(継承頼み・鍵の固定漏れ等) を監査する |
| 強制 | `guard` / `commit-msg` フック | 書き込みの操作対象から identity を解決し、トークンを呼び出しごとに注入。不正な対象は実行前に拒否 (fail-closed)。エージェントの自律実行にも効く |

## 読む順序

| ドキュメント | 内容 | こんなとき |
|---|---|---|
| [quick-start.md](quick-start.md) | インストール〜最初の check/switch まで | まず動かしたい |
| [concepts.md](concepts.md) | profile・解決規則・identity 3 層の考え方 | 仕組みを理解したい |
| [cli-reference.md](cli-reference.md) | 全 13 サブコマンドの仕様と終了コード | オプションを調べたい |
| [config-format.md](config-format.md) | `config.yml` スキーマと glob 仕様 | 設定を書きたい |
| [enforcement.md](enforcement.md) | guard (PATH シム) と commit-msg フックの詳細 | 強制レイヤを入れたい |
| [agents.md](agents.md) | AI エージェント (Claude Code / Copilot) 統合 | エージェントに書き込みを任せたい |
| [shell-integration.md](shell-integration.md) | PS1 / direnv / pre-commit レシピ | シェルに組み込みたい |
| [troubleshooting.md](troubleshooting.md) | 症状別の対処 | 動かない・ブロックされた |

## 設計の方針

- **フォールバック禁止** — config 不在・glob 未マッチ・外部ツール失敗は明示的にエラーで停止します。意図的な例外は 2 つだけ: `prompt` はシェルを止めないため黙って空文字列を返し、`guard` は自分が統治しない状況 (config 不在、または owners 未宣言の check 型での未マッチディレクトリ) では本物のコマンドをそのまま通します ([enforcement.md](enforcement.md#fail-open--fail-closed-の境界) 参照)。
- **決定論的** — 判定はすべて純粋なパターンロジックです。LLM は一切使いません。
- **ローカル完結** — 通信は `gh api user` (アカウント確認) と、opt-in の `ssh -T` (SSH ログイン検証) のみです。
- **最小依存** — PyPI 依存は `PyYAML` のみ。`git` / `gh` は外部 CLI として呼び出します。

## 対象バージョン

このマニュアルは gospelo-github-identity **0.2.x** の実装に基づきます。0.2.0 で enforce 型アーキテクチャ (操作対象基準の解決 + `gh.owners` 逆引き + 呼び出しごとのトークン注入 + fail-closed) が実装されました。設計の背景は [設計ドキュメント](https://github.com/gospelo-dev/github-identity/blob/main/development/docs/architecture-enforce-fail-closed.md) を参照してください。
