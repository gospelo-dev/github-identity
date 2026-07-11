# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.doctor``.

These drive ``doctor.main`` against *real* temporary git repositories (git
config / remote reads are offline and hermetic under the ``tmp_home`` HOME
redirect). Only the two helpers that need network/host tooling --
``ssh_resolve`` and ``gh_account_available`` -- are monkeypatched.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gospelo_github_identity import doctor
from gospelo_github_identity._external import SshHostConfig


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

EXP_NAME = "gorosun"
EXP_EMAIL = "goro@ns.net"

_CONFIG = (
    'version: "1"\n'
    "profiles:\n"
    "  gospelo:\n"
    "    git: {user.name: gorosun, user.email: goro@ns.net}\n"
    "    gh: {account: gorosun}\n"
    "    paths: ['~/projects/gospelo-dev/**']\n"
)


@pytest.fixture
def gospelo_config(write_config, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = write_config(_CONFIG)
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))


def _init_repo(
    path: Path,
    *,
    remote: str | None = None,
    name: str | None = EXP_NAME,
    email: str | None = EXP_EMAIL,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote is not None:
        subprocess.run(
            ["git", "-C", str(path), "remote", "add", "origin", remote], check=True
        )
    if name is not None:
        subprocess.run(["git", "-C", str(path), "config", "user.name", name], check=True)
    if email is not None:
        subprocess.run(["git", "-C", str(path), "config", "user.email", email], check=True)
    return path


def _tree_repo(tmp_home: Path, name: str) -> Path:
    return tmp_home / "projects" / "gospelo-dev" / name


def _fake_ssh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity_file: str | None,
    identities_only: bool = True,
) -> None:
    monkeypatch.setattr(
        "gospelo_github_identity._external.ssh_resolve",
        lambda host: SshHostConfig(
            hostname="github.com",
            user="git",
            identity_file=identity_file,
            identities_only=identities_only,
        ),
    )


def _fake_gh(monkeypatch: pytest.MonkeyPatch, *, available: bool = True) -> None:
    monkeypatch.setattr(
        "gospelo_github_identity._external.gh_account_available", lambda login: available
    )


def _run_doctor(monkeypatch: pytest.MonkeyPatch, cwd: Path, *extra: str) -> int:
    monkeypatch.setattr("sys.argv", ["doctor", "--cwd", str(cwd), *extra])
    with pytest.raises(SystemExit) as exc:
        doctor.main()
    return int(exc.value.code)


# ---------------------------------------------------------------------------
# Healthy path
# ---------------------------------------------------------------------------


def test_doctor_healthy_repo_exits_zero(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = tmp_path / "id_gospelo"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key), identities_only=True)
    _fake_gh(monkeypatch, available=True)

    repo = _init_repo(
        _tree_repo(tmp_home, "healthy"),
        remote="git@gospelo-dev:gospelo-dev/healthy.git",
    )

    code = _run_doctor(monkeypatch, repo)
    assert code == 0
    out = capsys.readouterr().out
    assert "setup is healthy" in out
    assert "pinned locally" in out
    assert "IdentitiesOnly yes" in out


# ---------------------------------------------------------------------------
# Remote robustness
# ---------------------------------------------------------------------------


def test_doctor_bare_github_remote_warns(
    gospelo_config,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_gh(monkeypatch, available=True)
    # ssh_resolve must not even be needed for a bare remote.
    repo = _init_repo(
        _tree_repo(tmp_home, "bare"),
        remote="git@github.com:gospelo-dev/bare.git",
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    out = capsys.readouterr().out
    assert "bare github.com" in out


def test_doctor_https_remote_warns(
    gospelo_config,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_gh(monkeypatch, available=True)
    repo = _init_repo(
        _tree_repo(tmp_home, "web"),
        remote="https://github.com/gospelo-dev/web.git",
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    assert "not an SSH remote" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# git identity value + scope
# ---------------------------------------------------------------------------


def test_doctor_wrong_email_fails(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A set-but-wrong email (the .com/.net typo) must be a FAIL, not a pass."""
    key = tmp_path / "k"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key))
    _fake_gh(monkeypatch, available=True)

    repo = _init_repo(
        _tree_repo(tmp_home, "typo"),
        remote="git@gospelo-dev:gospelo-dev/typo.git",
        email="goro@ns.com",  # wrong TLD
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    assert "git identity is wrong" in capsys.readouterr().out


def test_doctor_inherited_identity_warns(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Correct only via global inheritance (no local pin) is fragile -> WARN."""
    key = tmp_path / "k"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key))
    _fake_gh(monkeypatch, available=True)

    # Global identity == expected, so effective is correct...
    subprocess.run(["git", "config", "--global", "user.name", EXP_NAME], check=True)
    subprocess.run(["git", "config", "--global", "user.email", EXP_EMAIL], check=True)
    # ...but the repo sets no local override.
    repo = _init_repo(
        _tree_repo(tmp_home, "inherited"),
        remote="git@gospelo-dev:gospelo-dev/inherited.git",
        name=None,
        email=None,
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    out = capsys.readouterr().out
    assert "not pinned locally" in out


def test_doctor_unset_identity_fails(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = tmp_path / "k"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key))
    _fake_gh(monkeypatch, available=True)

    repo = _init_repo(
        _tree_repo(tmp_home, "unset"),
        remote="git@gospelo-dev:gospelo-dev/unset.git",
        name=None,
        email=None,
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    assert "git identity is unset" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# SSH-alias pinning
# ---------------------------------------------------------------------------


def test_doctor_identities_only_no_warns(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = tmp_path / "k"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key), identities_only=False)
    _fake_gh(monkeypatch, available=True)

    repo = _init_repo(
        _tree_repo(tmp_home, "weakpin"),
        remote="git@gospelo-dev:gospelo-dev/weakpin.git",
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    assert "IdentitiesOnly=no" in capsys.readouterr().out


def test_doctor_missing_key_file_fails(
    gospelo_config,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_ssh(monkeypatch, identity_file="~/.ssh/does-not-exist", identities_only=True)
    _fake_gh(monkeypatch, available=True)

    repo = _init_repo(
        _tree_repo(tmp_home, "nokey"),
        remote="git@gospelo-dev:gospelo-dev/nokey.git",
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    assert "key file is missing" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Machine-level
# ---------------------------------------------------------------------------


def test_doctor_gh_not_logged_in_warns(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = tmp_path / "k"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key))
    _fake_gh(monkeypatch, available=False)

    repo = _init_repo(
        _tree_repo(tmp_home, "ghmissing"),
        remote="git@gospelo-dev:gospelo-dev/ghmissing.git",
    )
    code = _run_doctor(monkeypatch, repo)
    assert code == 1
    assert "is not logged in" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def test_doctor_sweep_audits_all_repos(
    gospelo_config,
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = tmp_path / "k"
    key.write_text("x")
    _fake_ssh(monkeypatch, identity_file=str(key))
    _fake_gh(monkeypatch, available=True)

    good = _init_repo(
        _tree_repo(tmp_home, "good"),
        remote="git@gospelo-dev:gospelo-dev/good.git",
    )
    _init_repo(
        _tree_repo(tmp_home, "bad"),
        remote="git@github.com:gospelo-dev/bad.git",  # fragile
    )

    code = _run_doctor(monkeypatch, good, "--sweep")
    assert code == 1  # the bad repo drags it to non-zero
    out = capsys.readouterr().out
    assert "[repo] good" in out
    assert "[repo] bad" in out
    assert "bare github.com" in out


# ---------------------------------------------------------------------------
# Resolution edge cases
# ---------------------------------------------------------------------------


def test_doctor_no_matching_profile_exits_one(
    gospelo_config,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_gh(monkeypatch, available=True)
    nowhere = tmp_home / "elsewhere"
    nowhere.mkdir()
    code = _run_doctor(monkeypatch, nowhere)
    assert code == 1
    assert "no profile" in capsys.readouterr().err.lower()


def test_doctor_not_in_repo_notes_and_passes(
    gospelo_config,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A matched dir that is not a git repo (no --sweep): note it, machine-only."""
    _fake_gh(monkeypatch, available=True)
    bare_dir = tmp_home / "projects" / "gospelo-dev" / "not-a-repo"
    bare_dir.mkdir(parents=True)
    code = _run_doctor(monkeypatch, bare_dir)
    assert code == 0
    assert "not inside a git repository" in capsys.readouterr().out


def test_doctor_config_error_exits_two(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(tmp_home / "no-such.yml"))
    monkeypatch.setattr("sys.argv", ["doctor"])
    with pytest.raises(SystemExit) as exc:
        doctor.main()
    assert exc.value.code == 2
