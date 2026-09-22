# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Tests for ``gospelo_github_identity.config``.

Covers the public surface: ``load_config``, ``save_config``,
``resolve_config_path``, ``Config.get_profile``. Verifies strict validation
(no silent fallbacks).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from gospelo_github_identity.config import (
    CONFIG_PATH_ENV,
    Config,
    ConfigError,
    Profile,
    load_config,
    resolve_config_path,
    save_config,
    set_active_profile,
)


# ---------------------------------------------------------------------------
# load_config: happy path
# ---------------------------------------------------------------------------


def test_load_config_reads_valid_yaml(valid_config_file: Path) -> None:
    cfg = load_config(valid_config_file)
    assert cfg.version == "1", "version must be parsed as the string '1'"
    assert set(cfg.profiles) == {"personal", "work"}
    assert cfg.default_profile == "personal"
    assert cfg.active_profile is None
    assert cfg.source_path == valid_config_file


def test_load_config_parses_profile_fields(valid_config_file: Path) -> None:
    cfg = load_config(valid_config_file)
    p = cfg.profiles["personal"]
    assert p.git_user_name == "Alice Example"
    assert p.git_user_email == "alice@example.com"
    assert p.gh_account == "alice-personal"
    assert p.description == "Personal OSS work"
    assert p.paths == ["~/projects/personal/**", "~/projects/oss/**"]


def test_load_config_minimal_no_default(minimal_config_file: Path) -> None:
    cfg = load_config(minimal_config_file)
    assert cfg.default_profile is None, (
        "default_profile must be None when omitted (no silent fallback)"
    )
    assert list(cfg.profiles) == ["solo"]


def test_load_config_reads_active_profile(write_config) -> None:
    config_file = write_config(
        """version: \"1\"
profiles:
  p:
    git: {user.name: a, user.email: a@example.com}
    gh: {account: a}
    paths: []
active_profile: p
"""
    )
    assert load_config(config_file).active_profile == "p"


def test_set_active_profile_preserves_comments(valid_config_file: Path) -> None:
    config = load_config(valid_config_file)
    valid_config_file.write_text(
        "# keep this comment\n" + valid_config_file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    set_active_profile(config, "work")

    text = valid_config_file.read_text(encoding="utf-8")
    assert text.startswith("# keep this comment\n")
    assert "active_profile: work\n" in text
    assert config.active_profile == "work"


# ---------------------------------------------------------------------------
# load_config: error paths
# ---------------------------------------------------------------------------


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(missing)


def test_load_config_unsupported_version_raises(write_config) -> None:
    bad = write_config(
        dedent(
            """\
            version: "2"
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: a}
                paths: []
            """
        )
    )
    with pytest.raises(ConfigError, match="unsupported version"):
        load_config(bad)


def test_load_config_missing_version_raises(write_config) -> None:
    bad = write_config(
        dedent(
            """\
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: a}
                paths: []
            """
        )
    )
    with pytest.raises(ConfigError, match="version"):
        load_config(bad)


def test_load_config_profile_without_git_block_raises(write_config) -> None:
    bad = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                gh: {account: a}
                paths: []
            """
        )
    )
    with pytest.raises(ConfigError, match="missing required 'git'"):
        load_config(bad)


def test_load_config_profile_missing_user_email_raises(write_config) -> None:
    bad = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                git:
                  user.name: "alice"
                gh: {account: a}
                paths: []
            """
        )
    )
    with pytest.raises(ConfigError, match="user.email"):
        load_config(bad)


def test_load_config_default_profile_unknown_raises(write_config) -> None:
    bad = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: a}
                paths: []
            default_profile: nonexistent
            """
        )
    )
    with pytest.raises(ConfigError, match="default_profile"):
        load_config(bad)


def test_load_config_empty_file_raises(write_config) -> None:
    bad = write_config("")
    with pytest.raises(ConfigError, match="empty"):
        load_config(bad)


def test_load_config_malformed_yaml_raises(write_config) -> None:
    bad = write_config("version: '1'\nprofiles: [unclosed")
    with pytest.raises(ConfigError, match="Malformed YAML"):
        load_config(bad)


# ---------------------------------------------------------------------------
# Config.get_profile
# ---------------------------------------------------------------------------


def test_get_profile_returns_known(valid_config_file: Path) -> None:
    cfg = load_config(valid_config_file)
    p = cfg.get_profile("work")
    assert isinstance(p, Profile)
    assert p.name == "work"


def test_get_profile_unknown_raises(valid_config_file: Path) -> None:
    cfg = load_config(valid_config_file)
    with pytest.raises(ConfigError, match="Unknown profile"):
        cfg.get_profile("does-not-exist")


# ---------------------------------------------------------------------------
# resolve_config_path / env override
# ---------------------------------------------------------------------------


def test_resolve_config_path_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "custom.yml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(target))
    assert resolve_config_path() == target


def test_resolve_config_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_PATH_ENV, raising=False)
    path = resolve_config_path()
    # Defaults to ~/.config/gospelo-github-identity/config.yml. We assert the leaf
    # parts only so the test stays portable across HOMEs.
    assert path.name == "config.yml"
    assert path.parent.name == "gospelo-github-identity"


# ---------------------------------------------------------------------------
# save_config round-trip
# ---------------------------------------------------------------------------


def test_save_config_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "out.yml"
    cfg = Config(
        version="1",
        profiles={
            "p": Profile(
                name="p",
                description="desc",
                git_user_name="u",
                git_user_email="u@example.com",
                gh_account="login",
                paths=["~/code/**"],
            )
        },
        default_profile="p",
        source_path=target,
    )
    written = save_config(cfg, target)
    assert written == target
    reloaded = load_config(target)
    assert reloaded.profiles["p"].git_user_email == "u@example.com"
    assert reloaded.default_profile == "p"


# ---------------------------------------------------------------------------
# ssh block (optional SSH-login check)
# ---------------------------------------------------------------------------


def test_load_config_ssh_absent_disables_check(minimal_config_file: Path) -> None:
    """A profile without an `ssh` block leaves the check disabled (default)."""
    cfg = load_config(minimal_config_file)
    p = cfg.profiles["solo"]
    assert p.ssh_check is False
    assert p.ssh_login is None
    assert p.ssh_host is None


def test_load_config_ssh_empty_block_defaults_login_to_gh(write_config) -> None:
    """`ssh: {}` opts in; expected login defaults to `gh.account`."""
    cfg_file = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: octocat}
                ssh: {}
                paths: []
            """
        )
    )
    p = load_config(cfg_file).profiles["p"]
    assert p.ssh_check is True
    assert p.ssh_login is None
    assert p.expected_ssh_login == "octocat"


def test_load_config_ssh_explicit_login_and_host(write_config) -> None:
    cfg_file = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: octocat}
                ssh: {login: octocat-alt, host: github.com-alt}
                paths: []
            """
        )
    )
    p = load_config(cfg_file).profiles["p"]
    assert p.ssh_check is True
    assert p.ssh_login == "octocat-alt"
    assert p.expected_ssh_login == "octocat-alt"
    assert p.ssh_host == "github.com-alt"


def test_load_config_ssh_not_a_mapping_raises(write_config) -> None:
    cfg_file = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: a}
                ssh: "yes"
                paths: []
            """
        )
    )
    with pytest.raises(ConfigError, match="'ssh' must be a mapping"):
        load_config(cfg_file)


def test_load_config_ssh_blank_login_raises(write_config) -> None:
    cfg_file = write_config(
        dedent(
            """\
            version: "1"
            profiles:
              p:
                git: {user.name: a, user.email: a@example.com}
                gh: {account: a}
                ssh: {login: "  "}
                paths: []
            """
        )
    )
    with pytest.raises(ConfigError, match="'ssh.login' must be"):
        load_config(cfg_file)


def test_save_config_round_trip_preserves_ssh(tmp_path: Path) -> None:
    target = tmp_path / "out.yml"
    cfg = Config(
        version="1",
        profiles={
            "p": Profile(
                name="p",
                description="desc",
                git_user_name="u",
                git_user_email="u@example.com",
                gh_account="login",
                paths=["~/code/**"],
                ssh_check=True,
                ssh_login="login-alt",
                ssh_host="github.com-alt",
            ),
            "q": Profile(
                name="q",
                description="",
                git_user_name="v",
                git_user_email="v@example.com",
                gh_account="vlogin",
                paths=[],
                ssh_check=True,  # opted in, login defaults to gh.account
            ),
        },
        default_profile="p",
        source_path=target,
    )
    save_config(cfg, target)
    reloaded = load_config(target)
    rp = reloaded.profiles["p"]
    assert rp.ssh_check is True
    assert rp.ssh_login == "login-alt"
    assert rp.ssh_host == "github.com-alt"
    rq = reloaded.profiles["q"]
    assert rq.ssh_check is True
    assert rq.ssh_login is None
    assert rq.expected_ssh_login == "vlogin"


# ---------------------------------------------------------------------------
# gh.owners (target-aware enforcement opt-in)
# ---------------------------------------------------------------------------

OWNERS_YAML = """\
version: "1"
profiles:
  oss:
    git: {user.name: Alice, user.email: alice@example.com}
    gh:
      account: alice-oss
      owners: [alice-oss, Alice-Org]
    paths: []
  work:
    git: {user.name: Alice, user.email: alice@company.example}
    gh:
      account: alice-work
    paths: []
"""


def test_owners_parsed_and_default_empty(write_config):
    from gospelo_github_identity.config import load_config

    config = load_config(write_config(OWNERS_YAML))
    assert config.profiles["oss"].gh_owners == ["alice-oss", "Alice-Org"]
    assert config.profiles["work"].gh_owners == []


def test_owners_declared_and_reverse_lookup(write_config):
    from gospelo_github_identity.config import load_config

    config = load_config(write_config(OWNERS_YAML))
    assert config.owners_declared() is True
    assert config.profile_for_owner("alice-oss").name == "oss"
    # Case-insensitive, mirroring GitHub login semantics.
    assert config.profile_for_owner("ALICE-ORG").name == "oss"
    assert config.profile_for_owner("stranger") is None


def test_owners_declared_false_without_any(write_config):
    from gospelo_github_identity.config import load_config

    yaml_text = OWNERS_YAML.replace("      owners: [alice-oss, Alice-Org]\n", "")
    config = load_config(write_config(yaml_text))
    assert config.owners_declared() is False


def test_owners_must_be_a_list(write_config):
    from gospelo_github_identity.config import ConfigError, load_config

    bad = OWNERS_YAML.replace(
        "owners: [alice-oss, Alice-Org]", "owners: alice-oss"
    )
    with pytest.raises(ConfigError, match="'gh.owners' must be a list"):
        load_config(write_config(bad))


def test_owners_entries_must_be_nonempty_strings(write_config):
    from gospelo_github_identity.config import ConfigError, load_config

    bad = OWNERS_YAML.replace(
        "owners: [alice-oss, Alice-Org]", "owners: [alice-oss, '']"
    )
    with pytest.raises(ConfigError, match="non-empty strings"):
        load_config(write_config(bad))


def test_duplicate_owner_across_profiles_rejected(write_config):
    from gospelo_github_identity.config import ConfigError, load_config

    bad = OWNERS_YAML.replace(
        "      account: alice-work\n",
        "      account: alice-work\n      owners: [ALICE-OSS]\n",
    )
    with pytest.raises(ConfigError, match="only one profile"):
        load_config(write_config(bad))
