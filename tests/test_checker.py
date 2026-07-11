# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.checker``.

Drives ``checker.main`` via ``monkeypatch`` of ``sys.argv`` and the
``mock_external`` fixture so no real ``git`` / ``gh`` is invoked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gospelo_github_identity import checker
from gospelo_github_identity._external import ExternalToolError


def _make_target_dir(tmp_home: Path) -> Path:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    return target


# ---------------------------------------------------------------------------
# Happy path (everything matches)
# ---------------------------------------------------------------------------


def test_check_all_match_exits_zero(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _make_target_dir(tmp_home)
    mock_external["git_user_name"] = "Alice Example"
    mock_external["git_user_email"] = "alice@example.com"
    mock_external["gh_login"] = "alice-personal"

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])

    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "OK" in out
    assert "personal" in out


# ---------------------------------------------------------------------------
# Mismatch cases
# ---------------------------------------------------------------------------


def test_check_user_name_mismatch_exits_one(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _make_target_dir(tmp_home)
    mock_external["git_user_name"] = "Wrong Name"
    mock_external["git_user_email"] = "alice@example.com"
    mock_external["gh_login"] = "alice-personal"

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "NG" in out


def test_check_user_email_mismatch_exits_one(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _make_target_dir(tmp_home)
    mock_external["git_user_name"] = "Alice Example"
    mock_external["git_user_email"] = "wrong@example.com"
    mock_external["gh_login"] = "alice-personal"

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1


def test_check_gh_login_mismatch_exits_one(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _make_target_dir(tmp_home)
    mock_external["git_user_name"] = "Alice Example"
    mock_external["git_user_email"] = "alice@example.com"
    mock_external["gh_login"] = "alice-work"  # wrong account

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    # checker emits a "Run gospelo-github-identity switch ..." hint to stderr.
    assert "switch" in err


def test_check_all_mismatch_exits_one(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _make_target_dir(tmp_home)
    # Nothing matches.
    mock_external["git_user_name"] = "X"
    mock_external["git_user_email"] = "x@x"
    mock_external["gh_login"] = "x"

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# No matching profile
# ---------------------------------------------------------------------------


def test_check_no_matching_profile_no_default_exits_one(
    tmp_home: Path,
    write_config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a default_profile, an unmatched cwd must exit 1."""
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
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(nowhere)])

    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "no profile" in err.lower()


# ---------------------------------------------------------------------------
# External tool errors
# ---------------------------------------------------------------------------


def test_check_external_error_exits_two(
    isolated_config: Path,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = _make_target_dir(tmp_home)

    def boom(*a, **kw):
        raise ExternalToolError("git missing")

    monkeypatch.setattr("gospelo_github_identity._external.git_get_config", boom)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])

    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err


def test_check_config_error_exits_two(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing config file should produce exit 2 (config error), not 1."""
    monkeypatch.setenv(
        "GOSPELO_GITHUB_IDENTITY_CONFIG",
        str(tmp_home / "no-such-config.yml"),
    )
    monkeypatch.setattr("sys.argv", ["check"])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 2


def test_check_unset_git_config_shows_unset_marker(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When git config returns None, the report must show ``(unset)``."""
    target = _make_target_dir(tmp_home)
    mock_external["git_user_name"] = None
    mock_external["git_user_email"] = None
    mock_external["gh_login"] = None  # also unauthenticated

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit):
        checker.main()
    out = capsys.readouterr().out
    assert "(unset)" in out
    assert "(unauthenticated)" in out


# ---------------------------------------------------------------------------
# SSH-login check (opt-in `ssh` block)
# ---------------------------------------------------------------------------


_SSH_CONFIG_YAML = (
    'version: "1"\n'
    "profiles:\n"
    "  demo:\n"
    "    description: SSH demo\n"
    "    git: {user.name: Alice Example, user.email: alice@example.com}\n"
    "    gh: {account: octocat}\n"
    "    ssh: {}\n"
    "    paths: ['~/projects/ssh-demo/**']\n"
)


def _ssh_target_dir(tmp_home: Path) -> Path:
    target = tmp_home / "projects" / "ssh-demo" / "repo"
    target.mkdir(parents=True)
    return target


def _use_ssh_config(write_config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = write_config(_SSH_CONFIG_YAML)
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))


def _correct_git_gh(mock_external) -> None:
    mock_external["git_user_name"] = "Alice Example"
    mock_external["git_user_email"] = "alice@example.com"
    mock_external["gh_login"] = "octocat"


def test_check_ssh_login_match_exits_zero(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_ssh_config(write_config, monkeypatch)
    _correct_git_gh(mock_external)
    mock_external["remote_url"] = "git@github.com:org/repo.git"
    mock_external["ssh_probe_login"] = "octocat"  # matches gh.account default

    target = _ssh_target_dir(tmp_home)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "[ssh]" in out
    assert "octocat" in out


def test_check_ssh_login_mismatch_exits_one(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git/gh look correct, but the SSH key authenticates as someone else."""
    _use_ssh_config(write_config, monkeypatch)
    _correct_git_gh(mock_external)
    mock_external["remote_url"] = "git@github.com:org/repo.git"
    mock_external["ssh_probe_login"] = "pasona-ghayakawa"  # wrong identity

    target = _ssh_target_dir(tmp_home)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "NG" in captured.out
    assert "wrong GitHub identity" in captured.err


def test_check_ssh_skipped_when_origin_https(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An HTTPS origin means SSH keys are not used for push -> skip, exit 0."""
    _use_ssh_config(write_config, monkeypatch)
    _correct_git_gh(mock_external)
    mock_external["remote_url"] = "https://github.com/org/repo.git"

    target = _ssh_target_dir(tmp_home)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "(n/a: origin not SSH)" in captured.out
    assert "not an SSH remote" in captured.err


def test_check_ssh_skipped_when_unreachable(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A probe that cannot determine the login is a soft skip, not a failure."""
    _use_ssh_config(write_config, monkeypatch)
    _correct_git_gh(mock_external)
    mock_external["remote_url"] = "git@github.com:org/repo.git"
    mock_external["ssh_probe_login"] = None
    mock_external["ssh_probe_detail"] = "git@github.com: Permission denied (publickey)."

    target = _ssh_target_dir(tmp_home)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "(unreachable)" in captured.out
    assert "could not determine" in captured.err


def test_check_ssh_skipped_when_no_remote(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_ssh_config(write_config, monkeypatch)
    _correct_git_gh(mock_external)
    mock_external["remote_url"] = None  # no origin remote

    target = _ssh_target_dir(tmp_home)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 0
    assert "(n/a: origin not SSH)" in capsys.readouterr().out


def test_check_ssh_and_gh_both_mismatch_reports_both(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """gh mismatch keeps its switch hint; SSH mismatch adds its own warning."""
    _use_ssh_config(write_config, monkeypatch)
    mock_external["git_user_name"] = "Alice Example"
    mock_external["git_user_email"] = "alice@example.com"
    mock_external["gh_login"] = "someone-else"  # gh wrong
    mock_external["remote_url"] = "git@github.com:org/repo.git"
    mock_external["ssh_probe_login"] = "pasona-ghayakawa"  # ssh wrong too

    target = _ssh_target_dir(tmp_home)
    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "wrong GitHub identity" in err  # ssh warning
    assert "switch" in err  # gh warning retained


def test_check_via_default_marker_in_output(
    tmp_home: Path,
    write_config,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When the default profile is used, output must say ``(default)``."""
    cfg_yaml = (
        'version: "1"\n'
        "profiles:\n"
        "  solo:\n"
        "    description: Bob\n"
        "    git: {user.name: bob, user.email: bob@example.com}\n"
        "    gh: {account: bob}\n"
        "    paths: ['~/never-here/**']\n"
        "default_profile: solo\n"
    )
    cfg = write_config(cfg_yaml)
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))

    target = tmp_home / "elsewhere"
    target.mkdir()

    mock_external["git_user_name"] = "bob"
    mock_external["git_user_email"] = "bob@example.com"
    mock_external["gh_login"] = "bob"

    monkeypatch.setattr("sys.argv", ["check", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        checker.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "(default)" in out
