# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.lister``."""

from __future__ import annotations

from pathlib import Path

import pytest

from gospelo_github_identity import lister


def test_list_renders_table(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["list"])
    with pytest.raises(SystemExit) as exc:
        lister.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Header + both profiles must be visible.
    assert "name" in out
    assert "description" in out
    assert "git.user.email" in out
    assert "personal" in out
    assert "work" in out
    assert "Default profile: personal" in out


def test_list_minimal_omits_default_line(
    minimal_config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(minimal_config_file))
    monkeypatch.setattr("sys.argv", ["list"])
    with pytest.raises(SystemExit) as exc:
        lister.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "solo" in out
    # No default_profile -> the trailer line is omitted.
    assert "Default profile" not in out


def test_list_empty_profiles_exits_one(
    tmp_home: Path,
    write_config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Config rejects empty profiles at parse time -> exit 2.

    But if a config somehow has zero profiles, lister exits 1 with a hint.
    Validate the parser-level rejection here.
    """
    cfg = write_config('version: "1"\nprofiles: {}\n')
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))
    monkeypatch.setattr("sys.argv", ["list"])
    with pytest.raises(SystemExit) as exc:
        lister.main()
    # The config parser flags empty profiles as invalid (exit 2 via lister).
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err


def test_list_one_path_label_singular(
    minimal_config_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Profiles with exactly one path show ``1 path`` (not ``1 paths``)."""
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(minimal_config_file))
    monkeypatch.setattr("sys.argv", ["list"])
    with pytest.raises(SystemExit):
        lister.main()
    out = capsys.readouterr().out
    assert "1 path" in out
    assert "1 paths" not in out


def test_list_shows_active_profile(isolated_config, monkeypatch, capsys):
    from gospelo_github_identity import lister

    config_text = isolated_config.read_text(encoding="utf-8")
    isolated_config.write_text(config_text + "active_profile: work\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["list"])

    with pytest.raises(SystemExit) as exc:
        lister.main()

    assert exc.value.code == 0
    assert "Active profile: work" in capsys.readouterr().out


def test_list_multiple_paths_label_plural(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The personal profile in the valid config has 2 paths."""
    monkeypatch.setattr("sys.argv", ["list"])
    with pytest.raises(SystemExit):
        lister.main()
    out = capsys.readouterr().out
    assert "2 paths" in out


def test_list_config_error_exits_two(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "GOSPELO_GITHUB_IDENTITY_CONFIG",
        str(tmp_home / "no-such-config.yml"),
    )
    monkeypatch.setattr("sys.argv", ["list"])
    with pytest.raises(SystemExit) as exc:
        lister.main()
    assert exc.value.code == 2
