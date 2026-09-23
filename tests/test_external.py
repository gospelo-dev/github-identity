# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity._external``.

Covers the thin git / gh CLI wrappers via ``mock_subprocess``. No real
``git`` or ``gh`` binary is invoked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gospelo_github_identity import _external
from gospelo_github_identity._external import ExternalToolError


# ---------------------------------------------------------------------------
# git_get_config
# ---------------------------------------------------------------------------


def test_git_get_config_returns_value(mock_subprocess) -> None:
    mock_subprocess.set("git config --get user.name", returncode=0, stdout="alice\n")
    assert _external.git_get_config("user.name") == "alice"
    # Confirm the exact command shape is right.
    assert any("git config --get user.name" in call for call in mock_subprocess.calls)


def test_git_get_config_missing_key_returns_none(mock_subprocess) -> None:
    # `git config --get` exits 1 when the key is unset; that is *not* an error.
    mock_subprocess.set("git config --get user.name", returncode=1, stdout="")
    assert _external.git_get_config("user.name") is None


def test_git_get_config_other_error_raises(mock_subprocess) -> None:
    mock_subprocess.set(
        "git config --get user.name",
        returncode=128,
        stdout="",
        stderr="fatal: not in a git repo",
    )
    with pytest.raises(ExternalToolError, match="git config --get user.name failed"):
        _external.git_get_config("user.name")


def test_git_get_config_passes_cwd(mock_subprocess, tmp_path: Path) -> None:
    mock_subprocess.set("git config --get user.email", returncode=0, stdout="a@b.com")
    result = _external.git_get_config("user.email", cwd=tmp_path)
    assert result == "a@b.com"


def test_git_get_config_tool_missing_raises(monkeypatch) -> None:
    monkeypatch.setattr("gospelo_github_identity._external.shutil.which", lambda t: None)
    with pytest.raises(ExternalToolError, match="not found on PATH"):
        _external.git_get_config("user.name")


# ---------------------------------------------------------------------------
# git_set_config
# ---------------------------------------------------------------------------


def test_git_set_config_local_scope(mock_subprocess) -> None:
    mock_subprocess.set("git config --local user.name alice", returncode=0)
    _external.git_set_config("user.name", "alice")
    # Default scope is local; must NOT see --global.
    last = mock_subprocess.calls[-1]
    assert "--local" in last
    assert "--global" not in last


def test_git_set_config_global_scope(mock_subprocess) -> None:
    mock_subprocess.set("git config --global user.name alice", returncode=0)
    _external.git_set_config("user.name", "alice", scope="global")
    last = mock_subprocess.calls[-1]
    assert "--global" in last


def test_git_set_config_invalid_scope_raises() -> None:
    with pytest.raises(ValueError, match="invalid scope"):
        _external.git_set_config("user.name", "alice", scope="bogus")


def test_git_set_config_failure_raises(mock_subprocess) -> None:
    mock_subprocess.set(
        "git config --local user.name",
        returncode=2,
        stderr="boom",
    )
    with pytest.raises(ExternalToolError, match="failed"):
        _external.git_set_config("user.name", "alice")


# ---------------------------------------------------------------------------
# git_inside_work_tree
# ---------------------------------------------------------------------------


def test_git_inside_work_tree_true(mock_subprocess) -> None:
    mock_subprocess.set("git rev-parse --is-inside-work-tree", returncode=0, stdout="true")
    assert _external.git_inside_work_tree() is True


def test_git_inside_work_tree_false(mock_subprocess) -> None:
    mock_subprocess.set(
        "git rev-parse --is-inside-work-tree",
        returncode=128,
        stdout="",
        stderr="fatal: not a git repo",
    )
    assert _external.git_inside_work_tree() is False


# ---------------------------------------------------------------------------
# gh_active_login
# ---------------------------------------------------------------------------


def test_gh_active_login_returns_login(mock_subprocess) -> None:
    mock_subprocess.set("gh api user --jq .login", returncode=0, stdout="alice")
    assert _external.gh_active_login() == "alice"


def test_gh_active_login_unauthenticated_returns_none(mock_subprocess) -> None:
    mock_subprocess.set(
        "gh api user --jq .login",
        returncode=1,
        stdout="",
        stderr="not authenticated",
    )
    assert _external.gh_active_login() is None


# ---------------------------------------------------------------------------
# gh_logged_in_accounts
# ---------------------------------------------------------------------------


def test_gh_logged_in_accounts_parses_status(mock_subprocess) -> None:
    status_output = (
        "github.com\n"
        "  - Logged in to github.com account alice (oauth_token)\n"
        "    Active account: true\n"
        "  - Logged in to github.com account bob (oauth_token)\n"
    )
    mock_subprocess.set("gh auth status", returncode=0, stderr=status_output)
    accounts = _external.gh_logged_in_accounts()
    assert accounts == ["alice", "bob"]


def test_gh_logged_in_accounts_empty_when_logged_out(mock_subprocess) -> None:
    mock_subprocess.set("gh auth status", returncode=1, stderr="not logged in")
    assert _external.gh_logged_in_accounts() == []


# ---------------------------------------------------------------------------
# gh_switch_account
# ---------------------------------------------------------------------------


def test_gh_switch_account_success(mock_subprocess) -> None:
    mock_subprocess.set("gh auth switch -u alice", returncode=0)
    _external.gh_switch_account("alice")
    assert any("gh auth switch -u alice" in c for c in mock_subprocess.calls)


def test_gh_switch_account_failure_raises(mock_subprocess) -> None:
    mock_subprocess.set(
        "gh auth switch -u nobody",
        returncode=1,
        stderr="account not found",
    )
    with pytest.raises(ExternalToolError, match="failed"):
        _external.gh_switch_account("nobody")


# ---------------------------------------------------------------------------
# _run / FileNotFoundError surface
# ---------------------------------------------------------------------------


def test_run_filenotfound_translates_to_external_tool_error(monkeypatch) -> None:
    """When ``subprocess.run`` itself raises FileNotFoundError (binary
    disappeared between ``which`` and ``run``), we wrap it."""

    def boom(*a, **kw):
        raise FileNotFoundError("git: not found")

    monkeypatch.setattr("gospelo_github_identity._external.shutil.which", lambda t: "/usr/bin/git")
    monkeypatch.setattr("gospelo_github_identity._external.subprocess.run", boom)
    with pytest.raises(ExternalToolError, match="Failed to invoke"):
        _external.git_get_config("user.name")


def test_command_result_dataclass() -> None:
    r = _external.CommandResult(returncode=0, stdout="x", stderr="")
    assert r.returncode == 0
    assert r.stdout == "x"


# ---------------------------------------------------------------------------
# git_remote_url
# ---------------------------------------------------------------------------


def test_git_remote_url_returns_url(mock_subprocess) -> None:
    mock_subprocess.set(
        "git remote get-url origin",
        returncode=0,
        stdout="git@github.com:org/repo.git",
    )
    assert _external.git_remote_url() == "git@github.com:org/repo.git"


def test_git_remote_url_missing_remote_returns_none(mock_subprocess) -> None:
    # `git remote get-url` exits non-zero when the remote / repo is absent.
    mock_subprocess.set(
        "git remote get-url origin",
        returncode=2,
        stderr="error: No such remote 'origin'",
    )
    assert _external.git_remote_url() is None


# ---------------------------------------------------------------------------
# ssh_target_from_remote (pure parser)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("git@github.com:org/repo.git", "git@github.com"),
        ("git@github.com-work:org/repo.git", "git@github.com-work"),
        ("ssh://git@github.com/org/repo.git", "git@github.com"),
        ("ssh://git@github.com:22/org/repo.git", "git@github.com"),
        ("ssh://github.com/org/repo.git", "github.com"),
        ("https://github.com/org/repo.git", None),
        ("git://github.com/org/repo.git", None),
        ("/Users/me/local/repo", None),
        ("", None),
    ],
)
def test_ssh_target_from_remote(url: str, expected: str | None) -> None:
    assert _external.ssh_target_from_remote(url) == expected


# ---------------------------------------------------------------------------
# ssh_probe_login
# ---------------------------------------------------------------------------


def test_ssh_probe_login_parses_banner(mock_subprocess) -> None:
    # `ssh -T git@github.com` exits 1 on success and prints to stderr.
    mock_subprocess.set(
        "ssh -T",
        returncode=1,
        stderr=(
            "Hi octocat! You've successfully authenticated, but GitHub does "
            "not provide shell access."
        ),
    )
    login, detail = _external.ssh_probe_login("git@github.com")
    assert login == "octocat"
    assert "successfully authenticated" in detail


def test_ssh_probe_login_permission_denied_returns_none(mock_subprocess) -> None:
    mock_subprocess.set(
        "ssh -T",
        returncode=255,
        stderr="git@github.com: Permission denied (publickey).",
    )
    login, detail = _external.ssh_probe_login("git@github.com")
    assert login is None
    assert "Permission denied" in detail


def test_ssh_probe_login_passes_batchmode(mock_subprocess) -> None:
    mock_subprocess.set("ssh -T", returncode=1, stderr="Hi a! You've successfully authenticated")
    _external.ssh_probe_login("git@github.com")
    last = mock_subprocess.calls[-1]
    assert "BatchMode=yes" in last
    assert "ConnectTimeout=6" in last


# ---------------------------------------------------------------------------
# git_get_config scope / git_toplevel
# ---------------------------------------------------------------------------


def test_git_get_config_scope_local_adds_flag(mock_subprocess) -> None:
    mock_subprocess.set("git config --local --get user.name", returncode=0, stdout="alice")
    assert _external.git_get_config("user.name", scope="local") == "alice"
    assert any("git config --local --get user.name" in c for c in mock_subprocess.calls)


def test_git_get_config_scope_unset_returns_none(mock_subprocess) -> None:
    mock_subprocess.set("git config --global --get user.name", returncode=1, stdout="")
    assert _external.git_get_config("user.name", scope="global") is None


def test_git_get_config_invalid_scope_raises() -> None:
    with pytest.raises(ValueError, match="invalid scope"):
        _external.git_get_config("user.name", scope="bogus")


def test_git_toplevel_returns_path(mock_subprocess) -> None:
    mock_subprocess.set(
        "git rev-parse --show-toplevel", returncode=0, stdout="/home/me/repo"
    )
    top = _external.git_toplevel()
    assert top is not None and str(top) == "/home/me/repo"


def test_git_toplevel_outside_repo_returns_none(mock_subprocess) -> None:
    mock_subprocess.set(
        "git rev-parse --show-toplevel", returncode=128, stderr="fatal: not a repo"
    )
    assert _external.git_toplevel() is None


# ---------------------------------------------------------------------------
# ssh_resolve
# ---------------------------------------------------------------------------


def test_ssh_resolve_parses_config(mock_subprocess) -> None:
    output = (
        "host gospelo-dev\n"
        "hostname github.com\n"
        "user git\n"
        "identityfile ~/.ssh/id_gospelo-dev-gorosun\n"
        "identitiesonly yes\n"
    )
    mock_subprocess.set("ssh -G gospelo-dev", returncode=0, stdout=output)
    cfg = _external.ssh_resolve("gospelo-dev")
    assert cfg.hostname == "github.com"
    assert cfg.user == "git"
    assert cfg.identity_file == "~/.ssh/id_gospelo-dev-gorosun"
    assert cfg.identities_only is True


def test_ssh_resolve_identities_only_no(mock_subprocess) -> None:
    mock_subprocess.set(
        "ssh -G github.com",
        returncode=0,
        stdout="hostname github.com\nidentitiesonly no\n",
    )
    cfg = _external.ssh_resolve("github.com")
    assert cfg.identities_only is False
    assert cfg.identity_file is None


def test_ssh_resolve_takes_first_identityfile(mock_subprocess) -> None:
    mock_subprocess.set(
        "ssh -G h",
        returncode=0,
        stdout="identityfile ~/.ssh/first\nidentityfile ~/.ssh/second\n",
    )
    assert _external.ssh_resolve("h").identity_file == "~/.ssh/first"


# ---------------------------------------------------------------------------
# gh_account_available
# ---------------------------------------------------------------------------


def test_gh_account_available_true(mock_subprocess) -> None:
    mock_subprocess.set("gh auth token --user alice", returncode=0, stdout="gho_xxx")
    assert _external.gh_account_available("alice") is True


def test_gh_account_available_false_on_error(mock_subprocess) -> None:
    mock_subprocess.set(
        "gh auth token --user nobody", returncode=1, stderr="no such user"
    )
    assert _external.gh_account_available("nobody") is False


def test_gh_account_available_false_on_empty(mock_subprocess) -> None:
    mock_subprocess.set("gh auth token --user ghost", returncode=0, stdout="")
    assert _external.gh_account_available("ghost") is False


# ---------------------------------------------------------------------------
# owner_from_remote_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("git@github.com:acme/tool.git", "acme"),
        ("git@gospelo-dev:acme/tool.git", "acme"),        # SSH-alias host
        ("gospelo-dev:acme/tool", "acme"),                # alias without user@
        ("ssh://git@github.com/acme/tool.git", "acme"),
        ("ssh://git@github.com:2222/acme/tool.git", "acme"),
        ("https://github.com/acme/tool.git", "acme"),
        ("https://github.com/acme/tool", "acme"),
        ("git://github.com/acme/tool.git", "acme"),
        ("https://github.com/", None),                    # no owner segment
        ("/data/repos/tool.git", None),                   # local path
        ("../relative/repo", None),
        ("file:///data/repos/tool.git", None),            # non-remote scheme
        ("", None),
    ],
)
def test_owner_from_remote_url(url, expected) -> None:
    assert _external.owner_from_remote_url(url) == expected


# ---------------------------------------------------------------------------
# gh_auth_token
# ---------------------------------------------------------------------------


def test_gh_auth_token_returns_token(mock_subprocess) -> None:
    mock_subprocess.set("auth token --user alice", stdout="ghp_secret\n")
    assert _external.gh_auth_token("alice") == "ghp_secret"


def test_gh_auth_token_missing_returns_none(mock_subprocess) -> None:
    mock_subprocess.set(
        "auth token --user ghost", returncode=1,
        stderr="no accounts matched",
    )
    assert _external.gh_auth_token("ghost") is None


def test_gh_auth_token_uses_explicit_gh_path(mock_subprocess) -> None:
    """The guard passes the REAL gh path so the lookup never re-enters the
    PATH shim."""
    mock_subprocess.set("/opt/real/gh auth token --user alice", stdout="tok")
    assert _external.gh_auth_token("alice", gh_path="/opt/real/gh") == "tok"
    assert mock_subprocess.calls[-1].startswith("/opt/real/gh ")


# ---------------------------------------------------------------------------
# rewrite_remote_host (pure parser)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, new_host, expected",
    [
        ("git@github.com:org/repo.git", "gorosun", "git@gorosun:org/repo.git"),
        ("git@gorosun:org/repo.git", "pasona-ghayakawa", "git@pasona-ghayakawa:org/repo.git"),
        ("ssh://git@github.com/org/repo.git", "gorosun", "ssh://git@gorosun/org/repo.git"),
        ("ssh://github.com/org/repo.git", "gorosun", "ssh://gorosun/org/repo.git"),
        ("https://github.com/org/repo.git", "gorosun", None),
        ("/local/path/repo.git", "gorosun", None),
        ("", "gorosun", None),
    ],
)
def test_rewrite_remote_host(url: str, new_host: str, expected: str | None) -> None:
    assert _external.rewrite_remote_host(url, new_host) == expected


# ---------------------------------------------------------------------------
# git_set_remote_url
# ---------------------------------------------------------------------------


def test_git_set_remote_url_success(mock_subprocess) -> None:
    mock_subprocess.set(
        "git remote set-url origin git@gorosun:org/repo.git",
        returncode=0,
    )
    _external.git_set_remote_url("origin", "git@gorosun:org/repo.git")
    assert any("git remote set-url origin" in c for c in mock_subprocess.calls)


def test_git_set_remote_url_failure_raises(mock_subprocess) -> None:
    mock_subprocess.set(
        "git remote set-url origin",
        returncode=2,
        stderr="error: No such remote",
    )
    with pytest.raises(ExternalToolError, match="failed"):
        _external.git_set_remote_url("origin", "git@gorosun:org/repo.git")
