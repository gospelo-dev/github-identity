# シェル統合ガイド

`gospelo-github-identity` を対話シェルの日常フローに組み込むレシピ集です。エージェント向けの強制レイヤは [enforcement.md](enforcement.md) / [agents.md](agents.md) を参照してください。

## プロンプトに profile を常時表示する

`prompt` サブコマンドは、マッチした profile 名を `[name]` 形式で出力します。`--show-mismatch` を付けると、実状態が profile と不一致のときに `[oss !]` と警告マーカーが付きます。未マッチ・config 不在では黙って空文字列になるため、プロンプトが崩れることはありません。

### bash

```bash
PS1='$(gospelo-github-identity prompt --format=ps1 --show-mismatch) \w \$ '
```

`--format=ps1` は ANSI 色を readline の非印字マーカー `\[ \]` で囲むため、行折り返しが乱れません。

### zsh

`PROMPT_SUBST` を有効にし、色は zsh の `%F`/`%f` で付ける方が扱いやすいです:

```zsh
setopt PROMPT_SUBST

_identity_prompt() {
  local label
  label=$(gospelo-github-identity prompt --format=plain --show-mismatch)
  [[ -z "$label" ]] && return
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

> `prompt` は常に exit 0 で、エラーも表示しません。エラーを見たいときは `check` を直接実行してください。

## direnv 統合

リポジトリに入った瞬間に照合結果を表示したい場合、`.envrc` に:

```bash
# .envrc
gospelo-github-identity check >&2 || echo "WARNING: identity mismatch (see above)" >&2
```

`direnv allow` しておけば `cd` のたびに自動表示されます。

> **注意**: direnv は対話シェルのフックで動くため、AI エージェントの非対話実行 (`bash -c ...`) では発火しません。エージェント対策としては direnv ではなく [guard](enforcement.md) を使ってください。

## pre-commit 統合

コミット前に照合を強制する最も簡単な方法は `.git/hooks/pre-commit` に直接書くことです:

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

[pre-commit](https://pre-commit.com/) フレームワークを使っている場合は `repo: local` で:

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

> `Co-Authored-By` トレーラの除去は pre-commit ではなく専用の [commit-msg フック](enforcement.md#commit-msg-フック-co-authored-by-除去) が担当します (どの経路の commit でも最終メッセージに効くため)。

## CI では使わない

gospelo-github-identity は**ローカル開発マシンでの取り違え防止**が目的です。CI 環境は固定の bot アカウントで動くため、ディレクトリ連動の照合を走らせる意味は通常ありません。CI スクリプトには組み込まないでください。
