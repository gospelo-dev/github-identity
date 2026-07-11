# gospelo-github-identity - Directory-aware git/gh CLI identity guard
# Copyright (c) 2026 NoStudio LLC. All rights reserved.
# Licensed under the MIT License. See LICENSE.md for details.

"""Thin wrappers around ``git`` and ``gh`` CLI subprocess calls.

These helpers keep the actual command construction in one place so the rest
of the package can stay focused on logic. Errors are surfaced as
``ExternalToolError`` for the CLI to translate into exit code 2.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ExternalToolError(Exception):
    """Raised when an external tool is missing or returns a fatal error."""


@dataclass
class CommandResult:
    """Captured result of a subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise ExternalToolError(
            f"Required external tool not found on PATH: {tool!r}"
        )


def _run(args: list[str], cwd: Path | None = None) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExternalToolError(
            f"Failed to invoke {' '.join(args)}: {exc}"
        ) from exc
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


# ---- git -------------------------------------------------------------------


def git_get_config(
    key: str, cwd: Path | None = None, *, scope: str | None = None
) -> str | None:
    """Return ``git config <key>`` for the given cwd, or ``None`` if unset.

    ``scope`` restricts the read to a single config level (``local`` /
    ``global`` / ``system``); the default (``None``) reads the effective
    value across all levels. A key that is unset at the requested scope
    returns ``None`` (exit 1), which is not an error.
    """
    _require("git")
    args = ["git", "config"]
    if scope is not None:
        if scope not in ("local", "global", "system"):
            raise ValueError(f"invalid scope: {scope!r}")
        args.append(f"--{scope}")
    args += ["--get", key]
    result = _run(args, cwd=cwd)
    if result.returncode == 0:
        return result.stdout or None
    if result.returncode == 1:
        # `git config --get` exits 1 when the key is not set; not an error.
        return None
    raise ExternalToolError(
        f"{' '.join(args)} failed (exit {result.returncode}): "
        f"{result.stderr or result.stdout}"
    )


def git_set_config(
    key: str, value: str, *, scope: str = "local", cwd: Path | None = None
) -> None:
    """Set ``git config <key> <value>``.

    ``scope`` is one of ``local``, ``global``, ``system``.
    """
    _require("git")
    if scope not in ("local", "global", "system"):
        raise ValueError(f"invalid scope: {scope!r}")
    args = ["git", "config", f"--{scope}", key, value]
    result = _run(args, cwd=cwd)
    if result.returncode != 0:
        raise ExternalToolError(
            f"{' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr or result.stdout}"
        )


def git_inside_work_tree(cwd: Path | None = None) -> bool:
    """Return True if ``cwd`` is inside a git working tree."""
    _require("git")
    result = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd)
    return result.returncode == 0 and result.stdout == "true"


def git_toplevel(cwd: Path | None = None) -> Path | None:
    """Return the working-tree root containing ``cwd``, or ``None`` if none."""
    _require("git")
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if result.returncode == 0 and result.stdout:
        return Path(result.stdout)
    return None


def git_remote_url(remote: str = "origin", cwd: Path | None = None) -> str | None:
    """Return the push URL of ``remote`` for the repo at ``cwd``.

    Returns ``None`` when the remote does not exist or ``cwd`` is not a git
    repository -- both are ordinary "no SSH target to test" situations for the
    caller, not errors.
    """
    _require("git")
    result = _run(["git", "remote", "get-url", remote], cwd=cwd)
    if result.returncode == 0:
        return result.stdout or None
    return None


# ---- ssh -------------------------------------------------------------------


def ssh_target_from_remote(url: str) -> str | None:
    """Extract the ``[user@]host`` to probe from a git remote URL.

    Returns ``None`` for non-SSH remotes (``https://``, ``git://``, plain
    local paths) -- SSH keys are not used to push those, so there is nothing
    to verify. An SSH-alias host (e.g. ``git@github.com-work:org/repo.git``)
    is preserved verbatim so the probe reproduces exactly what ``git push``
    would resolve.
    """
    url = url.strip()
    if not url:
        return None

    if url.startswith("ssh://"):
        authority = url[len("ssh://"):].split("/", 1)[0]
        if "@" in authority:
            user, hostport = authority.split("@", 1)
            host = hostport.rsplit(":", 1)[0] if ":" in hostport else hostport
            return f"{user}@{host}" if host else None
        host = authority.rsplit(":", 1)[0] if ":" in authority else authority
        return host or None

    if "://" in url:
        # http(s)://, git://, ftp:// ... -- not SSH.
        return None

    # scp-like syntax: ``[user@]host:path``.
    if ":" in url:
        target = url.split(":", 1)[0]
        return target or None

    return None


def ssh_probe_login(target: str, *, connect_timeout: int = 6) -> tuple[str | None, str]:
    """Probe which GitHub login ``ssh -T <target>`` authenticates as.

    Returns ``(login, detail)``. ``login`` is parsed from GitHub's
    ``Hi <login>! You've successfully authenticated`` banner, or ``None`` when
    authentication failed / the host was unreachable / the banner did not
    match. ``detail`` is the combined stdout+stderr for surfacing to the user.

    ``ssh -T git@github.com`` deliberately exits non-zero (GitHub grants no
    shell), so the return code is ignored and the banner text is authoritative.
    ``BatchMode=yes`` prevents any interactive passphrase / host-key prompt so
    the probe never blocks.
    """
    _require("ssh")
    result = _run(
        [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={connect_timeout}",
            target,
        ]
    )
    detail = "\n".join(p for p in (result.stdout, result.stderr) if p).strip()
    match = re.search(
        r"Hi ([^!]+)! You've successfully authenticated", detail
    )
    login = match.group(1).strip() if match else None
    return login, detail


@dataclass
class SshHostConfig:
    """The resolved ``ssh -G <host>`` settings relevant to identity pinning."""

    hostname: str | None
    user: str | None
    identity_file: str | None
    identities_only: bool


def ssh_resolve(host: str) -> SshHostConfig:
    """Return the effective ssh config for ``host`` via ``ssh -G``.

    This is config resolution only -- no network connection is made -- so it is
    safe and fast for auditing whether an SSH-alias host pins a single key
    (``IdentitiesOnly yes`` + a concrete ``IdentityFile``). Only the first
    ``identityfile`` line is reported.
    """
    _require("ssh")
    result = _run(["ssh", "-G", host])
    hostname: str | None = None
    user: str | None = None
    identity_file: str | None = None
    identities_only = False
    for line in result.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts[0].lower(), parts[1].strip()
        if key == "hostname" and hostname is None:
            hostname = value
        elif key == "user" and user is None:
            user = value
        elif key == "identityfile" and identity_file is None:
            identity_file = value
        elif key == "identitiesonly":
            identities_only = value.lower() == "yes"
    return SshHostConfig(
        hostname=hostname,
        user=user,
        identity_file=identity_file,
        identities_only=identities_only,
    )


# ---- gh --------------------------------------------------------------------


def gh_active_login() -> str | None:
    """Return the login name of the currently active gh CLI account.

    Returns ``None`` if gh CLI is not authenticated.
    """
    _require("gh")
    result = _run(["gh", "api", "user", "--jq", ".login"])
    if result.returncode == 0 and result.stdout:
        return result.stdout
    return None


def gh_logged_in_accounts() -> list[str]:
    """Return all gh CLI accounts the user is currently authenticated as."""
    _require("gh")
    result = _run(["gh", "auth", "status"])
    # gh auth status prints to stderr regardless of result.
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    accounts: list[str] = []
    for line in text.splitlines():
        # Looking for: "  - Logged in to github.com account <login> (...)"
        marker = "Logged in to github.com account "
        idx = line.find(marker)
        if idx >= 0:
            tail = line[idx + len(marker):].strip()
            login = tail.split()[0] if tail else ""
            if login:
                accounts.append(login)
    return accounts


def gh_switch_account(account: str) -> None:
    """Run ``gh auth switch -u <account>``."""
    _require("gh")
    args = ["gh", "auth", "switch", "-u", account]
    result = _run(args)
    if result.returncode != 0:
        raise ExternalToolError(
            f"{' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr or result.stdout}\n"
            f"Hint: run `gh auth login --hostname github.com` "
            f"to add the account first."
        )


def gh_account_available(login: str) -> bool:
    """Return True if ``gh`` holds a usable credential for ``login``.

    Uses ``gh auth token --user <login>`` (which prints the stored token for
    that specific account without changing the active one). A non-zero exit or
    empty output means the account is not logged in, so ``switch`` / direnv
    ``GH_TOKEN`` automation cannot act as it. The token itself is discarded.
    """
    _require("gh")
    result = _run(["gh", "auth", "token", "--user", login])
    return result.returncode == 0 and bool(result.stdout)
