# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""gospelo-github-identity: directory-aware git/gh CLI identity guard."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    # Single source of truth: the installed distribution's metadata
    # (driven by pyproject.toml's version). Avoids a hardcoded duplicate.
    __version__ = _version("gospelo-github-identity")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"
