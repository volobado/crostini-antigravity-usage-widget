"""
Self-healing discovery of everything Antigravity might rename.

Nothing about Antigravity's internals is a public contract, so Lagrange never
assumes: it locates the binary, lifts the OAuth client credentials out of it,
confirms which Credential Manager entry holds the live token, and reads the
quota endpoint names from the same binary. Results are cached per Antigravity
build and re-derived automatically the moment `agy` updates.

That is also why the repository ships no Google client secret: the credentials
come from the copy of Antigravity already installed on the user's machine.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable

from . import config, credstore

# ─── where Antigravity tends to live ────────────────────────────────────────

_AGY_CANDIDATES = [
    r"%LOCALAPPDATA%\agy\bin\agy.exe",
    r"%LOCALAPPDATA%\Programs\agy\bin\agy.exe",
    r"%USERPROFILE%\.agy\bin\agy.exe",
    r"%LOCALAPPDATA%\antigravity\bin\agy.exe",
]

# ─── patterns lifted from the binary ────────────────────────────────────────

_RE_CLIENT_ID = re.compile(r"[0-9]{6,}-[a-z0-9]{16,}\.apps\.googleusercontent\.com")
_RE_CLIENT_SECRET = re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,40}")
_RE_QUOTA_HOST = re.compile(r"[a-z0-9-]*cloudcode-pa\.googleapis\.com")
_RE_QUOTA_METHOD = re.compile(r"v1internal:retrieveUserQuota[A-Za-z]*")

_CHUNK = 8 * 1024 * 1024
_OVERLAP = 512


def find_agy() -> str | None:
    """Path to agy.exe, honouring an explicit `agy_path` override."""
    override = config.get("agy_path")
    if override and os.path.exists(override):
        return override
    for template in _AGY_CANDIDATES:
        path = os.path.expandvars(template)
        if os.path.exists(path):
            return path
    return shutil.which("agy.exe") or shutil.which("agy")


def agy_version(path: str | None = None) -> str | None:
    path = path or find_agy()
    if not path:
        return None
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True,
                             timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout or out.stderr).strip().splitlines()[0].strip() or None


def _signature(path: str) -> str:
    stat = os.stat(path)
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def scan_binary(path: str, patterns: Iterable[re.Pattern]) -> dict[str, list[str]]:
    """
    Collect every match for each pattern, streaming the file in chunks.

    Antigravity is a ~175 MB Go binary; reading it whole would spike memory for
    no reason. Consecutive chunks overlap so matches on a boundary survive.
    """
    found: dict[str, list[str]] = {p.pattern: [] for p in patterns}
    seen: dict[str, set[str]] = {p.pattern: set() for p in patterns}
    tail = ""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            text = tail + chunk.decode("latin-1")
            for pattern in patterns:
                for match in pattern.findall(text):
                    if match not in seen[pattern.pattern]:
                        seen[pattern.pattern].add(match)
                        found[pattern.pattern].append(match)
            tail = text[-_OVERLAP:]
    return found


def _load_cache(signature: str) -> dict | None:
    cached = config.read_json(config.DISCOVERY_CACHE, None)
    if isinstance(cached, dict) and cached.get("signature") == signature:
        return cached
    return None


def probe_binary(force: bool = False) -> dict:
    """
    Everything readable from agy.exe, cached until the binary changes.

    Returns keys: signature, path, version, client_ids, client_secrets,
    quota_hosts, quota_methods.
    """
    path = find_agy()
    if not path:
        return {"path": None, "error": "agy.exe not found"}

    signature = _signature(path)
    if not force:
        cached = _load_cache(signature)
        if cached:
            return cached

    matches = scan_binary(path, [_RE_CLIENT_ID, _RE_CLIENT_SECRET,
                                 _RE_QUOTA_HOST, _RE_QUOTA_METHOD])
    result = {
        "signature": signature,
        "path": path,
        "version": agy_version(path),
        "client_ids": matches[_RE_CLIENT_ID.pattern],
        # Go packs adjacent string constants together, so a match can carry the
        # next literal glued to its tail. Secrets are a fixed 35 characters.
        "client_secrets": sorted({s[:35] for s in matches[_RE_CLIENT_SECRET.pattern]}),
        "quota_hosts": matches[_RE_QUOTA_HOST.pattern],
        "quota_methods": matches[_RE_QUOTA_METHOD.pattern],
    }
    config.write_json(config.DISCOVERY_CACHE, result)
    return result


# ─── OAuth client credentials ───────────────────────────────────────────────

def client_credentials(validator=None, force: bool = False) -> tuple[str, str]:
    """
    The (client_id, client_secret) pair Antigravity authenticates with.

    Order of preference: explicit config override, previously validated pair,
    then every combination found in the binary — each tried against `validator`
    until one is accepted. `validator(client_id, client_secret) -> bool` is
    normally a token refresh, which is the only way to tell a live pair from a
    stale constant left in the binary.
    """
    cfg = config.load()
    if cfg["client_id"] and cfg["client_secret"]:
        return cfg["client_id"], cfg["client_secret"]

    cached = config.read_json(config.DISCOVERY_CACHE, {}) or {}
    if not force:
        pair = cached.get("validated_client")
        if pair:
            return pair["client_id"], pair["client_secret"]

    probe = probe_binary(force=force)
    ids = probe.get("client_ids") or []
    secrets = probe.get("client_secrets") or []
    if not ids or not secrets:
        raise RuntimeError(
            "could not read OAuth client credentials out of agy.exe — "
            "set client_id and client_secret in ~/.lagrange/config.json"
        )

    if validator is None:
        return ids[0], secrets[0]

    for client_id in ids:
        for secret in secrets:
            if validator(client_id, secret):
                cached = config.read_json(config.DISCOVERY_CACHE, {}) or {}
                cached["validated_client"] = {"client_id": client_id,
                                              "client_secret": secret}
                config.write_json(config.DISCOVERY_CACHE, cached)
                return client_id, secret

    raise RuntimeError(
        "no OAuth client credentials from agy.exe were accepted by Google — "
        f"tried {len(ids)}x{len(secrets)} combinations; run `lagrange doctor`"
    )


def forget_validated_client() -> None:
    cached = config.read_json(config.DISCOVERY_CACHE, {}) or {}
    cached.pop("validated_client", None)
    config.write_json(config.DISCOVERY_CACHE, cached)


# ─── the live credential entry ──────────────────────────────────────────────

def _looks_like_agy_token(blob: bytes | None) -> bool:
    if not blob:
        return False
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    token = data.get("token")
    return isinstance(token, dict) and "refresh_token" in token


def find_agy_cred_target() -> str | None:
    """
    Which Credential Manager entry Antigravity is actually using.

    Tries the configured name first, then sweeps the vault for an entry whose
    blob has Antigravity's token shape. A rename upstream costs one slow
    startup instead of breaking the tool.
    """
    configured = config.get("agy_cred_target")
    if _looks_like_agy_token(credstore.read(configured)):
        return configured

    try:
        targets = credstore.enumerate_targets()
    except credstore.CredentialError:
        return None

    def rank(name: str) -> int:
        low = name.lower()
        return (0 if "antigravity" in low else 1, 0 if "gemini" in low else 1)

    for target in sorted((t for t in targets if t), key=rank):
        low = target.lower()
        if "gemini" not in low and "antigravity" not in low and "agy" not in low:
            continue
        if _looks_like_agy_token(credstore.read(target)):
            return target
    return None


def resolve_quota_host() -> str:
    """Prefer the production host the binary references; fall back to config."""
    configured = config.get("quota_host")
    hosts = (probe_binary().get("quota_hosts") or [])
    if configured in hosts or not hosts:
        return configured
    for host in hosts:
        if not host.startswith("daily-"):  # `daily-` is Google's staging ring
            return host
    return hosts[0]
