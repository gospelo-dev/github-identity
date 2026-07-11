# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Smoke tests for the ``gospelo-github-identity`` CLI.

Each test invokes the CLI as a subprocess so that argparse, importlib
dispatch, and the console-script entry point are all exercised. No real
git / gh CLI is invoked; we only hit ``--help`` / ``--version`` / unknown
subcommand paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI via ``python -m gospelo_github_identity.cli``.

    Using ``python -m`` (instead of the installed console script) keeps the
    smoke tests runnable from a plain checkout without ``pip install -e .``.
    """
    env = os.environ.copy()
    # Make sure the package under test wins over any installed copy.
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "gospelo_github_identity.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Top-level CLI
# ---------------------------------------------------------------------------


def test_cli_version() -> None:
    proc = _run_cli("--version")
    assert proc.returncode == 0, f"--version must exit 0, got: {proc.stderr}"
    assert "gospelo-github-identity" in proc.stdout
    # Version string must be present.
    from gospelo_github_identity import __version__

    assert __version__ in proc.stdout


def test_cli_help_lists_subcommands() -> None:
    proc = _run_cli("--help")
    assert proc.returncode == 0, f"--help must exit 0, got: {proc.stderr}"
    combined = proc.stdout + proc.stderr
    for sub in ("init", "list", "detect", "check", "switch", "prompt"):
        assert sub in combined, f"subcommand {sub!r} should appear in --help output"


def test_cli_no_args_prints_usage_and_exits_nonzero() -> None:
    proc = _run_cli()
    assert proc.returncode != 0, "running with no subcommand should fail"
    assert "Usage" in (proc.stdout + proc.stderr)


def test_cli_unknown_subcommand_errors() -> None:
    proc = _run_cli("nonsense")
    assert proc.returncode != 0
    assert "unknown subcommand" in (proc.stdout + proc.stderr).lower()


# ---------------------------------------------------------------------------
# Subcommand --help (smoke: argparse + import wiring)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcommand",
    ["list", "detect", "check", "switch", "init", "prompt"],
)
def test_subcommand_help_exits_clean(subcommand: str) -> None:
    proc = _run_cli(subcommand, "--help")
    assert proc.returncode == 0, (
        f"`{subcommand} --help` must exit 0, got rc={proc.returncode}, "
        f"stderr={proc.stderr!r}"
    )
    combined = proc.stdout + proc.stderr
    assert subcommand in combined.lower() or "usage" in combined.lower(), (
        f"`{subcommand} --help` output should mention the subcommand or 'usage'"
    )


def test_init_help_documents_template_flags() -> None:
    proc = _run_cli("init", "--help")
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "--from-template" in combined, (
        "init --help should document --from-template"
    )
    assert "--show-example" in combined, (
        "init --help should document --show-example"
    )


def test_prompt_help_documents_format_flag() -> None:
    proc = _run_cli("prompt", "--help")
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "--format" in combined, "prompt --help should document --format"


def test_switch_help_documents_dry_run() -> None:
    proc = _run_cli("switch", "--help")
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "--dry-run" in combined
    assert "--global" in combined


# ---------------------------------------------------------------------------
# init --show-example (no external deps, no prompts)
# ---------------------------------------------------------------------------


def test_init_show_example_prints_template() -> None:
    proc = _run_cli("init", "--show-example")
    assert proc.returncode == 0, f"--show-example must exit 0, got: {proc.stderr}"
    # The bundled template must be a valid version-1 config skeleton.
    assert "version:" in proc.stdout
    assert "profiles:" in proc.stdout


# ---------------------------------------------------------------------------
# In-process dispatcher tests (faster + better coverage of cli.py)
# ---------------------------------------------------------------------------


def test_resolve_known_subcommand_returns_callable() -> None:
    from gospelo_github_identity import cli

    handler = cli._resolve("list")
    assert callable(handler)


def test_resolve_unknown_subcommand_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gospelo_github_identity import cli

    with pytest.raises(SystemExit) as exc:
        cli._resolve("does-not-exist")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err.lower()


def test_main_no_args_exits_two_and_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gospelo_github_identity import cli

    monkeypatch.setattr("sys.argv", ["gospelo-github-identity"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Usage" in err


def test_main_help_short_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gospelo_github_identity import cli

    monkeypatch.setattr("sys.argv", ["gospelo-github-identity", "-h"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert "Subcommands" in err


def test_main_version_short_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gospelo_github_identity import cli
    from gospelo_github_identity import __version__

    monkeypatch.setattr("sys.argv", ["gospelo-github-identity", "-V"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_main_dispatches_to_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``main`` should rewrite ``sys.argv`` and call the resolved handler."""
    from gospelo_github_identity import cli

    called: dict[str, list[str]] = {}

    def fake_handler() -> None:
        import sys

        called["argv"] = list(sys.argv)

    monkeypatch.setattr(cli, "_resolve", lambda sub: fake_handler)
    monkeypatch.setattr(
        "sys.argv", ["gospelo-github-identity", "list", "--some-flag"]
    )
    cli.main()
    assert called["argv"] == ["gospelo-github-identity list", "--some-flag"]
