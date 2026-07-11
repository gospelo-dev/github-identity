# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.matcher``.

Covers the public glob translation and the ``resolve_profile`` selection
rules (longest-literal-prefix wins, default fallback, miss case).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gospelo_github_identity.config import Config, Profile
from gospelo_github_identity.matcher import (
    MatchResult,
    expand,
    resolve_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile(name: str, paths: list[str]) -> Profile:
    return Profile(
        name=name,
        description=f"{name} profile",
        git_user_name=f"{name}-name",
        git_user_email=f"{name}@example.com",
        gh_account=f"{name}-login",
        paths=paths,
    )


def _config(profiles: list[Profile], default: str | None = None) -> Config:
    return Config(
        version="1",
        profiles={p.name: p for p in profiles},
        default_profile=default,
        source_path=Path("/tmp/fake-config.yml"),
    )


# ---------------------------------------------------------------------------
# expand()
# ---------------------------------------------------------------------------


def test_expand_resolves_tilde(tmp_home: Path) -> None:
    expanded = expand("~/projects/foo")
    assert expanded == str(tmp_home / "projects" / "foo")
    assert "~" not in expanded, "tilde must be fully expanded"


def test_expand_passes_through_absolute_path() -> None:
    assert expand("/etc/hosts") == "/etc/hosts"


# ---------------------------------------------------------------------------
# resolve_profile: symlink handling
# ---------------------------------------------------------------------------


def test_matches_pattern_written_against_symlinked_path(tmp_path: Path) -> None:
    # real/proj is the actual directory; link -> real is a symlink. A pattern
    # written against the *symlinked* path must still match a cwd that resolves
    # to the real path (the macOS /var -> /private/var case).
    real = tmp_path / "real"
    (real / "proj").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    cfg = _config([_profile("p", [str(link / "proj") + "/**", str(link / "proj")])])
    result = resolve_profile(cfg, real / "proj")
    assert result.matched, "symlink-form pattern should match the real cwd"
    assert result.profile.name == "p"


def test_matches_real_pattern_from_symlinked_cwd(tmp_path: Path) -> None:
    # The reverse: pattern written against the real path, cwd reached via the
    # symlink. cwd resolves to the real path, so it matches.
    real = tmp_path / "real"
    (real / "proj").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    cfg = _config([_profile("p", [str(real / "proj")])])
    result = resolve_profile(cfg, link / "proj")
    assert result.matched, "real-form pattern should match the symlinked cwd"
    assert result.profile.name == "p"


# ---------------------------------------------------------------------------
# resolve_profile: glob semantics
# ---------------------------------------------------------------------------


def test_double_star_matches_multiple_components(tmp_home: Path) -> None:
    target = tmp_home / "projects" / "gospelo-dev" / "identity" / "foo"
    target.mkdir(parents=True)

    cfg = _config([_profile("p", ["~/projects/gospelo-dev/**"])])
    result = resolve_profile(cfg, target)
    assert result.matched
    assert result.profile is not None and result.profile.name == "p"
    assert result.via_default is False


def test_double_star_matches_immediate_child(tmp_home: Path) -> None:
    """A single child directory under a ``/**`` pattern must match.

    Note: trailing ``/**`` requires the literal slash before the ``**``,
    so the parent directory itself (``~/projects/gospelo-dev`` with no
    trailing slash) does not match its own ``~/projects/gospelo-dev/**``
    pattern. Tested separately below.
    """
    target = tmp_home / "projects" / "gospelo-dev" / "identity"
    target.mkdir(parents=True)

    cfg = _config([_profile("p", ["~/projects/gospelo-dev/**"])])
    result = resolve_profile(cfg, target)
    assert result.matched, "immediate child of /** parent must match"


def test_trailing_double_star_does_not_match_parent_directory(
    tmp_home: Path,
) -> None:
    """Documented current behavior: ``~/foo/**`` does not match ``~/foo`` itself.

    The implementation's regex is ``~/foo/.*`` so the trailing slash is
    required. Users who want to include the parent dir must list both
    ``~/foo`` and ``~/foo/**`` (or rely on a parent-level pattern). This
    test pins the behavior so we notice if it changes.
    """
    target = tmp_home / "projects" / "gospelo-dev"
    target.mkdir(parents=True)

    cfg = _config([_profile("p", ["~/projects/gospelo-dev/**"])])
    result = resolve_profile(cfg, target)
    assert not result.matched, (
        "current implementation: trailing /** requires at least one "
        "child segment; parent directory itself is not matched"
    )


def test_single_star_does_not_cross_slash(tmp_home: Path) -> None:
    nested = tmp_home / "projects" / "a" / "b"
    nested.mkdir(parents=True)
    sibling = tmp_home / "projects" / "a"

    cfg = _config([_profile("p", ["~/projects/*"])])
    # Single-level child: matches.
    result_top = resolve_profile(cfg, sibling)
    assert result_top.matched, "single-level child should match '~/projects/*'"
    # Two levels deep: must not match a single '*'.
    result_deep = resolve_profile(cfg, nested)
    assert not result_deep.matched, (
        "single '*' must not span '/', deep child must miss"
    )


# ---------------------------------------------------------------------------
# resolve_profile: priority and fallback
# ---------------------------------------------------------------------------


def test_longest_literal_prefix_wins(tmp_home: Path) -> None:
    target = tmp_home / "projects" / "work" / "oss-fork" / "module"
    target.mkdir(parents=True)

    broad = _profile("work", ["~/projects/work/**"])
    narrow = _profile("oss-fork", ["~/projects/work/oss-fork/**"])
    cfg = _config([broad, narrow])

    result = resolve_profile(cfg, target)
    assert result.matched
    assert result.profile is not None
    assert result.profile.name == "oss-fork", (
        "more specific path with longer literal prefix must win"
    )


def test_no_match_falls_back_to_default(tmp_home: Path) -> None:
    nowhere = tmp_home / "elsewhere"
    nowhere.mkdir()

    cfg = _config(
        [_profile("p", ["~/projects/specific/**"])],
        default="p",
    )
    result = resolve_profile(cfg, nowhere)
    assert result.matched
    assert result.via_default is True
    assert result.matched_pattern is None


def test_no_match_no_default_returns_empty(tmp_home: Path) -> None:
    nowhere = tmp_home / "elsewhere"
    nowhere.mkdir()

    cfg = _config([_profile("p", ["~/projects/specific/**"])])
    result = resolve_profile(cfg, nowhere)
    assert isinstance(result, MatchResult)
    assert not result.matched
    assert result.profile is None
    assert result.via_default is False


def test_matched_pattern_is_reported(tmp_home: Path) -> None:
    target = tmp_home / "projects" / "personal" / "deep" / "nested"
    target.mkdir(parents=True)

    cfg = _config([_profile("p", ["~/projects/personal/**"])])
    result = resolve_profile(cfg, target)
    assert result.matched
    assert result.matched_pattern == "~/projects/personal/**", (
        "matched_pattern should expose the original (un-expanded) pattern"
    )
