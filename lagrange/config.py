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

import contextlib
import json
import os
from typing import Any

DATA_DIR = os.path.join(os.path.expanduser("~"), ".lagrange")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
UI_FILE = os.path.join(DATA_DIR, "ui.json")
DISCOVERY_CACHE = os.path.join(DATA_DIR, "discovered.json")
# Last switch_to() call, with whoever made it — several independent tools
# (Vecna, pnews, a person at the widget) share the one credential slot, and
# this is how any of them can tell who else has touched it and when.
USAGE_FILE = os.path.join(DATA_DIR, "usage.json")

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

    # Account order. Emails (lower-case) in the order Lagrange prefers them, best
    # first. Drives both the list order in the widget and which account auto-switch
    # reaches for next. Accounts not listed here sort after the listed ones, by
    # email. Left empty in the public build — a personal order lives in the user's
    # ~/.lagrange/config.json, never in the repo.
    "account_priority": [],

    # Auto-switch. When the loaded account's 5-hour window crosses this much *used*
    # quota, Lagrange loads the next account in `account_priority` that still has
    # headroom — so a session never drains an account to 100% and always leaves a
    # slice for small tasks. Off by default; a switch still only lands when agy
    # next starts (same in-place restart as a manual switch).
    "auto_switch": False,
    "auto_switch_used_fraction": 0.85,
    "auto_switch_window": "5h",

    # Which accounts auto-switch is allowed to touch. Empty means "all of them",
    # which is the right default for a single user at one console. Set it when
    # other tools on the machine drive `agy` on their own schedule and manage
    # their own accounts: Antigravity has exactly one credential slot per
    # machine, so an unrestricted auto-switch will happily move the credential
    # onto an account another tool is mid-way through using — or off the one the
    # person at the keyboard is working on. Listing only the accounts reserved
    # for interactive use keeps the widget out of the others' way.
    "auto_switch_pool": [],

    # Token ledger. Google reports quota only as a remaining fraction, so the
    # tokens themselves are read out of Antigravity's own conversation files and
    # attributed to whichever account was loaded at the time. Empty
    # `conversations_dir` means "find it" — the usual place is
    # ~/.gemini/antigravity-cli/conversations. History older than
    # `token_history_days` is dropped on the next sync; 0 keeps everything.
    "track_tokens": True,
    "conversations_dir": "",
    "token_history_days": 90,

    # UI. Empty language follows the system locale, falling back to English.
    "language": "",

    # Visual effects: the breathing star field behind the title, the scan sweep
    # across it, and the pulse of the horizon line when fresh figures land.
    # False leaves the same layout drawn flat and completely still — the widget
    # then repaints only when its numbers change.
    "effects": True,
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
    """Atomic write.

    The temporary name carries the pid: several processes now write here (the
    widget, plus any tool that switches accounts on its own), and a shared
    `.tmp` name means two of them interleave into one file and the reader gets
    a broken half-and-half JSON.
    """
    ensure_data_dir()
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
