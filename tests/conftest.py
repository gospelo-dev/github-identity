# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Shared pytest fixtures for gospelo-github-identity tests.

All fixtures are designed to keep tests fully hermetic: no test reads or
writes the user's real ``~/.config/gospelo-github-identity/config.yml``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable

import pytest


# ---------------------------------------------------------------------------
# Sample YAML payloads
# ---------------------------------------------------------------------------

VALID_CONFIG_YAML = dedent(
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
        paths:
          - ~/projects/personal/**
          - ~/projects/oss/**
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


MINIMAL_CONFIG_YAML = dedent(
    """\
    version: "1"
    profiles:
      solo:
        git:
          user.name: "Bob"
          user.email: "bob@example.com"
        gh:
          account: "bob"
        paths:
          - ~/projects/**
    """
)


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``$HOME`` to a temporary directory.

    Anything that calls ``Path.expanduser()`` or reads ``~`` lands in this
    isolated tree. Nothing touches the real user home.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # macOS / pyenv occasionally reads these too. Force them in lockstep.
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture
def write_config(tmp_path: Path):
    """Return a helper that writes a YAML payload to a temp file and returns
    its ``Path``."""

    def _write(content: str, name: str = "config.yml") -> Path:
        target = tmp_path / name
        target.write_text(content, encoding="utf-8")
        return target

    return _write


@pytest.fixture
def valid_config_file(write_config) -> Path:
    """A temp config.yml containing two profiles + a default."""
    return write_config(VALID_CONFIG_YAML)


@pytest.fixture
def minimal_config_file(write_config) -> Path:
    """A temp config.yml with a single profile, no default."""
    return write_config(MINIMAL_CONFIG_YAML)


@pytest.fixture
def isolated_config(
    tmp_home: Path, valid_config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``GOSPELO_GITHUB_IDENTITY_CONFIG`` at a temp file under a temp HOME.

    Useful for any code path that calls ``resolve_config_path()`` /
    ``load_config()`` without an explicit path argument.
    """
    monkeypatch.setenv("GOSPELO_GITHUB_IDENTITY_CONFIG", str(valid_config_file))
    return valid_config_file


# ---------------------------------------------------------------------------
# Subprocess / external CLI fixtures
# ---------------------------------------------------------------------------


class MockSubprocess:
    """Programmable replacement for ``subprocess.run`` used by tests.

    Tests register expected commands with :meth:`set` and the mock returns the
    configured ``CompletedProcess`` whenever a matching command is invoked.
    All invocations are recorded in :attr:`calls` so tests can assert on
    history. If a command is invoked without a matching expectation the mock
    raises ``AssertionError`` -- there is no silent fallback.
    """

    def __init__(self) -> None:
        self.responses: dict[str, tuple[int, str, str]] = {}
        self.calls: list[str] = []

    def set(
        self,
        cmd_signature: str,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Register a stub for any command whose signature contains
        ``cmd_signature``."""
        self.responses[cmd_signature] = (returncode, stdout, stderr)

    def _signature(self, cmd) -> str:
        if isinstance(cmd, list):
            return " ".join(str(c) for c in cmd)
        return str(cmd)

    def __call__(self, cmd, **kwargs) -> subprocess.CompletedProcess:
        sig = self._signature(cmd)
        self.calls.append(sig)
        for key, resp in self.responses.items():
            if key in sig:
                rc, out, err = resp
                return subprocess.CompletedProcess(
                    args=cmd, returncode=rc, stdout=out, stderr=err
                )
        raise AssertionError(
            f"MockSubprocess: no stub registered for command: {sig!r}. "
            f"Registered keys: {list(self.responses)}"
        )


@pytest.fixture
def mock_subprocess(monkeypatch: pytest.MonkeyPatch) -> MockSubprocess:
    """Replace ``subprocess.run`` (used by ``_external``) with a programmable
    mock so the test does not actually invoke ``git`` / ``gh``.

    Also patches ``shutil.which`` so the ``_require`` helper inside
    ``_external`` always reports the tool as available.
    """
    mock = MockSubprocess()
    monkeypatch.setattr("gospelo_github_identity._external.subprocess.run", mock)
    monkeypatch.setattr(
        "gospelo_github_identity._external.shutil.which",
        lambda tool: f"/usr/bin/{tool}",
    )
    return mock


@pytest.fixture
def mock_external(monkeypatch: pytest.MonkeyPatch) -> dict:
    """High-level mock that stubs the public ``_external`` helpers directly.

    Tests can mutate the returned dict (e.g. ``mock_external['git_user_name']
    = 'alice'``) to control what each helper returns. This is more convenient
    than ``mock_subprocess`` when the test does not care about which CLI
    arguments were passed.
    """
    state: dict[str, Any] = {
        "git_user_name": None,
        "git_user_email": None,
        "gh_login": None,
        "inside_work_tree": True,
        "set_config_calls": [],
        "switch_calls": [],
        "git_set_raises": None,
        "gh_switch_raises": None,
        # SSH-login check (opt-in). ``remote_url`` is what `git remote get-url
        # origin` returns; ``ssh_probe_login`` / ``ssh_probe_detail`` are what
        # the `ssh -T` probe reports back.
        "remote_url": None,
        "ssh_probe_login": None,
        "ssh_probe_detail": "",
        # Simulate the real identity reported by `gh api user` AFTER a switch.
        # None  -> a correct switch (real login becomes the target account).
        # str   -> a keyring mismatch (real login stays this stale value).
        "gh_switch_stale_login": None,
        # Remote URL rewriting tracking.
        "set_remote_calls": [],
    }

    def fake_get_config(key: str, cwd=None) -> str | None:
        if key == "user.name":
            return state["git_user_name"]
        if key == "user.email":
            return state["git_user_email"]
        return None

    def fake_set_config(key: str, value: str, *, scope: str = "local", cwd=None) -> None:
        state["set_config_calls"].append((key, value, scope, cwd))
        if state["git_set_raises"] is not None:
            from gospelo_github_identity._external import ExternalToolError
            raise ExternalToolError(state["git_set_raises"])

    def fake_inside_tree(cwd=None) -> bool:
        return bool(state["inside_work_tree"])

    def fake_active_login() -> str | None:
        return state["gh_login"]

    def fake_switch(account: str) -> None:
        state["switch_calls"].append(account)
        if state["gh_switch_raises"] is not None:
            from gospelo_github_identity._external import ExternalToolError
            raise ExternalToolError(state["gh_switch_raises"])
        # A real `gh auth switch` changes which token `gh api user` resolves to.
        # Mirror that here so the switcher's post-switch verification has
        # something to read: the target account on success, or a stale login
        # when simulating a corrupted keyring credential.
        state["gh_login"] = state["gh_switch_stale_login"] or account

    def fake_remote_url(remote: str = "origin", cwd=None) -> str | None:
        return state["remote_url"]

    def fake_ssh_probe(target: str, **kwargs) -> tuple[str | None, str]:
        return state["ssh_probe_login"], state["ssh_probe_detail"]

    def fake_set_remote_url(remote: str, url: str, cwd=None) -> None:
        state["set_remote_calls"].append((remote, url, cwd))

    monkeypatch.setattr("gospelo_github_identity._external.git_get_config", fake_get_config)
    monkeypatch.setattr("gospelo_github_identity._external.git_set_config", fake_set_config)
    monkeypatch.setattr("gospelo_github_identity._external.git_inside_work_tree", fake_inside_tree)
    monkeypatch.setattr("gospelo_github_identity._external.gh_active_login", fake_active_login)
    monkeypatch.setattr("gospelo_github_identity._external.gh_switch_account", fake_switch)
    monkeypatch.setattr("gospelo_github_identity._external.git_remote_url", fake_remote_url)
    monkeypatch.setattr("gospelo_github_identity._external.ssh_probe_login", fake_ssh_probe)
    monkeypatch.setattr("gospelo_github_identity._external.git_set_remote_url", fake_set_remote_url)
    return state
