# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Deterministic, local, fail-closed command guard for ``gh`` / ``git``.

This shadows ``gh`` and ``git`` on ``PATH`` with tiny shim executables. Every
invocation is routed through ``gospelo-github-identity guard``, which:

  * passes **read-only** commands straight through to the real binary, and
  * for **write** commands (``git push``; ``gh release/pr/repo/... create`` etc.)
    runs the directory's identity check first and **blocks** (non-zero exit,
    real binary never executed) when the active git/gh identity does not match
    the profile that owns the current directory.

Design constraints (why this exists rather than depending on a third-party
"command firewall"):

  * **Deterministic** — pure pattern logic, never an LLM. There is no prompt to
    inject.
  * **Local** — nothing leaves the machine beyond the ``gh api user`` call the
    check already makes.
  * **Fail-closed within a declared profile** — a write under a matched profile
    with a mismatched identity is blocked. Outside any declared profile (or when
    ``GOSPELO_GITHUB_IDENTITY_SKIP`` is set) the real command runs unchanged, so the
    guard never breaks unrelated work.

Limitations (documented, not silently assumed away):

  * A ``PATH`` shim only intercepts **name-based** calls. A command invoked by
    absolute path (``/usr/bin/git push``) bypasses it. For tamper-resistance
    against an adversarial process, layer an OS sandbox; the shim's job is to
    stop *accidental* wrong-identity writes during autonomous agent runs.
  * The write-classifier covers the common irreversible/outward subcommands; it
    is intentionally conservative (unknown subcommands pass through).
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

from . import _external
from .config import ConfigError, load_config
from .matcher import resolve_profile

SKIP_ENV = "GOSPELO_GITHUB_IDENTITY_SKIP"
QUIET_ENV = "GOSPELO_GITHUB_IDENTITY_QUIET"
DEFAULT_GUARD_DIR = "~/.gospelo-github-identity/bin"
SUPPORTED_TOOLS = ("gh", "git")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip() not in ("", "0", "false", "False")


def _notice(message: str) -> None:
    """Print an informational guard notice to stderr.

    Suppressed when ``GOSPELO_GITHUB_IDENTITY_QUIET`` is set, so scripts that pipe
    git/gh output can silence the per-write status lines. BLOCK messages do
    NOT go through here — a blocked write is always reported.
    """
    if not _truthy_env(QUIET_ENV):
        print(f"gospelo-github-identity guard: {message}", file=sys.stderr)

# gh subcommands -> the actions under them that WRITE / are outward-facing.
# Conservative: anything not listed here passes through. ``api`` is handled
# separately by inspecting the HTTP method / field flags.
_GH_WRITE_ACTIONS: dict[str, set[str]] = {
    "release": {"create", "delete", "edit", "upload", "delete-asset"},
    "pr": {"create", "merge", "close", "edit", "review", "ready", "comment",
           "reopen", "lock", "unlock"},
    "repo": {"create", "delete", "edit", "archive", "unarchive", "rename",
             "sync", "set-default", "fork"},
    "gist": {"create", "delete", "edit", "rename"},
    "issue": {"create", "close", "edit", "comment", "reopen", "delete",
              "transfer", "pin", "unpin", "lock", "unlock"},
    "secret": {"set", "delete"},
    "variable": {"set", "delete"},
    "workflow": {"run", "enable", "disable"},
    "run": {"rerun", "cancel", "delete"},
    "label": {"create", "delete", "edit", "clone"},
    "cache": {"delete"},
}

# git global flags that consume the following token as a value (so the real
# subcommand is not mistaken for that value).
_GIT_VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}


# ---------------------------------------------------------------------------
# Write classification (pure, unit-tested)
# ---------------------------------------------------------------------------


def _git_subcommand(argv: list[str]) -> str | None:
    """Return the git subcommand, skipping value-taking global flags."""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _GIT_VALUE_FLAGS:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a
    return None


def _gh_sub_action(argv: list[str]) -> tuple[str | None, str | None]:
    """Return (subcommand, action) from the bare (non-flag) gh tokens."""
    bare = [a for a in argv if not a.startswith("-")]
    sub = bare[0] if bare else None
    action = bare[1] if len(bare) > 1 else None
    return sub, action


def _gh_api_is_write(argv: list[str]) -> bool:
    """True if a ``gh api`` call mutates (non-GET method or field/input flags)."""
    write_flags = {"-f", "-F", "--field", "--raw-field", "--input"}
    method: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-X", "--method"):
            method = argv[i + 1].upper() if i + 1 < len(argv) else None
            i += 2
            continue
        if a.startswith("--method="):
            method = a.split("=", 1)[1].upper()
            i += 1
            continue
        if a in write_flags or a.startswith("--field=") or a.startswith("--raw-field="):
            return True
        i += 1
    return method is not None and method not in ("GET", "HEAD")


def is_write_invocation(tool: str, argv: list[str]) -> bool:
    """Return True if ``<tool> argv`` is a write / outward-facing operation."""
    if tool == "git":
        return _git_subcommand(argv) == "push"
    if tool == "gh":
        sub, action = _gh_sub_action(argv)
        if sub == "api":
            return _gh_api_is_write(argv)
        actions = _GH_WRITE_ACTIONS.get(sub or "")
        return actions is not None and action in actions
    return False


# ---------------------------------------------------------------------------
# Runtime gate: `gospelo-github-identity guard --tool <t> --real <path> -- <args>`
# ---------------------------------------------------------------------------


def _exec_real(real: str, argv: list[str]) -> None:
    """Replace this process with the real binary (preserves exit code/tty)."""
    os.execv(real, [real, *argv])


def _identity_mismatches(tool: str, cwd: Path) -> tuple[str | None, list[str]]:
    """Compare the active identity against the cwd's profile for a write.

    Returns ``(profile_name | None, mismatches)``. ``profile_name`` is None when
    no profile governs this directory (-> caller passes through). A non-empty
    ``mismatches`` list means the write must be blocked.
    """
    config = load_config()
    match = resolve_profile(config, cwd)
    profile = match.profile
    if profile is None:
        return None, []  # not a governed directory

    # Prevent the check's own `gh api user` (which goes through the shim) from
    # recursing back into the guard.
    os.environ[SKIP_ENV] = "1"

    mismatches: list[str] = []
    if tool == "git":
        # git push identity == the commit author (local git config).
        name = _external.git_get_config("user.name", cwd=cwd)
        email = _external.git_get_config("user.email", cwd=cwd)
        if name != profile.git_user_name:
            mismatches.append(f"git user.name={name!r} (expected {profile.git_user_name!r})")
        if email != profile.git_user_email:
            mismatches.append(f"git user.email={email!r} (expected {profile.git_user_email!r})")
    else:  # gh
        login = _external.gh_active_login()
        if login != profile.gh_account:
            shown = login if login is not None else "(unauthenticated/unverifiable)"
            mismatches.append(f"gh account={shown!r} (expected {profile.gh_account!r})")
    return profile.name, mismatches


def guard_main() -> None:
    """Entry point the shims call. Gate a single ``gh``/``git`` invocation."""
    raw = sys.argv[1:]

    # Capability probe used by install-guard to confirm the resolved
    # ``gospelo-github-identity`` actually has this subcommand before baking it into a
    # shim. A build predating the guard feature errors with "unknown
    # subcommand: guard" instead, so a clean exit 0 here is the signal.
    if "--selftest" in raw:
        print("gospelo-github-identity guard: ok")
        return

    cmd_argv: list[str] = []
    if "--" in raw:
        sep = raw.index("--")
        opt_args, cmd_argv = raw[:sep], raw[sep + 1:]
    else:
        opt_args = raw

    parser = argparse.ArgumentParser(prog="gospelo-github-identity guard", add_help=False)
    parser.add_argument("--tool", required=True, choices=list(SUPPORTED_TOOLS))
    parser.add_argument("--real", required=True)
    opts, _unknown = parser.parse_known_args(opt_args)

    real = opts.real
    tool = opts.tool

    # Escape hatch + recursion guard: run the real binary untouched.
    if os.environ.get(SKIP_ENV, "").strip() not in ("", "0", "false", "False"):
        _exec_real(real, cmd_argv)
        return  # (unreachable after execv; kept for tests that patch execv)

    # Read-only commands are never gated.
    if not is_write_invocation(tool, cmd_argv):
        _exec_real(real, cmd_argv)
        return

    # Write command: enforce identity for the governing profile.
    try:
        profile_name, mismatches = _identity_mismatches(tool, Path.cwd())
    except ConfigError:
        # No usable config -> the guard governs nothing; do not break the user.
        _notice(
            "no usable config; passing through "
            "(run `gospelo-github-identity init` to enable enforcement)."
        )
        _exec_real(real, cmd_argv)
        return
    except _external.ExternalToolError as exc:
        # Cannot determine identity for a governed write -> fail closed.
        print(f"gospelo-github-identity guard: BLOCKED ({exc})", file=sys.stderr)
        sys.exit(1)

    if profile_name is None:
        # Directory governed by no profile. Announce on writes so a path-glob
        # typo (expected-to-be-governed dir that silently isn't) is visible.
        _notice("directory not governed by any profile; passing through.")
        _exec_real(real, cmd_argv)
        return

    if mismatches:
        cmd = f"{tool} {' '.join(cmd_argv)}".strip()
        print(
            f"gospelo-github-identity guard: BLOCKED write under profile "
            f"{profile_name!r} — identity does not match.\n"
            f"  command : {cmd}\n"
            + "".join(f"  mismatch: {m}\n" for m in mismatches)
            + f"  fix     : gospelo-github-identity switch {profile_name}\n"
            f"            (if switch reports OK but this persists, the keyring "
            f"credential is stale — re-login: gh auth logout --user <account> "
            f"&& gh auth login)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Identity matches -> allow, with a positive confirmation so the user can
    # see enforcement actually ran and passed (not silently skipped).
    _notice(f"identity OK for profile {profile_name!r}; passing through.")
    _exec_real(real, cmd_argv)


# ---------------------------------------------------------------------------
# install-guard / uninstall-guard
# ---------------------------------------------------------------------------


def _resolve_real_binary(tool: str, guard_dir: Path) -> str | None:
    """First ``tool`` on PATH that is NOT our own shim under ``guard_dir``."""
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if Path(entry).resolve() == guard_dir.resolve():
                continue  # skip our shim dir
        except OSError:
            pass
        candidate = Path(entry) / tool
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _gospelo_github_identity_command() -> str:
    """How the shim should invoke this CLI (absolute path preferred)."""
    found = shutil.which("gospelo-github-identity")
    if found:
        return found
    return f"{sys.executable} -m gospelo_github_identity"


def _command_supports_guard(command: str) -> bool:
    """True if ``<command> guard --selftest`` exits 0.

    ``command`` is the string the shim will exec — either an absolute path or
    ``"<python> -m gospelo_github_identity"``. We invoke it exactly as the shim would
    so a stale build on ``PATH`` (one without the ``guard`` subcommand) is
    caught here instead of silently breaking every ``git``/``gh`` call.
    """
    import shlex
    import subprocess

    try:
        result = subprocess.run(
            [*shlex.split(command), "guard", "--selftest"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def install_main() -> None:
    parser = argparse.ArgumentParser(prog="gospelo-github-identity install-guard")
    parser.add_argument("--dir", default=DEFAULT_GUARD_DIR, help="Shim directory.")
    parser.add_argument(
        "--tools",
        default="gh",
        help="Comma-separated tools to shadow. Default 'gh' only — shadowing "
        "'git' adds Python startup to every git call and a large blast radius, "
        "so opt in explicitly with --tools gh,git if you want git push guarded "
        "(commit-message hygiene is handled separately by install-commit-hook).",
    )
    args = parser.parse_args()

    guard_dir = Path(args.dir).expanduser()
    guard_dir.mkdir(parents=True, exist_ok=True)
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    gi = _gospelo_github_identity_command()

    # Fail loudly now rather than baking a broken command into every shim. A
    # shim pointing at a build without the ``guard`` subcommand would make every
    # guarded git/gh call exit non-zero with "unknown subcommand", blocking even
    # read-only commands.
    if not _command_supports_guard(gi):
        print(
            f"gospelo-github-identity install-guard: the resolved command {gi!r} does "
            "not support the 'guard' subcommand (likely a stale install on "
            "PATH). Refusing to install broken shims.\n"
            "  fix: reinstall the current build, e.g. `uv tool install --force "
            ".` or `pip install -U gospelo-github-identity`, then re-run install-guard.",
            file=sys.stderr,
        )
        sys.exit(1)

    installed: list[str] = []
    for tool in tools:
        if tool not in SUPPORTED_TOOLS:
            print(f"  [skip] unsupported tool: {tool}", file=sys.stderr)
            continue
        real = _resolve_real_binary(tool, guard_dir)
        if real is None:
            print(f"  [skip] {tool} not found on PATH; cannot shim it.", file=sys.stderr)
            continue
        shim = guard_dir / tool
        shim.write_text(
            "#!/bin/sh\n"
            "# gospelo-github-identity guard shim — do not edit.\n"
            "# Regenerate with `gospelo-github-identity install-guard`.\n"
            f'exec {gi} guard --tool {tool} --real "{real}" -- "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        installed.append(f"{tool} -> {real}")
        print(f"  installed shim: {shim}  (real: {real})")

    if not installed:
        print("No shims installed.", file=sys.stderr)
        sys.exit(1)

    print()
    print("Add the shim directory to the FRONT of your PATH so it shadows the real binaries:")
    print(f'  export PATH="{guard_dir}:$PATH"')
    print("Put that line in ~/.zshrc / ~/.bashrc (or your agent's launch env), then reopen the shell.")
    print("Verify:  command -v gh   # should print the shim path above")
    print("Bypass once:  GOSPELO_GITHUB_IDENTITY_SKIP=1 gh ...")
    sys.exit(0)


def uninstall_main() -> None:
    parser = argparse.ArgumentParser(prog="gospelo-github-identity uninstall-guard")
    parser.add_argument("--dir", default=DEFAULT_GUARD_DIR, help="Shim directory.")
    parser.add_argument("--tools", default=",".join(SUPPORTED_TOOLS))
    args = parser.parse_args()

    guard_dir = Path(args.dir).expanduser()
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    removed = 0
    for tool in tools:
        shim = guard_dir / tool
        if shim.exists():
            shim.unlink()
            removed += 1
            print(f"  removed: {shim}")
    if removed == 0:
        print("No shims found to remove.", file=sys.stderr)
    else:
        print()
        print(f'Remove `export PATH="{guard_dir}:$PATH"` from your shell rc if you added it.')
    sys.exit(0)


if __name__ == "__main__":
    guard_main()
