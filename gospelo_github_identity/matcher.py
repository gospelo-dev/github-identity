# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Path glob matching: cwd -> profile resolution.

The glob translation here mirrors the implementation in
``gospelo_review.executor.scope_resolver``. We re-implement it instead of
importing because gospelo-github-identity must be installable on its own.

Supported glob syntax:

  ``**`` / ``**/``   matches any number of path components (including zero)
  ``*``              matches any sequence of characters except ``/``
  ``?``              matches a single character except ``/``
  ``[abc]``/``[a-z]``  character class
  ``~``              expanded to ``$HOME`` before matching
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config, Profile


@dataclass
class MatchResult:
    """Result of resolving a directory to a profile."""

    profile: Profile | None
    matched_pattern: str | None
    via_default: bool

    @property
    def matched(self) -> bool:
        return self.profile is not None


def expand(path_pattern: str) -> str:
    """Expand ``~`` and environment variables in a path pattern."""
    return str(Path(path_pattern).expanduser())


def resolve_profile(config: Config, cwd: Path) -> MatchResult:
    """Find the profile that owns the given directory.

    Selection rules:
      1. Expand ``~`` in every profile path entry.
      2. Match symmetrically against symlinks: the cwd is resolved to its real
         path, and each pattern's **literal prefix** is resolved too, so a
         pattern written against a symlinked path (e.g. macOS ``/var/...`` ->
         ``/private/var/...``, or a ``~`` through a symlinked home) still
         matches. The unresolved-absolute forms are also compared as a fallback
         for paths that do not exist on disk.
      3. If multiple profiles match, the one with the longest **literal
         prefix** (the part before the first glob metacharacter) wins. This
         keeps nested directories like ``~/projects/work/oss-fork/**``
         beating a broader ``~/projects/work/**``.
      4. If nothing matches, fall back to ``default_profile`` if set;
         otherwise return an empty result.
    """
    cwd_real = _safe_resolve(cwd)
    cwd_abs = os.path.abspath(str(cwd))

    candidates: list[tuple[int, Profile, str]] = []
    for profile in config.profiles.values():
        for raw_pattern in profile.paths:
            pattern = expand(raw_pattern)
            pattern_resolved = _resolve_pattern_prefix(pattern)
            if _glob_match(cwd_real, pattern_resolved) or _glob_match(cwd_abs, pattern):
                # Specificity ranks on the as-written pattern, not the resolved
                # one, so symlink resolution never changes which profile wins.
                prefix_len = len(_literal_prefix(pattern))
                candidates.append((prefix_len, profile, raw_pattern))

    if candidates:
        # Longest literal prefix wins; ties broken by insertion order.
        candidates.sort(key=lambda item: item[0], reverse=True)
        best = candidates[0]
        return MatchResult(profile=best[1], matched_pattern=best[2], via_default=False)

    if config.default_profile is not None:
        return MatchResult(
            profile=config.profiles[config.default_profile],
            matched_pattern=None,
            via_default=True,
        )

    return MatchResult(profile=None, matched_pattern=None, via_default=False)


def _safe_resolve(path: Path) -> str:
    """``path.resolve()`` as a string, falling back to abspath on error."""
    try:
        return str(path.resolve())
    except OSError:
        return os.path.abspath(str(path))


def _resolve_pattern_prefix(pattern: str) -> str:
    """Resolve symlinks in the pattern's literal prefix, keeping the glob part.

    Only the part before the first glob metacharacter is a real path we can
    resolve; the glob suffix is reattached verbatim. This makes pattern/cwd
    matching symmetric under symlinks (both sides end up as real paths).
    """
    prefix = _literal_prefix(pattern)
    if not prefix:
        return pattern
    suffix = pattern[len(prefix):]
    trailing = "/" if prefix.endswith("/") and prefix != os.sep else ""
    base = prefix[:-1] if trailing else prefix
    try:
        resolved = str(Path(base).resolve())
    except OSError:
        return pattern
    return resolved + trailing + suffix


def _literal_prefix(pattern: str) -> str:
    """Return the part of the pattern before the first glob metacharacter."""
    for i, c in enumerate(pattern):
        if c in "*?[":
            return pattern[:i]
    return pattern


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob pattern to a compiled regex.

    Anchored (fullmatch) at both ends.
    """
    i = 0
    parts: list[str] = []
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # Consume **
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    # '**/' -- matches any number of dirs (including zero)
                    i += 1
                    parts.append("(?:.*/)?")
                else:
                    # Trailing '**' -- matches anything (including /)
                    parts.append(".*")
            else:
                i += 1
                parts.append("[^/]*")
        elif c == "?":
            i += 1
            parts.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < len(pattern) and pattern[j] == "!":
                j += 1
            while j < len(pattern) and pattern[j] != "]":
                j += 1
            if j >= len(pattern):
                parts.append(re.escape("["))
                i += 1
            else:
                cls = pattern[i : j + 1]
                if cls.startswith("[!"):
                    cls = "[^" + cls[2:]
                parts.append(cls)
                i = j + 1
        else:
            parts.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(parts) + "$")


def _glob_match(path: str, pattern: str) -> bool:
    return _glob_to_regex(pattern).match(path) is not None
