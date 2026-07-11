# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""gospelo-github-identity CLI entry point.

Dispatches subcommands to the corresponding modules. Each subcommand module
remains directly executable as ``python -m gospelo_github_identity.<name>``.
"""

from __future__ import annotations

import sys
from typing import Callable

from . import __version__


# Subcommand name -> (module path, callable name)
_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "init": ("gospelo_github_identity.initializer", "main"),
    "list": ("gospelo_github_identity.lister", "main"),
    "detect": ("gospelo_github_identity.detector", "main"),
    "check": ("gospelo_github_identity.checker", "main"),
    "doctor": ("gospelo_github_identity.doctor", "main"),
    "switch": ("gospelo_github_identity.switcher", "main"),
    "prompt": ("gospelo_github_identity.prompter", "main"),
    "guard": ("gospelo_github_identity.guard", "guard_main"),
    "install-guard": ("gospelo_github_identity.guard", "install_main"),
    "uninstall-guard": ("gospelo_github_identity.guard", "uninstall_main"),
    "strip-coauthors": ("gospelo_github_identity.commit_hook", "strip_main"),
    "install-commit-hook": ("gospelo_github_identity.commit_hook", "install_main"),
    "uninstall-commit-hook": ("gospelo_github_identity.commit_hook", "uninstall_main"),
}


def _print_usage() -> None:
    print(f"gospelo-github-identity {__version__}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Usage: gospelo-github-identity <subcommand> [args...]", file=sys.stderr)
    print("", file=sys.stderr)
    print("Subcommands:", file=sys.stderr)
    print("  init      Interactively scaffold ~/.config/gospelo-github-identity/config.yml", file=sys.stderr)
    print("  list      List registered profiles", file=sys.stderr)
    print("  detect    Print the profile that owns the current directory", file=sys.stderr)
    print("  check     Compare expected vs actual git config + gh CLI account", file=sys.stderr)
    print("  doctor    Audit setup health (identity scope/value, remote + SSH-alias pinning)", file=sys.stderr)
    print("  switch    Switch git config + gh auth to the named profile", file=sys.stderr)
    print("  prompt    Shell prompt helper (use in PS1)", file=sys.stderr)
    print("  install-guard    Shadow gh (and optionally git) to block wrong-identity writes", file=sys.stderr)
    print("  uninstall-guard  Remove the gh/git guard shims", file=sys.stderr)
    print("  install-commit-hook    Strip Co-Authored-By from every commit message", file=sys.stderr)
    print("  uninstall-commit-hook  Remove the commit-msg guard", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Run 'gospelo-github-identity <subcommand> --help' for subcommand-specific options.",
        file=sys.stderr,
    )


def _resolve(subcommand: str) -> Callable[[], None]:
    if subcommand not in _SUBCOMMANDS:
        print(f"ERROR: unknown subcommand: {subcommand}", file=sys.stderr)
        _print_usage()
        sys.exit(2)
    module_path, attr = _SUBCOMMANDS[subcommand]
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)


def main() -> None:
    """Dispatch to the requested subcommand.

    Strips the subcommand from argv so the underlying module's argparse sees
    a normal argv (positional argv[0] == script name, then its own args).
    """
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        _print_usage()
        sys.exit(0 if (len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help")) else 2)

    if sys.argv[1] in ("-V", "--version"):
        print(f"gospelo-github-identity {__version__}")
        sys.exit(0)

    subcommand = sys.argv[1]
    handler = _resolve(subcommand)

    sys.argv = [f"gospelo-github-identity {subcommand}"] + sys.argv[2:]
    handler()


if __name__ == "__main__":
    main()
