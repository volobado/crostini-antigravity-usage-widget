"""
Handshake between the widget and the `agy` wrapper.

Antigravity reads its credential once, at startup, so a switch only takes effect
on the next launch. Rather than opening a second console — which loses the
window, the scrollback and the conversation — Lagrange asks the wrapper already
running in *that* console to relaunch `agy` in place the moment it exits.

The wrapper announces itself with a session file; Lagrange only raises the
restart flag while at least one such session is alive, so a switch made with no
console open never surprises the next one.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import time

from . import config

SESSIONS_DIR = os.path.join(config.DATA_DIR, "sessions")
RESTART_FLAG = os.path.join(config.DATA_DIR, "restart.flag")

# A console left open for days is normal; one whose session file outlived the
# machine's uptime is not. Sessions older than this are treated as leaked.
STALE_AFTER_SECONDS = 36 * 3600


_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _process_alive(pid: int | None) -> bool:
    """
    Is that wrapper process still there?

    Closing a console with the X button kills the wrapper outright, so its
    session file is never cleaned up. Trusting the file alone would report a
    console that no longer exists as still running an account — which is worse
    than reporting nothing.
    """
    if not pid or pid <= 0:
        return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _read_session(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    # A bare pid is how a pre-1.0 wrapper wrote its file.
    if isinstance(data, int):
        return {"pid": data, "account": None}
    return data if isinstance(data, dict) else None


def _ensure() -> None:
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def prune_stale() -> None:
    """Drop session files whose wrapper is gone, or that outlived any console."""
    _ensure()
    now = time.time()
    try:
        names = os.listdir(SESSIONS_DIR)
    except OSError:
        return
    for name in names:
        path = os.path.join(SESSIONS_DIR, name)
        try:
            data = _read_session(path)
            dead = data is None or not _process_alive(data.get("pid"))
            too_old = now - os.path.getmtime(path) > STALE_AFTER_SECONDS
            if dead or too_old:
                os.remove(path)
        except OSError:
            pass


def live_sessions() -> list[str]:
    """Session files for wrapper-run consoles that are genuinely still open."""
    prune_stale()
    try:
        return [os.path.join(SESSIONS_DIR, n) for n in os.listdir(SESSIONS_DIR)
                if n.endswith(".session")]
    except OSError:
        return []


def has_live_session() -> bool:
    return bool(live_sessions())


def request_restart(email: str) -> bool:
    """
    Ask wrapper-run consoles to relaunch `agy` when the user leaves it.

    Returns False when no wrapper is running, which is the widget's cue to tell
    the user to restart Antigravity themselves.
    """
    if not has_live_session():
        return False
    config.ensure_data_dir()
    with open(RESTART_FLAG, "w", encoding="utf-8") as fh:
        fh.write(email)
    return True


def restart_pending() -> bool:
    return os.path.exists(RESTART_FLAG)


def clear_restart() -> None:
    with contextlib.suppress(OSError):
        os.remove(RESTART_FLAG)


def running_accounts() -> set[str]:
    """
    Accounts the currently open Antigravity sessions actually started under.

    The credential can be swapped at any moment, but a running `agy` keeps the
    account it launched with — so "what is loaded" and "what is running" are
    different questions, and the widget must not answer the second with the
    first.
    """
    running: set[str] = set()
    for path in live_sessions():
        data = _read_session(path)
        email = (data or {}).get("account")
        if email:
            running.add(email.lower())
    return running


# ─── used by the wrapper ────────────────────────────────────────────────────

def open_session(token: str, account: str | None = None) -> str:
    _ensure()
    path = os.path.join(SESSIONS_DIR, f"{token}.session")
    _write(path, account)
    return path


def update_session(token: str, account: str | None) -> None:
    """Record the account the next `agy` run is starting under."""
    _write(os.path.join(SESSIONS_DIR, f"{token}.session"), account)


def _write(path: str, account: str | None) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "account": account, "started": time.time()}, fh)
    except OSError:
        pass


def close_session(token: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(os.path.join(SESSIONS_DIR, f"{token}.session"))


def touch_session(token: str) -> None:
    """Keep a long-lived console from being pruned as stale."""
    with contextlib.suppress(OSError):
        os.utime(os.path.join(SESSIONS_DIR, f"{token}.session"), None)
