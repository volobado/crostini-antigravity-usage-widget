"""
Command line entry point.

    lagrange              open the widget
    lagrange run [args]   run Antigravity so it can restart in place on a switch
    lagrange doctor       check every assumption and report what drifted
    lagrange list         accounts and their remaining quota
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
        if account["error"]:
            print(f"    {account['error']}")
            continue
        for group in account["groups"]:
            for bucket in group["buckets"]:
                remaining = bucket["remaining"]
                value = "n/a" if remaining is None else f"{remaining * 100:5.1f}%"
                print(f"    {group['name']:<14} {bucket['window_label']:<8} {value}")
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
