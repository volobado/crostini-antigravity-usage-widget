"""
The account store: saving, switching, and reading quota for every account.

Antigravity reads one credential entry at startup. Lagrange keeps a copy of each
signed-in account beside it and swaps the live entry on request. Because every
copy carries its own refresh token, quota for *inactive* accounts can be read
without disturbing the one currently in use — the whole point of the widget.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import secrets
import shutil
import urllib.error
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone

from . import api, config, credstore, discovery


class AccountError(Exception):
    pass


def _slot(email: str) -> str:
    return config.CRED_PREFIX + email.lower()


# ─── index ──────────────────────────────────────────────────────────────────

def load_index() -> dict:
    index = config.read_json(config.ACCOUNTS_FILE, {"accounts": []})
    index.setdefault("accounts", [])
    return index


def save_index(index: dict) -> None:
    config.write_json(config.ACCOUNTS_FILE, index)


def load_ui_state() -> dict:
    return config.read_json(config.UI_FILE, {})


def save_ui_state(state: dict) -> None:
    with contextlib.suppress(OSError):
        config.write_json(config.UI_FILE, state)


# ─── migration from the pre-release layout ──────────────────────────────────

def migrate_legacy() -> int:
    """Adopt accounts saved by an earlier prefix. Returns how many moved."""
    moved = 0
    for legacy_dir in config.LEGACY_DATA_DIRS:
        legacy_index = os.path.join(legacy_dir, "accounts.json")
        if not os.path.exists(legacy_index) or os.path.exists(config.ACCOUNTS_FILE):
            continue
        data = config.read_json(legacy_index, None)
        if not isinstance(data, dict):
            continue
        for account in data.get("accounts", []):
            email = account.get("email")
            if not email:
                continue
            for prefix in config.LEGACY_CRED_PREFIXES:
                blob = credstore.read(prefix + email.lower())
                if blob:
                    credstore.write(_slot(email), blob, username=email)
                    moved += 1
                    break
        if moved:
            save_index(data)
        legacy_ui = os.path.join(legacy_dir, "ui.json")
        if os.path.exists(legacy_ui) and not os.path.exists(config.UI_FILE):
            config.ensure_data_dir()
            shutil.copyfile(legacy_ui, config.UI_FILE)
    return moved


# ─── credentials ────────────────────────────────────────────────────────────

def _agy_target() -> str:
    found = discovery.find_agy_cred_target()
    if found:
        return found
    return config.get("agy_cred_target")


def read_live_cred() -> dict | None:
    """The credential Antigravity is using right now."""
    blob = credstore.read(_agy_target())
    if not blob:
        return None
    try:
        return json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def read_account_cred(email: str) -> dict | None:
    blob = credstore.read(_slot(email))
    if not blob:
        return None
    try:
        return json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def store_account(email: str, blob: bytes, name: str = "", picture: str = "") -> None:
    credstore.write(_slot(email), blob, username=email)
    index = load_index()
    for account in index["accounts"]:
        if account["email"].lower() == email.lower():
            account["name"] = name or account.get("name", "")
            account["picture"] = picture or account.get("picture", "")
            break
    else:
        index["accounts"].append({
            "email": email,
            "name": name,
            "picture": picture,
            "added": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
    save_index(index)


def forget_account(email: str) -> None:
    credstore.delete(_slot(email))
    index = load_index()
    index["accounts"] = [a for a in index["accounts"] if a["email"].lower() != email.lower()]
    save_index(index)


def _client() -> tuple[str, str]:
    """
    Validated OAuth client credentials.

    Validation means "Google accepted a refresh with this pair", which needs a
    refresh token — any stored account will do.
    """
    sample = None
    for account in load_index()["accounts"]:
        cred = read_account_cred(account["email"])
        token = (cred or {}).get("token", {}).get("refresh_token")
        if token:
            sample = token
            break
    if sample is None:
        live = read_live_cred() or {}
        sample = live.get("token", {}).get("refresh_token")

    if sample is None:
        return discovery.client_credentials()

    def validator(client_id: str, client_secret: str) -> bool:
        try:
            api.refresh_access_token(sample, client_id, client_secret)
            return True
        except api.NeedsReauth:
            return False
        except (api.ApiError, urllib.error.URLError, OSError):
            return False

    return discovery.client_credentials(validator=validator)


def active_email() -> str | None:
    """Which stored account is currently loaded into Antigravity."""
    live = read_live_cred()
    live_refresh = (live or {}).get("token", {}).get("refresh_token")
    if not live_refresh:
        return None
    for account in load_index()["accounts"]:
        cred = read_account_cred(account["email"])
        if cred and cred.get("token", {}).get("refresh_token") == live_refresh:
            return account["email"]
    return None


def adopt_live_account() -> str | None:
    """
    Pull whichever account Antigravity is already signed into under management.

    This is what makes first run seamless: the widget starts already knowing the
    account the user has been working with.
    """
    live = read_live_cred()
    if not live:
        return None
    known = active_email()
    if known:
        return known

    token = live.get("token", {})
    access = token.get("access_token", "")
    if not api.cred_is_fresh(live) or not access:
        refresh = token.get("refresh_token")
        if not refresh:
            return None
        client_id, client_secret = _client()
        access = api.refresh_access_token(refresh, client_id, client_secret)["access_token"]

    info = api.fetch_userinfo(access)
    email = info.get("email")
    if not email:
        return None
    blob = json.dumps(live, separators=(",", ":")).encode("utf-8")
    store_account(email, blob, info.get("name", ""), info.get("picture", ""))
    return email


def sync_live_to_store() -> None:
    """Antigravity refreshes its own token; keep our copy in step."""
    email = active_email()
    if not email:
        return
    live = credstore.read(_agy_target())
    if live and live != credstore.read(_slot(email)):
        credstore.write(_slot(email), live, username=email)


def switch_to(email: str) -> None:
    """
    Load an account into Antigravity.

    Takes effect on the next `agy` start — Antigravity reads its credential once
    at launch and does not re-read it.
    """
    blob = credstore.read(_slot(email))
    if not blob:
        raise AccountError(f"no stored credentials for {email}")
    sync_live_to_store()
    credstore.write(_agy_target(), blob, username=config.get("agy_cred_user"))


def valid_access_token(email: str) -> str:
    """A usable access token, refreshing and persisting when it has expired."""
    cred = read_account_cred(email)
    if not cred:
        raise AccountError(f"no stored credentials for {email}")
    if api.cred_is_fresh(cred):
        return cred["token"]["access_token"]

    refresh = cred.get("token", {}).get("refresh_token")
    if not refresh:
        raise api.NeedsReauth(f"{email}: no refresh token stored")

    client_id, client_secret = _client()
    fresh = api.refresh_access_token(refresh, client_id, client_secret)
    blob = api.build_cred(fresh["access_token"], refresh, fresh.get("expires_in", 3600),
                          cred.get("auth_method", "consumer"))
    credstore.write(_slot(email), blob, username=email)

    live = read_live_cred()
    if live and live.get("token", {}).get("refresh_token") == refresh:
        credstore.write(_agy_target(), blob, username=config.get("agy_cred_user"))
    return fresh["access_token"]


# ─── state for the UI ───────────────────────────────────────────────────────

def collect_state() -> dict:
    """
    Every account with its quota, active one first.

    Two different truths are reported, because conflating them is misleading:
    `loaded` is the account written into the credential entry, and `running` is
    what the open Antigravity consoles actually started under. A switch changes
    the first immediately and the second only on restart.
    """
    from . import session

    # Best effort on both: a widget that refuses to draw because one bookkeeping
    # step failed is less useful than one showing slightly stale bars.
    with contextlib.suppress(AccountError, api.ApiError, urllib.error.URLError,
                             OSError, RuntimeError):
        adopt_live_account()
    with contextlib.suppress(AccountError, credstore.CredentialError):
        sync_live_to_store()

    current = active_email()
    running = session.running_accounts()
    tracking = session.has_live_session()
    accounts = []

    for account in load_index()["accounts"]:
        email = account["email"]
        loaded = current is not None and email.lower() == current.lower()
        is_running = email.lower() in running
        entry = {
            "email": email,
            "name": account.get("name", ""),
            "loaded": loaded,
            "running": is_running,
            # Loaded but not yet in use: takes effect when agy restarts.
            "pending": loaded and tracking and not is_running,
            "active": loaded,  # kept for callers that only care about the swap
            "groups": [],
            "error": None,
        }
        try:
            entry["groups"] = api.normalize_summary(
                api.fetch_quota_summary(valid_access_token(email)))
        except api.NeedsReauth:
            entry["error"] = "reauth"
        except (AccountError, api.ApiError, urllib.error.URLError, urllib.error.HTTPError,
                OSError, ValueError, RuntimeError) as exc:
            entry["error"] = str(exc)[:140]
        accounts.append(entry)

    accounts.sort(key=lambda a: (not (a["running"] or a["loaded"]), not a["running"],
                                 a["email"]))
    return {
        "accounts": accounts,
        "active": current,
        "running": sorted(running),
        "tracking": tracking,
        "logged_in": read_live_cred() is not None,
        "fetched_at": datetime.now(timezone.utc),
    }


# ─── adding an account ──────────────────────────────────────────────────────

_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>
<body style="background:#12131a;color:#e6e8f0;font:16px/1.6 system-ui,sans-serif;
             display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center">
  <div style="font-size:44px;color:{color}">{mark}</div>
  <h1 style="font-weight:600;font-size:20px">{title}</h1>
  <p style="color:#8b90a5">{note}</p>
</div></body></html>"""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802 — name fixed by the base class
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        ok = "code" in params and params.get("state", [""])[0] == self.server.expected_state
        if ok:
            _CallbackHandler.result = {"code": params["code"][0]}
            page = _PAGE.format(title="Account added", mark="&#10003;", color="#3ddc84",
                                note="You can close this tab and go back to Lagrange.")
        else:
            _CallbackHandler.result = {"error": params.get("error", ["state mismatch"])[0]}
            page = _PAGE.format(title="Sign-in incomplete", mark="&#10007;", color="#ff5c5c",
                                note="Go back to Lagrange and try again.")
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def add_account(timeout: int = 300) -> dict:
    """
    Sign in through the browser and store the account.

    Leaves the live credential alone, so the account Antigravity is currently
    running under keeps working while a new one is added.
    """
    state = secrets.token_urlsafe(24)
    _CallbackHandler.result = {}
    client_id, client_secret = _client()

    server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    server.expected_state = state
    server.timeout = timeout
    redirect_uri = f"http://localhost:{server.server_address[1]}/callback"

    webbrowser.open(api.authorization_url(redirect_uri, state, client_id))

    deadline = datetime.now() + timedelta(seconds=timeout)
    try:
        while not _CallbackHandler.result and datetime.now() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    result = _CallbackHandler.result
    if not result:
        raise AccountError("sign-in timed out")
    if "error" in result:
        raise AccountError(f"sign-in failed: {result['error']}")

    tokens = api.exchange_code(result["code"], redirect_uri, client_id, client_secret)
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise AccountError("Google returned no refresh token — sign in again and approve access")

    info = api.fetch_userinfo(tokens["access_token"])
    email = info.get("email")
    if not email:
        raise AccountError("could not determine the account email")

    store_account(email, api.build_cred(tokens["access_token"], refresh,
                                        tokens.get("expires_in", 3600)),
                  info.get("name", ""), info.get("picture", ""))
    return {"email": email, "name": info.get("name", ""), "picture": info.get("picture", "")}
