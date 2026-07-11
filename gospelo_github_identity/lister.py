# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity list`` command.

Print the registered profiles in a fixed-width table.
"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity list",
        description="List registered identity profiles.",
    )
    parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if not config.profiles:
        print("No profiles registered. Run `gospelo-github-identity init`.", file=sys.stderr)
        sys.exit(1)

    rows: list[tuple[str, str, str, str, str]] = []
    for name, profile in config.profiles.items():
        path_count = len(profile.paths)
        path_label = "1 path" if path_count == 1 else f"{path_count} paths"
        rows.append(
            (
                name,
                profile.description or "",
                profile.git_user_email,
                profile.gh_account,
                path_label,
            )
        )

    headers = ("name", "description", "git.user.email", "gh.account", "paths")
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(5)]

    print("=== Profiles ===")
    print(_format_row(headers, widths))
    print(_format_row(tuple("-" * w for w in widths), widths))
    for row in rows:
        print(_format_row(row, widths))

    if config.default_profile:
        print(f"\nDefault profile: {config.default_profile}")
    sys.exit(0)


def _format_row(row: tuple[str, ...], widths: list[int]) -> str:
    return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))


if __name__ == "__main__":
    main()
