# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.commit_hook`` — Co-Authored-By stripping plus
the global commit-msg hook install/uninstall."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gospelo_github_identity import commit_hook


# ---------------------------------------------------------------------------
# strip_coauthored_by (pure)
# ---------------------------------------------------------------------------


def test_strips_single_trailer():
    msg = "feat: thing\n\nbody\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
    assert commit_hook.strip_coauthored_by(msg) == "feat: thing\n\nbody\n"


def test_strips_all_coauthors_including_humans():
    msg = (
        "fix: x\n\n"
        "Co-authored-by: Alice <alice@example.com>\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n"
    )
    assert commit_hook.strip_coauthored_by(msg) == "fix: x\n"


def test_case_insensitive_and_leading_space():
    msg = "t\n\n   co-AUTHORED-by:  Bob <b@x>\n"
    assert commit_hook.strip_coauthored_by(msg) == "t\n"


def test_keeps_non_coauthor_trailers():
    msg = "t\n\nSigned-off-by: Me <me@x>\nCo-authored-by: AI <a@x>\n"
    assert commit_hook.strip_coauthored_by(msg) == "t\n\nSigned-off-by: Me <me@x>\n"


def test_no_coauthor_is_unchanged():
    msg = "just a message\n\nwith body\n"
    assert commit_hook.strip_coauthored_by(msg) == msg


def test_empty_after_strip():
    assert commit_hook.strip_coauthored_by("Co-authored-by: X <x@y>\n") == ""


def test_strip_main_rewrites_file(tmp_path, monkeypatch):
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text("feat: y\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["strip-coauthors", str(f)])
    with pytest.raises(SystemExit) as exc:
        commit_hook.strip_main()
    assert exc.value.code == 0
    assert f.read_text(encoding="utf-8") == "feat: y\n"


# ---------------------------------------------------------------------------
# install / uninstall (sandboxed global git config)
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox_git_global(tmp_path, monkeypatch):
    """Redirect `git config --global` to a temp file (never touch the real one)."""
    cfg = tmp_path / "gitconfig"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return cfg


def _global_hookspath() -> str:
    return subprocess.run(
        ["git", "config", "--global", "--get", "core.hooksPath"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()


def test_install_and_uninstall_commit_hook(sandbox_git_global, tmp_path, monkeypatch):
    hooks_dir = tmp_path / "ghooks"
    monkeypatch.setattr("shutil.which", lambda n: "/usr/local/bin/gospelo-github-identity"
                        if n == "gospelo-github-identity" else None)

    monkeypatch.setattr("sys.argv", ["install-commit-hook", "--dir", str(hooks_dir)])
    with pytest.raises(SystemExit) as exc:
        commit_hook.install_main()
    assert exc.value.code == 0

    # commit-msg dispatcher exists and core.hooksPath is set to our dir.
    assert (hooks_dir / "commit-msg").exists()
    assert (hooks_dir / "pre-commit").exists()  # chained passthrough preserved
    assert _global_hookspath() == str(hooks_dir)
    body = (hooks_dir / "_dispatch").read_text()
    assert "strip-coauthors" in body and "git rev-parse --git-dir" in body

    # Uninstall unsets hooksPath and removes the dir.
    monkeypatch.setattr("sys.argv", ["uninstall-commit-hook", "--dir", str(hooks_dir)])
    with pytest.raises(SystemExit) as exc:
        commit_hook.uninstall_main()
    assert exc.value.code == 0
    assert _global_hookspath() == ""
    assert not (hooks_dir / "commit-msg").exists()


def test_install_does_not_clobber_existing_hookspath(sandbox_git_global, tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "config", "--global", "core.hooksPath", "/someone/else"], check=True)
    hooks_dir = tmp_path / "ghooks"
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr("sys.argv", ["install-commit-hook", "--dir", str(hooks_dir)])
    with pytest.raises(SystemExit) as exc:
        commit_hook.install_main()
    assert exc.value.code == 1
    assert "already set" in capsys.readouterr().err
    assert _global_hookspath() == "/someone/else"  # untouched
