#!/usr/bin/env bash
# このリポジトリのテスト。手元の pr-gate.sh と GitHub Actions（ci.yml）の両方が実行する。
# リポジトリのルートで実行される前提（作業ツリーのルートに移動してから動く）。
# 中身はリポジトリに合わせて書き換えてよい。既定ではファイル構成からテストを自動で選ぶ:
#   *.sh → shellcheck / package.json → npm の lint・test・build / pyproject.toml → pytest
# 依存は lock ファイルどおりにだけ入れる（その時点の最新版を入れない。サプライチェーン攻撃への備え）。
# lock ファイルが無ければ止まる。
# 環境変数 PR_GATE_BASE（pr-gate.sh が渡す PR の向き先）を使えば、差分に応じたテストにもできる。
if [ -z "${BASH_VERSINFO:-}" ] || (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4) )); then
  echo "bash 4.4 以上が必要です（現在: ${BASH_VERSION:-不明}）。macOS では brew install bash" >&2
  exit 1
fi
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

ran=false

mapfile -t sh_files < <(git ls-files '*.sh')
if (( ${#sh_files[@]} > 0 )); then
  command -v shellcheck >/dev/null || { echo "shellcheck が必要です。" >&2; exit 1; }
  echo "== shellcheck (${#sh_files[@]} files)"
  shellcheck "${sh_files[@]}"
  ran=true
fi

if [[ -f package.json ]]; then
  echo "== npm"
  [[ -f package-lock.json ]] ||
    { echo "package-lock.json がありません。npm install で作ってコミットしてください（lock なしでは版を固定できない）。" >&2; exit 1; }
  npm ci   # package-lock.json どおりに入れる（合わなければ失敗する）
  npm run --if-present lint
  npm test --if-present
  npm run --if-present build
  ran=true
fi

if [[ -f pyproject.toml ]]; then
  echo "== python"
  command -v uv >/dev/null || { echo "uv が必要です（https://docs.astral.sh/uv/）。" >&2; exit 1; }
  [[ -f uv.lock ]] ||
    { echo "uv.lock がありません。uv lock で作ってコミットしてください（lock なしでは版を固定できない）。" >&2; exit 1; }
  # --locked: uv.lock が pyproject.toml と合っていなければ止まる。Python の版は .python-version で固定する
  # pytest は optional-dependencies の dev にあるので --extra dev を付ける
  uv sync --locked --extra dev
  if [[ -d tests ]]; then uv run --locked --extra dev pytest; fi
  ran=true
fi

if [[ "$ran" == false ]]; then
  echo "実行するテストがありません（scripts/ci.sh を編集して追加してください）。"
fi
