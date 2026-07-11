# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity check`` command.

Compares the expected profile (resolved from cwd) against actual local
``git config`` and the active ``gh`` CLI account, then prints a table.

When the matched profile declares an ``ssh`` block, an extra row probes the
GitHub login that ``ssh -T`` authenticates as for the repo's ``origin`` host
and compares it against the expected login -- catching the case where a stray
SSH agent key would push as the wrong account even though git/gh look correct.
The SSH row is skipped ("--", never a failure) when ``origin`` is not an SSH
remote or the host is unreachable.

Exit codes:
  0 - everything matches
  1 - one or more values mismatch, or no profile matched the directory
  2 - configuration or external tool error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import _external
from .config import ConfigError, Profile, load_config
from .matcher import resolve_profile

# One row of the comparison table: (section, key, actual, expected, status)
# where status is "OK" (match), "NG" (mismatch), or "--" (skipped / N/A).
Row = tuple[str, str, str, str, str]


def _status(ok: bool) -> str:
    return "OK" if ok else "NG"


def _ssh_row(profile: Profile, cwd: Path) -> tuple[Row, str]:
    """Build the optional SSH-login row.

    Reproduces what ``git push`` would do: probe the SSH host that this repo's
    ``origin`` remote resolves to (honouring an SSH-alias host), and compare the
    GitHub login it authenticates as against the profile's expected login.

    Returns ``(row, note)``. ``note`` is a stderr line: empty on a clean match,
    an explanation when the check is skipped ("--"), or the fix hint on a real
    mismatch ("NG").
    """
    expected_login = profile.expected_ssh_login

    if profile.ssh_host:
        target: str | None = f"git@{profile.ssh_host}"
    else:
        try:
            url = _external.git_remote_url("origin", cwd=cwd)
        except _external.ExternalToolError:
            url = None
        target = _external.ssh_target_from_remote(url) if url else None

    if target is None:
        return (
            ("ssh", "login", "(n/a: origin not SSH)", expected_login, "--"),
            "NOTE: SSH check skipped -- 'origin' is not an SSH remote "
            "(HTTPS or absent), so pushes from here do not use an SSH key.",
        )

    try:
        actual_login, detail = _external.ssh_probe_login(target)
    except _external.ExternalToolError as exc:
        return (
            ("ssh", "login", "(ssh unavailable)", expected_login, "--"),
            f"NOTE: SSH check skipped -- {exc}",
        )

    if actual_login is None:
        first_line = detail.splitlines()[0] if detail else "no response"
        return (
            ("ssh", "login", "(unreachable)", expected_login, "--"),
            f"NOTE: SSH check skipped -- could not determine the SSH identity "
            f"for {target!r} (host key/agent not set up, offline, or auth "
            f"denied): {first_line}",
        )

    if actual_login == expected_login:
        return (("ssh", "login", actual_login, expected_login, "OK"), "")

    note = (
        f"WARNING: SSH to {target} authenticates as {actual_login!r}, but this "
        f"directory's profile expects {expected_login!r}. A push would use the "
        f"wrong GitHub identity. Fix with either:\n"
        f"  A) HTTPS + gh credentials (removes SSH-key ambiguity):\n"
        f"       gh auth setup-git\n"
        f"       git remote set-url origin "
        f"https://github.com/<owner>/<repo>.git\n"
        f"  B) Pin this account's key via an ~/.ssh/config Host alias "
        f"(IdentitiesOnly yes) and point origin at that alias."
    )
    return (("ssh", "login", actual_login, expected_login, "NG"), note)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity check",
        description=(
            "Compare expected profile (resolved from the current directory) "
            "against actual git config + gh CLI active account."
        ),
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Override the directory to test against (default: current).",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    cwd = (args.cwd if args.cwd is not None else Path.cwd()).resolve()
    match = resolve_profile(config, cwd)

    print("=== Identity Check ===")
    print(f"Working dir: {cwd}")

    if not match.matched:
        print("Matched profile: (none)")
        print(
            "\nERROR: no profile path matched this directory and no "
            "default_profile is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    expected: Profile = match.profile
    via = " (default)" if match.via_default else f" (via pattern: {match.matched_pattern})"
    print(f"Matched profile: {expected.name}{via}")
    print()

    try:
        actual_name = _external.git_get_config("user.name", cwd=cwd)
        actual_email = _external.git_get_config("user.email", cwd=cwd)
        actual_login = _external.gh_active_login()
    except _external.ExternalToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    rows: list[Row] = [
        (
            "git",
            "user.name",
            actual_name or "(unset)",
            expected.git_user_name,
            _status(actual_name == expected.git_user_name),
        ),
        (
            "git",
            "user.email",
            actual_email or "(unset)",
            expected.git_user_email,
            _status(actual_email == expected.git_user_email),
        ),
        (
            "gh CLI",
            "login",
            actual_login or "(unauthenticated)",
            expected.gh_account,
            _status(actual_login == expected.gh_account),
        ),
    ]

    ssh_note = ""
    if expected.ssh_check:
        ssh_row, ssh_note = _ssh_row(expected, cwd)
        rows.append(ssh_row)

    name_w = max(len(r[1]) for r in rows)
    actual_w = max(len(r[2]) for r in rows)
    expected_w = max(len(r[3]) for r in rows)

    current_section = ""
    for section, key, actual, expected_value, status in rows:
        if section != current_section:
            print(f"[{section}]")
            current_section = section
        print(
            f"  {key.ljust(name_w)} : "
            f"{actual.ljust(actual_w)}   "
            f"(expected: {expected_value.ljust(expected_w)})  {status}"
        )

    # "--" rows (SSH check skipped / N/A) never fail the run; only "NG" does.
    all_ok = all(r[4] != "NG" for r in rows)
    print()
    if all_ok:
        print(f"OK: identity matches profile {expected.name!r}.")
        if ssh_note:
            print(ssh_note, file=sys.stderr)
        sys.exit(0)

    if ssh_note:
        print(ssh_note, file=sys.stderr)
    if rows[2][4] == "NG":
        print(
            f"WARNING: gh CLI account does not match expected profile.\n"
            f"Run `gospelo-github-identity switch {expected.name}` to fix.\n"
            f"If `switch` reports success but this stays NG, the stored "
            f"credential for {expected.gh_account!r} is stale (keyring mismatch); "
            f"re-login:\n"
            f"  gh auth logout --hostname github.com --user {expected.gh_account}\n"
            f"  gh auth login  --hostname github.com",
            file=sys.stderr,
        )
    elif rows[0][4] == "NG" or rows[1][4] == "NG":
        print(
            f"WARNING: git config does not match expected profile.\n"
            f"Run `gospelo-github-identity switch {expected.name}` to fix.",
            file=sys.stderr,
        )
    sys.exit(1)


if __name__ == "__main__":
    main()
