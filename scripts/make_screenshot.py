"""
Render the widget with fabricated accounts and capture docs/screenshot.png.

Documentation must never carry a real address, and a screenshot taken from a
live install would. This also lets the picture show every state at once —
running, queued for next start, and the three bar colours — which a real
install rarely does.

    python scripts/make_screenshot.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

OUTPUT = os.path.join(REPO, "docs", "screenshot.png")
WINDOW_X, WINDOW_Y = 120, 120

_CAPTURE = r"""
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class Cap {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
'@
$p = Get-Process -Id %PID% -ErrorAction Stop
$r = New-Object Cap+RECT
[Cap]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
$w = $r.R - $r.L; $h = $r.B - $r.T
if ($w -lt 100 -or $h -lt 100) { Write-Error "window not ready: ${w}x${h}"; exit 1 }
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$bmp.Save('%OUT%', [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "${w}x${h}"
"""


def _bucket(window: str, label: str, remaining: float, reset: datetime | None):
    return {"id": "", "window": window, "window_label": label,
            "remaining": remaining, "reset": reset, "description": ""}


def _groups(gemini_5h, gemini_week, third_5h, third_week):
    now = datetime.now(timezone.utc)
    return [
        {"name": "Gemini", "full_name": "Gemini Models",
         "models": "Gemini Flash, Gemini Pro", "buckets": [
             _bucket("5h", "5-hour", gemini_5h, now + timedelta(hours=2, minutes=41)),
             _bucket("weekly", "weekly", gemini_week, now + timedelta(days=4, hours=6))]},
        {"name": "Claude / GPT", "full_name": "Claude and GPT models",
         "models": "Claude Opus, Claude Sonnet, GPT-OSS", "buckets": [
             _bucket("5h", "5-hour", third_5h, now + timedelta(hours=4, minutes=52)),
             _bucket("weekly", "weekly", third_week, now + timedelta(days=6, hours=1))]},
    ]


def _account(email, running=False, pending=False, groups=None):
    return {"email": email, "name": "", "running": running, "pending": pending,
            "loaded": running or pending, "active": running or pending,
            "error": None, "groups": groups or []}


# One of each state, and all three bar colours, so the picture documents the
# whole interface rather than whatever the author's quota happened to be.
STATE = {
    "accounts": [
        _account("account-1@example.com", running=True,
                 groups=_groups(0.62, 0.88, 1.0, 0.97)),
        _account("account-2@example.com", pending=True,
                 groups=_groups(1.0, 1.0, 1.0, 1.0)),
        _account("account-3@example.com", groups=_groups(0.34, 0.71, 1.0, 1.0)),
        _account("account-4@example.com", groups=_groups(0.08, 0.44, 0.9, 0.9)),
    ],
    "active": "account-2@example.com",
    "running": ["account-1@example.com"],
    "tracking": True,
    "logged_in": True,
    "fetched_at": datetime.now(timezone.utc),
}


def main() -> int:
    from lagrange import accounts, ui

    # Isolated from a real install: no network, no shared singleton port, and
    # no chance of writing the fabricated layout into the user's ui.json.
    ui.SINGLETON_PORT = 52799
    accounts.collect_state = lambda: STATE
    accounts.load_ui_state = lambda: {"geometry": f"+{WINDOW_X}+{WINDOW_Y}",
                                      "pinned": True, "expanded": []}
    accounts.save_ui_state = lambda state: None

    widget = ui.Widget()
    widget.state = STATE
    widget.busy_text = None
    widget.seconds_left = 47
    widget._render()
    widget.status.configure(text="next refresh in 47s")
    for _ in range(5):
        widget.root.update()
        time.sleep(0.15)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    script = _CAPTURE.replace("%PID%", str(os.getpid())).replace("%OUT%", OUTPUT)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                            capture_output=True, text=True)
    widget.root.destroy()

    if result.returncode != 0:
        print(result.stderr.strip() or "capture failed", file=sys.stderr)
        return 1
    print(f"saved {OUTPUT} ({result.stdout.strip()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
