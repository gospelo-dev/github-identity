# gospelo-github-identity ドキュメント

ディレクトリ連動 git/gh CLI アイデンティティガード `gospelo-github-identity` のドキュメント索引。

## このドキュメントについて

gospelo-github-identity は、現在の作業ディレクトリから「期待される profile」を解決し、ローカル `git config` と `gh` CLI のアクティブアカウントが一致しているかを検証・切替する CLI ツール。複数の GitHub アカウント（個人 OSS / 業務 / クライアント）を使い分ける開発者の取り違え事故を防ぎます。

対象読者:
- **利用者**: 複数アカウントを安全に運用したい開発者 → [クイックスタート](quick-start.md)
- **設定保守者**: チームや組織で標準 profile セットを定義したい人 → [設定ファイル仕様](config-format.md)

## ドキュメント一覧

| ファイル | 用途 |
|---|---|
| [quick-start.md](quick-start.md) | 5 分で始めるセットアップ手順 |
| [cli-reference.md](cli-reference.md) | 全サブコマンドとオプション、終了コード |
| [config-format.md](config-format.md) | `config.yml` のスキーマ詳細 |
| [shell-integration.md](shell-integration.md) | `PS1` / `direnv` / pre-commit との統合レシピ |

## 設計の方針

- **フォールバック禁止**: 設定ファイルが見つからない、glob にマッチしない、外部ツールが失敗、いずれの場合も明示的にエラーで停止します。意図的な例外は2つ: `prompt` はシェル動作を止めないために黙って空文字列を返し、`guard` シムは使える config が無い／どの profile にもマッチしないとき **fail-open**（本物のコマンドを実行。書き込み時は stderr に1行通知）します。これによりシムを入れても無関係な git/gh 作業を壊しません。
- **最小依存**: PyPI 依存は `PyYAML` のみ。`git` / `gh` は外部 CLI として呼び出します。
- **ディレクトリ起点**: profile 選択の主軸は「どこで作業しているか」。意図しないアカウント混入を防ぎます。

## 関連プロジェクト

- [gospelo-review](https://github.com/gospelo-dev/review) — PR レビュー自動化ツールキット。`pip install gospelo-review[identity]` で本ツールと連携。
