# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.initializer``.

The interactive flow is exercised with monkeypatched ``input`` / ``$EDITOR``
so no real shell prompts or editor processes are spawned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gospelo_github_identity import initializer
from gospelo_github_identity.config import load_config


# ---------------------------------------------------------------------------
# --show-example
# ---------------------------------------------------------------------------


def test_show_example_prints_template(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["init", "--show-example"])
    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "version:" in out
    assert "profiles:" in out


def test_show_example_template_missing_exits_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """If the bundled template is missing, exit 2 (no silent fallback)."""
    monkeypatch.setattr(
        "gospelo_github_identity.initializer._template_path",
        lambda: tmp_path / "missing.yml",
    )
    monkeypatch.setattr("sys.argv", ["init", "--show-example"])
    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "bundled template not found" in err


# ---------------------------------------------------------------------------
# Conflicting flags
# ---------------------------------------------------------------------------


def test_show_example_and_from_template_conflict(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["init", "--show-example", "--from-template"])
    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Cannot use both" in err


# ---------------------------------------------------------------------------
# --from-template
# ---------------------------------------------------------------------------


def test_from_template_copies_to_target(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "config.yml"
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))
    # Skip the editor invocation.
    monkeypatch.setattr(
        "gospelo_github_identity.initializer.subprocess.run",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("sys.argv", ["init", "--from-template"])

    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 0
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "version:" in text
    assert "profiles:" in text


def test_from_template_existing_overwrite_yes(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_home / "config.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("OLD CONTENT\n", encoding="utf-8")

    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    monkeypatch.setattr(
        "gospelo_github_identity.initializer.subprocess.run",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("sys.argv", ["init", "--from-template"])

    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 0
    assert "OLD CONTENT" not in target.read_text(encoding="utf-8")


def test_from_template_existing_overwrite_no_aborts(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "config.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("OLD CONTENT\n", encoding="utf-8")

    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    monkeypatch.setattr("sys.argv", ["init", "--from-template"])

    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Aborted" in err
    # Original content preserved.
    assert target.read_text(encoding="utf-8") == "OLD CONTENT\n"


def test_from_template_force_skips_prompt(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_home / "config.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("OLD CONTENT\n", encoding="utf-8")

    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))

    # Make input() raise so we know it must NOT be called when --force is set.
    def boom(*a, **kw):
        raise AssertionError("input must not be called when --force is set")

    monkeypatch.setattr("builtins.input", boom)
    monkeypatch.setattr(
        "gospelo_github_identity.initializer.subprocess.run",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("sys.argv", ["init", "--from-template", "--force"])

    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 0


def test_from_template_editor_missing_exits_two(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "config.yml"
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))
    monkeypatch.setenv("EDITOR", "definitely-no-such-editor-xyz")

    def raise_fnf(*a, **kw):
        raise FileNotFoundError("editor not found")

    monkeypatch.setattr(
        "gospelo_github_identity.initializer.subprocess.run", raise_fnf
    )
    monkeypatch.setattr("sys.argv", ["init", "--from-template"])
    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "editor not found" in err


# ---------------------------------------------------------------------------
# Interactive flow
# ---------------------------------------------------------------------------


def test_interactive_init_writes_valid_config(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drive a full happy-path interactive init via canned ``input``."""
    target = tmp_home / "config.yml"
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))

    # Sequence drives _prompt_profile, then "no more profiles", then default
    # confirmation (default Y for the single-profile shortcut).
    answers = iter(
        [
            "personal",          # Profile name
            "Personal OSS",      # Description (optional)
            "Test User",         # git user.name
            "test-user@example.com",  # git user.email
            "test-login",        # gh account
            "~/projects/personal/**",  # path 1
            "",                  # finish paths
            "n",                 # add another profile? -> no
            "",                  # default_profile shortcut -> accept default Y
        ]
    )

    def fake_input(prompt=""):
        try:
            return next(answers)
        except StopIteration as e:
            raise AssertionError(f"Unexpected extra input prompt: {prompt!r}") from e

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("sys.argv", ["init"])

    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 0
    assert target.is_file()
    cfg = load_config(target)
    assert "personal" in cfg.profiles
    p = cfg.profiles["personal"]
    assert p.git_user_email == "test-user@example.com"
    assert p.gh_account == "test-login"
    assert cfg.default_profile == "personal"


def test_interactive_init_aborts_on_eof(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "config.yml"
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))

    def raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    monkeypatch.setattr("sys.argv", ["init"])
    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Aborted" in err
    assert not target.exists()


def test_interactive_init_existing_config_no_overwrite(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "config.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("KEEP ME\n", encoding="utf-8")

    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(target))
    answers = iter(["n"])  # decline overwrite
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    monkeypatch.setattr("sys.argv", ["init"])

    with pytest.raises(SystemExit) as exc:
        initializer.main()
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert "Aborted" in err
    # Original content untouched.
    assert target.read_text(encoding="utf-8") == "KEEP ME\n"
