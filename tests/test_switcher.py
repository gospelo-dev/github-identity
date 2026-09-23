# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.switcher``.

Drives ``switcher.main`` via ``monkeypatch`` of ``sys.argv`` and the
``mock_external`` fixture. No real ``git`` / ``gh`` is touched.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from gospelo_github_identity import switcher
from gospelo_github_identity._external import ExternalToolError


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_switch_local_runs_git_and_gh(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    mock_external["inside_work_tree"] = True

    monkeypatch.setattr("sys.argv", ["switch", "personal", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0

    # Both git config keys must have been set with scope=local.
    keys = {(k, scope) for k, _, scope, _ in mock_external["set_config_calls"]}
    assert ("user.name", "local") in keys
    assert ("user.email", "local") in keys
    # gh switch must have been called with the profile's account.
    assert mock_external["switch_calls"] == ["alice-personal"]
    assert "active_profile: personal" in isolated_config.read_text(encoding="utf-8")


def test_switch_global_uses_global_scope(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    scopes = {scope for _, _, scope, _ in mock_external["set_config_calls"]}
    assert scopes == {"global"}


def test_switch_dry_run_executes_nothing(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--dry-run", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    # No real calls happened.
    assert mock_external["set_config_calls"] == []
    assert mock_external["switch_calls"] == []
    out = capsys.readouterr().out
    assert "dry-run" in out


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_switch_unknown_profile_exits_two(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["switch", "does-not-exist", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Unknown profile" in err


def test_switch_missing_arg_exits_two(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """argparse should exit 2 when the positional profile is missing."""
    monkeypatch.setattr("sys.argv", ["switch"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 2


def test_switch_local_outside_work_tree_exits_two(
    isolated_config: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Local scope outside a git work tree must abort with exit 2."""
    target = tmp_home / "elsewhere"
    target.mkdir()
    mock_external["inside_work_tree"] = False

    monkeypatch.setattr("sys.argv", ["switch", "personal", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not inside a git work tree" in err
    # No git_set_config / gh_switch_account calls should have happened.
    assert mock_external["set_config_calls"] == []
    assert mock_external["switch_calls"] == []


def test_switch_gh_failure_partial_exit_one(
    isolated_config: Path,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git ok + gh failure must yield exit 1 (partial success)."""
    mock_external["gh_switch_raises"] = "auth switch failed"
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "gh auth switch failed" in err


def test_switch_both_failure_exit_two(
    isolated_config: Path,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """git fail + gh fail must yield exit 2 (total failure)."""
    mock_external["git_set_raises"] = "git config refused"
    mock_external["gh_switch_raises"] = "auth switch failed"
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 2


def test_switch_config_error_exits_two(
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GOSPELO_GITHUB_IDENTITY_CONFIG",
        str(tmp_home / "no-such-config.yml"),
    )
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 2


def test_switch_local_inside_tree_check_failure_exits_two(
    isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If git_inside_work_tree itself raises ExternalToolError, exit 2."""

    def boom(cwd=None):
        raise ExternalToolError("git missing")

    monkeypatch.setattr("gospelo_github_identity._external.git_inside_work_tree", boom)
    monkeypatch.setattr("sys.argv", ["switch", "personal"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Post-switch identity verification (keyring-mismatch guard)
# ---------------------------------------------------------------------------


def test_switch_detects_keyring_mismatch_exit_one(
    isolated_config: Path,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`gh auth switch` succeeds but the real token authenticates as someone
    else (stale keyring credential). The switcher must detect this via
    `gh api user`, report NG, and exit 1 -- not falsely claim success."""
    # gh auth switch "succeeds", but the active token still resolves to a
    # different account.
    mock_external["gh_switch_stale_login"] = "alice-work"
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "authenticates as 'alice-work'" in err
    assert "keyring mismatch" in err
    assert "gh auth logout" in err and "gh auth login" in err


def test_switch_success_is_verified_via_api(
    isolated_config: Path,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A correct switch (real login == target) reports OK and exits 0."""
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "OK: gh CLI active account switched to alice-personal." in out


def test_switch_unverifiable_is_non_fatal(
    isolated_config: Path,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the real identity cannot be confirmed (e.g. offline, gh api user
    returns nothing), the switch is not failed -- it exits 0 with a note."""

    def unauth() -> None:
        return None

    # Switch records the call but leaves the real login unresolved.
    def fake_switch(account: str) -> None:
        mock_external["switch_calls"].append(account)

    monkeypatch.setattr("gospelo_github_identity._external.gh_switch_account", fake_switch)
    monkeypatch.setattr("gospelo_github_identity._external.gh_active_login", unauth)
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "could not confirm" in out


# ---------------------------------------------------------------------------
# Remote URL rewriting on switch
# ---------------------------------------------------------------------------

CONFIG_WITH_SSH_HOST = dedent(
    """\
    version: "1"
    profiles:
      personal:
        description: "Personal OSS work"
        git:
          user.name: "Alice Example"
          user.email: "alice@example.com"
        gh:
          account: "alice-personal"
        ssh:
          host: alice-ssh
        paths:
          - ~/projects/personal/**
      work:
        description: "Day job"
        git:
          user.name: "Alice Example"
          user.email: "alice@company.example"
        gh:
          account: "alice-work"
        paths:
          - ~/projects/work/**
    default_profile: personal
    """
)


@pytest.fixture
def isolated_config_ssh(
    tmp_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Path:
    cfg = tmp_path / "config-ssh.yml"
    cfg.write_text(CONFIG_WITH_SSH_HOST, encoding="utf-8")
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))
    return cfg


def test_switch_rewrites_origin_remote(
    isolated_config_ssh: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    mock_external["inside_work_tree"] = True
    mock_external["remote_url"] = "git@github.com:org/repo.git"

    monkeypatch.setattr("sys.argv", ["switch", "personal", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    assert mock_external["set_remote_calls"] == [
        ("origin", "git@alice-ssh:org/repo.git", target),
    ]
    out = capsys.readouterr().out
    assert "origin remote rewritten" in out


def test_switch_no_rewrite_when_host_matches(
    isolated_config_ssh: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    mock_external["inside_work_tree"] = True
    mock_external["remote_url"] = "git@alice-ssh:org/repo.git"

    monkeypatch.setattr("sys.argv", ["switch", "personal", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    assert mock_external["set_remote_calls"] == []
    out = capsys.readouterr().out
    assert "already uses ssh host alice-ssh" in out


def test_switch_no_rewrite_without_ssh_host(
    isolated_config: Path,
    mock_external,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_external["remote_url"] = "git@github.com:org/repo.git"
    monkeypatch.setattr("sys.argv", ["switch", "personal", "--global"])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    assert mock_external["set_remote_calls"] == []


def test_switch_no_rewrite_on_https_remote(
    isolated_config_ssh: Path,
    mock_external,
    tmp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_home / "projects" / "personal" / "demo"
    target.mkdir(parents=True)
    mock_external["inside_work_tree"] = True
    mock_external["remote_url"] = "https://github.com/org/repo.git"

    monkeypatch.setattr("sys.argv", ["switch", "personal", "--cwd", str(target)])
    with pytest.raises(SystemExit) as exc:
        switcher.main()
    assert exc.value.code == 0
    assert mock_external["set_remote_calls"] == []
