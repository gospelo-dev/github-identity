# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.detector``."""

from __future__ import annotations

from pathlib import Path

import pytest

from gospelo_github_identity import detector


def test_detect_matched_path_prints_profile(
    isolated_config: Path,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["detect", "--cwd", str(target)])

    with pytest.raises(SystemExit) as exc:
        detector.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out == "personal"


def test_detect_falls_back_to_default(
    isolated_config: Path,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The valid_config_file has default_profile=personal."""
    nowhere = tmp_home / "elsewhere"
    nowhere.mkdir()
    monkeypatch.setattr("sys.argv", ["detect", "--cwd", str(nowhere)])

    with pytest.raises(SystemExit) as exc:
        detector.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "personal"


def test_detect_no_match_no_default_exits_one(
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
    monkeypatch.setattr("sys.argv", ["detect", "--cwd", str(nowhere)])

    with pytest.raises(SystemExit) as exc:
        detector.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no profile matched" in err.lower()


def test_detect_config_error_exits_two(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "GOSPELO_GITHUB_IDENTITY_CONFIG",
        str(tmp_home / "no-such-config.yml"),
    )
    monkeypatch.setattr("sys.argv", ["detect"])
    with pytest.raises(SystemExit) as exc:
        detector.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err


def test_detect_uses_cwd_default_when_no_arg(
    isolated_config: Path,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --cwd, ``detector`` uses the process cwd."""
    target = tmp_home / "projects" / "work" / "task"
    target.mkdir(parents=True)
    monkeypatch.chdir(target)
    monkeypatch.setattr("sys.argv", ["detect"])

    with pytest.raises(SystemExit) as exc:
        detector.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "work"


def test_detect_longest_prefix_wins(
    tmp_home: Path,
    write_config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When two profiles match, the longest literal prefix wins."""
    cfg_yaml = (
        'version: "1"\n'
        "profiles:\n"
        "  broad:\n"
        "    git: {user.name: b, user.email: b@example.com}\n"
        "    gh: {account: broad}\n"
        "    paths: ['~/projects/work/**']\n"
        "  narrow:\n"
        "    git: {user.name: n, user.email: n@example.com}\n"
        "    gh: {account: narrow}\n"
        "    paths: ['~/projects/work/oss-fork/**']\n"
    )
    cfg = write_config(cfg_yaml)
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))

    target = tmp_home / "projects" / "work" / "oss-fork" / "module"
    target.mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["detect", "--cwd", str(target)])

    with pytest.raises(SystemExit) as exc:
        detector.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "narrow"
