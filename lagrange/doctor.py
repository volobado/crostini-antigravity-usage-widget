"""
Diagnostics.

`lagrange doctor` checks every assumption Lagrange makes about Antigravity, one
at a time, and says which one broke. When Google changes something the report
points straight at the layer that moved, so an issue arrives already diagnosed.

Output is safe to paste in public: no token, secret or client id is printed.
"""

from __future__ import annotations

import json
import platform
import sys
import urllib.error
from datetime import datetime, timezone

from . import VERIFIED_AGY_VERSION, __version__, accounts, api, config, discovery

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARKS = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}

# Settings that say nothing about compatibility — how the widget looks and what
# it can launch, rather than what it assumes about Antigravity.
PREFERENCE_KEYS = {"language", "launchers", "refresh_seconds", "request_timeout",
                   "account_priority", "auto_switch", "auto_switch_used_fraction",
                   "auto_switch_window", "auto_switch_pool",
                   "track_tokens", "token_history_days"}


class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.checks.append({"status": status, "name": name, "detail": detail})

    @property
    def worst(self) -> str:
        for level in (FAIL, WARN):
            if any(c["status"] == level for c in self.checks):
                return level
        return OK

    def render(self) -> str:
        lines = []
        for check in self.checks:
            line = f"{_MARKS[check['status']]} {check['name']}"
            if check["detail"]:
                line += f"\n        {check['detail']}"
            lines.append(line)
        return "\n".join(lines)


def _fingerprint(value: str, keep: int = 4) -> str:
    """Enough of a secret to compare two reports, not enough to use one."""
    if not value:
        return "(empty)"
    return f"…{value[-keep:]} (len {len(value)})"


def run(deep: bool = True) -> Report:
    report = Report()

    report.add(OK, "environment",
               f"Lagrange {__version__} · Python {sys.version.split()[0]} · "
               f"{platform.system()} {platform.release()}")

    if sys.platform != "win32":
        report.add(FAIL, "platform",
                   "Lagrange needs Windows: Antigravity stores its token in "
                   "Windows Credential Manager")
        return report

    # ── Antigravity binary ──────────────────────────────────────────────────
    agy_path = discovery.find_agy()
    if not agy_path:
        report.add(FAIL, "agy.exe", "not found — set agy_path in ~/.lagrange/config.json")
    else:
        version = discovery.agy_version(agy_path) or "unknown"
        status = OK if version == VERIFIED_AGY_VERSION else WARN
        note = "" if status == OK else f" (verified against {VERIFIED_AGY_VERSION})"
        report.add(status, "agy.exe", f"{agy_path}\n        version {version}{note}")

    # ── credential entry ────────────────────────────────────────────────────
    configured = config.get("agy_cred_target")
    target = discovery.find_agy_cred_target()
    if not target:
        report.add(FAIL, "credential entry",
                   f"no Credential Manager entry with Antigravity's token shape "
                   f"(looked for '{configured}'). Is Antigravity signed in?")
    elif target != configured:
        report.add(WARN, "credential entry",
                   f"found '{target}', expected '{configured}' — Antigravity "
                   f"renamed it; Lagrange adapted. Please open an issue.")
    else:
        report.add(OK, "credential entry", target)

    live = accounts.read_live_cred()
    if live is None:
        report.add(WARN, "live token", "Antigravity is not signed in")
    else:
        token = live.get("token", {})
        missing = [k for k in ("access_token", "refresh_token", "expiry") if k not in token]
        if missing:
            report.add(FAIL, "live token", f"blob is missing {', '.join(missing)}")
        else:
            expiry = api.cred_expiry(live)
            fresh = "fresh" if api.cred_is_fresh(live) else "expired (will refresh)"
            report.add(OK, "live token",
                       f"{fresh}, expires {expiry.astimezone().isoformat(timespec='seconds')}")

    # ── OAuth client credentials ────────────────────────────────────────────
    probe = discovery.probe_binary()
    ids, secrets_found = probe.get("client_ids") or [], probe.get("client_secrets") or []
    if agy_path and not (ids and secrets_found):
        report.add(FAIL, "oauth client",
                   "could not read client credentials from agy.exe — Antigravity "
                   "may have obfuscated them. Set client_id/client_secret in "
                   "~/.lagrange/config.json")
    else:
        report.add(OK, "oauth client",
                   f"{len(ids)} client id(s), {len(secrets_found)} secret(s) in binary")

    if deep:
        try:
            client_id, client_secret = accounts._client()
            report.add(OK, "oauth client validated",
                       f"id {_fingerprint(client_id, 8)} · secret {_fingerprint(client_secret)}")
        except (RuntimeError, api.ApiError) as exc:
            report.add(FAIL, "oauth client validated", str(exc)[:200])

    # ── quota endpoint ──────────────────────────────────────────────────────
    hosts = probe.get("quota_hosts") or []
    methods = probe.get("quota_methods") or []
    configured_method = config.get("quota_summary_method")
    if methods and configured_method not in methods:
        report.add(WARN, "quota endpoint",
                   f"binary offers {methods}, config uses '{configured_method}' — "
                   f"the API may have been renamed")
    else:
        report.add(OK, "quota endpoint",
                   f"{config.get('quota_host')}/{configured_method}"
                   + (f"\n        binary also references: {', '.join(hosts)}" if hosts else ""))

    # ── accounts and a live call ────────────────────────────────────────────
    index = accounts.load_index()
    account_list = index.get("accounts", [])
    active = accounts.active_email()
    report.add(OK if account_list else WARN, "accounts",
               f"{len(account_list)} stored, active: {active or 'none'}")

    if deep:
        for account in account_list:
            email = account["email"]
            masked = _mask_email(email)
            try:
                token = accounts.valid_access_token(email)
                summary = api.fetch_quota_summary(token)
                groups = api.normalize_summary(summary)
                if not groups:
                    report.add(WARN, f"quota · {masked}",
                               f"response had no groups; top-level keys: "
                               f"{sorted(summary.keys())}")
                    continue
                shape = ", ".join(
                    f"{g['full_name'] or g['name']}[{'/'.join(b['window'] for b in g['buckets'])}]"
                    for g in groups)
                worst = min((b["remaining"] for g in groups for b in g["buckets"]
                             if b["remaining"] is not None), default=None)
                left = "n/a" if worst is None else f"{worst * 100:.0f}% lowest bucket"
                report.add(OK, f"quota · {masked}", f"{left}\n        shape: {shape}")
            except api.NeedsReauth:
                report.add(WARN, f"quota · {masked}", "refresh token rejected — sign in again")
            except api.TransientError as exc:
                # Not a broken install: the request never got an answer. Usually
                # TLS interception (antivirus, VPN, corporate proxy) or a flaky link.
                report.add(WARN, f"quota · {masked}",
                           f"{exc}\n        retried {api.RETRY_ATTEMPTS}x — network or "
                           f"TLS interference (VPN, antivirus, proxy)")
            except (accounts.AccountError, api.ApiError, urllib.error.URLError,
                    OSError, RuntimeError) as exc:
                report.add(FAIL, f"quota · {masked}", str(exc)[:200])

    # ── token ledger ────────────────────────────────────────────────────────
    _check_ledger(report)

    # ── overrides in effect ─────────────────────────────────────────────────
    overrides = config.read_json(config.CONFIG_FILE, {})
    if not overrides:
        report.add(OK, "config overrides", "none (all defaults)")
        return report

    redacted = {k: ("(set)" if "secret" in k or k == "client_id" else v)
                for k, v in overrides.items()}
    # Preferences are nobody's business; a pinned endpoint or credential means
    # this install is patched around an upstream change and should go back to
    # tracking defaults once a release covers it.
    patched = sorted(set(redacted) - PREFERENCE_KEYS)
    if patched:
        report.add(WARN, "config overrides",
                   f"compatibility patches in effect: {', '.join(patched)}\n"
                   f"        {json.dumps(redacted, ensure_ascii=False)}")
    else:
        report.add(OK, "config overrides",
                   f"preferences only: {', '.join(sorted(redacted))}")

    return report


def _check_ledger(report: Report) -> None:
    """
    Can the token figures be read at all, and do they cover anything yet?

    Reported as a warning at worst: the ledger is an extra. The check exists
    because its two ways of going quiet — Antigravity moving its conversation
    directory, and a timeline that has not seen a switch yet — both look
    identical from the widget, where the numbers simply read zero.
    """
    from . import agylog, tokens

    if not tokens.enabled():
        report.add(OK, "token ledger", "off (track_tokens is false)")
        return

    directory = agylog.conversations_dir()
    if not directory:
        report.add(WARN, "token ledger",
                   "Antigravity's conversations directory not found — token "
                   "figures will read zero. Set conversations_dir in "
                   "~/.lagrange/config.json")
        return

    files = agylog.conversation_files(directory)
    since = tokens.tracking_since()
    totals = tokens.totals()
    detail = (f"{directory}\n        {len(files)} conversation file(s) · "
              f"{totals['turns']} turn(s) recorded · "
              f"↑ {tokens.human(totals['sent'])} ↓ {tokens.human(totals['received'])}")
    if since:
        detail += f"\n        attributed since {since.astimezone():%Y-%m-%d %H:%M}"
    status = OK if files else WARN
    report.add(status, "token ledger", detail)


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if len(name) <= 2:
        return f"{name[:1]}***@{domain}"
    return f"{name[:2]}***{name[-1]}@{domain}"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    as_json = "--json" in argv
    quick = "--quick" in argv

    report = run(deep=not quick)

    if as_json:
        print(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lagrange": __version__,
            "verdict": report.worst,
            "checks": report.checks,
        }, ensure_ascii=False, indent=2))
    else:
        print("Lagrange doctor")
        print("=" * 60)
        print(report.render())
        print("=" * 60)
        verdict = {
            OK: "All checks passed.",
            WARN: "Working, but something drifted from what this release expects.",
            FAIL: "Something is broken — details above.",
        }[report.worst]
        print(verdict)
        if report.worst != OK:
            print("Paste this report into an issue: "
                  "https://github.com/Vovka666/lagrange/issues/new/choose")
    return 0 if report.worst != FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
