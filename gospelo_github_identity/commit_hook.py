# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``commit-msg`` hook that sanitizes AI-related traces from commit messages.

Two layers of protection:

   1. **Strip + block** — ``Co-authored-by:`` and ``Claude-Session:`` trailer
      lines are removed, then the commit is rejected so the user notices and
      retries with the cleaned message.
   2. **Block** — after stripping, the message is scanned for forbidden
      AI-related words (Claude, Copilot, Fable, Opus, Sonnet, Haiku,
      Anthropic). If any remain the commit is **rejected** so no AI provenance
      leaks into history.

Why a git hook rather than the ``gh``/``git`` PATH shim:

  * ``git`` funnels the *final* message (from ``-m`` / ``-F`` / the editor /
    ``--amend``) through the ``commit-msg`` hook, so one hook covers every path.
  * The hook fires even when ``git`` is called by absolute path or by an IDE,
    because git itself runs it — no name-based shim gap.
  * It runs only at commit time, so there is no per-call latency on the ``git``
    hot path (unlike shadowing ``git`` itself).

Installation uses a global ``core.hooksPath`` dispatcher that **chains** to each
repository's own ``.git/hooks/<name>`` so existing hooks (husky, pre-commit,
…) keep working.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

DEFAULT_HOOKS_DIR = "~/.gospelo-github-identity/git-hooks"

# Match a ``Co-authored-by:`` trailer line (key is case-insensitive in git).
_COAUTHOR_RE = re.compile(r"^[ \t]*co-authored-by[ \t]*:.*$", re.IGNORECASE)

# Match a ``Claude-Session:`` trailer line (AI session URL trace).
_AI_SESSION_RE = re.compile(r"^[ \t]*claude-session[ \t]*:.*$", re.IGNORECASE)

_STRIP_PATTERNS = (_COAUTHOR_RE, _AI_SESSION_RE)

# AI-related words that must not appear in a committed message.
_FORBIDDEN_WORDS_RE = re.compile(
    r"\b(?:Claude|Copilot|Fable|Opus|Sonnet|Haiku|Anthropic)\b",
    re.IGNORECASE,
)

# Standard client-side hook names. The dispatcher must exist for every hook the
# user might rely on, otherwise setting core.hooksPath would silently DISABLE a
# repo's own hooks of that type.
_GIT_HOOK_NAMES = (
    "applypatch-msg", "pre-applypatch", "post-applypatch",
    "pre-commit", "pre-merge-commit", "prepare-commit-msg", "commit-msg",
    "post-commit", "pre-rebase", "post-checkout", "post-merge", "pre-push",
    "pre-auto-gc", "post-rewrite", "post-index-change", "sendemail-validate",
)


# ---------------------------------------------------------------------------
# Pure stripping logic
# ---------------------------------------------------------------------------


def strip_coauthored_by(text: str) -> str:
    """Return ``text`` with AI-trace trailer lines removed.

    Removes ``Co-authored-by:`` and ``Claude-Session:`` lines.
    Trailing blank lines left behind by the removal are also trimmed. A single
    trailing newline is preserved when the message is non-empty.
    """
    lines = text.splitlines()
    kept = [ln for ln in lines if not any(p.match(ln) for p in _STRIP_PATTERNS)]
    while kept and kept[-1].strip() == "":
        kept.pop()
    if not kept:
        return ""
    return "\n".join(kept) + "\n"


def find_forbidden_words(text: str) -> list[str]:
    """Return distinct forbidden AI-related words found in ``text``."""
    return sorted({m.group() for m in _FORBIDDEN_WORDS_RE.finditer(text)}, key=str.lower)


def strip_main() -> None:
    """``gospelo-github-identity strip-coauthors <commit-msg-file>`` (called by the hook)."""
    parser = argparse.ArgumentParser(prog="gospelo-github-identity strip-coauthors")
    parser.add_argument("message_file", help="Path to the commit message file.")
    args = parser.parse_args()

    path = Path(args.message_file)
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"gospelo-github-identity strip-coauthors: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(0)  # never block the commit on our own IO error

    cleaned = strip_coauthored_by(original)
    stripped = cleaned != original
    if stripped:
        path.write_text(cleaned, encoding="utf-8")

    forbidden = find_forbidden_words(cleaned)
    if forbidden:
        words = ", ".join(forbidden)
        print(
            f"gospelo-github-identity strip-coauthors: BLOCKED — commit message "
            f"contains forbidden AI-related words: {words}\n"
            f"  Edit the message to remove these words and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    if stripped:
        print(
            "gospelo-github-identity strip-coauthors: BLOCKED — removed "
            "Co-Authored-By or Claude-Session trailers from the commit message.\n"
            "  Review the cleaned message and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.exit(0)


# ---------------------------------------------------------------------------
# Install / uninstall (global core.hooksPath dispatcher)
# ---------------------------------------------------------------------------


def _gospelo_github_identity_command() -> str:
    found = shutil.which("gospelo-github-identity")
    if found:
        return found
    raise RuntimeError(
        "gospelo-github-identity is not installed on PATH. "
        "Install it with `uv tool install gospelo-github-identity`, "
        "then run install-commit-hook again. Direct Python execution is not supported."
    )


def _git_global(get_args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "config", "--global", *get_args],
                          capture_output=True, text=True, check=False)


def _dispatcher_body(gi_cmd: str) -> str:
    return (
        "#!/bin/sh\n"
        "# gospelo-github-identity global git-hooks dispatcher. Managed by gospelo-github-identity.\n"
        '# Strips AI traces and blocks forbidden words on commit-msg, then chains to the repo\'s own hook.\n'
        'hook="$(basename "$0")"\n'
        f'if [ "$hook" = "commit-msg" ] && [ -n "$1" ]; then\n'
        f'  {gi_cmd} strip-coauthors "$1" || exit $?\n'
        "fi\n"
        '# Chain to the repository\'s real hook (NOT core.hooksPath, to avoid recursion).\n'
        'gitdir="$(git rev-parse --git-dir 2>/dev/null)"\n'
        'if [ -n "$gitdir" ] && [ -x "$gitdir/hooks/$hook" ]; then\n'
        '  exec "$gitdir/hooks/$hook" "$@"\n'
        "fi\n"
        "exit 0\n"
    )


def install_main() -> None:
    parser = argparse.ArgumentParser(prog="gospelo-github-identity install-commit-hook")
    parser.add_argument("--dir", default=DEFAULT_HOOKS_DIR, help="Global hooks dir.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing global core.hooksPath that points elsewhere.",
    )
    args = parser.parse_args()

    hooks_dir = Path(args.dir).expanduser()
    current = _git_global(["--get", "core.hooksPath"]).stdout.strip()
    desired = str(hooks_dir)
    if current and current != desired and not args.force:
        print(
            f"WARNING: global core.hooksPath is already set to {current!r}.\n"
            f"Not overwriting. Either re-run with --force, or chain manually.\n"
            f"The dispatcher itself chains to each repo's .git/hooks, but it does "
            f"not chain to another global hooksPath.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        gi_command = _gospelo_github_identity_command()
    except RuntimeError as exc:
        print(f"gospelo-github-identity install-commit-hook: {exc}", file=sys.stderr)
        sys.exit(1)

    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Write the dispatcher and link every standard hook name to it.
    dispatcher = hooks_dir / "_dispatch"
    dispatcher.write_text(_dispatcher_body(gi_command), encoding="utf-8")
    dispatcher.chmod(dispatcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    for name in _GIT_HOOK_NAMES:
        link = hooks_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        try:
            link.symlink_to(dispatcher.name)  # relative symlink to _dispatch
        except OSError:
            shutil.copyfile(dispatcher, link)
            link.chmod(link.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Set global core.hooksPath after all validation succeeds.
    set_result = _git_global(["core.hooksPath", desired])
    if set_result.returncode != 0:
        print(f"ERROR: failed to set core.hooksPath: {set_result.stderr.strip()}", file=sys.stderr)
        sys.exit(2)

    print(f"Installed global commit-msg guard at: {hooks_dir}")
    print(f"  git config --global core.hooksPath = {desired}")
    print("Every `git commit` now strips AI traces (Co-Authored-By, Claude-Session)")
    print("and blocks forbidden AI-related words (Claude, Fable, Opus, Sonnet, Haiku, Anthropic).")
    print("Note: repos that set their OWN core.hooksPath (e.g. husky) override this; install per-repo there.")
    print("Uninstall: gospelo-github-identity uninstall-commit-hook")
    sys.exit(0)


def uninstall_main() -> None:
    parser = argparse.ArgumentParser(prog="gospelo-github-identity uninstall-commit-hook")
    parser.add_argument("--dir", default=DEFAULT_HOOKS_DIR)
    args = parser.parse_args()
    hooks_dir = Path(args.dir).expanduser()

    current = _git_global(["--get", "core.hooksPath"]).stdout.strip()
    if current == str(hooks_dir):
        _git_global(["--unset", "core.hooksPath"])
        print("Unset global core.hooksPath.")
    elif current:
        print(
            f"global core.hooksPath is {current!r} (not ours); leaving it untouched.",
            file=sys.stderr,
        )

    if hooks_dir.exists():
        for name in (*_GIT_HOOK_NAMES, "_dispatch"):
            f = hooks_dir / name
            if f.exists() or f.is_symlink():
                f.unlink()
        try:
            hooks_dir.rmdir()
        except OSError:
            pass
        print(f"Removed hook dispatcher from {hooks_dir}.")
    sys.exit(0)


if __name__ == "__main__":
    strip_main()
