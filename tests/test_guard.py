# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.guard`` — write classification, the runtime
gate (fail-closed on identity mismatch), and shim install/uninstall."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gospelo_github_identity import guard


@pytest.fixture(autouse=True)
def _clear_skip_env():
    """The guard sets GOSPELO_GITHUB_IDENTITY_SKIP in os.environ (correct for the real
    one-shot process, which then execs/exits). Across in-process tests it would
    leak, so clear it around every test."""
    os.environ.pop(guard.SKIP_ENV, None)
    yield
    os.environ.pop(guard.SKIP_ENV, None)


# ---------------------------------------------------------------------------
# Write classification (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,argv,expected",
    [
        ("git", ["push"], True),
        ("git", ["push", "origin", "main"], True),
        ("git", ["-C", "/tmp/repo", "push"], True),      # value flag skipped
        ("git", ["status"], False),
        ("git", ["log", "--oneline"], False),
        ("git", ["-c", "user.name=x", "status"], False),
        ("gh", ["release", "create", "v1"], True),
        ("gh", ["pr", "create"], True),
        ("gh", ["repo", "create", "x"], True),
        ("gh", ["secret", "set", "TOKEN"], True),
        ("gh", ["release", "view", "v1"], False),
        ("gh", ["pr", "view", "12"], False),
        ("gh", ["repo", "clone", "x"], False),
        ("gh", ["auth", "status"], False),
        ("gh", ["api", "user"], False),                   # GET
        ("gh", ["api", "user", "--jq", ".login"], False),
        ("gh", ["api", "-X", "POST", "/repos/x/y/issues"], True),
        ("gh", ["api", "--method", "delete", "/x"], True),
        ("gh", ["api", "/x", "-f", "a=b"], True),         # field implies POST
        ("git", [], False),
        ("gh", [], False),
    ],
)
def test_is_write_invocation(tool, argv, expected):
    assert guard.is_write_invocation(tool, argv) is expected


# ---------------------------------------------------------------------------
# Runtime gate
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_exec(monkeypatch):
    """Capture os.execv instead of replacing the process."""
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(guard.os, "execv", lambda real, argv: calls.append((real, argv)))
    return calls


def _run_guard(monkeypatch, tool, real, args):
    monkeypatch.setattr(
        "sys.argv",
        ["gospelo-github-identity guard", "--tool", tool, "--real", real, "--", *args],
    )
    guard.guard_main()


def test_readonly_passes_through(monkeypatch, captured_exec, mock_external):
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["pr", "view", "1"])
    assert captured_exec == [("/usr/bin/gh", ["/usr/bin/gh", "pr", "view", "1"])]


def test_skip_env_bypasses(monkeypatch, captured_exec):
    monkeypatch.setenv(guard.SKIP_ENV, "1")
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["release", "create", "v1"])
    assert captured_exec == [("/usr/bin/gh", ["/usr/bin/gh", "release", "create", "v1"])]


def test_write_blocked_on_mismatch(
    monkeypatch, captured_exec, isolated_config, tmp_home, mock_external, capsys
):
    """gh write under the matched profile, wrong gh account -> exit 1, no exec."""
    target = tmp_home / "projects" / "personal" / "repo"
    target.mkdir(parents=True)
    monkeypatch.chdir(target)
    mock_external["gh_login"] = "someone-else"   # expected: alice-personal
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["release", "create", "v1"])
    assert exc.value.code == 1
    assert captured_exec == []  # real binary NEVER executed
    err = capsys.readouterr().err
    assert "BLOCKED" in err and "personal" in err


def test_write_allowed_on_match(
    monkeypatch, captured_exec, isolated_config, tmp_home, mock_external, capsys
):
    target = tmp_home / "projects" / "personal" / "repo"
    target.mkdir(parents=True)
    monkeypatch.chdir(target)
    mock_external["gh_login"] = "alice-personal"   # matches profile
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["release", "create", "v1"])
    assert captured_exec == [("/usr/bin/gh", ["/usr/bin/gh", "release", "create", "v1"])]
    # A matched write announces a positive confirmation on stderr.
    assert "identity OK" in capsys.readouterr().err


def test_readonly_is_silent(monkeypatch, captured_exec, mock_external, capsys):
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["pr", "view", "1"])
    assert capsys.readouterr().err == "", "read-only must never emit notices"


def test_write_ungoverned_dir_announces_passthrough(
    monkeypatch, captured_exec, tmp_home, minimal_config_file, mock_external, capsys
):
    """Config valid but the target matches no profile (and no default): the
    write passes through, but it must SAY SO — a silent pass-through could
    mask a path-glob typo."""
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(minimal_config_file))
    outside = tmp_home / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)
    _run_guard(monkeypatch, "git", "/usr/bin/git", ["push"])
    assert captured_exec == [("/usr/bin/git", ["/usr/bin/git", "push"])]
    assert "not governed" in capsys.readouterr().err


def test_quiet_env_suppresses_notice_but_not_block(
    monkeypatch, captured_exec, isolated_config, tmp_home, mock_external, capsys
):
    monkeypatch.setenv(guard.QUIET_ENV, "1")
    target = tmp_home / "projects" / "personal" / "repo"
    target.mkdir(parents=True)
    monkeypatch.chdir(target)

    # QUIET silences the positive "identity OK" line on a matched write.
    mock_external["gh_login"] = "alice-personal"
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["release", "create", "v1"])
    assert capsys.readouterr().err == ""

    # The gate sets SKIP_ENV during its own identity probe (recursion guard);
    # clear it so this second invocation is gated rather than bypassed.
    os.environ.pop(guard.SKIP_ENV, None)

    # ...but a BLOCK is always reported, even with QUIET set.
    mock_external["gh_login"] = "someone-else"
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["release", "create", "v1"])
    assert exc.value.code == 1
    assert "BLOCKED" in capsys.readouterr().err


def test_write_outside_profile_passes_through(
    monkeypatch, captured_exec, isolated_config, tmp_home, mock_external
):
    """A directory governed by no profile (and config has a default) ..."""
    # VALID_CONFIG_YAML has default_profile: personal, so everything matches.
    # Use a config-less dir scenario via ConfigError path instead.
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(tmp_home / "none.yml"))
    _run_guard(monkeypatch, "git", "/usr/bin/git", ["push"])
    assert captured_exec == [("/usr/bin/git", ["/usr/bin/git", "push"])]


def test_git_push_blocked_on_wrong_author(
    monkeypatch, captured_exec, isolated_config, tmp_home, mock_external
):
    target = tmp_home / "projects" / "personal" / "repo"
    target.mkdir(parents=True)
    monkeypatch.chdir(target)
    mock_external["git_user_email"] = "wrong@example.com"  # expected alice@example.com
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "git", "/usr/bin/git", ["push"])
    assert exc.value.code == 1
    assert captured_exec == []


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------


def _make_realbin(tmp_path, *, guard_capable: bool):
    """A fake PATH dir with gh/git plus a gospelo-github-identity of known capability."""
    realbin = tmp_path / "realbin"
    realbin.mkdir()
    for t in ("gh", "git"):
        p = realbin / t
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
    gi = realbin / "gospelo-github-identity"
    if guard_capable:
        # Exit 0 on `guard --selftest`, like the current build.
        gi.write_text(
            '#!/bin/sh\n'
            'if [ "$1" = "guard" ] && [ "$2" = "--selftest" ]; then exit 0; fi\n'
            'exit 2\n'
        )
    else:
        # A stale build: every invocation (incl. selftest) errors out.
        gi.write_text('#!/bin/sh\necho "ERROR: unknown subcommand: $1" >&2\nexit 2\n')
    gi.chmod(0o755)
    return realbin


def test_install_and_uninstall_guard(monkeypatch, tmp_path, capsys):
    # Provide a fake PATH with a real gh/git so resolution succeeds.
    realbin = _make_realbin(tmp_path, guard_capable=True)
    monkeypatch.setenv("PATH", str(realbin))
    monkeypatch.setattr("shutil.which", lambda name: str(realbin / "gospelo-github-identity")
                        if name == "gospelo-github-identity" else None)

    shim_dir = tmp_path / "guardbin"
    # Default is gh-only; opt into git explicitly for this test.
    monkeypatch.setattr("sys.argv", ["install-guard", "--dir", str(shim_dir), "--tools", "gh,git"])
    with pytest.raises(SystemExit) as exc:
        guard.install_main()
    assert exc.value.code == 0
    gh_shim = shim_dir / "gh"
    git_shim = shim_dir / "git"
    assert gh_shim.exists() and git_shim.exists()
    body = gh_shim.read_text()
    assert "guard --tool gh --real" in body
    assert str(realbin / "gh") in body
    assert gh_shim.stat().st_mode & 0o111  # executable

    # Uninstall removes them.
    monkeypatch.setattr("sys.argv", ["uninstall-guard", "--dir", str(shim_dir)])
    with pytest.raises(SystemExit) as exc:
        guard.uninstall_main()
    assert exc.value.code == 0
    assert not gh_shim.exists() and not git_shim.exists()


def test_install_guard_refuses_stale_build(monkeypatch, tmp_path, capsys):
    # The resolved gospelo-github-identity lacks the `guard` subcommand (stale install).
    realbin = _make_realbin(tmp_path, guard_capable=False)
    monkeypatch.setenv("PATH", str(realbin))
    monkeypatch.setattr("shutil.which", lambda name: str(realbin / "gospelo-github-identity")
                        if name == "gospelo-github-identity" else None)

    shim_dir = tmp_path / "guardbin"
    monkeypatch.setattr("sys.argv", ["install-guard", "--dir", str(shim_dir), "--tools", "gh"])
    with pytest.raises(SystemExit) as exc:
        guard.install_main()
    assert exc.value.code == 1
    # No broken shim should have been written.
    assert not (shim_dir / "gh").exists()
    assert "does not support the 'guard' subcommand" in capsys.readouterr().err


def test_guard_selftest_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gospelo-github-identity guard", "--selftest"])
    guard.guard_main()  # returns normally (no SystemExit)
    assert "ok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Target resolution (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["pr", "create", "--repo", "acme-corp/tool"], "acme-corp"),
        (["pr", "create", "-R", "acme-corp/tool"], "acme-corp"),
        (["release", "create", "v1", "--repo=acme-corp/tool"], "acme-corp"),
        (["pr", "create", "--repo", "github.com/acme-corp/tool"], "acme-corp"),
        (["pr", "create", "--repo", "https://github.com/acme-corp/tool"], "acme-corp"),
        (["repo", "delete", "acme-corp/tool", "--yes"], "acme-corp"),
        (["repo", "edit", "acme-corp/tool", "--visibility", "private"], "acme-corp"),
        # A flag value must never be mistaken for the positional repo spec.
        (["repo", "edit", "--description", "a/b"], None),
        (["api", "-X", "POST", "/repos/acme-corp/tool/issues"], "acme-corp"),
        (["api", "repos/acme-corp/tool/releases", "-f", "tag=v1"], "acme-corp"),
        (["api", "/user", "-f", "name=x"], None),
        (["pr", "create"], None),
        (["gist", "create", "notes.md"], None),
        ([], None),
    ],
)
def test_gh_target_owner(argv, expected):
    assert guard.gh_target_owner(argv) == expected


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["push"], "/base"),
        (["-C", "/repo", "push"], "/repo"),
        (["-C", "a", "push"], "/base/a"),
        (["-C", "a", "-C", "b", "push"], "/base/a/b"),          # composes
        (["-C", "a", "-C", "/abs", "push"], "/abs"),
        (["-C", "", "push"], "/base"),                          # documented no-op
        (["-c", "user.name=x", "push"], "/base"),               # value flag skipped
        (["push", "-C", "/late"], "/base"),                     # after subcommand: ignored
    ],
)
def test_git_target_dir(argv, expected):
    assert guard.git_target_dir(argv, Path("/base")) == Path(expected)


# ---------------------------------------------------------------------------
# Enforce mode (gh.owners declared -> token injection, fail-closed)
# ---------------------------------------------------------------------------

OWNERS_CONFIG_YAML = """\
version: "1"
profiles:
  personal:
    git: {user.name: "Alice Example", user.email: "alice@example.com"}
    gh:
      account: "alice-personal"
      owners: [alice-personal, alice-oss-org]
    paths:
      - ~/projects/personal/**
  work:
    git: {user.name: "Alice Example", user.email: "alice@company.example"}
    gh:
      account: "alice-work"
      owners: [acme-corp]
    paths:
      - ~/projects/work/**
"""


@pytest.fixture
def owners_config(tmp_home, write_config, monkeypatch):
    cfg = write_config(OWNERS_CONFIG_YAML)
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(cfg))
    return cfg


@pytest.fixture
def token_store(monkeypatch):
    """Stub the keyring: account -> token. Records lookups (incl. gh_path)."""
    store = {"alice-personal": "tok-personal", "alice-work": "tok-work"}
    calls: list[tuple[str, str | None]] = []

    def fake_token(login, *, gh_path=None):
        calls.append((login, gh_path))
        return store.get(login)

    monkeypatch.setattr("gospelo_github_identity._external.gh_auth_token", fake_token)
    monkeypatch.delenv("GH_TOKEN", raising=False)  # registers teardown restore
    return calls


def test_enforce_repo_flag_wins_over_cwd(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, token_store, capsys
):
    """`gh --repo acme-corp/x` from a personal dir must act as the WORK
    identity: the target owner outranks the working directory."""
    cwd = tmp_home / "projects" / "personal" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    _run_guard(monkeypatch, "gh", "/usr/bin/gh",
               ["pr", "create", "--repo", "acme-corp/tool"])
    assert captured_exec == [
        ("/usr/bin/gh", ["/usr/bin/gh", "pr", "create", "--repo", "acme-corp/tool"])
    ]
    assert os.environ["GH_TOKEN"] == "tok-work"
    assert token_store == [("alice-work", "/usr/bin/gh")]  # real binary, not the shim
    assert "enforcing identity 'alice-work'" in capsys.readouterr().err


def test_enforce_unknown_owner_blocks(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, token_store, capsys
):
    cwd = tmp_home / "projects" / "personal" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "gh", "/usr/bin/gh",
                   ["pr", "create", "--repo", "stranger-org/tool"])
    assert exc.value.code == 1
    assert captured_exec == []
    err = capsys.readouterr().err
    assert "BLOCKED" in err and "stranger-org" in err and "gh.owners" in err


def test_enforce_cwd_remote_resolves_owner(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, token_store
):
    """No --repo: the cwd repo's remote owner decides, even from an
    ungoverned directory (target-aware, not cwd-aware)."""
    outside = tmp_home / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)
    mock_external["remote_url"] = "git@gospelo-dev:alice-oss-org/lib.git"
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["release", "create", "v1"])
    assert captured_exec != []
    assert os.environ["GH_TOKEN"] == "tok-personal"


def test_enforce_targetless_falls_back_to_cwd_profile(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, token_store
):
    cwd = tmp_home / "projects" / "work" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    mock_external["remote_url"] = None  # not a repo / no remote
    _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["gist", "create", "notes.md"])
    assert captured_exec != []
    assert os.environ["GH_TOKEN"] == "tok-work"


def test_enforce_targetless_ungoverned_blocks(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, token_store, capsys
):
    outside = tmp_home / "elsewhere"
    outside.mkdir()
    monkeypatch.chdir(outside)
    mock_external["remote_url"] = None
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "gh", "/usr/bin/gh", ["gist", "create", "notes.md"])
    assert exc.value.code == 1
    assert captured_exec == []
    assert "fail-closed" in capsys.readouterr().err


def test_enforce_missing_credential_blocks(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, capsys
):
    monkeypatch.setattr(
        "gospelo_github_identity._external.gh_auth_token",
        lambda login, *, gh_path=None: None,
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    cwd = tmp_home / "projects" / "personal" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "gh", "/usr/bin/gh",
                   ["pr", "create", "--repo", "acme-corp/tool"])
    assert exc.value.code == 1
    assert captured_exec == []
    assert "no stored credential" in capsys.readouterr().err


def test_git_push_gated_against_dash_c_target(
    monkeypatch, captured_exec, isolated_config, tmp_home, capsys
):
    """`git -C <work-repo> push` from a personal dir must be judged by the
    WORK repo's config, not the cwd's."""
    personal = tmp_home / "projects" / "personal" / "repo"
    work = tmp_home / "projects" / "work" / "repo"
    personal.mkdir(parents=True)
    work.mkdir(parents=True)
    monkeypatch.chdir(personal)

    def cwd_sensitive_config(key, cwd=None, **kwargs):
        # The work repo carries the personal author -> mismatch for `work`.
        values = {"user.name": "Alice Example", "user.email": "alice@example.com"}
        return values.get(key)

    monkeypatch.setattr(
        "gospelo_github_identity._external.git_get_config", cwd_sensitive_config
    )
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "git", "/usr/bin/git", ["-C", str(work), "push"])
    assert exc.value.code == 1
    assert captured_exec == []
    err = capsys.readouterr().err
    assert "BLOCKED" in err and "'work'" in err  # judged as the work profile


def test_git_push_unknown_owner_blocks_when_owners_enabled(
    monkeypatch, captured_exec, owners_config, tmp_home, mock_external, capsys
):
    outside = tmp_home / "clones" / "third-party"
    outside.mkdir(parents=True)
    monkeypatch.chdir(outside)
    mock_external["remote_url"] = "git@github.com:stranger-org/tool.git"
    with pytest.raises(SystemExit) as exc:
        _run_guard(monkeypatch, "git", "/usr/bin/git", ["push"])
    assert exc.value.code == 1
    assert captured_exec == []
    assert "stranger-org" in capsys.readouterr().err
