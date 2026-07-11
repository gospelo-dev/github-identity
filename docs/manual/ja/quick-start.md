# クイックスタート

## 前提

- Python 3.11 以降
- `git` がインストール済み
- [`gh` CLI](https://cli.github.com/) がインストール済みで、使用予定の各アカウントで `gh auth login --hostname github.com` 済みであること

## インストール

```bash
pip install gospelo-github-identity
```

確認:

```bash
gospelo-github-identity --version
```

## 1. 設定を作る

対話的に `~/.config/gospelo-github-identity/config.yml` を作成:

```bash
gospelo-github-identity init
```

対話入力をスキップしたい場合は、同梱テンプレートをコピーして `$EDITOR` で開く方法もあります:

```bash
# 同梱テンプレートをコピー + $EDITOR (既定: vi) で開く
gospelo-github-identity init --from-template

# 同梱テンプレートを stdout に出力 (パイプ用)
gospelo-github-identity init --show-example > ~/.config/gospelo-github-identity/config.yml
```

サンプル設定 (basic / minimal / advanced) は [examples/](https://github.com/gospelo-dev/gospelo-github-identity/tree/main/examples) を参照してください。

入力例:

```
Welcome to gospelo-github-identity init.
Config file will be saved to: /Users/you/.config/gospelo-github-identity/config.yml

Profile name: oss
Description (optional): Personal OSS work
git user.name: your-oss-login
git user.email: you@example.com
gh CLI account login: your-oss-login
Paths (one per line, empty line to finish):
  > ~/projects/gospelo-dev/**
  > ~/projects/personal/**
  >
Add another profile? [y/N]: y

Profile name: work
Description (optional): Company work
git user.name: your-oss-login
git user.email: you@company.com
gh CLI account login: your-work-login
Paths (one per line, empty line to finish):
  > ~/projects/work/**
  >
Add another profile? [y/N]: n
Default profile (one of: oss, work) [leave blank for none]: oss

Saved: /Users/you/.config/gospelo-github-identity/config.yml
```

## 2. 確認

```bash
gospelo-github-identity list
```

表で profile 一覧が表示されます。

## 3. 期待 profile と実状態を照合

OSS リポジトリに移動して:

```bash
cd ~/projects/gospelo-dev/your-repo
gospelo-github-identity check
```

`OK: identity matches profile 'oss'.` が出れば現在の git/gh 設定は profile と一致しています。`NG` の行があれば取り違えています。

## 4. 一括で切替

```bash
gospelo-github-identity switch oss
```

ローカル `git config user.name` / `user.email` と `gh auth switch -u <account>` を一括適用します。

`--global` でユーザー全体に適用、`--dry-run` で実際には変更せず予定だけ表示します。

## 次のステップ

- [シェル統合](shell-integration.md): `PS1` で常時 profile を表示
- [CLI リファレンス](cli-reference.md): 全サブコマンドの詳細
- [設定ファイル仕様](config-format.md): `paths` glob の細かい挙動
