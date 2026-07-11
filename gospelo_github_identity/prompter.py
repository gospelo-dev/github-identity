# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity prompt`` command.

Shell-prompt helper. Prints the matched profile name (with optional colour
escapes / mismatch warning) for embedding in ``PS1`` etc. Always exits 0.
When no profile matches, the output is empty so the prompt simply collapses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import _external
from .config import ConfigError, load_config
from .matcher import resolve_profile


# ANSI yellow + reset
_COLOR_OK = "\033[33m"
_COLOR_WARN = "\033[31m"
_COLOR_RESET = "\033[0m"

# Same escapes wrapped in PS1 non-printing markers so readline measures the
# prompt width correctly.
_PS1_OK = r"\[\e[33m\]"
_PS1_WARN = r"\[\e[31m\]"
_PS1_RESET = r"\[\e[0m\]"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity prompt",
        description="Shell prompt helper: print [<profile>] for embedding in PS1.",
    )
    parser.add_argument(
        "--format",
        choices=("plain", "color", "ps1"),
        default="plain",
        help="Output format (default: plain).",
    )
    parser.add_argument(
        "--show-mismatch",
        action="store_true",
        help="Append a '!' marker if git/gh state does not match the profile.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Override the directory (default: current).",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError:
        # The prompt must never abort the shell. Empty output, exit 0.
        print("", end="")
        sys.exit(0)

    cwd = args.cwd if args.cwd is not None else Path.cwd()
    match = resolve_profile(config, cwd)

    if not match.matched:
        print("", end="")
        sys.exit(0)

    label = match.profile.name
    mismatch = False
    if args.show_mismatch:
        mismatch = _has_mismatch(match.profile, cwd)

    body = f"[{label}{' !' if mismatch else ''}]"

    if args.format == "plain":
        print(body, end="")
    elif args.format == "color":
        prefix = _COLOR_WARN if mismatch else _COLOR_OK
        print(f"{prefix}{body}{_COLOR_RESET}", end="")
    else:  # ps1
        prefix = _PS1_WARN if mismatch else _PS1_OK
        print(f"{prefix}{body}{_PS1_RESET}", end="")

    sys.exit(0)


def _has_mismatch(profile, cwd: Path) -> bool:  # type: ignore[no-untyped-def]
    """Best-effort mismatch detection that never raises."""
    try:
        actual_email = _external.git_get_config("user.email", cwd=cwd)
    except _external.ExternalToolError:
        actual_email = None
    try:
        actual_login = _external.gh_active_login()
    except _external.ExternalToolError:
        actual_login = None

    if actual_email is None and actual_login is None:
        # Likely outside a repo + gh not authenticated; do not flag.
        return False
    if actual_email is not None and actual_email != profile.git_user_email:
        return True
    if actual_login is not None and actual_login != profile.gh_account:
        return True
    return False


if __name__ == "__main__":
    main()
