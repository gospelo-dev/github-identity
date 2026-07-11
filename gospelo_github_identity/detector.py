# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity detect`` command.

Prints the profile name that owns the current working directory, or exits
with code 1 when no profile (and no ``default_profile``) matches.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .matcher import resolve_profile


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity detect",
        description="Print the profile name matched by the current directory.",
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

    cwd = args.cwd if args.cwd is not None else Path.cwd()
    result = resolve_profile(config, cwd)

    if not result.matched:
        print("ERROR: no profile matched the current directory.", file=sys.stderr)
        sys.exit(1)

    print(result.profile.name)
    sys.exit(0)


if __name__ == "__main__":
    main()
