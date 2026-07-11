# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""``gospelo-github-identity doctor`` command.

Where ``check`` answers "is my identity correct *right now*?", ``doctor``
answers "is the setup wired so it *stays* correct, for the right reasons?".
It audits the structural health of the setup rather than the resolved runtime
values, so it catches problems ``check`` cannot:

  * a repo whose git identity is set but *wrong* (e.g. a ``.com``/``.net``
    typo) -- not just unset;
  * git identity that is only correct by *inheriting* the global config
    (fragile: a global change silently breaks it);
  * a remote that still uses bare ``git@github.com`` -- which authenticates as
    whatever key ``ssh-agent`` offers first, so it works today but is one key
    reorder away from pushing as the wrong account;
  * an SSH-alias host that does not actually pin one key
    (``IdentitiesOnly no`` / missing key file);
  * the expected ``gh`` account not being logged in at all.

With ``--sweep`` it audits every repo under the matched profile's ``paths``
globs at once, surfacing the whole tree's health instead of one directory.

This audit is config-only (no ``ssh -T`` network probe) so it is fast and works
offline; run ``check`` for the live-authentication verification.

Exit codes:
  0 - every audited item is OK
  1 - at least one WARN/FAIL finding, or no profile matched the directory
  2 - configuration or external tool error
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import _external
from .config import Config, ConfigError, Profile, load_config
from .matcher import _literal_prefix, expand, resolve_profile

# A finding is (level, message). Levels, worst first: FAIL, WARN, INFO, OK.
Finding = tuple[str, str]

_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gospelo-github-identity doctor",
        description=(
            "Audit the structural health of the identity setup (git identity "
            "scope/value, remote robustness, SSH-alias key pinning, gh login) "
            "for the profile that owns the current directory."
        ),
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Override the directory to resolve the profile from (default: current).",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Audit every git repo under the matched profile's paths, not just cwd.",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    cwd = (args.cwd if args.cwd is not None else Path.cwd()).resolve()
    match = resolve_profile(config, cwd)

    print("=== Identity Doctor ===")
    print(f"Working dir: {cwd}")

    if not match.matched:
        print("Matched profile: (none)")
        print(
            "\nERROR: no profile path matched this directory and no "
            "default_profile is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    profile: Profile = match.profile
    via = " (default)" if match.via_default else f" (via pattern: {match.matched_pattern})"
    print(f"Matched profile: {profile.name}{via}")

    worst = "OK"

    # ---- machine-level -----------------------------------------------------
    print("\n[machine]")
    try:
        for finding in _machine_findings(profile):
            worst = _emit(finding, worst)
    except _external.ExternalToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    # ---- per-repo ----------------------------------------------------------
    try:
        if args.sweep:
            repos = _sweep_repos(config, profile)
            if not repos:
                print("\n[repos] (no git repositories found under this profile's paths)")
            for repo in repos:
                print(f"\n[repo] {repo.name}  ({repo})")
                for finding in _repo_findings(profile, repo):
                    worst = _emit(finding, worst)
        else:
            repo = _external.git_toplevel(cwd=cwd)
            if repo is None:
                print("\n[repo] (current directory is not inside a git repository)")
                print(
                    "       Run inside a repo, or use --sweep to audit the "
                    "whole profile tree."
                )
            else:
                print(f"\n[repo] {repo.name}  ({repo})")
                for finding in _repo_findings(profile, repo):
                    worst = _emit(finding, worst)
    except _external.ExternalToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    print()
    if worst == "OK":
        print(f"OK: setup is healthy for profile {profile.name!r}.")
        sys.exit(0)
    print(
        f"{'FAIL' if worst == 'FAIL' else 'WARN'}: setup has issues for profile "
        f"{profile.name!r} (see above).",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_MARK = {"OK": "OK  ", "INFO": "INFO", "WARN": "WARN", "FAIL": "FAIL"}
_RANK = {"OK": 0, "INFO": 0, "WARN": 1, "FAIL": 2}


def _emit(finding: Finding, worst: str) -> str:
    level, message = finding
    print(f"  [{_MARK.get(level, level)}] {message}")
    return level if _RANK.get(level, 0) > _RANK.get(worst, 0) else worst


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _machine_findings(profile: Profile) -> list[Finding]:
    findings: list[Finding] = []

    gname = _external.git_get_config("user.name", scope="global")
    gemail = _external.git_get_config("user.email", scope="global")
    if gname is None and gemail is None:
        findings.append(("OK", "global git identity is unset (identity is left to each repo)"))
    else:
        findings.append(
            (
                "INFO",
                f"global git identity is set ({gname} / {gemail}); repos without a "
                f"local override inherit it",
            )
        )

    if _external.gh_account_available(profile.gh_account):
        findings.append(("OK", f"gh account {profile.gh_account!r} is logged in"))
    else:
        findings.append(
            (
                "WARN",
                f"gh account {profile.gh_account!r} is not logged in "
                f"(switch / GH_TOKEN automation cannot act as it) -- "
                f"run `gh auth login --hostname github.com`",
            )
        )
    return findings


def _repo_findings(profile: Profile, repo: Path) -> list[Finding]:
    findings: list[Finding] = [_check_git_identity(profile, repo)]
    findings.extend(_check_remote(repo))
    return findings


def _check_git_identity(profile: Profile, repo: Path) -> Finding:
    exp_name, exp_email = profile.git_user_name, profile.git_user_email
    local_name = _external.git_get_config("user.name", cwd=repo, scope="local")
    local_email = _external.git_get_config("user.email", cwd=repo, scope="local")
    eff_name = _external.git_get_config("user.name", cwd=repo)
    eff_email = _external.git_get_config("user.email", cwd=repo)

    # What will actually author commits (effective value) is what matters most.
    if eff_name is None or eff_email is None:
        return (
            "FAIL",
            f"git identity is unset (commits will fail): "
            f"name={eff_name or '(unset)'}, email={eff_email or '(unset)'}",
        )
    if eff_name != exp_name or eff_email != exp_email:
        return (
            "FAIL",
            f"git identity is wrong: {eff_name} / {eff_email} "
            f"(expected {exp_name} / {exp_email})",
        )
    # Effective value is correct. Is it pinned locally, or only inherited?
    if local_name != exp_name or local_email != exp_email:
        return (
            "WARN",
            "git identity is correct but not pinned locally (inherited from "
            "global/system); a global change would silently break it -- run "
            f"`gospelo-github-identity switch {profile.name}`",
        )
    return ("OK", f"git identity pinned locally: {exp_name} / {exp_email}")


def _check_remote(repo: Path) -> list[Finding]:
    url = _external.git_remote_url("origin", cwd=repo)
    if not url:
        return [("WARN", "no 'origin' remote")]

    target = _external.ssh_target_from_remote(url)
    if target is None:
        return [
            (
                "WARN",
                f"origin is not an SSH remote ({url}); SSH-alias remotes are "
                f"recommended so the key is pinned per repo",
            )
        ]

    host = target.split("@")[-1]
    if host == "github.com":
        return [
            (
                "WARN",
                f"origin uses bare github.com ({url}); authenticates as whatever "
                f"key ssh-agent offers first -- switch to an SSH-alias remote",
            )
        ]

    findings: list[Finding] = [("OK", f"origin uses SSH alias '{host}' ({url})")]
    findings.append(_check_ssh_pin(host))
    return findings


def _check_ssh_pin(host: str) -> Finding:
    try:
        cfg = _external.ssh_resolve(host)
    except _external.ExternalToolError as exc:
        return ("WARN", f"could not resolve ssh config for '{host}': {exc}")

    if cfg.identity_file is None:
        return (
            "WARN",
            f"alias '{host}' pins no IdentityFile (falls back to agent key order)",
        )
    key_path = Path(cfg.identity_file).expanduser()
    if not key_path.exists():
        return ("FAIL", f"alias '{host}' key file is missing: {cfg.identity_file}")
    if not cfg.identities_only:
        return (
            "WARN",
            f"alias '{host}' has IdentitiesOnly=no ({cfg.identity_file}); a stray "
            f"agent key could still be offered first",
        )
    return ("OK", f"alias '{host}' pins {cfg.identity_file} (IdentitiesOnly yes)")


# ---------------------------------------------------------------------------
# Repo enumeration (--sweep)
# ---------------------------------------------------------------------------


def _sweep_repos(config: Config, profile: Profile) -> list[Path]:
    """Return git repos under the profile's path prefixes that it owns."""
    seen: set[Path] = set()
    repos: list[Path] = []
    for raw in profile.paths:
        base = Path(_literal_prefix(expand(raw)))
        for repo in _find_git_repos(base):
            real = repo.resolve()
            if real in seen:
                continue
            seen.add(real)
            owner = resolve_profile(config, repo)
            if owner.matched and not owner.via_default and owner.profile.name == profile.name:
                repos.append(repo)
    return sorted(repos)


def _find_git_repos(base: Path) -> list[Path]:
    """Walk ``base`` and return every working-tree root (dirs holding ``.git``)."""
    repos: list[Path] = []
    if not base.exists():
        return repos
    for root, dirs, _files in os.walk(base):
        if ".git" in dirs:
            repos.append(Path(root))
            dirs[:] = []  # do not descend into a repository
            continue
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
    return repos


if __name__ == "__main__":
    main()
