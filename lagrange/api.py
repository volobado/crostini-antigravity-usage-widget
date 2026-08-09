"""
Google endpoints Lagrange talks to.

The quota call is the same one Antigravity uses to draw its own indicator, so
the numbers here are Google's numbers — not an estimate reconstructed from log
lines. Quotas come as fractions remaining across two model groups, each with a
five-hour and a weekly window.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = " ".join([
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
])


class ApiError(Exception):
    pass


class NeedsReauth(ApiError):
    """The refresh token no longer works — the account must sign in again."""


def _headers(access_token: str | None = None) -> dict[str, str]:
    headers = {"User-Agent": config.get("user_agent")}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def post_json(url: str, body: dict, access_token: str) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={**_headers(access_token), "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=config.get("request_timeout")) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_form(url: str, form: dict) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode("utf-8"),
                                     method="POST", headers=_headers())
    with urllib.request.urlopen(request, timeout=config.get("request_timeout")) as resp:
        return json.loads(resp.read().decode("utf-8"))


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    try:
        return post_form(TOKEN_URL, {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        if exc.code in (400, 401):
            raise NeedsReauth(detail) from exc
        raise ApiError(f"token refresh failed: {exc.code} {detail}") from exc


def exchange_code(code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict:
    return post_form(TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })


def authorization_url(redirect_uri: str, state: str, client_id: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent select_account",
        "state": state,
    })


def fetch_userinfo(access_token: str) -> dict:
    request = urllib.request.Request(USERINFO_URL, headers=_headers(access_token))
    with urllib.request.urlopen(request, timeout=config.get("request_timeout")) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_quota_summary(access_token: str, host: str | None = None) -> dict:
    url = config.quota_url()
    if host:
        url = url.replace(config.get("quota_host"), host)
    return post_json(url, {}, access_token)


def fetch_quota_detail(access_token: str) -> dict:
    """Per-model breakdown. Not shown in the widget; handy when diagnosing."""
    return post_json(config.quota_url(detail=True), {}, access_token)


# ─── shaping the response ───────────────────────────────────────────────────

WINDOW_LABELS = {"5h": "5-hour", "weekly": "weekly", "daily": "daily", "monthly": "monthly"}
WINDOW_ORDER = {"5h": 0, "daily": 1, "weekly": 2, "monthly": 3}

# Display names are prose from the backend and have changed before, so they are
# shortened only when recognised and otherwise passed through untouched.
GROUP_LABELS = {
    "Gemini Models": "Gemini",
    "Claude and GPT models": "Claude / GPT",
}


def _parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def normalize_summary(summary: dict) -> list[dict]:
    """
    Flatten the quota response into groups of buckets.

    Deliberately tolerant: unknown windows and unknown group names render as
    themselves, and a response carrying bare `buckets` instead of `groups` is
    wrapped into one anonymous group. New quota dimensions show up in the UI on
    their own instead of crashing it.
    """
    groups_raw = summary.get("groups")
    if groups_raw is None and "buckets" in summary:
        groups_raw = [{"displayName": "", "buckets": summary["buckets"]}]
    groups = []

    for group in groups_raw or []:
        buckets = []
        for bucket in group.get("buckets", []):
            window = bucket.get("window") or bucket.get("tokenType") or ""
            remaining = bucket.get("remainingFraction")
            buckets.append({
                "id": bucket.get("bucketId", ""),
                "window": window,
                "window_label": WINDOW_LABELS.get(window, window or "?"),
                "remaining": float(remaining) if remaining is not None else None,
                "reset": _parse_time(bucket.get("resetTime")),
                "description": bucket.get("description", ""),
            })
        buckets.sort(key=lambda b: WINDOW_ORDER.get(b["window"], 9))
        name = group.get("displayName", "")
        groups.append({
            "name": GROUP_LABELS.get(name, name or "Quota"),
            "full_name": name,
            "models": group.get("description", ""),
            "buckets": buckets,
        })
    return groups


# ─── credential blob format ─────────────────────────────────────────────────

def build_cred(access_token: str, refresh_token: str, expires_in: int,
               auth_method: str = "consumer") -> bytes:
    """Serialise a token the way Antigravity itself stores it."""
    expiry = datetime.now().astimezone() + timedelta(seconds=int(expires_in) - 30)
    return json.dumps({
        "token": {
            "access_token": access_token,
            "token_type": "Bearer",
            "refresh_token": refresh_token,
            "expiry": expiry.isoformat(),
        },
        "auth_method": auth_method,
    }, separators=(",", ":")).encode("utf-8")


def cred_expiry(cred: dict) -> datetime | None:
    raw = cred.get("token", {}).get("expiry")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def cred_is_fresh(cred: dict, margin_seconds: int = 120) -> bool:
    expiry = cred_expiry(cred)
    return bool(expiry and expiry > datetime.now(timezone.utc) + timedelta(seconds=margin_seconds))
