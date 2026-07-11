# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity init`` command.

Interactively scaffolds ``~/.config/gospelo-github-identity/config.yml``. Asks the
user for one or more profiles and (optionally) a ``default_profile``.

Two non-interactive modes are also supported:

- ``--from-template``: copy the bundled template to the config path and open
  it in ``$EDITOR`` (default ``vi``). Skips interactive prompts.
- ``--show-example``: print the bundled template to stdout (for piping).

Aborts (exit 1) on EOF / Ctrl-C; refuses to silently overwrite an existing
config (exit 0 if the user declines).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import (
    Config,
    Profile,
    resolve_config_path,
    save_config,
)


def _template_path() -> Path:
    """Resolve the bundled template path (no fallback)."""
    return Path(__file__).parent / "templates" / "config.template.yml"


def _show_example() -> None:
    """Print the bundled template to stdout."""
    template_src = _template_path()
    if not template_src.is_file():
        sys.stderr.write(f"ERROR: bundled template not found: {template_src}\n")
        sys.exit(2)
    sys.stdout.write(template_src.read_text(encoding="utf-8"))


def _init_from_template(target_path: Path, *, force: bool = False) -> None:
    """Copy the bundled template to ``target_path`` and open it in ``$EDITOR``."""
    template_src = _template_path()
    if not template_src.is_file():
        sys.stderr.write(f"ERROR: bundled template not found: {template_src}\n")
        sys.exit(2)

    if target_path.exists() and not force:
        try:
            confirm = input(f"Overwrite existing {target_path}? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\nAborted.\n")
            sys.exit(1)
        if confirm != "y":
            sys.stderr.write("Aborted; existing config left untouched.\n")
            sys.exit(1)

    target_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(template_src, target_path)
    try:
        target_path.chmod(0o600)
    except OSError:
        # Best-effort: same policy as save_config().
        pass
    sys.stderr.write(f"Template copied to: {target_path}\n")

    editor = os.environ.get("EDITOR", "vi")
    sys.stderr.write(f"Opening with: {editor}\n")
    try:
        subprocess.run([editor, str(target_path)], check=False)
    except FileNotFoundError:
        sys.stderr.write(
            f"ERROR: editor not found: {editor!r}. "
            f"Set $EDITOR to an installed editor and re-run, "
            f"or edit {target_path} manually.\n"
        )
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity init",
        description="Initialize ~/.config/gospelo-github-identity/config.yml",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config without prompting.",
    )
    parser.add_argument(
        "--from-template",
        dest="from_template",
        action="store_true",
        help=(
            "Copy the bundled template to the config path and open in "
            "$EDITOR (default: vi). Skips interactive prompts."
        ),
    )
    parser.add_argument(
        "--show-example",
        dest="show_example",
        action="store_true",
        help=(
            "Print the bundled template to stdout. Useful for redirecting "
            "to a custom location."
        ),
    )
    args = parser.parse_args()

    if args.from_template and args.show_example:
        sys.stderr.write(
            "ERROR: Cannot use both --from-template and --show-example.\n"
        )
        sys.exit(2)

    if args.show_example:
        _show_example()
        sys.exit(0)

    target = resolve_config_path()

    if args.from_template:
        _init_from_template(target, force=args.force)
        sys.stderr.write("Run `gospelo-github-identity list` to verify.\n")
        sys.exit(0)

    print("Welcome to gospelo-github-identity init.")
    print(f"Config file will be saved to: {target}")
    print()

    if target.exists() and not args.force:
        if not _ask_yes_no(f"{target} already exists. Overwrite?", default=False):
            print("Aborted; existing config left untouched.", file=sys.stderr)
            sys.exit(0)

    profiles: dict[str, Profile] = {}
    try:
        while True:
            profile = _prompt_profile(existing=set(profiles))
            profiles[profile.name] = profile
            if not _ask_yes_no("Add another profile?", default=False):
                break

        if not profiles:
            print("ERROR: at least one profile is required.", file=sys.stderr)
            sys.exit(1)

        default_profile: str | None = None
        if len(profiles) == 1:
            single = next(iter(profiles))
            if _ask_yes_no(
                f"Set {single!r} as default_profile (used when no path matches)?",
                default=True,
            ):
                default_profile = single
        else:
            names = ", ".join(profiles)
            answer = _prompt(
                f"Default profile (one of: {names}) [leave blank for none]"
            )
            if answer:
                if answer not in profiles:
                    print(
                        f"ERROR: {answer!r} is not one of the entered profiles.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                default_profile = answer

        config = Config(
            version="1",
            profiles=profiles,
            default_profile=default_profile,
            source_path=target,
        )
        written = save_config(config, target)
        print(f"\nSaved: {written}")
        print("Run `gospelo-github-identity list` to verify.")
        sys.exit(0)
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.", file=sys.stderr)
        sys.exit(1)


def _prompt(message: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{message}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        # Required field, ask again
        print("  (value required)", file=sys.stderr)


def _prompt_optional(message: str) -> str:
    return input(f"{message} (optional): ").strip()


def _ask_yes_no(message: str, *, default: bool) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        raw = input(f"{message}{suffix}: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  (please answer y or n)", file=sys.stderr)


def _prompt_profile(existing: set[str]) -> Profile:
    print()
    while True:
        name = _prompt("Profile name (e.g. oss, work)")
        if name in existing:
            print(f"  (profile {name!r} already added; choose a different name)", file=sys.stderr)
            continue
        if not name.replace("-", "").replace("_", "").isalnum():
            print("  (use letters, digits, hyphen, or underscore)", file=sys.stderr)
            continue
        break

    description = _prompt_optional("Description")
    git_user_name = _prompt("git user.name")
    git_user_email = _prompt("git user.email")
    gh_account = _prompt("gh CLI account login")

    print("Paths (one per line, empty line to finish):")
    paths: list[str] = []
    while True:
        try:
            entry = input("  > ").strip()
        except EOFError:
            entry = ""
        if not entry:
            break
        paths.append(entry)

    return Profile(
        name=name,
        description=description,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
        gh_account=gh_account,
        paths=paths,
    )


if __name__ == "__main__":
    main()
