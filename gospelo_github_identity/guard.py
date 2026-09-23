# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Deterministic, local, target-aware command guard for ``gh`` / ``git``.

This shadows ``gh`` and ``git`` on ``PATH`` with tiny shim executables. Every
invocation is routed through ``gospelo-github-identity guard``, which passes
**read-only** commands straight through to the real binary, and gates **write**
commands (``git push``; ``gh release/pr/repo/... create`` etc.):

  * The write's **target** is resolved first — the ``--repo`` argument, the
    ``git -C`` directory, or the working directory's remote — never just cwd.
  * When any profile declares ``gh.owners``, the guard runs in **enforce mode**
    for ``gh``: the target owner is reverse-mapped to a profile and that
    profile's token is materialized (``gh auth token --user``) and injected as
    ``GH_TOKEN`` into the single real invocation. The machine-global active
    account stops mattering. An owner no profile declares, or an unresolvable
    target from an ungoverned directory, is **refused** (fail-closed).
  * With no ``owners`` declared anywhere, the guard stays in legacy **check
    mode**: the active identity is compared against the governing profile and
    mismatched writes are blocked; ungoverned directories pass through.
  * ``git push`` is gated by the **target repo's** author config against the
    profile governing that repo (by path, falling back to its remote owner).

Design constraints (why this exists rather than depending on a third-party
"command firewall"):

  * **Deterministic** — pure pattern logic, never an LLM. There is no prompt to
    inject.
  * **Local** — token materialization reads the gh keyring; the only network
    call is the legacy mode's ``gh api user``.
  * **Fail-closed where governed** — inside declared territory (a matched
    profile, a declared owner) a wrong or unresolvable identity blocks the
    write. Without a usable config the guard governs nothing and passes
    through, so installing the shims never breaks unrelated machines.

Limitations (documented, not silently assumed away):

  * A ``PATH`` shim only intercepts **name-based** calls. A command invoked by
    absolute path (``/usr/bin/git push``) bypasses it. Pair the shim with the
    ambient-credential discipline ``doctor`` audits (no ``GH_TOKEN`` parked in
    the environment) so a bypassed path finds no credentials and fails safely.
    For tamper-resistance against an adversarial process, layer an OS sandbox.
  * The write-classifier covers the common irreversible/outward subcommands; it
    is intentionally conservative (unknown subcommands pass through).
"""

from __future__ import annotations

import argparse
import os
import re
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

_FORBIDDEN_COMMENT_WORDS_RE = re.compile(
    r"\b(?:Claude|Copilot|Fable|Opus|Sonnet|Haiku|Anthropic)\b", re.IGNORECASE
)
_FORBIDDEN_COMMENT_TRAILERS_RE = re.compile(
    r"(?mi)^[ \t]*(?:co-authored-by|claude-session)[ \t]*:"
)


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
        return _git_subcommand(argv) in {"commit", "push"}
    if tool == "gh":
        sub, action = _gh_sub_action(argv)
        if sub == "api":
            return _gh_api_is_write(argv)
        actions = _GH_WRITE_ACTIONS.get(sub or "")
        return actions is not None and action in actions
    return False


def comment_input_violation(tool: str, argv: list[str]) -> str | None:
    """Reject inline, generated, or AI-attributed commit/PR comments."""
    if tool == "git" and _git_subcommand(argv) == "commit":
        has_file = False
        message_file: str | None = None
        i = 0
        while i < len(argv):
            arg = argv[i]
            if arg in ("-F", "--file"):
                has_file = i + 1 < len(argv) and argv[i + 1] != "-"
                message_file = argv[i + 1] if has_file else None
                i += 2
                continue
            if arg.startswith("--file="):
                has_file = arg.split("=", 1)[1] not in ("", "-")
                message_file = arg.split("=", 1)[1] if has_file else None
                i += 1
                continue
            if arg in ("-m", "--message") or arg.startswith("--message="):
                return "git commit のメッセージは -F/--file によるファイル入力のみ許可します。"
            i += 1
        if not has_file:
            return "git commit は -F/--file によるメッセージファイルを指定してください。"
        try:
            message = Path(message_file).read_text(encoding="utf-8")
        except OSError as exc:
            return f"git commit のメッセージファイルを検証できません: {exc}"
        if _FORBIDDEN_COMMENT_TRAILERS_RE.search(message):
            return (
                "git commit のメッセージファイルに Co-Authored-By または "
                "Claude-Session を含めることはできません。"
            )
        forbidden = sorted({m.group() for m in _FORBIDDEN_COMMENT_WORDS_RE.finditer(message)})
        if forbidden:
            return (
                "git commit のメッセージファイルに禁止されたAI帰属が含まれています: "
                f"{', '.join(forbidden)}"
            )

    if tool == "gh":
        sub, action = _gh_sub_action(argv)
        if sub == "pr" and action == "create":
            has_body_file = False
            body_file: str | None = None
            i = 0
            while i < len(argv):
                arg = argv[i]
                if arg == "--body-file":
                    has_body_file = i + 1 < len(argv) and argv[i + 1] != "-"
                    body_file = argv[i + 1] if has_body_file else None
                    i += 2
                    continue
                if arg.startswith("--body-file="):
                    has_body_file = arg.split("=", 1)[1] not in ("", "-")
                    body_file = arg.split("=", 1)[1] if has_body_file else None
                    i += 1
                    continue
                if arg in ("-b", "--body") or arg.startswith("--body="):
                    return "gh pr create の本文は --body-file によるファイル入力のみ許可します。"
                if arg in ("--fill", "--fill-first", "--fill-verbose", "--editor"):
                    return "gh pr create の本文自動生成は許可していません。--body-file を指定してください。"
                i += 1
            if not has_body_file:
                return "gh pr create は --body-file による本文ファイルを指定してください。"
            try:
                body = Path(body_file).read_text(encoding="utf-8")
            except OSError as exc:
                return f"gh pr create の本文ファイルを検証できません: {exc}"
            forbidden = sorted({m.group() for m in _FORBIDDEN_COMMENT_WORDS_RE.finditer(body)})
            if forbidden:
                return (
                    "gh pr create の本文ファイルに禁止されたAI帰属が含まれています: "
                    f"{', '.join(forbidden)}"
                )
            if _FORBIDDEN_COMMENT_TRAILERS_RE.search(body):
                return (
                    "gh pr create の本文ファイルに Co-Authored-By または "
                    "Claude-Session を含めることはできません。"
                )

    return None


# ---------------------------------------------------------------------------
# Target resolution (pure, unit-tested)
# ---------------------------------------------------------------------------

_GH_API_REPOS_RE = re.compile(r"(?:^|/)repos/([^/]+)/[^/]+")


def _repo_spec_owner(value: str) -> str | None:
    """Owner from a gh repo spec: ``OWNER/REPO``, ``HOST/OWNER/REPO``, or a URL."""
    value = value.strip()
    if not value:
        return None
    if "://" in value:
        return _external.owner_from_remote_url(value)
    parts = [p for p in value.split("/") if p]
    if len(parts) == 2:
        return parts[0]
    if len(parts) == 3:
        return parts[1]  # HOST/OWNER/REPO
    return None


def gh_target_owner(argv: list[str]) -> str | None:
    """Extract the GitHub owner a gh invocation targets, when determinable.

    Sources, in priority order:

      1. the ``--repo`` / ``-R`` flag (space or ``=`` form)
      2. the positional ``OWNER/REPO`` spec directly after a ``gh repo``
         action (``gh repo delete owner/x``) — only the token immediately
         following the action, so a flag value is never mistaken for it
      3. a ``repos/<owner>/<repo>`` segment in a ``gh api`` endpoint

    Returns ``None`` when the invocation carries no repo target (``gh gist
    create``, ``gh api /user``, ...).
    """
    for i, a in enumerate(argv):
        if a in ("--repo", "-R") and i + 1 < len(argv):
            return _repo_spec_owner(argv[i + 1])
        if a.startswith("--repo="):
            return _repo_spec_owner(a.split("=", 1)[1])

    sub, action = _gh_sub_action(argv)
    if sub == "repo" and action is not None:
        try:
            idx = argv.index(action)
        except ValueError:
            idx = -1
        if 0 <= idx and idx + 1 < len(argv):
            candidate = argv[idx + 1]
            if not candidate.startswith("-") and "/" in candidate:
                return _repo_spec_owner(candidate)
    if sub == "api":
        for a in argv:
            if a.startswith("-"):
                continue
            m = _GH_API_REPOS_RE.search(a)
            if m:
                return m.group(1)
    return None


def git_target_dir(argv: list[str], cwd: Path) -> Path:
    """The directory a git invocation operates on.

    Successive ``-C`` values compose left-to-right (a relative path resolves
    against the running composition), mirroring git's own semantics; an empty
    ``-C ''`` is a documented no-op. Without ``-C`` the target is ``cwd``.
    """
    target = cwd
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "-C":
            if i + 1 < len(argv) and argv[i + 1]:
                nxt = Path(argv[i + 1])
                target = nxt if nxt.is_absolute() else target / nxt
            i += 2
            continue
        if a in _GIT_VALUE_FLAGS:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        break  # reached the subcommand
    return target


# ---------------------------------------------------------------------------
# Runtime gate: `gospelo-github-identity guard --tool <t> --real <path> -- <args>`
# ---------------------------------------------------------------------------


def _exec_real(real: str, argv: list[str]) -> None:
    """Replace this process with the real binary (preserves exit code/tty)."""
    os.execv(real, [real, *argv])


def _block(headline: str, cmd: str, fix_lines: list[str]) -> None:
    """Print a BLOCKED report to stderr and exit 1. Never suppressed by QUIET."""
    body = f"gospelo-github-identity guard: BLOCKED {headline}\n  command : {cmd}\n"
    for i, line in enumerate(fix_lines):
        body += ("  fix     : " if i == 0 else "            ") + line + "\n"
    print(body.rstrip("\n"), file=sys.stderr)
    sys.exit(1)


def _block_mismatch(profile_name: str, cmd: str, mismatches: list[str]) -> None:
    body = (
        f"gospelo-github-identity guard: BLOCKED write under profile "
        f"{profile_name!r} — identity does not match.\n"
        f"  command : {cmd}\n"
        + "".join(f"  mismatch: {m}\n" for m in mismatches)
        + f"  fix     : gospelo-github-identity switch {profile_name}\n"
        f"            (if switch reports OK but this persists, the keyring "
        f"credential is stale — re-login: gh auth logout --user <account> "
        f"&& gh auth login)"
    )
    print(body, file=sys.stderr)
    sys.exit(1)


def _cmd_str(tool: str, cmd_argv: list[str]) -> str:
    return f"{tool} {' '.join(cmd_argv)}".strip()


def _gate_git(config, cmd_argv: list[str], real: str) -> None:
    """Gate a ``git push``: the target repo's author config must match the
    profile governing that repo (by path; falling back to its remote owner
    when owners-based enforcement is enabled)."""
    target = git_target_dir(cmd_argv, Path.cwd())
    match = resolve_profile(config, target)
    profile = match.profile

    # Prevent identity probes (which may themselves go through a shim) from
    # recursing back into the guard.
    os.environ[SKIP_ENV] = "1"

    if profile is None and config.owners_declared():
        url = _external.git_remote_url("origin", cwd=target)
        owner = _external.owner_from_remote_url(url) if url else None
        if owner is not None:
            profile = config.profile_for_owner(owner)
            if profile is None:
                _block(
                    f"git push targeting owner {owner!r} — no profile declares "
                    f"this owner (fail-closed).",
                    _cmd_str("git", cmd_argv),
                    [
                        f"add {owner!r} to the intended profile's gh.owners "
                        f"in {config.source_path},",
                        "or bypass once with GOSPELO_GITHUB_IDENTITY_SKIP=1",
                    ],
                )

    if profile is None:
        _notice("target repo not governed by any profile; passing through.")
        _exec_real(real, cmd_argv)
        return

    # git push identity == the commit author (the TARGET repo's git config).
    name = _external.git_get_config("user.name", cwd=target)
    email = _external.git_get_config("user.email", cwd=target)
    mismatches: list[str] = []
    if name != profile.git_user_name:
        mismatches.append(f"git user.name={name!r} (expected {profile.git_user_name!r})")
    if email != profile.git_user_email:
        mismatches.append(f"git user.email={email!r} (expected {profile.git_user_email!r})")
    if mismatches:
        _block_mismatch(profile.name, _cmd_str("git", cmd_argv), mismatches)

    _notice(f"identity OK for profile {profile.name!r}; passing through.")
    _exec_real(real, cmd_argv)


def _enforce_gh(profile, owner: str | None, source: str, real: str, cmd_argv: list[str]) -> None:
    """Materialize the profile's token and exec the real gh with it injected."""
    token = _external.gh_auth_token(profile.gh_account, gh_path=real)
    if not token:
        _block(
            f"gh write for profile {profile.name!r} — no stored credential "
            f"for account {profile.gh_account!r} (fail-closed).",
            _cmd_str("gh", cmd_argv),
            [f"gh auth login --hostname github.com   (as {profile.gh_account!r})"],
        )
    os.environ["GH_TOKEN"] = token
    _notice(
        f"enforcing identity {profile.gh_account!r} for {source} "
        f"(profile {profile.name!r}); token injected."
    )
    _exec_real(real, cmd_argv)


def _gate_gh(config, cmd_argv: list[str], real: str) -> None:
    """Gate a gh write.

    Enforce mode (any profile declares ``gh.owners``): resolve the target
    owner, reverse-map it to a profile, inject that profile's token. Unknown
    owners and unresolvable targets from ungoverned directories are refused.

    Legacy check mode (no owners anywhere): compare the active account against
    the cwd's profile; block on mismatch; pass through when ungoverned.
    """
    owners_enabled = config.owners_declared()

    owner = gh_target_owner(cmd_argv)
    source = f"target owner {owner!r}" if owner is not None else ""
    if owner is None:
        # No explicit target in the arguments: the operation acts on the
        # cwd's repository (if any) -> derive the owner from its remote.
        os.environ[SKIP_ENV] = "1"
        url = _external.git_remote_url("origin", cwd=Path.cwd())
        owner = _external.owner_from_remote_url(url) if url else None
        source = f"cwd remote owner {owner!r}" if owner is not None else ""

    if owners_enabled:
        if owner is not None:
            profile = config.profile_for_owner(owner)
            if profile is None:
                _block(
                    f"gh write targeting owner {owner!r} — no profile declares "
                    f"this owner (fail-closed).",
                    _cmd_str("gh", cmd_argv),
                    [
                        f"add {owner!r} to the intended profile's gh.owners "
                        f"in {config.source_path},",
                        "or bypass once with GOSPELO_GITHUB_IDENTITY_SKIP=1",
                    ],
                )
            _enforce_gh(profile, owner, source, real, cmd_argv)
            return
        # Repo-target-less operation (gh gist create, gh api /user, ...):
        # fall back to the directory's profile; refuse when ungoverned.
        match = resolve_profile(config, Path.cwd())
        if match.profile is None:
            _block(
                "gh write with no resolvable target owner from a directory "
                "governed by no profile (fail-closed).",
                _cmd_str("gh", cmd_argv),
                [
                    "run it inside a governed directory, pass --repo <owner>/<repo>,",
                    "declare the owner in a profile's gh.owners,",
                    "or bypass once with GOSPELO_GITHUB_IDENTITY_SKIP=1",
                ],
            )
        _enforce_gh(match.profile, None, "the working directory's profile", real, cmd_argv)
        return

    # ---- legacy check mode (no gh.owners declared anywhere) ----------------
    match = resolve_profile(config, Path.cwd())
    profile = match.profile
    if profile is None:
        _notice("directory not governed by any profile; passing through.")
        _exec_real(real, cmd_argv)
        return

    os.environ[SKIP_ENV] = "1"
    login = _external.gh_active_login()
    if login != profile.gh_account:
        shown = login if login is not None else "(unauthenticated/unverifiable)"
        _block_mismatch(
            profile.name,
            _cmd_str("gh", cmd_argv),
            [f"gh account={shown!r} (expected {profile.gh_account!r})"],
        )

    _notice(f"identity OK for profile {profile.name!r}; passing through.")
    _exec_real(real, cmd_argv)


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

    violation = comment_input_violation(tool, cmd_argv)
    if violation:
        print(f"gospelo-github-identity guard: BLOCKED ({violation})", file=sys.stderr)
        sys.exit(1)

    # Write command: gate it against the operation's target.
    try:
        config = load_config()
    except ConfigError:
        # No usable config -> the guard governs nothing; do not break the user.
        _notice(
            "no usable config; passing through "
            "(run `gospelo-github-identity init` to enable enforcement)."
        )
        _exec_real(real, cmd_argv)
        return

    try:
        if tool == "git":
            _gate_git(config, cmd_argv, real)
        else:
            _gate_gh(config, cmd_argv, real)
    except _external.ExternalToolError as exc:
        # Cannot determine identity for a governed write -> fail closed.
        print(f"gospelo-github-identity guard: BLOCKED ({exc})", file=sys.stderr)
        sys.exit(1)


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
    raise RuntimeError(
        "gospelo-github-identity is not installed on PATH. "
        "Install it with `uv tool install gospelo-github-identity`, "
        "then run install-guard again. Direct Python execution is not supported."
    )


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
    try:
        gi = _gospelo_github_identity_command()
    except RuntimeError as exc:
        print(f"gospelo-github-identity install-guard: {exc}", file=sys.stderr)
        sys.exit(1)

    # Fail loudly now rather than baking a broken command into every shim. A
    # shim pointing at a build without the ``guard`` subcommand would make every
    # guarded git/gh call exit non-zero with "unknown subcommand", blocking even
    # read-only commands.
    if not _command_supports_guard(gi):
        print(
            f"gospelo-github-identity install-guard: the resolved command {gi!r} does "
            "not support the 'guard' subcommand (likely a stale install on "
            "PATH). Refusing to install broken shims.\n"
            "  fix: reinstall the current build with `uv tool install --force .`, "
            "then re-run install-guard.",
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
