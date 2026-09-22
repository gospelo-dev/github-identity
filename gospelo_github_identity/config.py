# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Config loading and writing for gospelo-github-identity.

The config file lives at ``~/.config/gospelo-github-identity/config.yml`` and follows
the schema documented in ``docs/manual/ja/config-format.md``.

This module is deliberately strict: there are no silent fallbacks. If the file
is missing, the YAML is malformed, or a required key is absent, the caller
receives an exception that the CLI translates into a non-zero exit code with a
helpful message.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH_ENV = "GOSPELO_GITHUB_IDENTITY_CONFIG"
DEFAULT_CONFIG_PATH = Path("~/.config/gospelo-github-identity/config.yml").expanduser()


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or invalid."""


@dataclass
class Profile:
    """One declared identity profile."""

    name: str
    description: str
    git_user_name: str
    git_user_email: str
    gh_account: str
    # GitHub owners (users / orgs) whose repositories this profile's identity
    # writes to. The guard reverse-maps an operation's target owner to a
    # profile through this list (target-aware enforcement). Matching is
    # case-insensitive, mirroring GitHub login semantics.
    gh_owners: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    # Optional SSH-login verification. ``ssh_check`` is True when the profile
    # declares an ``ssh`` block (opt-in). ``ssh_login`` is the raw expected
    # GitHub login as written; when omitted it defaults to ``gh_account`` (the
    # same GitHub identity). ``ssh_host`` forces a host instead of deriving it
    # from the repo's ``origin`` remote.
    ssh_check: bool = False
    ssh_login: str | None = None
    ssh_host: str | None = None

    @property
    def expected_ssh_login(self) -> str:
        """Effective GitHub login the SSH key is expected to authenticate as."""
        return self.ssh_login or self.gh_account


@dataclass
class Config:
    """Top-level config object."""

    version: str
    profiles: dict[str, Profile]
    default_profile: str | None
    source_path: Path
    # A manually selected profile wins when it also matches the current path.
    # This lets users select between identities that intentionally share paths.
    active_profile: str | None = None

    def get_profile(self, name: str) -> Profile:
        """Return a profile by name, or raise ``ConfigError``."""
        if name not in self.profiles:
            available = ", ".join(sorted(self.profiles)) or "(none)"
            raise ConfigError(
                f"Unknown profile: {name!r}. Available: {available}"
            )
        return self.profiles[name]

    def owners_declared(self) -> bool:
        """True when at least one profile declares ``gh.owners``.

        This is the opt-in switch for target-aware enforcement: with no owners
        anywhere, the guard stays in legacy cwd-based check mode.
        """
        return any(p.gh_owners for p in self.profiles.values())

    def profile_for_owner(self, owner: str) -> Profile | None:
        """Reverse-map a GitHub owner (user/org) to the profile declaring it.

        Case-insensitive. Returns ``None`` when no profile declares the owner
        (parse-time validation guarantees an owner appears in at most one
        profile).
        """
        needle = owner.casefold()
        for profile in self.profiles.values():
            if any(o.casefold() == needle for o in profile.gh_owners):
                return profile
        return None


def resolve_config_path() -> Path:
    """Return the active config file path.

    Honours ``GOSPELO_GITHUB_IDENTITY_CONFIG`` if set; otherwise uses the XDG-style
    default ``~/.config/gospelo-github-identity/config.yml``.
    """
    override = os.environ.get(CONFIG_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> Config:
    """Load and validate the config file.

    Raises ``ConfigError`` when the file is missing, the YAML is malformed,
    or required schema keys are absent. The caller is expected to catch this
    and surface a friendly message + exit code 2.
    """
    config_path = path if path is not None else resolve_config_path()

    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}\n"
            f"Run `gospelo-github-identity init` to create one."
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML in {config_path}: {exc}") from exc

    if raw is None:
        raise ConfigError(f"Config file is empty: {config_path}")
    if not isinstance(raw, dict):
        raise ConfigError(
            f"Config file root must be a mapping, got {type(raw).__name__}"
        )

    return _parse_config(raw, config_path)


def _parse_config(raw: dict[str, Any], source_path: Path) -> Config:
    version = raw.get("version")
    if not version:
        raise ConfigError(
            f"{source_path}: missing required key 'version' (expected '1')"
        )
    if str(version) != "1":
        raise ConfigError(
            f"{source_path}: unsupported version {version!r}, this build "
            f"understands version '1' only"
        )

    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, dict) or not profiles_raw:
        raise ConfigError(
            f"{source_path}: missing or empty 'profiles' mapping"
        )

    profiles: dict[str, Profile] = {}
    for name, body in profiles_raw.items():
        profiles[name] = _parse_profile(name, body, source_path)

    # An owner must map to exactly one profile -- an ambiguous reverse map
    # would make the guard's target-aware enforcement nondeterministic.
    owner_seen: dict[str, str] = {}
    for name, profile in profiles.items():
        for owner in profile.gh_owners:
            key = owner.casefold()
            if key in owner_seen:
                raise ConfigError(
                    f"{source_path}: gh owner {owner!r} is declared by both "
                    f"profile {owner_seen[key]!r} and {name!r}; an owner may "
                    f"belong to only one profile"
                )
            owner_seen[key] = name

    default_profile = raw.get("default_profile")
    _validate_profile_reference("default_profile", default_profile, profiles, source_path)

    active_profile = raw.get("active_profile")
    _validate_profile_reference("active_profile", active_profile, profiles, source_path)

    return Config(
        version=str(version),
        profiles=profiles,
        default_profile=default_profile,
        source_path=source_path,
        active_profile=active_profile,
    )


def _validate_profile_reference(
    key: str, value: Any, profiles: dict[str, Profile], source_path: Path
) -> None:
    """Ensure an optional top-level profile reference names a declared profile."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ConfigError(f"{source_path}: '{key}' must be a string")
    if value not in profiles:
        raise ConfigError(
            f"{source_path}: '{key}' references unknown profile {value!r}"
        )


def _parse_profile(name: str, body: Any, source_path: Path) -> Profile:
    if not isinstance(body, dict):
        raise ConfigError(
            f"{source_path}: profile {name!r} must be a mapping"
        )

    git_block = body.get("git")
    if not isinstance(git_block, dict):
        raise ConfigError(
            f"{source_path}: profile {name!r} missing required 'git' mapping"
        )

    user_name = git_block.get("user.name")
    user_email = git_block.get("user.email")
    if not isinstance(user_name, str) or not user_name.strip():
        raise ConfigError(
            f"{source_path}: profile {name!r} missing required "
            f"'git.user.name'"
        )
    if not isinstance(user_email, str) or not user_email.strip():
        raise ConfigError(
            f"{source_path}: profile {name!r} missing required "
            f"'git.user.email'"
        )

    gh_block = body.get("gh")
    if not isinstance(gh_block, dict):
        raise ConfigError(
            f"{source_path}: profile {name!r} missing required 'gh' mapping"
        )
    gh_account = gh_block.get("account")
    if not isinstance(gh_account, str) or not gh_account.strip():
        raise ConfigError(
            f"{source_path}: profile {name!r} missing required 'gh.account'"
        )

    owners_raw = gh_block.get("owners", [])
    if not isinstance(owners_raw, list):
        raise ConfigError(
            f"{source_path}: profile {name!r} 'gh.owners' must be a list"
        )
    gh_owners: list[str] = []
    for entry in owners_raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigError(
                f"{source_path}: profile {name!r} 'gh.owners' entries must be "
                f"non-empty strings"
            )
        gh_owners.append(entry.strip())

    ssh_check, ssh_login, ssh_host = _parse_ssh(name, body.get("ssh"), source_path)

    paths_raw = body.get("paths", [])
    if not isinstance(paths_raw, list):
        raise ConfigError(
            f"{source_path}: profile {name!r} 'paths' must be a list"
        )
    paths: list[str] = []
    for entry in paths_raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ConfigError(
                f"{source_path}: profile {name!r} 'paths' entries must be "
                f"non-empty strings"
            )
        paths.append(entry)

    description = body.get("description", "") or ""
    if not isinstance(description, str):
        raise ConfigError(
            f"{source_path}: profile {name!r} 'description' must be a string"
        )

    return Profile(
        name=name,
        description=description,
        git_user_name=user_name.strip(),
        git_user_email=user_email.strip(),
        gh_account=gh_account.strip(),
        gh_owners=gh_owners,
        paths=paths,
        ssh_check=ssh_check,
        ssh_login=ssh_login,
        ssh_host=ssh_host,
    )


def _parse_ssh(
    name: str, ssh_block: Any, source_path: Path
) -> tuple[bool, str | None, str | None]:
    """Parse the optional ``ssh`` block of a profile.

    Returns ``(ssh_check, ssh_login, ssh_host)``. When the block is absent
    (``None``) the SSH-login check stays disabled and behavior is unchanged.
    Presence of a mapping (even the empty ``ssh: {}``) opts the profile in;
    ``login`` defaults to ``gh.account`` and ``host`` is derived from the
    repo's ``origin`` remote at check time.
    """
    if ssh_block is None:
        return False, None, None
    if not isinstance(ssh_block, dict):
        raise ConfigError(
            f"{source_path}: profile {name!r} 'ssh' must be a mapping"
        )

    login = ssh_block.get("login")
    if login is not None and (not isinstance(login, str) or not login.strip()):
        raise ConfigError(
            f"{source_path}: profile {name!r} 'ssh.login' must be a "
            f"non-empty string"
        )

    host = ssh_block.get("host")
    if host is not None and (not isinstance(host, str) or not host.strip()):
        raise ConfigError(
            f"{source_path}: profile {name!r} 'ssh.host' must be a "
            f"non-empty string"
        )

    return (
        True,
        login.strip() if isinstance(login, str) else None,
        host.strip() if isinstance(host, str) else None,
    )


def save_config(config: Config, path: Path | None = None) -> Path:
    """Serialise a ``Config`` back to YAML.

    The output path defaults to the config's ``source_path``. The parent
    directory is created with ``mode=0o700`` if missing. Existing files are
    overwritten without prompting; the CLI ``init`` command is responsible
    for asking before calling this.
    """
    target = path if path is not None else config.source_path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    payload: dict[str, Any] = {"version": config.version, "profiles": {}}
    for name, profile in config.profiles.items():
        entry: dict[str, Any] = {
            "description": profile.description,
            "git": {
                "user.name": profile.git_user_name,
                "user.email": profile.git_user_email,
            },
            "gh": {
                "account": profile.gh_account,
            },
        }
        if profile.gh_owners:
            entry["gh"]["owners"] = list(profile.gh_owners)
        if profile.ssh_check:
            ssh_out: dict[str, str] = {}
            if profile.ssh_login is not None:
                ssh_out["login"] = profile.ssh_login
            if profile.ssh_host is not None:
                ssh_out["host"] = profile.ssh_host
            entry["ssh"] = ssh_out
        entry["paths"] = list(profile.paths)
        payload["profiles"][name] = entry
    if config.default_profile is not None:
        payload["default_profile"] = config.default_profile
    if config.active_profile is not None:
        payload["active_profile"] = config.active_profile

    text = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    target.write_text(text, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        # Best-effort: fail open on filesystems that do not support chmod.
        pass
    return target


def set_active_profile(config: Config, name: str) -> None:
    """Persist a selected profile without rewriting the user's YAML comments."""
    config.get_profile(name)
    line = f"active_profile: {name}\n"
    text = config.source_path.read_text(encoding="utf-8")
    if re.search(r"(?m)^active_profile:[^\n]*(?:\n|$)", text):
        text = re.sub(r"(?m)^active_profile:[^\n]*(?:\n|$)", line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line
    config.source_path.write_text(text, encoding="utf-8")
    config.active_profile = name
