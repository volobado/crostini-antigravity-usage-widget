"""
The widget itself: a compact always-on-top Tkinter window.

Quota is fetched on a worker thread so the window never freezes, including
during the browser sign-in, which can take minutes.
"""

from __future__ import annotations

import contextlib
import os
import queue
import socket
import subprocess
import threading
import tkinter as tk
from datetime import datetime, timezone

from . import accounts, config, screens, session
from . import tray as tray_module
from .i18n import t
from .i18n import window as window_label

# ─── palette ────────────────────────────────────────────────────────────────
BG = "#12131a"
CARD = "#1a1c26"
CARD_ACTIVE = "#1f2333"
BORDER = "#272b3a"
TEXT = "#e6e8f0"
MUTED = "#8b90a5"
DIM = "#5f6478"
ACCENT = "#6d8cff"
TRACK = "#2a2e3d"

GREEN = "#3ddc84"
AMBER = "#ffb84d"
RED = "#ff5c5c"

F_TITLE = ("Segoe UI Semibold", 9)
F_MAIN = ("Segoe UI", 9)
F_SMALL = ("Segoe UI", 8)
F_TINY = ("Segoe UI", 7)
F_MAIL = ("Segoe UI Semibold", 10)

SINGLETON_PORT = 52719

# Narrow enough to stay out of the way, wide enough that the title bar buttons
# remain clickable when the widget is collapsed.
MIN_WIDTH = 320


def bar_color(fraction: float) -> str:
    if fraction > 0.5:
        return GREEN
    if fraction > 0.2:
        return AMBER
    return RED


def human_left(reset: datetime | None) -> str:
    if not reset:
        return ""
    seconds = (reset - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return t("refreshing_now")
    hours, minutes = int(seconds // 3600), int(seconds % 3600 // 60)
    if hours >= 24:
        return t("days_short", days=hours // 24, hours=hours % 24)
    if hours:
        return t("hours_short", hours=hours, minutes=minutes)
    return t("minutes_short", minutes=minutes)


class Singleton:
    """
    A lock held on a loopback port.

    Launching Lagrange twice — from both Antigravity shortcuts, say — should not
    open two windows, so the second run pokes the first and exits.
    """

    def __init__(self, on_raise=None):
        self.on_raise = on_raise
        self._sock: socket.socket | None = None

    def acquire(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", SINGLETON_PORT))
        except OSError:
            sock.close()
            return False
        sock.listen(4)
        self._sock = sock
        threading.Thread(target=self._serve, daemon=True).start()
        return True

    def _serve(self):
        while True:
            try:
                conn, _ = self._sock.accept()
                conn.close()
                if self.on_raise:
                    self.on_raise()
            except OSError:
                return

    @staticmethod
    def poke() -> None:
        try:
            with socket.create_connection(("127.0.0.1", SINGLETON_PORT), timeout=2):
                pass
        except OSError:
            pass


class Tooltip:
    """
    Hover label for the title-bar glyphs.

    The buttons are single characters with no room for words, and a pin that
    nobody recognises is a pin nobody uses.
    """

    def __init__(self, widget, text: str):
        self.widget, self.text = widget, text
        self.window: tk.Toplevel | None = None
        self.timer: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self.timer = self.widget.after(450, self._show)

    def _cancel(self):
        if self.timer:
            with contextlib.suppress(tk.TclError):
                self.widget.after_cancel(self.timer)
            self.timer = None

    def _show(self):
        if self.window or not self.widget.winfo_viewable():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        tk.Label(self.window, text=self.text, bg=CARD_ACTIVE, fg=TEXT, font=F_TINY,
                 padx=6, pady=3, highlightbackground=BORDER,
                 highlightthickness=1).pack()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.update_idletasks()
        self.window.geometry(f"+{x - self.window.winfo_reqwidth() // 2}+{y}")

    def _hide(self, _event=None):
        self._cancel()
        if self.window:
            with contextlib.suppress(tk.TclError):
                self.window.destroy()
            self.window = None


class Bar(tk.Frame):
    """Remaining-quota bar."""

    def __init__(self, master, width=132, height=7):
        super().__init__(master, bg=TRACK, width=width, height=height, highlightthickness=0)
        self.pack_propagate(False)
        self._fill = tk.Frame(self, bg=GREEN, highlightthickness=0)
        self._fill.place(x=0, y=0, relheight=1.0, relwidth=1.0)

    def set(self, fraction: float | None):
        if fraction is None:
            self._fill.place_configure(relwidth=0)
            return
        fraction = max(0.0, min(1.0, fraction))
        self._fill.configure(bg=bar_color(fraction))
        # A sliver reads worse than nothing at all.
        self._fill.place_configure(relwidth=fraction if fraction > 0.012 else 0)


class Widget:
    def __init__(self):
        self.ui_state = accounts.load_ui_state()
        self.expanded: set[str] = set(self.ui_state.get("expanded", []))
        self.results: queue.Queue = queue.Queue()
        self.commands: queue.Queue = queue.Queue()
        self.state: dict | None = None
        self.busy_text: str | None = t("loading")
        self.banner: tuple[str, str] | None = None
        self.countdowns: list[tuple[tk.Label, datetime]] = []
        self.refresh_seconds = int(config.get("refresh_seconds"))
        self.seconds_left = self.refresh_seconds
        self.compact = bool(self.ui_state.get("compact", False))
        self.hidden = False
        self._width = MIN_WIDTH
        self._stop = threading.Event()

        # Before the window: whether the tray took means whether hiding is offered.
        self.tray = self._start_tray()

        self._build()
        threading.Thread(target=self._worker, daemon=True).start()
        self.commands.put(("refresh", None))
        self.root.after(150, self._drain)
        self.root.after(1000, self._tick)

    # ── window ──────────────────────────────────────────────────────────────
    def _build(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Lagrange")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)
        self.root.geometry(self.ui_state.get("geometry") or "+40+60")
        self.root.attributes("-topmost", bool(self.ui_state.get("pinned", True)))

        outer = tk.Frame(self.root, bg=BORDER, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        shell = tk.Frame(outer, bg=BG)
        shell.pack(fill="both", expand=True)

        titlebar = tk.Frame(shell, bg=BG, height=30)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)

        caption = tk.Label(titlebar, text=t("title"), bg=BG, fg=TEXT, font=F_TITLE)
        caption.pack(side="left", padx=(12, 0))

        # Packed right to left, so this reads 📌 ▭ ▁ ✕ on screen.
        buttons = [("✕", self._close, "close", t("tip_close"))]
        if self.tray:
            buttons.append(("▁", self._hide_to_tray, "tray", t("tip_tray")))
        buttons.append(("▭", self._toggle_compact, "compact", t("tip_compact")))
        buttons.append(("📌", self._toggle_pin, "pin", t("tip_pin")))

        for text, command, name, tip in buttons:
            button = tk.Label(titlebar, text=text, bg=BG, fg=MUTED, font=F_MAIN,
                              cursor="hand2", padx=8)
            button.pack(side="right")
            button.bind("<Button-1>", lambda _e, c=command: c())
            button.bind("<Enter>", lambda e: e.widget.configure(fg=TEXT))
            button.bind("<Leave>", lambda e: e.widget.configure(fg=MUTED))
            hint = Tooltip(button, tip)
            if name == "pin":
                self.pin_button = button
            elif name == "compact":
                self.compact_button, self.compact_tip = button, hint

        for widget in (titlebar, caption):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.body = tk.Frame(shell, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.content = tk.Frame(self.body, bg=BG)
        self.content.pack(fill="both", expand=True, padx=8, pady=(2, 0))

        self.footer = tk.Frame(self.body, bg=BG, height=34)
        self.footer.pack(fill="x", padx=8, pady=(4, 8))
        self._button(self.footer, t("add_account"), self._add_account,
                     primary=True).pack(side="left")

        self.status = tk.Label(self.footer, text="", bg=BG, fg=DIM, font=F_SMALL)
        self.status.pack(side="right", padx=(0, 4))

        refresh = tk.Label(self.footer, text="⟳", bg=BG, fg=MUTED, font=F_MAIN,
                           cursor="hand2", padx=6)
        refresh.pack(side="right")
        refresh.bind("<Button-1>", lambda _e: self._request("refresh"))
        refresh.bind("<Enter>", lambda e: e.widget.configure(fg=ACCENT))
        refresh.bind("<Leave>", lambda e: e.widget.configure(fg=MUTED))

        self._sync_pin()
        self._sync_compact()
        self.root.minsize(MIN_WIDTH, 32)
        self.root.deiconify()
        self.root.update_idletasks()
        self._pull_on_screen()

    def _button(self, master, text, command, primary=False, small=False):
        bg = ACCENT if primary else CARD
        fg = "#0d1020" if primary else TEXT
        button = tk.Label(master, text=text, bg=bg, fg=fg,
                          font=F_SMALL if small else F_MAIN,
                          padx=8 if small else 12, pady=3 if small else 5, cursor="hand2")
        hover = "#8aa3ff" if primary else BORDER
        button.bind("<Button-1>", lambda _e: command())
        button.bind("<Enter>", lambda e: e.widget.configure(bg=hover))
        button.bind("<Leave>", lambda e: e.widget.configure(bg=bg))
        return button

    def _drag_start(self, event):
        self._drag_from = (event.x_root, event.y_root)
        self._win_from = (self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event):
        self.root.geometry(
            f"+{self._win_from[0] + event.x_root - self._drag_from[0]}"
            f"+{self._win_from[1] + event.y_root - self._drag_from[1]}")

    def _toggle_pin(self):
        pinned = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", pinned)
        self.ui_state["pinned"] = pinned
        self._sync_pin()
        self._save_ui()

    def _sync_pin(self):
        pinned = bool(self.root.attributes("-topmost"))
        self.pin_button.configure(fg=ACCENT if pinned else DIM)
        if self.tray:
            self.tray.set_pinned(pinned)

    def _toggle_compact(self):
        self.compact = not self.compact
        self.ui_state["compact"] = self.compact
        self._sync_compact()
        self._save_ui()
        self._render()

    def _sync_compact(self):
        """
        Compact keeps the one thing worth glancing at — the active account —
        and drops the footer, the countdown and every other account with it.
        """
        self.compact_button.configure(text="▤" if self.compact else "▭",
                                      fg=ACCENT if self.compact else MUTED)
        self.compact_tip.text = t("tip_expand") if self.compact else t("tip_compact")
        if self.compact:
            self.footer.pack_forget()
            self._width = MIN_WIDTH  # stop the wide layout from sticking
        else:
            self.footer.pack(fill="x", padx=8, pady=(4, 8))

    # ── tray ────────────────────────────────────────────────────────────────
    def _start_tray(self):
        labels = {"show": t("tray_show"), "pin": t("tray_pin"),
                  "refresh": t("tray_refresh"), "quit": t("tray_quit")}
        icon = tray_module.Tray(lambda name: self.results.put(("tray", name)), labels)
        icon.set_pinned(bool(self.ui_state.get("pinned", True)))
        # No tray, no hiding: a borderless window has no taskbar button either,
        # and a widget you cannot get back is worse than one always on screen.
        return icon if icon.start() else None

    def _hide_to_tray(self):
        if not self.tray:
            return
        # Once, on the first hide: an icon nobody can find reads as a crash.
        first_time = not self.ui_state.get("tray_hint_shown")
        self.ui_state["tray_hint_shown"] = True
        self._save_ui()  # geometry, while the window still reports it
        self.hidden = True
        self.root.withdraw()
        if first_time:
            self.tray.notify(t("title").replace(" ", ""), t("tray_hint"))

    def _on_tray(self, name: str):
        if name == "show":
            self._show_window()
        elif name == "pin":
            self._toggle_pin()
        elif name == "refresh":
            self._request("refresh")
        elif name == "quit":
            self._close()

    def _sync_tray(self):
        """Redraw the icon as a gauge of the tightest window in play."""
        if not self.tray:
            return
        account = self._active_account()
        if account is None or account.get("error"):
            detail = (account or {}).get("error") or ""
            tip = f"{account['email']} — {detail}" if account else t("tray_tip_signed_out")
            self.tray.update(0.0, MUTED, tip[:127])
            return

        values, lines = [], [account["email"]]
        for group in account["groups"]:
            parts = []
            for bucket in group["buckets"]:
                remaining = bucket["remaining"]
                if remaining is None:
                    continue
                values.append(remaining)
                parts.append(f"{window_label(bucket['window'], bucket['window_label'])} "
                             f"{remaining * 100:.0f}%")
            if parts:
                lines.append(f"{group['name']}: " + " · ".join(parts))
        worst = min(values) if values else None
        self.tray.update(worst, MUTED if worst is None else bar_color(worst),
                         "\n".join(lines)[:127])

    def _active_account(self) -> dict | None:
        if not self.state or not self.state["accounts"]:
            return None
        for account in self.state["accounts"]:
            if account["running"]:
                return account
        for account in self.state["accounts"]:
            if account["loaded"]:
                return account
        return self.state["accounts"][0]

    def _close(self):
        self._save_ui()
        self._stop.set()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def _pull_on_screen(self):
        """
        A saved position outlives the screen it was saved on. If no monitor
        shows any part of the window, it is moved back into view — otherwise
        the widget starts, reports itself visible, and is nowhere on the desk.
        """
        self.root.update_idletasks()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        width = self.root.winfo_width() or MIN_WIDTH
        height = self.root.winfo_height() or 120
        moved_x, moved_y = screens.on_screen(x, y, width, height)
        if (moved_x, moved_y) != (x, y):
            self.root.geometry(f"+{moved_x}+{moved_y}")
            self.ui_state["geometry"] = f"+{moved_x}+{moved_y}"

    def _save_ui(self):
        self.ui_state["geometry"] = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        self.ui_state["expanded"] = sorted(self.expanded)
        accounts.save_ui_state(self.ui_state)

    def raise_window(self):
        """
        Bring the window back — callable from any thread.

        The singleton listener calls this from its own thread when a second
        launch pokes it, which is also the way back when the tray icon is not
        where the user expects it: running the shortcut again re-opens the
        window instead of doing nothing.
        """
        self.results.put(("tray", "show"))

    def _show_window(self):
        """
        Come back where it was, in front, whatever asked for it.

        Coming back unpinned behind a maximised console is indistinguishable
        from not coming back at all, so the window is forced to the top for a
        few seconds even when the pin is off.
        """
        def show():
            self.hidden = False
            self.root.deiconify()
            self.root.update_idletasks()
            self.root.geometry(self.ui_state.get("geometry")
                               or f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
            self._pull_on_screen()  # the screen may have changed while it was away
            self.root.lift()
            self.root.attributes("-topmost", True)
            with contextlib.suppress(tk.TclError):
                self.root.focus_force()
            if not self.ui_state.get("pinned", True):
                self.root.after(4000, lambda: self.root.attributes("-topmost", False))
        self.root.after(0, show)

    # ── background work ─────────────────────────────────────────────────────
    def _request(self, action, payload=None):
        self.busy_text = {"refresh": t("refreshing"), "switch": t("switching"),
                          "add": t("waiting_browser")}.get(action)
        self._render()
        self.commands.put((action, payload))

    def _worker(self):
        while not self._stop.is_set():
            try:
                action, payload = self.commands.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if action == "refresh":
                    self.results.put(("state", accounts.collect_state()))
                elif action == "switch":
                    accounts.switch_to(payload)
                    in_place = session.request_restart(payload)
                    self.results.put(
                        ("banner", ("switched_here" if in_place else "switched", payload)))
                    self.results.put(("state", accounts.collect_state()))
                elif action == "add":
                    info = accounts.add_account()
                    self.results.put(("banner", ("added", info["email"])))
                    self.results.put(("state", accounts.collect_state()))
            except Exception as exc:  # a network blip must not kill the widget
                self.results.put(("banner", ("error", str(exc)[:160])))
                try:
                    self.results.put(("state", accounts.collect_state()))
                except Exception:
                    self.results.put(("idle", None))

    def _drain(self):
        try:
            while True:
                kind, payload = self.results.get_nowait()
                if kind == "state":
                    self.state = payload
                    self.busy_text = None
                    self.seconds_left = self.refresh_seconds
                    self._sync_tray()
                elif kind == "banner":
                    self.banner = payload
                elif kind == "idle":
                    self.busy_text = None
                elif kind == "tray":
                    self._on_tray(payload)
                    continue
                self._render()
        except queue.Empty:
            pass
        if not self._stop.is_set():  # "Quit" from the tray destroys the window here
            self.root.after(150, self._drain)

    def _tick(self):
        if self._stop.is_set():
            return
        self.seconds_left -= 1
        if self.seconds_left <= 0 and not self.busy_text:
            self.seconds_left = self.refresh_seconds
            self.commands.put(("refresh", None))
        for label, reset in self.countdowns:
            with contextlib.suppress(tk.TclError):
                label.configure(text=human_left(reset))
        if not self.busy_text:
            self.status.configure(text=t("next_refresh", seconds=self.seconds_left))
        if not self.hidden:
            # Screens come and go — a remote session, an unplugged monitor —
            # and a widget stranded outside them all is indistinguishable from
            # one that never opened.
            self._pull_on_screen()
        self.root.after(1000, self._tick)

    # ── rendering ───────────────────────────────────────────────────────────
    def _render(self):
        for child in self.content.winfo_children():
            child.destroy()
        self.countdowns.clear()

        if self.banner:
            self._render_banner()

        if self.state is None:
            tk.Label(self.content, text=self.busy_text or "…", bg=BG, fg=MUTED,
                     font=F_MAIN, pady=18).pack()
            self._fit()
            return

        if not self.state["accounts"]:
            self._render_empty()
        elif self.compact:
            self._render_compact_view()
        else:
            for account in self.state["accounts"]:
                self._render_account(account)

        if self.busy_text:
            self.status.configure(text=self.busy_text)
        self._fit()

    def _fit(self):
        """
        Resize to fit without losing position: geometry("") hands placement back
        to the window manager and the window jumps away from where it was put.

        Width is floored at MIN_WIDTH because the title bar has size propagation
        switched off — with little in the body it asks for almost no width at
        all, and the window would shrink to a strip too narrow to click.

        In the full view the widest layout so far is kept, so the window stops
        twitching sideways as accounts expand and collapse. Compact starts over
        from its own natural width instead of inheriting that.
        """
        self.root.update_idletasks()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        width = max(self.root.winfo_reqwidth(), MIN_WIDTH)
        if not self.compact:
            width = max(width, self._width)
            self._width = width
        self.root.geometry(f"{width}x{self.root.winfo_reqheight()}+{x}+{y}")

    def _render_banner(self):
        kind, value = self.banner
        color = {"switched": ACCENT, "switched_here": GREEN,
                 "added": GREEN, "error": RED}[kind]
        text = {"switched": t("switched", email=value),
                "switched_here": t("switched", email=value),
                "added": t("added", email=value),
                "error": value}[kind]

        box = tk.Frame(self.content, bg=CARD, highlightbackground=color, highlightthickness=1)
        box.pack(fill="x", pady=(4, 6))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(row, text=text, bg=CARD, fg=TEXT, font=F_SMALL, wraplength=270,
                 justify="left").pack(side="left")
        close = tk.Label(row, text="✕", bg=CARD, fg=DIM, font=F_TINY, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._dismiss())

        if kind == "switched_here":
            # A wrapper is running: leaving agy relaunches it in that console.
            tk.Label(box, text=t("restart_in_place"), bg=CARD, fg=MUTED, font=F_TINY,
                     wraplength=280, justify="left").pack(anchor="w", padx=8, pady=(0, 8))
        elif kind == "switched":
            launchers = config.get("launchers") or []
            tk.Label(box, text=t("restart_hint") if launchers else t("restart_manual"),
                     bg=CARD, fg=MUTED, font=F_TINY, wraplength=280,
                     justify="left").pack(anchor="w", padx=8,
                                          pady=(0, 0 if launchers else 8))
            if launchers:
                row = tk.Frame(box, bg=CARD)
                row.pack(anchor="w", padx=8, pady=(4, 8))
                for launcher in launchers[:3]:
                    path = launcher.get("path", "")
                    self._button(row, launcher.get("label", "Launch"),
                                 lambda p=path: self._launch(p),
                                 small=True).pack(side="left", padx=(0, 6))
        else:
            tk.Frame(box, bg=CARD, height=6).pack()

    def _dismiss(self):
        self.banner = None
        self._render()

    def _launch(self, path: str):
        if not path or not os.path.exists(path):
            self.banner = ("error", f"launcher not found: {path}")
            self._render()
            return
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", "cmd.exe", "/k", path],
                             cwd=os.path.dirname(path) or None, close_fds=True)
        except OSError as exc:
            self.banner = ("error", f"could not start {os.path.basename(path)}: {exc}")
            self._render()

    def _render_empty(self):
        box = tk.Frame(self.content, bg=CARD)
        box.pack(fill="x", pady=6)
        message = t("no_accounts") if self.state.get("logged_in") else t("not_signed_in")
        tk.Label(box, text=message, bg=CARD, fg=MUTED, font=F_MAIN, justify="left",
                 wraplength=280, padx=12, pady=14).pack(anchor="w")

    def _render_account(self, account: dict):
        email = account["email"]
        running, loaded, pending = account["running"], account["loaded"], account["pending"]
        # A card is highlighted for what agy is really using; when nothing is
        # known to be running, the loaded account takes that role.
        highlighted = running or (loaded and not self.state.get("tracking"))
        expanded = highlighted or pending or email in self.expanded
        bg = CARD_ACTIVE if highlighted else CARD

        border = ACCENT if highlighted else (AMBER if pending else BORDER)
        card = tk.Frame(self.content, bg=bg, highlightbackground=border, highlightthickness=1)
        card.pack(fill="x", pady=3)

        interactive = not (running or (loaded and not self.state.get("tracking")))
        header = tk.Frame(card, bg=bg, cursor="hand2" if interactive else "")
        header.pack(fill="x", padx=10, pady=(7, 2))
        tk.Label(header, text="●" if highlighted else "○", bg=bg,
                 fg=ACCENT if highlighted else (AMBER if pending else DIM),
                 font=F_MAIN).pack(side="left")
        tk.Label(header, text=email, bg=bg, fg=TEXT if highlighted else MUTED,
                 font=F_MAIL if highlighted else F_MAIN).pack(side="left", padx=(6, 0))

        if running:
            tk.Label(header, text=t("running"), bg=bg, fg=ACCENT,
                     font=F_TINY).pack(side="right")
        elif pending:
            tk.Label(header, text=t("next_start"), bg=bg, fg=AMBER,
                     font=F_TINY).pack(side="right")
        elif loaded:
            tk.Label(header, text=t("loaded"), bg=bg, fg=ACCENT,
                     font=F_TINY).pack(side="right")
        else:
            tk.Label(header, text="▾" if expanded else "▸", bg=bg, fg=DIM,
                     font=F_TINY).pack(side="right")

        if interactive:
            for widget in (header, *header.winfo_children()):
                widget.bind("<Button-1>", lambda _e, m=email: self._toggle_account(m))

        if pending:
            tk.Label(card, text=t("pending_hint"), bg=bg, fg=AMBER, font=F_TINY,
                     wraplength=280, justify="left").pack(anchor="w", padx=10, pady=(0, 2))

        if account["error"] == "reauth":
            box = tk.Frame(card, bg=bg)
            box.pack(fill="x", padx=10, pady=(2, 8))
            tk.Label(box, text=t("revoked"), bg=bg, fg=RED, font=F_SMALL).pack(anchor="w")
            self._button(box, t("sign_in_again"), self._add_account,
                         small=True).pack(anchor="w", pady=(4, 0))
            return

        if account["error"]:
            tk.Label(card, text=account["error"], bg=bg, fg=AMBER, font=F_SMALL,
                     wraplength=280, justify="left").pack(anchor="w", padx=10, pady=(2, 8))
            return

        if expanded:
            for group in account["groups"]:
                self._render_group(card, group, bg)
        else:
            self._render_compact(card, account, bg)

        if running or loaded:
            tk.Frame(card, bg=bg, height=6).pack()
        else:
            row = tk.Frame(card, bg=bg)
            row.pack(fill="x", padx=10, pady=(2, 8))
            self._button(row, t("switch"), lambda m=email: self._request("switch", m),
                         small=True).pack(side="right")

    def _render_group(self, card, group: dict, bg: str):
        tk.Label(card, text=group["name"], bg=bg, fg=MUTED,
                 font=F_TITLE).pack(anchor="w", padx=10, pady=(6, 1))
        for bucket in group["buckets"]:
            row = tk.Frame(card, bg=bg)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=window_label(bucket["window"], bucket["window_label"]),
                     bg=bg, fg=DIM, font=F_SMALL, width=8, anchor="w").pack(side="left")

            bar = Bar(row)
            bar.pack(side="left", padx=(0, 8))
            bar.set(bucket["remaining"])

            remaining = bucket["remaining"]
            tk.Label(row, text="—" if remaining is None else f"{remaining * 100:.0f}%",
                     bg=bg, fg=TEXT if remaining is None else bar_color(remaining),
                     font=F_TITLE, width=5, anchor="e").pack(side="left")

            countdown = tk.Label(row, text=human_left(bucket["reset"]), bg=bg, fg=DIM,
                                 font=F_TINY, width=9, anchor="e")
            countdown.pack(side="right")
            if bucket["reset"]:
                self.countdowns.append((countdown, bucket["reset"]))

    def _render_compact_view(self):
        """
        The whole widget shrunk to the account actually in use: one line of
        identity, one bar per model group, showing that group's tightest window.
        Clicking anywhere in it goes back to the full view.
        """
        account = self._active_account()
        if account is None:
            self._render_empty()
            return

        box = tk.Frame(self.content, bg=CARD_ACTIVE, highlightbackground=ACCENT,
                       highlightthickness=1)
        box.pack(fill="x", pady=(2, 4))

        header = tk.Frame(box, bg=CARD_ACTIVE, cursor="hand2")
        header.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(header, text="●", bg=CARD_ACTIVE, fg=ACCENT, font=F_TINY).pack(side="left")
        tk.Label(header, text=account["email"], bg=CARD_ACTIVE, fg=TEXT,
                 font=F_MAIN).pack(side="left", padx=(6, 0))

        if account["error"]:
            tk.Label(box, text=t("revoked") if account["error"] == "reauth"
                     else account["error"], bg=CARD_ACTIVE, fg=AMBER, font=F_SMALL,
                     wraplength=280, justify="left").pack(anchor="w", padx=10, pady=(0, 8))
        else:
            for group in account["groups"]:
                values = [(b["remaining"], b) for b in group["buckets"]
                          if b["remaining"] is not None]
                if not values:
                    continue
                worst, bucket = min(values, key=lambda pair: pair[0])
                row = tk.Frame(box, bg=CARD_ACTIVE)
                row.pack(fill="x", padx=10, pady=1)
                tk.Label(row, text=group["name"], bg=CARD_ACTIVE, fg=MUTED, font=F_SMALL,
                         width=11, anchor="w").pack(side="left")
                bar = Bar(row, width=104)
                bar.pack(side="left", padx=(0, 8))
                bar.set(worst)
                tk.Label(row, text=f"{worst * 100:.0f}%", bg=CARD_ACTIVE,
                         fg=bar_color(worst), font=F_TITLE, width=5,
                         anchor="e").pack(side="left")
                countdown = tk.Label(row, text=human_left(bucket["reset"]), bg=CARD_ACTIVE,
                                     fg=DIM, font=F_TINY, width=8, anchor="e")
                countdown.pack(side="right")
                if bucket["reset"]:
                    self.countdowns.append((countdown, bucket["reset"]))
            tk.Frame(box, bg=CARD_ACTIVE, height=5).pack()

        for widget in (box, header, *header.winfo_children()):
            widget.bind("<Button-1>", lambda _e: self._toggle_compact())

    def _render_compact(self, card, account: dict, bg: str):
        """Collapsed card: one row per group, showing its tightest window."""
        for group in account["groups"]:
            values = [b["remaining"] for b in group["buckets"] if b["remaining"] is not None]
            if not values:
                continue
            worst = min(values)
            row = tk.Frame(card, bg=bg)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=group["name"], bg=bg, fg=DIM, font=F_SMALL, width=11,
                     anchor="w").pack(side="left")
            bar = Bar(row, width=110)
            bar.pack(side="left", padx=(0, 8))
            bar.set(worst)
            tk.Label(row, text=f"{worst * 100:.0f}%", bg=bg, fg=bar_color(worst),
                     font=F_TITLE, width=5, anchor="e").pack(side="left")

    def _toggle_account(self, email: str):
        self.expanded.symmetric_difference_update({email})
        self._save_ui()
        self._render()

    def _add_account(self):
        self._request("add")

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.mainloop()


def main() -> int:
    accounts.migrate_legacy()
    lock = Singleton()
    if not lock.acquire():
        Singleton.poke()  # already running — surface that window instead
        return 0
    widget = Widget()
    lock.on_raise = widget.raise_window
    widget.run()
    return 0
