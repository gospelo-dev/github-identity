# クイックスタート

インストールから「check で照合 → switch で切替」までを 5 分で通します。強制レイヤ (guard / commit-msg フック) は動きを理解してから [enforcement.md](enforcement.md) で追加してください。

## 前提

- Python 3.11 以降
- `git` がインストール済み
- [`gh` CLI](https://cli.github.com/) がインストール済みで、**使い分けたい各アカウント**で認証済みであること:

```bash
gh auth login --hostname github.com    # アカウントごとに 1 回
gh auth status                         # 認証済みアカウントの一覧を確認
```

## インストール

```bash
uv tool install gospelo-github-identity
```

確認:

```bash
gospelo-github-identity --version
```

## 1. 設定を作る

対話的に `~/.config/gospelo-github-identity/config.yml` を作成します:

```bash
gospelo-github-identity init
```

入力例:

```
Welcome to gospelo-github-identity init.
Config file will be saved to: /Users/you/.config/gospelo-github-identity/config.yml

Profile name: oss
Description (optional): Personal OSS work
git user.name: your-oss-login
git user.email: you@example.com
gh CLI account login: your-oss-login
GitHub owners this identity writes to, comma-separated (enables target-aware guard enforcement) (optional): your-oss-login, your-oss-org
Paths (one per line, empty line to finish):
  > ~/projects/oss/**
  >
Add another profile? [y/N]: y

Profile name: work
Description (optional): Company work
git user.name: your-work-name
git user.email: you@company.com
gh CLI account login: your-work-login
GitHub owners this identity writes to, comma-separated (enables target-aware guard enforcement) (optional): your-company-org
Paths (one per line, empty line to finish):
  > ~/projects/work/**
  >
Add another profile? [y/N]: n
Default profile (one of: oss, work) [leave blank for none]:

Saved: /Users/you/.config/gospelo-github-identity/config.yml
```

対話入力をスキップしたい場合:

```bash
# 同梱テンプレートをコピーして $EDITOR (既定: vi) で開く
gospelo-github-identity init --from-template

# 同梱テンプレートを stdout に出力 (リダイレクト用)
gospelo-github-identity init --show-example > my-config.yml
```

サンプル設定 (basic / minimal / advanced) は [examples/](https://github.com/gospelo-dev/github-identity/tree/main/examples) にあります。スキーマの詳細は [config-format.md](config-format.md) を参照してください。

## 2. profile 解決を確認する

```bash
gospelo-github-identity list      # 登録した profile の一覧
gospelo-github-identity detect    # いまのディレクトリを支配する profile 名
```

`detect` が意図した profile 名を返さない場合は `paths` の glob を見直します ([troubleshooting.md](troubleshooting.md#path-glob-がマッチしない--意図しない-profile-が選ばれる) 参照)。

## 3. 期待と実状態を照合する

管理対象のリポジトリに移動して:

```bash
cd ~/projects/oss/your-repo
gospelo-github-identity check
```

```
=== Identity Check ===
Working dir: /Users/you/projects/oss/your-repo
Matched profile: oss (via pattern: ~/projects/oss/**)

[git]
  user.name  : your-oss-login  (expected: your-oss-login )  OK
  user.email : you@example.com (expected: you@example.com)  OK
[gh CLI]
  login      : your-work-login (expected: your-oss-login )  NG

WARNING: gh CLI account does not match expected profile.
Run `gospelo-github-identity switch oss` to fix.
```

`OK: identity matches profile 'oss'.` なら一致、`NG` 行があれば取り違えです。

## 4. 一括で切り替える

```bash
gospelo-github-identity switch oss
```

ローカル `git config user.name` / `user.email` の設定と `gh auth switch -u <account>` を一括適用します。`--dry-run` で予定だけ確認、`--global` でユーザー全体に適用できます。

切替後にもう一度 `check` を実行し、すべて `OK` になることを確認してください。

## 5. 設定の堅牢さを監査する

いま一致していても、「global 設定を継承しているだけ」「remote が素の `git@github.com`」のような**壊れやすい構成**は check では見えません。doctor で監査します:

```bash
gospelo-github-identity doctor           # いまのリポジトリを監査
gospelo-github-identity doctor --sweep   # profile 配下の全リポジトリを一括監査
```

`WARN` / `FAIL` が出たら指示に従って解消します。詳細は [cli-reference.md](cli-reference.md#doctor) を参照してください。

## 次のステップ

- [enforcement.md](enforcement.md) — 不一致の書き込みを実行前にブロックする guard と、`Co-Authored-By` を除去する commit-msg フック
- [agents.md](agents.md) — Claude Code / Copilot などの AI エージェントに GitHub 書き込みを任せる場合のセットアップ
- [shell-integration.md](shell-integration.md) — プロンプトに profile を常時表示する
