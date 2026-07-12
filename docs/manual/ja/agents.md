# AI エージェント統合

Claude Code / GitHub Copilot などの自律エージェントに `git push` / `gh pr create` / `gh release` といった GitHub 書き込みを任せるためのセットアップです。

## なぜエージェントには専用の対策が要るのか

人間向けの identity 管理は、エージェントの実行環境で前提が崩れます:

- **エージェントは非対話シェルで動く** — direnv のようなシェルフックはプロンプト表示時に発火するため、エージェントの `bash -c ...` では `.envrc` が評価されません ([direnv/direnv#262](https://github.com/direnv/direnv/issues/262))。「cd したら自動で切り替わる」仕組みは効いていない前提で設計する必要があります。
- **cwd と操作対象がズレる** — エージェントは `gh --repo owner/x pr create` や `git -C /path push` を任意の場所から実行します。cwd 基準の仕組みは操作対象を見ていません。
- **人間が見ていない** — プロンプトの `[oss !]` 表示や check の WARNING は、読む人間がいなければ意味がありません。
- **gh のアクティブアカウントはマシングローバル** — エージェントが動いている間に別ターミナルで `gh auth switch` されうる状態です。

guard はこの 4 つすべてに答えます: PATH シムなので非対話シェルでも常時有効、identity は**操作対象から**解決され (`gh.owners` の逆引き)、トークンは呼び出しごとに注入されるためグローバルなアクティブアカウントに依存しません。その上に、**エージェント自身に事前チェックを課す**層 (skill) を重ねます。

## 多層防御の構成

| 層 | 仕組み | 効く範囲 |
|---|---|---|
| 強制 (外側) | [guard](enforcement.md#guard-gh--git-の-path-シム) — PATH シムが書き込み直前に照合しブロック | エージェントの設定に関係なく、名前ベースの gh/git 呼び出しすべて |
| 自己チェック (内側) | agent skill — 書き込み操作の前に `check` を実行し、不一致なら操作を中止 | skill を読むエージェント (Claude Code / Copilot) |
| 土台 | [doctor](cli-reference.md#doctor) — 構成の堅牢さを事前に監査 | セットアップ時・定期点検 |

guard が最後の砦、skill は「ブロックされる前にエージェントが自分で気づいて止まる」ための冗長化です。skill はエージェントがそれを無視すれば効きませんが、guard は無視できません。

## セットアップ手順

人間が 1 回だけ実施します。以後、そのマシンはエージェントが安全に操作できる状態を保ちます。

```bash
# 1. config を作成 (profile / paths / owners を宣言 — owners が enforce 型の要)
gospelo-github-identity init

# 2. 構成を監査 (素の github.com remote、鍵未固定のエイリアス、未ログイン、環境の GH_TOKEN 残留等)
gospelo-github-identity doctor --sweep

# 3. guard をインストール (gh をシャドウ。git push もガードするなら --tools gh,git)
gospelo-github-identity install-guard --tools gh,git
export PATH="$HOME/.gospelo-github-identity/bin:$PATH"   # ~/.zshrc / ~/.bashrc に追記

# 4. 動作確認 — どの cwd からでも操作対象の identity が選ばれる
command -v gh          # シムのパスが出れば guard が有効
gospelo-github-identity check
```

guard の導入後は、direnv による `GH_TOKEN` 注入 (`.envrc`) は**廃止できます**。むしろ環境に常駐する `GH_TOKEN` は guard の注入を上書きし、シム迂回経路を認証してしまうため、外すのが正解です (`doctor` が WARN で検出します)。

**PATH がエージェントに届いているかを必ず確認してください。** シェル rc を読まない起動方法 (launchd、IDE 直接起動など) では、エージェントの起動環境側に PATH を設定する必要があります。エージェントのシェルで `command -v gh` を実行させ、シムのパスが返ることを確認するのが確実です。

## agent skill のインストール

skill はリポジトリの [skills/](https://github.com/gospelo-dev/github-identity/tree/main/skills) に同梱されています。

### Claude Code

```bash
# プロジェクト単位 (推奨)
mkdir -p .claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   .claude/skills/gospelo-github-identity-check/skill.md

# グローバル (全プロジェクトに適用)
mkdir -p ~/.claude/skills/gospelo-github-identity-check
cp /path/to/gospelo-github-identity/skills/claude/skill.md \
   ~/.claude/skills/gospelo-github-identity-check/skill.md
```

インストール後、Claude Code を再起動 (または skill の再読み込みを実行) してください。

### GitHub Copilot

Copilot の skill 仕様は流動的です。[skills/copilot/README.md](https://github.com/gospelo-dev/github-identity/blob/main/skills/copilot/README.md) の現時点の推奨配置に従ってください。`copilot/skill.md` の本文はエージェント非依存の Markdown なので、他のエージェントのシステムプロンプト断片としても使えます。

### skill の挙動

skill は `git push` / PR 作成 / リリース / パッケージ公開などの書き込み操作の**前に** `gospelo-github-identity check` を実行するようエージェントに指示します:

| check の終了コード | skill が指示する行動 |
|---|---|
| `0` (一致) | 黙ってそのまま続行 (摩擦ゼロ) |
| `1` (不一致) | **書き込みを中止**し、差分と `switch <profile>` コマンドを提示、ユーザーの判断を待つ |
| `2` (ツールエラー) | エラーをそのままユーザーに提示。デフォルト identity への暗黙フォールバックはしない |

## 運用上の注意

- `GOSPELO_GITHUB_IDENTITY_SKIP=1` は guard の明示的バイパスです。エージェントのシステムプロンプトや自動化スクリプトに**恒常的に埋め込まないでください** (ガードが無意味になります)。人間が意図を持って 1 回だけ使う脱出ハッチです。
- guard のブロックメッセージには修正コマンド (`switch <profile>`) が含まれます。エージェントはそれを実行して再試行できますが、それこそが正しい復旧手順なので問題ありません — ブロックされたのは「間違った identity のまま書き込むこと」であり、switch 後の書き込みは正しい identity で行われます。
- 定期的に `doctor --sweep` を実行する (または人間のレビュー時に確認する) と、リポジトリ追加時の構成漏れに早く気づけます。
