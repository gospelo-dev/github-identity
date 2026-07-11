# シェル統合ガイド

`gospelo-github-identity` をシェルや既存の開発フローに組み込むレシピ集です。

## PS1 / プロンプト表示

### bash

```bash
PS1='$(gospelo-github-identity prompt --format=ps1 --show-mismatch) \w \$ '
```

`--show-mismatch` を付けると、git/gh の実状態が profile と一致していない場合にプロンプトが赤く `[oss !]` のように表示されます。

### zsh

`PROMPT_SUBST` を有効にし、`%F`/`%f` で色を付ける方が綺麗:

```zsh
setopt PROMPT_SUBST

_identity_prompt() {
  local label
  label=$(gospelo-github-identity prompt --format=plain --show-mismatch)
  if [[ -z "$label" ]]; then
    return
  fi
  if [[ "$label" == *"!"* ]]; then
    print -n "%F{red}${label}%f"
  else
    print -n "%F{yellow}${label}%f"
  fi
}

PROMPT='$(_identity_prompt) %~ %# '
```

### fish

```fish
function fish_right_prompt
  set -l label (gospelo-github-identity prompt --format=plain --show-mismatch)
  if test -n "$label"
    if string match -q "*!*" -- $label
      set_color red
    else
      set_color yellow
    end
    echo -n $label
    set_color normal
  end
end
```

> **注意**: `gospelo-github-identity prompt` は config 不在時にも黙って空文字列を返すため、シェルの動作を止めません。例外を流したい場合は `check` を別途呼び出してください。

## direnv 統合

リポジトリに入った瞬間に `check` を走らせて警告したい場合、`.envrc` で:

```bash
# .envrc
gospelo-github-identity check >&2 || echo "WARNING: identity mismatch (see above)" >&2
```

`direnv allow` を実行しておけば、`cd` するたびに自動で表示されます。

## pre-commit hook 統合

コミット前に強制チェックする最も簡易な方法は `.git/hooks/pre-commit` に直接書く:

```bash
#!/usr/bin/env bash
gospelo-github-identity check
status=$?
if [[ $status -ne 0 ]]; then
  echo "" >&2
  echo "Identity check failed. Refusing to commit." >&2
  echo "Run 'gospelo-github-identity switch <profile>' to fix." >&2
  exit 1
fi
```

`pre-commit` フレームワークを使っているなら `repo: local` で:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: gospelo-github-identity-check
        name: gospelo-github-identity check
        entry: gospelo-github-identity check
        language: system
        pass_filenames: false
        stages: [commit]
```

## CI で使わない

gospelo-github-identity は **ローカル開発時の取り違え防止** が目的です。CI 環境では git config / gh CLI のアカウントは固定の bot アカウントが期待されるため、`check` を走らせる意味は通常ありません。CI スクリプトには組み込まないでください。

## トラブルシューティング

### `gh auth switch` が失敗する

事前に対象アカウントで `gh auth login --hostname github.com` を実行している必要があります。`gh auth status` で現在認証済みのアカウント一覧を確認してください。

### `git config --local` が失敗する

`switch` のデフォルトは `--local` なので、git work tree の外（普通のディレクトリ）で実行すると exit 2 になります。`--global` を付けるか、リポジトリに `cd` してから再実行してください。

### path glob がマッチしない

`detect` で実際にどの profile が選ばれるかを確認できます:

```bash
gospelo-github-identity detect --cwd ~/projects/oss/foo
```

config の `paths` が `~` 始まりであること、`**` を入れているか（再帰マッチが必要な場合）を確認してください。
