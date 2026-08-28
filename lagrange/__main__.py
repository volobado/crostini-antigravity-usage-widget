"""
Command line entry point.

    lagrange              open the widget
    lagrange run [args]   run Antigravity so it can restart in place on a switch
    lagrange doctor       check every assumption and report what drifted
    lagrange list         accounts and their remaining quota
    lagrange usage        tokens sent and received per account and quota window
                          (--by-day [N], --by-model)
    lagrange status       who loaded the credential last, with which account
    lagrange switch <email>
    lagrange add          sign in to another account
    lagrange forget <email>
    lagrange version
"""

from __future__ import annotations

import sys

from . import VERIFIED_AGY_VERSION, __version__


def _print_accounts() -> int:
    from . import accounts

    state = accounts.collect_state()
    if not state["accounts"]:
        print("No accounts stored yet. Run `lagrange add`.")
        return 1
    if state["tracking"] and not state["running"]:
        print("(no Antigravity console is reporting an account yet)\n")
    for account in state["accounts"]:
        if account["running"]:
            mark, note = "*", "  [running]"
        elif account["pending"]:
            mark, note = "+", "  [next start]"
        elif account["loaded"]:
            mark, note = "*", "  [loaded]"
        else:
            mark, note = " ", ""
        print(f"{mark} {account['email']}{note}")
        if account["error"] == "reauth":
            print("    access revoked — run `lagrange add` and sign in again")
            continue
        if account["error"] == "offline":
            # Quota may still be there, from the last call that got through.
            print("    no connection to Google" + ("" if account["groups"]
                                                   else " — no figures yet"))
        elif account["error"]:
            print(f"    {account['error']}")
            continue
        for group in account["groups"]:
            for bucket in group["buckets"]:
                remaining = bucket["remaining"]
                value = "n/a" if remaining is None else f"{remaining * 100:5.1f}%"
                print(f"    {group['name']:<14} {bucket['window_label']:<8} {value}")
    return 0


def _figures(figures: dict) -> str:
    from . import tokens

    return (f"↑ {tokens.human(figures['sent']):>7}  ↓ {tokens.human(figures['received']):>7}"
            f"  cache {tokens.human(figures['cached']):>7}  {figures['turns']:>4} turns")


def _print_usage(argv: list[str]) -> int:
    """
    Tokens per account, measured over the same windows the quota bars use.

    Google never reports tokens — only how much of a window is left — so these
    come from Antigravity's own conversation files, attributed to whichever
    account Lagrange had loaded at the time.
    """
    from . import accounts, tokens
    from .i18n import window as window_label

    if not tokens.enabled():
        print("Token tracking is off (`track_tokens` in ~/.lagrange/config.json).")
        return 1

    if "--by-day" in argv:
        position = argv.index("--by-day") + 1
        days = int(argv[position]) if position < len(argv) and argv[position].isdigit() else 14
        tokens.sync()
        rows = tokens.by_day(days)
        if not rows:
            print("No turns recorded yet.")
            return 0
        for day, figures in rows:
            print(f"{day}  {_figures(figures)}")
        return 0

    if "--by-model" in argv:
        tokens.sync()
        rows = tokens.by_model()
        if not rows:
            print("No turns recorded yet.")
            return 0
        for name, figures in rows:
            print(f"{name:<28} {_figures(figures)}")
        return 0

    state = accounts.collect_state()
    ledger = state.get("tokens") or {}
    if not ledger:
        print("No token data yet — is Antigravity installed on this machine?")
        return 1

    since = ledger.get("since")
    if since:
        print(f"Tokens counted since {since.astimezone():%Y-%m-%d %H:%M}; "
              f"anything earlier is unattributed.\n")

    for account in state["accounts"]:
        email = account["email"]
        note = "  [running]" if account["running"] else ("  [loaded]" if account["loaded"] else "")
        print(f"{email}{note}")
        windows = ledger.get("accounts", {}).get(email, {})
        if not windows:
            print("    no quota windows to measure against")
        for window, figures in sorted(windows.items(),
                                      key=lambda item: {"5h": 0, "daily": 1, "weekly": 2,
                                                        "monthly": 3}.get(item[0], 9)):
            print(f"    {window_label(window):<10} {_figures(figures)}")
        print()

    print("All accounts")
    for window, figures in sorted((ledger.get("total") or {}).items(),
                                  key=lambda item: {"5h": 0, "daily": 1, "weekly": 2,
                                                    "monthly": 3}.get(item[0], 9)):
        print(f"    {window_label(window):<10} {_figures(figures)}")

    for window, figures in (ledger.get("unattributed") or {}).items():
        if figures.get("turns"):
            print(f"    unattributed ({window_label(window)}): {_figures(figures)}")

    context = ledger.get("context")
    if context:
        share = context["used"] / context["limit"] * 100 if context["limit"] else 0
        print(f"\nLast conversation context: {tokens.human(context['used'])} of "
              f"{tokens.human(context['limit'])} ({share:.0f}%)"
              f"{' — ' + context['model'] if context.get('model') else ''}")
    return 0


def _print_status() -> int:
    from . import accounts

    usage = accounts.last_usage()
    active = accounts.active_email()
    # usage.json пишут несколько независимых процессов, так что в нём может
    # оказаться что угодно — от null в поле до обрывка чужой записи. Статус
    # обязан пережить это и напечатать хоть что-то, а не упасть трейсбеком.
    if not isinstance(usage, dict) or not usage.get("account"):
        print(f"No switch recorded yet. Currently loaded: {active or 'nobody signed in'}")
        return 0

    print(f"Loaded:  {active or 'nobody signed in'}")
    print(f"Last switch: {usage.get('account')} by {usage.get('holder') or '?'} "
          f"at {usage.get('at') or '?'}")

    recorded = str(usage.get("account") or "").lower()
    if active and recorded != active.lower():
        print("(loaded account differs from the last recorded switch — "
              "something changed the credential outside lagrange.switch_to)")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    command = argv[0] if argv else "widget"

    if command in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0

    if command in ("-V", "--version", "version"):
        print(f"lagrange {__version__} (verified against agy {VERIFIED_AGY_VERSION})")
        return 0

    # Cheap and idempotent: adopt accounts saved by a pre-release layout.
    from . import accounts as _accounts
    _accounts.migrate_legacy()

    if command == "run":
        from . import runner
        return runner.main(argv[1:])

    if command == "doctor":
        from . import doctor
        return doctor.main(argv[1:])

    if command == "list":
        return _print_accounts()

    if command == "usage":
        return _print_usage(argv[1:])

    if command == "status":
        return _print_status()

    if command == "add":
        from . import accounts
        info = accounts.add_account()
        print(f"Added {info['email']}")
        return 0

    if command == "switch":
        if len(argv) < 2:
            print("usage: lagrange switch <email>", file=sys.stderr)
            return 2
        from . import accounts, session
        accounts.switch_to(argv[1])
        if session.request_restart(argv[1]):
            print(f"Switched to {argv[1]}. Leave Antigravity and it will restart "
                  f"in place on this account.")
        else:
            print(f"Switched to {argv[1]}. Restart agy to apply.")
        return 0

    if command == "forget":
        if len(argv) < 2:
            print("usage: lagrange forget <email>", file=sys.stderr)
            return 2
        from . import accounts
        accounts.forget_account(argv[1])
        print(f"Removed {argv[1]}")
        return 0

    if command == "widget":
        from . import ui
        return ui.main()

    print(f"unknown command: {command}\n", file=sys.stderr)
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
