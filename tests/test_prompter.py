# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.prompter``."""

from __future__ import annotations

from pathlib import Path

import pytest

from gospelo_github_identity import prompter
from gospelo_github_identity._external import ExternalToolError


def _matched_target(tmp_home: Path) -> Path:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    return target


# ---------------------------------------------------------------------------
# Format variants
# ---------------------------------------------------------------------------


def test_prompt_plain_format(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _matched_target(tmp_home)
    monkeypatch.setattr(
        "sys.argv", ["prompt", "--cwd", str(target), "--format", "plain"]
    )
    with pytest.raises(SystemExit) as exc:
        prompter.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out == "[personal]"


def test_prompt_color_format(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _matched_target(tmp_home)
    monkeypatch.setattr(
        "sys.argv", ["prompt", "--cwd", str(target), "--format", "color"]
    )
    with pytest.raises(SystemExit) as exc:
        prompter.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # ANSI yellow + label + reset.
    assert "\033[33m" in out
    assert "[personal]" in out
    assert "\033[0m" in out


def test_prompt_ps1_format(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _matched_target(tmp_home)
    monkeypatch.setattr(
        "sys.argv", ["prompt", "--cwd", str(target), "--format", "ps1"]
    )
    with pytest.raises(SystemExit) as exc:
        prompter.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Non-printing PS1 escape markers.
    assert r"\[" in out
    assert r"\]" in out
    assert "[personal]" in out


# ---------------------------------------------------------------------------
# Empty / error cases (must never fail-loud; always exit 0)
# ---------------------------------------------------------------------------


def test_prompt_no_match_no_default_emits_empty(
    tmp_home: Path,
    write_config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg_yaml = (
        'version: "1"\n'
        "profiles:\n"
        "  solo:\n"
        "    git: {user.name: a, user.email: a@example.com}\n"
        "    gh: {account: solo}\n"
        "    paths: ['~/projects/specific/**']\n"
    )
    cfg = write_config(cfg_yaml)
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))

    nowhere = tmp_home / "elsewhere"
    nowhere.mkdir()
    monkeypatch.setattr("sys.argv", ["prompt", "--cwd", str(nowhere)])
    with pytest.raises(SystemExit) as exc:
        prompter.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out == ""


def test_prompt_swallows_config_error_and_exits_zero(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The prompt helper must NEVER abort the shell, even on bad config."""
    monkeypatch.setenv(
        "GOSPELO_GITHUB_IDENTITY_CONFIG",
        str(tmp_home / "no-such-config.yml"),
    )
    monkeypatch.setattr("sys.argv", ["prompt"])
    with pytest.raises(SystemExit) as exc:
        prompter.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# --show-mismatch
# ---------------------------------------------------------------------------


def test_prompt_show_mismatch_marks_when_mismatched(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _matched_target(tmp_home)
    # Email mismatch -> _has_mismatch returns True.
    mock_external["git_user_email"] = "wrong@example.com"
    mock_external["gh_login"] = "alice-personal"

    monkeypatch.setattr(
        "sys.argv",
        ["prompt", "--cwd", str(target), "--show-mismatch", "--format", "plain"],
    )
    with pytest.raises(SystemExit):
        prompter.main()
    out = capsys.readouterr().out
    assert out == "[personal !]"


def test_prompt_show_mismatch_no_mark_when_matched(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _matched_target(tmp_home)
    mock_external["git_user_email"] = "alice@example.com"
    mock_external["gh_login"] = "alice-personal"

    monkeypatch.setattr(
        "sys.argv",
        ["prompt", "--cwd", str(target), "--show-mismatch", "--format", "plain"],
    )
    with pytest.raises(SystemExit):
        prompter.main()
    out = capsys.readouterr().out
    assert out == "[personal]"


def test_prompt_show_mismatch_color_uses_red_when_mismatched(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _matched_target(tmp_home)
    mock_external["git_user_email"] = "wrong@example.com"
    mock_external["gh_login"] = "alice-personal"

    monkeypatch.setattr(
        "sys.argv",
        ["prompt", "--cwd", str(target), "--show-mismatch", "--format", "color"],
    )
    with pytest.raises(SystemExit):
        prompter.main()
    out = capsys.readouterr().out
    # Red ANSI escape (warning) appears, not yellow.
    assert "\033[31m" in out
    assert "[personal !]" in out


def test_prompt_show_mismatch_ignores_external_errors(
    isolated_config: Path,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If git / gh raise, mismatch detection silently treats them as None."""
    target = _matched_target(tmp_home)

    def boom_get_config(*a, **kw):
        raise ExternalToolError("git missing")

    def boom_login():
        raise ExternalToolError("gh missing")

    monkeypatch.setattr("gospelo_github_identity._external.git_get_config", boom_get_config)
    monkeypatch.setattr("gospelo_github_identity._external.gh_active_login", boom_login)
    monkeypatch.setattr(
        "sys.argv",
        ["prompt", "--cwd", str(target), "--show-mismatch", "--format", "plain"],
    )
    with pytest.raises(SystemExit) as exc:
        prompter.main()
    assert exc.value.code == 0
    # Both probes returned None -> no mismatch flagged.
    assert capsys.readouterr().out == "[personal]"
