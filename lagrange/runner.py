"""
`lagrange run` — the wrapper that keeps Antigravity in one console.

It launches `agy` in the console it was started from and stays out of the way.
When you switch accounts in the widget and then leave Antigravity, the wrapper
relaunches it right there — same window, same scrollback — and resumes the
conversation you were in, because a credential change only lands at startup.

Nothing is ever forced: the wrapper never interrupts a running session, it only
acts once `agy` has exited on its own.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import uuid

from . import discovery, session

RESUME_FLAG = "--continue"


def _make_output_safe() -> None:
    """
    Never let a console codepage kill the wrapper.

    Windows consoles still default to legacy codepages — cp1251, cp866, cp437 —
    and a single unencodable character would raise right at the moment the user
    is waiting for Antigravity to come back.
    """
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")


def _agy() -> str:
    path = discovery.find_agy()
    if not path:
        raise SystemExit(
            "lagrange run: agy.exe not found. Install Antigravity CLI, or set "
            '"agy_path" in ~/.lagrange/config.json'
        )
    return path


def _spawn(agy: str, argv: list[str]) -> int:
    """Run agy in this console and return its exit code."""
    # CreateProcess cannot start a .bat/.cmd on its own, and `agy_path` is
    # allowed to point at a shim script.
    command = ["cmd.exe", "/c", agy, *argv] \
        if os.path.splitext(agy)[1].lower() in (".bat", ".cmd") else [agy, *argv]
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        # Ctrl+C belongs to agy; the wrapper should not add its own noise.
        return 130


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    _make_output_safe()
    agy = _agy()

    token = uuid.uuid4().hex
    session.open_session(token, _current_account())
    resumed = False

    try:
        while True:
            # Recorded per launch, not per session: this is what the widget
            # reports as actually running, and it only changes on restart.
            account = _current_account()
            session.update_session(token, account)

            code = _spawn(agy, _with_resume(argv) if resumed else argv)

            if not session.restart_pending():
                return code

            session.clear_restart()
            resumed = True
            # Plain ASCII: this line has to survive every console codepage.
            switched = _current_account() or "the selected account"
            print(f"\n-- Lagrange: restarting Antigravity here as {switched} --\n",
                  flush=True)
    finally:
        session.close_session(token)


def _current_account() -> str | None:
    """Whichever account is loaded in the credential entry right now."""
    try:
        from . import accounts
        return accounts.active_email()
    except Exception:
        return None


def _with_resume(argv: list[str]) -> list[str]:
    """
    Resume the previous conversation unless the caller already said otherwise.

    A restart that drops the thread would defeat the point of staying in the
    same window.
    """
    directive = {"--continue", "-c", "--conversation", "--prompt", "-p", "--print"}
    if any(arg in directive or arg.startswith("--conversation=") for arg in argv):
        return argv
    return [RESUME_FLAG, *argv]


if __name__ == "__main__":
    sys.exit(main())
