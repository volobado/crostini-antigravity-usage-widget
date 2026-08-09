"""
Paths, defaults and user overrides.

Every value Antigravity could plausibly rename lives here and can be overridden
in `~/.lagrange/config.json` without touching code. That file is the escape
hatch: when Google changes something, a one-line override keeps people running
while a proper release is prepared.

Example `~/.lagrange/config.json`:

    {
      "quota_host": "cloudcode-pa.googleapis.com",
      "agy_cred_target": "gemini:antigravity",
      "refresh_seconds": 90
    }
"""

from __future__ import annotations

import json
import os
from typing import Any

DATA_DIR = os.path.join(os.path.expanduser("~"), ".lagrange")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
UI_FILE = os.path.join(DATA_DIR, "ui.json")
DISCOVERY_CACHE = os.path.join(DATA_DIR, "discovered.json")

# Credential Manager entry Antigravity itself reads at startup.
DEFAULT_AGY_CRED_TARGET = "gemini:antigravity"
DEFAULT_AGY_CRED_USER = "antigravity"

# Where Lagrange keeps its own copy of each account.
CRED_PREFIX = "lagrange:"

# Legacy prefixes migrated on first run.
LEGACY_CRED_PREFIXES = ("agy-widget:",)
LEGACY_DATA_DIRS = (os.path.join(os.path.expanduser("~"), ".agy-widget"),)

DEFAULTS: dict[str, Any] = {
    # Backend. `daily-` is the staging host some builds talk to; both answer.
    "quota_host": "cloudcode-pa.googleapis.com",
    "quota_summary_method": "v1internal:retrieveUserQuotaSummary",
    "quota_detail_method": "v1internal:retrieveUserQuota",
    "agy_cred_target": DEFAULT_AGY_CRED_TARGET,
    "agy_cred_user": DEFAULT_AGY_CRED_USER,

    # OAuth. Left empty on purpose: Lagrange lifts the client credentials out of
    # the Antigravity binary already installed on the machine rather than
    # shipping Google's own client secret in a public repository.
    "client_id": "",
    "client_secret": "",

    "user_agent": "antigravity-cli/1.1.11",
    "refresh_seconds": 60,
    "request_timeout": 30,
    "agy_path": "",

    # UI. Empty language follows the system locale, falling back to English.
    "language": "",
    # Buttons offered after switching, so `agy` can be restarted in place:
    # [{"label": "Standard", "path": "C:\\...\\agy_standard.bat"}]
    "launchers": [],
}

_cache: dict[str, Any] | None = None


def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load() -> dict[str, Any]:
    """Defaults merged with the user's overrides. Cached for the process."""
    global _cache
    if _cache is not None:
        return _cache
    values = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            values.update(json.load(fh))
    except (OSError, json.JSONDecodeError):
        pass
    _cache = values
    return values


def get(key: str) -> Any:
    return load()[key]


def set_values(**pairs: Any) -> None:
    """Persist overrides into `~/.lagrange/config.json`."""
    ensure_data_dir()
    current: dict[str, Any] = {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            current = json.load(fh)
    except (OSError, json.JSONDecodeError):
        pass
    current.update(pairs)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    global _cache
    _cache = None


def quota_url(detail: bool = False) -> str:
    cfg = load()
    method = cfg["quota_detail_method"] if detail else cfg["quota_summary_method"]
    return f"https://{cfg['quota_host']}/{method}"


def read_json(path: str, fallback: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: str, payload: Any) -> None:
    ensure_data_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
