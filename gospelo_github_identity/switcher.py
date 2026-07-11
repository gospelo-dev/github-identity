# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity switch <profile>`` command.

Applies the requested profile by:
  1. Setting ``git config user.name`` and ``user.email`` (local by default,
     ``--global`` to set globally).
  2. Running ``gh auth switch -u <account>``.

Exit codes:
  0 - both git config and gh switch succeeded
  1 - partial success (one of the two failed)
  2 - both failed, configuration missing, or external tool missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import _external
from .config import ConfigError, load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity switch",
        description="Switch local git config + gh CLI active account to the named profile.",
    )
    parser.add_argument("profile", help="Profile name to activate.")
    parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Apply git config with --global instead of --local.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned changes without executing them.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Override the directory used for the local git config call.",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        profile = config.get_profile(args.profile)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    cwd = (args.cwd if args.cwd is not None else Path.cwd()).resolve()
    scope = "global" if args.global_scope else "local"

    print(f"Switching to profile: {profile.name}")
    print(f"  git ({scope}): user.name={profile.git_user_name}, user.email={profile.git_user_email}")
    print(f"  gh CLI       : auth switch -u {profile.gh_account}")

    if args.dry_run:
        print("\n(dry-run: no changes applied)")
        sys.exit(0)

    if scope == "local":
        try:
            inside_tree = _external.git_inside_work_tree(cwd=cwd)
        except _external.ExternalToolError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        if not inside_tree:
            print(
                f"ERROR: {cwd} is not inside a git work tree. "
                f"Use --global to set git config globally, or `cd` into a "
                f"repository first.",
                file=sys.stderr,
            )
            sys.exit(2)

    git_ok = True
    gh_ok = True

    try:
        _external.git_set_config("user.name", profile.git_user_name, scope=scope, cwd=cwd)
        _external.git_set_config("user.email", profile.git_user_email, scope=scope, cwd=cwd)
        print(f"OK: git config ({scope}) updated.")
    except _external.ExternalToolError as exc:
        git_ok = False
        print(f"NG: git config failed: {exc}", file=sys.stderr)

    try:
        _external.gh_switch_account(profile.gh_account)
    except _external.ExternalToolError as exc:
        gh_ok = False
        print(f"NG: gh auth switch failed: {exc}", file=sys.stderr)
    else:
        # `gh auth switch` can exit 0 while the keyring serves a stale or
        # mismatched credential, so the active token may still authenticate as
        # a DIFFERENT account. Confirm the real identity via `gh api user`
        # instead of trusting the switch's success.
        try:
            real_login = _external.gh_active_login()
        except _external.ExternalToolError:
            real_login = None

        if real_login == profile.gh_account:
            print(f"OK: gh CLI active account switched to {profile.gh_account}.")
        elif real_login is None:
            # Could not confirm (e.g. offline / `gh api user` unavailable).
            # The switch command itself succeeded, so do not fail the run.
            print(
                f"OK: gh auth switch to {profile.gh_account} reported success "
                f"(could not confirm via `gh api user`; expected if you are offline)."
            )
        else:
            gh_ok = False
            print(
                f"NG: gh auth switch reported success, but the active token "
                f"authenticates as {real_login!r}, not {profile.gh_account!r}.\n"
                f"     The stored credential for {profile.gh_account!r} is stale "
                f"(keyring mismatch). Re-login to fix:\n"
                f"       gh auth logout --hostname github.com --user {profile.gh_account}\n"
                f"       gh auth login  --hostname github.com",
                file=sys.stderr,
            )

    if git_ok and gh_ok:
        sys.exit(0)
    if not git_ok and not gh_ok:
        sys.exit(2)
    sys.exit(1)


if __name__ == "__main__":
    main()
