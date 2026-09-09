"""
The widget itself: a compact always-on-top Tkinter window.

Quota is fetched on a worker thread so the window never freezes, including
during the browser sign-in, which can take minutes.

The look is deliberate. This thing sits on top of a console all day, so it is
built to be read at a glance and to be pleasant to have around: a deep-space
ground, one neon accent per state, gradient meters, and a horizon line under
the title bar that pulses when fresh figures land. Every effect is drawn with
Tk primitives — no image files, no dependencies — and all of it can be switched
off with `"effects": false` for anyone who wants the plain instrument.
"""

from __future__ import annotations

import contextlib
import os
import queue
import random
import socket
import subprocess
import threading
import tkinter as tk
from datetime import datetime, timezone

from . import accounts, api, chrome, config, screens, session, tokens
from . import tray as tray_module
from .i18n import month as month_name
from .i18n import t
from .i18n import window as window_label

# ─── palette ────────────────────────────────────────────────────────────────
#
# Space at the bottom, terminal green and AI cyan on top of it. The three status
# colours stay far apart in hue so a bar's state is readable before the number
# beside it is.

VOID = "#05070e"          # the window ground
BG = "#080c15"
CARD = "#0d1420"
CARD_ACTIVE = "#111b2c"
BORDER = "#1b2740"
GRID = "#152441"          # meter track ticks, hairlines
TRACK = "#111a2b"

TEXT = "#dce8f5"
MUTED = "#7b8aa6"
DIM = "#4b5a75"

NEON = "#3df5a7"          # matrix green — healthy
CYAN = "#4fd8ff"          # the AI accent — active, selected
VIOLET = "#a476ff"        # deep space — context, secondary readings
AMBER = "#ffc46b"
RED = "#ff6b7d"

ACCENT = CYAN
STAR = "#25406b"

F_BRAND = ("Consolas", 10, "bold")
F_TITLE = ("Segoe UI Semibold", 9)
F_MAIN = ("Segoe UI", 9)
F_SMALL = ("Segoe UI", 8)
F_TINY = ("Segoe UI", 7)
F_MAIL = ("Segoe UI Semibold", 10)
F_BIG = ("Consolas", 15, "bold")
F_MONO = ("Consolas", 8)

SINGLETON_PORT = 52719

# Narrow enough to stay out of the way, wide enough that the title bar buttons
# remain clickable. Compact has its own floor: it is meant to be small.
MIN_WIDTH = 330
COMPACT_WIDTH = 268
COMPACT_HEIGHT = 244

# What a person may drag the compact window down to. Small enough to be a strip
# on the edge of a screen, large enough that the title bar buttons survive.
COMPACT_MIN = (232, 96)
GRIP = 6

CORNER_RADIUS = 14


# ─── colour helpers ─────────────────────────────────────────────────────────

def _rgb(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def mix(first: str, second: str, amount: float) -> str:
    """`first` shaded towards `second`; amount 0 → first, 1 → second."""
    amount = max(0.0, min(1.0, amount))
    channels = (round(x + (y - x) * amount)
                for x, y in zip(_rgb(first), _rgb(second), strict=True))
    return "#" + "".join(f"{value:02x}" for value in channels)


def bar_color(fraction: float) -> str:
    if fraction > 0.5:
        return NEON
    if fraction > 0.2:
        return AMBER
    return RED


def effects_on() -> bool:
    return bool(config.get("effects"))


def human_left(reset: datetime | None) -> str:
    if not reset:
        return ""
    seconds = (reset - datetime.now(timezone.utc)).total_seconds()
    if seconds <= 0:
        return t("refreshing_now")
    return human_age(int(seconds))


def reset_day(reset: datetime) -> str:
    """`today`, `tomorrow`, or a short date with no year — "Sep 4", "4 сен"."""
    local = reset.astimezone()
    today = datetime.now().astimezone().date()
    delta = (local.date() - today).days
    if delta == 0:
        return t("today")
    if delta == 1:
        return t("tomorrow")
    return t("date_short", month=month_name(local.month), day=local.day)


def reset_stamp(reset: datetime | None, with_day: bool = True) -> str:
    """
    When the window actually refills: "16:20 · Sep 4".

    A countdown answers "how long do I wait", which is the question during a
    session; the clock time answers "can I start this tonight", which is the one
    asked while planning. Both are cheap to show, so both are shown — the
    countdown ticking, this one fixed. The year is left out on purpose: no quota
    window here is longer than a month.
    """
    if not reset:
        return ""
    local = reset.astimezone()
    clock = f"{local.hour:02d}:{local.minute:02d}"
    return f"{clock} · {reset_day(reset)}" if with_day else clock


def reset_brief(reset: datetime | None) -> str:
    """
    The narrow form for a row that already carries a countdown.

    Whichever half is not already obvious: a window refilling today needs the
    clock time, one refilling later needs the date — printing both would push
    the row wider than the widget wants to be.
    """
    if not reset:
        return ""
    local = reset.astimezone()
    if local.date() == datetime.now().astimezone().date():
        return f"{local.hour:02d}:{local.minute:02d}"
    return t("date_short", month=month_name(local.month), day=local.day)


def human_age(seconds: int) -> str:
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
                 padx=6, pady=3, highlightbackground=CYAN,
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


class Starfield(tk.Canvas):
    """
    The title bar's backdrop: a slow star field with a scan line crossing it.

    Deliberately quiet. A widget that lives above someone's editor all day has
    no business flickering, so the stars only breathe — a handful redrawn a
    shade brighter or dimmer every second and a half — and the scan sweep runs
    once every twelve seconds, taking two of them to cross. With `effects` off
    the field is drawn once and never animated at all.
    """

    STARS = 26
    BREATH_MS = 1500
    SWEEP_EVERY_MS = 12000
    SWEEP_STEP_MS = 40

    def __init__(self, master, height: int = 32, title: tuple[str, ...] = (),
                 subtitle: tuple[str, ...] = ()):
        # width=1: a Tk canvas asks for 378 pixels by default, which would set
        # the floor for the whole window and make compact mode anything but.
        super().__init__(master, bg=VOID, width=1, height=height,
                         highlightthickness=0, bd=0)
        self._title = title
        self._subtitle = subtitle
        self._stars: list[tuple[int, float]] = []
        self._sweep: list[int] = []
        self._timers: list[str] = []
        self._animated = effects_on()
        self._drag_callbacks = None
        self.bind("<Configure>", lambda _e: self._paint())
        if self._animated:
            self._later(self.BREATH_MS, self._breathe)
            self._later(self.SWEEP_EVERY_MS, self._sweep_once)

    def bind_drag(self, start, move, end):
        self._drag_callbacks = (start, move, end)
        self.bind("<Button-1>", start)
        self.bind("<B1-Motion>", move)
        self.bind("<ButtonRelease-1>", end)

    # A canvas that outlives its window would keep the whole widget alive; every
    # callback re-checks existence instead of trusting the schedule.
    def _later(self, delay: int, call):
        with contextlib.suppress(tk.TclError):
            self._timers.append(self.after(delay, call))

    def _paint(self):
        with contextlib.suppress(tk.TclError):
            self.delete("star")
            self.delete("brand")
            width = max(self.winfo_width(), 1)
            height = max(self.winfo_height(), 1)
            self._stars.clear()
            rng = random.Random(0x1A67)  # same sky every launch — no twitching
            for _ in range(self.STARS):
                x = rng.randrange(2, max(3, width - 2))
                y = rng.randrange(2, max(3, height - 2))
                weight = rng.random()
                size = 1 if weight < 0.75 else 2
                colour = mix(VOID, STAR, 0.35 + weight * 0.65)
                item = self.create_oval(x, y, x + size, y + size, fill=colour,
                                        outline="", tags="star")
                self._stars.append((item, weight))

            if self._title:
                # The name drawn twice, a pixel apart: the lower copy in dim
                # green reads as a glow behind the letters. On the canvas rather
                # than in a label, because a label would bring an opaque
                # rectangle and paint out the sky it is standing in.
                #
                # A spaced-out wordmark is wide, and compact mode is not, so the
                # name comes as candidates: the widest that fits is kept, and
                # each one is measured rather than guessed at.
                middle = height // 2
                mark = None
                for text in self._title:
                    glow = self.create_text(13, middle + 1, text=text, anchor="w",
                                            fill=mix(VOID, NEON, 0.7), font=F_BRAND,
                                            tags="brand")
                    mark = self.create_text(12, middle, text=text, anchor="w",
                                            fill=TEXT, font=F_BRAND, tags="brand")
                    if self.bbox(mark)[2] <= width - 6:
                        break
                    self.delete(glow)
                    self.delete(mark)
                    mark = None
                if mark is None:
                    return
                # What this Lagrange is. Measured rather than estimated: each
                # candidate is drawn, and dropped again if its right edge lands
                # past the canvas — the longest one that fits stays, and in
                # compact, where the wordmark and the buttons are all the room
                # there is, none of them do.
                start = self.bbox(mark)[2] + 9
                for text in self._subtitle:
                    item = self.create_text(start, middle + 1, text=text, anchor="w",
                                            fill=mix(VOID, MUTED, 0.85), font=F_TINY,
                                            tags="brand")
                    if self.bbox(item)[2] <= width - 6:
                        break
                    self.delete(item)

            if self._drag_callbacks:
                start, move, end = self._drag_callbacks
                for tag in ("brand", "star", "sweep"):
                    self.tag_bind(tag, "<Button-1>", start)
                    self.tag_bind(tag, "<B1-Motion>", move)
                    self.tag_bind(tag, "<ButtonRelease-1>", end)

    def _breathe(self):
        if not self.winfo_exists():
            return
        rng = random.Random()
        for item, weight in rng.sample(self._stars, min(6, len(self._stars))):
            shade = 0.3 + weight * 0.7 * rng.uniform(0.5, 1.15)
            with contextlib.suppress(tk.TclError):
                self.itemconfigure(item, fill=mix(VOID, STAR, min(shade, 1.0)))
        self._later(self.BREATH_MS, self._breathe)

    def _sweep_once(self, x: int | None = None):
        """One pale band travelling left to right, then gone."""
        if not self.winfo_exists():
            return
        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)
        if x is None:
            x = -30
            for item in self._sweep:
                with contextlib.suppress(tk.TclError):
                    self.delete(item)
            self._sweep = [
                self.create_line(0, 0, 0, height, fill=mix(VOID, CYAN, 0.05 + 0.10 * i),
                                 width=6)
                for i in range(4)
            ]
        if x > width + 30:
            for item in self._sweep:
                with contextlib.suppress(tk.TclError):
                    self.delete(item)
            self._sweep = []
            self._later(self.SWEEP_EVERY_MS, self._sweep_once)
            return
        for index, item in enumerate(self._sweep):
            position = x - index * 6
            with contextlib.suppress(tk.TclError):
                self.coords(item, position, 0, position, height)
        self._later(self.SWEEP_STEP_MS, lambda: self._sweep_once(x + 9))

    def stop(self):
        for timer in self._timers:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(timer)
        self._timers.clear()


class Horizon(tk.Canvas):
    """
    The hairline under the title bar: green to cyan to violet, left to right.

    It doubles as the widget's heartbeat — `flash()` brightens it for a moment
    when new figures arrive, which is the whole feedback anyone needs that the
    numbers on screen are the ones Google just gave.
    """

    def __init__(self, master, height: int = 2):
        super().__init__(master, bg=VOID, width=1, height=height,
                         highlightthickness=0, bd=0)
        self._segments: list[tuple[int, str]] = []
        self._timer: str | None = None
        self.bind("<Configure>", lambda _e: self._paint())

    def _paint(self, boost: float = 0.0):
        with contextlib.suppress(tk.TclError):
            self.delete("all")
            self._segments.clear()
            width = max(self.winfo_width(), 1)
            height = max(self.winfo_height(), 1)
            steps = max(width // 4, 8)
            for index in range(steps):
                position = index / (steps - 1 or 1)
                # Two stops: green→cyan over the first half, cyan→violet after.
                if position < 0.5:
                    hue = mix(NEON, CYAN, position * 2)
                else:
                    hue = mix(CYAN, VIOLET, (position - 0.5) * 2)
                shade = mix(VOID, hue, 0.42 + boost)
                # Both edges come off the same formula, and the right one
                # overshoots by a pixel — mismatched rounding leaves gaps and
                # the line reads as a dotted rule instead of a horizon.
                x0 = round(index / steps * width)
                x1 = round((index + 1) / steps * width) + 1
                self._segments.append(
                    (self.create_rectangle(x0, 0, x1, height, fill=shade, outline=""), hue))

    def flash(self):
        if not effects_on() or not self.winfo_exists():
            return
        self._paint(boost=0.5)
        if self._timer:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._timer)
        self._timer = self.after(650, self._paint)


class Bar(tk.Canvas):
    """
    A quota meter: gridded track, gradient fill, a brighter head.

    Drawn rather than packed out of frames because the gradient is the point —
    the eye reads a bar that fades towards its tip as a level, not as a block,
    and the ticks behind it give the level a scale to sit against.
    """

    def __init__(self, master, width=118, height=8, bg=CARD):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._fraction: float | None = None
        # Repaint at whatever width the packer ends up giving: a meter that
        # keeps its requested width while the window is dragged wider leaves a
        # gap where the level should be.
        self.bind("<Configure>", lambda _e: self._paint())
        self._paint()

    def _paint(self):
        with contextlib.suppress(tk.TclError):
            self.delete("all")
            height = self.winfo_height() if self.winfo_height() > 1 else self._height
            width = self.winfo_width() if self.winfo_width() > 1 else self._width
            self.create_rectangle(0, 0, width, height, fill=TRACK, outline="")
            for x in range(0, width, 11):  # the scale behind the level
                self.create_line(x, 1, x, height - 1, fill=GRID)

            fraction = self._fraction
            if fraction is None:
                return
            filled = round(width * max(0.0, min(1.0, fraction)))
            if filled < 2:
                return
            base = bar_color(fraction)
            tip = mix(base, "#ffffff", 0.45)
            steps = max(filled // 3, 6)
            for index in range(steps):
                x0 = round(index / steps * filled)
                x1 = round((index + 1) / steps * filled) + 1
                self.create_rectangle(x0, 0, x1, height,
                                      fill=mix(base, tip, index / (steps - 1 or 1)),
                                      outline="")
            # The head: a bright cap, so the level has an edge to land on.
            self.create_rectangle(max(filled - 2, 0), 0, filled, height,
                                  fill=mix(tip, "#ffffff", 0.35), outline="")

    def set(self, fraction: float | None):
        # A sliver reads worse than nothing at all.
        self._fraction = None if fraction is None or fraction <= 0.012 else fraction
        self._paint()


class Widget:
    def __init__(self):
        self.ui_state = accounts.load_ui_state()
        self.expanded: set[str] = set(self.ui_state.get("expanded", []))
        self.collapsed: set[str] = set(self.ui_state.get("collapsed", []))
        self.results: queue.Queue = queue.Queue()
        self.commands: queue.Queue = queue.Queue()
        self.state: dict | None = None
        self.busy_text: str | None = t("loading")
        self.banner: tuple[str, str] | None = None
        self.countdowns: list[tuple[tk.Label, datetime]] = []
        self.refresh_seconds = int(config.get("refresh_seconds"))
        self.seconds_left = self.refresh_seconds
        self.compact = bool(self.ui_state.get("compact", False))
        self.compact_size = self._saved_compact_size()
        self.hidden = False
        self._width = MIN_WIDTH
        self._shape = (0, 0)
        self._resize_axis = ""
        self._resize_from = (0, 0)
        self._resize_size = (0, 0)
        self._scrollable = False
        # Set when a remembered position has just been restored, so the next fit
        # honours it instead of deriving a corner from the previous size.
        self._restored = False
        self._stop = threading.Event()
        self._timers: dict[str, str] = {}

        # Before the window: whether the tray took means whether hiding is offered.
        self.tray = self._start_tray()

        self._build()
        self._worker_thread = threading.Thread(target=self._worker, daemon=True,
                                               name="lagrange-worker")
        self._worker_thread.start()
        self.commands.put(("refresh", None))
        self.root.after(150, self._drain)
        self.root.after(1000, self._tick)

    # ── window ──────────────────────────────────────────────────────────────
    def _build(self):
        self.root = tk.Tk(className="lagrange-widget")
        self.root.withdraw()
        self.root.title(t("product"))
        self.root.configure(bg=VOID)
        self.root.overrideredirect(True)
        self.root.geometry(self.ui_state.get("geometry") or "+40+60")
        self.root.attributes("-topmost", bool(self.ui_state.get("pinned", True)))

        outer = tk.Frame(self.root, bg=BORDER, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        shell = tk.Frame(outer, bg=BG)
        shell.pack(fill="both", expand=True)

        titlebar = tk.Frame(shell, bg=VOID, height=32)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)

        self.sky = Starfield(titlebar, height=32,
                             title=(t("title"), t("title_short"), t("title_min")),
                             subtitle=(t("subtitle"), t("subtitle_short")))
        self.sky.pack(side="left", fill="both", expand=True)

        # Packed right to left, so this reads 📌 ▭ — ✕ on screen.
        buttons = [("✕", self._close, "close", t("tip_close"), RED)]
        if self.tray:
            buttons.append(("▁", self._hide_to_tray, "tray", t("tip_tray"), CYAN))
        else:
            buttons.append(("—", self._minimize_window, "minimize", t("tip_minimize"), CYAN))
        buttons.append(("▭", self._toggle_compact, "compact", t("tip_compact"), CYAN))
        buttons.append(("📌", self._toggle_pin, "pin", t("tip_pin"), NEON))

        for text, command, name, tip, hot in buttons:
            button = tk.Label(titlebar, text=text, bg=VOID, fg=MUTED, font=F_MAIN,
                              cursor="hand2", padx=8)
            button.pack(side="right", fill="y")
            button.bind("<Button-1>", lambda _e, c=command: c())
            button.bind("<Enter>", lambda e, c=hot: e.widget.configure(fg=c))
            button.bind("<Leave>", lambda e, n=name: self._cool_button(e.widget, n))
            hint = Tooltip(button, tip)
            if name == "pin":
                self.pin_button = button
            elif name == "compact":
                self.compact_button, self.compact_tip = button, hint

        self.sky.bind_drag(self._drag_start, self._drag_move, self._drag_end)
        for widget in (titlebar, outer, shell):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)

        self.horizon = Horizon(shell)
        self.horizon.pack(fill="x")
        self.horizon.bind("<Button-1>", self._drag_start)
        self.horizon.bind("<B1-Motion>", self._drag_move)
        self.horizon.bind("<ButtonRelease-1>", self._drag_end)

        self.body = tk.Frame(shell, bg=BG)
        self.body.pack(fill="both", expand=True)

        # The account list is put inside a canvas rather than straight into the
        # window, because on a laptop-sized work area seven accounts are taller
        # than the desktop and the bottom of the list would simply be off the
        # screen. The viewport is capped at what fits and scrolls past it.
        self.viewport = tk.Canvas(self.body, bg=BG, highlightthickness=0, bd=0,
                                  width=1, height=1)
        self.viewport.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.content = tk.Frame(self.viewport, bg=BG)
        self._content_id = self.viewport.create_window((0, 0), window=self.content,
                                                       anchor="nw")
        self.viewport.bind(
            "<Configure>",
            lambda e: self.viewport.itemconfigure(self._content_id, width=e.width))
        self.root.bind("<MouseWheel>", self._on_wheel)
        self.root.bind("<Button-4>", lambda e: self._on_wheel_button(e, -1))
        self.root.bind("<Button-5>", lambda e: self._on_wheel_button(e, 1))

        self.footer = tk.Frame(self.body, bg=BG, height=34)
        self.footer.pack(fill="x", padx=8, pady=(4, 8))
        self._button(self.footer, t("add_account"), self._add_account,
                     primary=True).pack(side="left")

        self.status = tk.Label(self.footer, text="", bg=BG, fg=DIM, font=F_TINY)
        self.status.pack(side="right", padx=(0, 4))

        refresh = tk.Label(self.footer, text="⟳", bg=BG, fg=MUTED, font=F_MAIN,
                           cursor="hand2", padx=6)
        refresh.pack(side="right")
        refresh.bind("<Button-1>", lambda _e: self._request("refresh"))
        refresh.bind("<Enter>", lambda e: e.widget.configure(fg=CYAN))
        refresh.bind("<Leave>", lambda e: e.widget.configure(fg=MUTED))

        self._build_grips()
        self._sync_pin()
        self._sync_compact()
        self.root.minsize(COMPACT_MIN[0], 32)
        self.root.deiconify()
        self.root.update_idletasks()
        chrome.prefer_round_corners(self.root.winfo_id())
        self._pull_on_screen()

    # ── resizing the compact view by hand ───────────────────────────────────
    def _build_grips(self):
        """
        Drag handles along the right and bottom edges, and the corner.

        A borderless window gets no resize border from Windows, so the widget
        provides its own: three strips laid over the frame, shown only in
        compact mode, where the size is the user's to choose. The full view
        sizes itself to its content and has nothing to drag.
        """
        self.grips = []
        for axis, options in (
            # The right-hand strip starts below the title bar: laid over it, the
            # last few pixels of the close button would resize instead of close.
            ("x", {"relx": 1.0, "rely": 0.0, "y": 34, "anchor": "ne", "width": GRIP,
                   "relheight": 1.0, "height": -34}),
            ("y", {"relx": 0.0, "rely": 1.0, "anchor": "sw", "height": GRIP,
                   "relwidth": 1.0}),
            ("xy", {"relx": 1.0, "rely": 1.0, "anchor": "se", "width": 13,
                    "height": 13}),
        ):
            cursor = {"x": "sb_h_double_arrow", "y": "sb_v_double_arrow",
                      "xy": "sizing"}[axis]
            if axis == "xy":
                # Drawn, not blank: a handle nobody can see is a handle nobody
                # reaches for. Three hairlines is the least that reads as one.
                grip = tk.Canvas(self.root, bg=BG, cursor=cursor, width=13, height=13,
                                 highlightthickness=0, bd=0)
                for offset in (2, 6, 10):
                    grip.create_line(12 - offset, 12, 12, 12 - offset,
                                     fill=mix(BG, CYAN, 0.45))
            else:
                grip = tk.Frame(self.root, bg=VOID, cursor=cursor)
            grip.bind("<Button-1>", lambda e, a=axis: self._resize_start(e, a))
            grip.bind("<B1-Motion>", self._resize_move)
            grip.bind("<ButtonRelease-1>", lambda _e: self._resize_end())
            self.grips.append((grip, options))

    def _sync_grips(self):
        for grip, options in self.grips:
            if self.compact:
                grip.place(**options)
                # Misc.lift explicitly: on a Canvas, `lift` is the alias for
                # tag_raise and raising the widget itself needs the base method.
                tk.Misc.lift(grip)
            else:
                grip.place_forget()

    def _resize_start(self, event, axis: str):
        self._resize_axis = axis
        self._resize_from = (event.x_root, event.y_root)
        self._resize_size = (self.root.winfo_width(), self.root.winfo_height())

    def _resize_move(self, event):
        if not self.compact:
            return
        width, height = self._resize_size
        if "x" in self._resize_axis:
            width += event.x_root - self._resize_from[0]
        if "y" in self._resize_axis:
            height += event.y_root - self._resize_from[1]

        try:
            left, top, right, bottom = screens.work_area(
                self.root.winfo_x(), self.root.winfo_y(), width, height)
            ceiling = (right - left, bottom - top)
        except OSError:
            ceiling = (2000, 2000)
        width = max(COMPACT_MIN[0], min(width, ceiling[0]))
        height = max(COMPACT_MIN[1], min(height, ceiling[1]))

        before = self._compact_layout()
        self.compact_size = (width, height)
        self.root.geometry(f"{width}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        # The meters follow the drag on their own — they repaint to whatever
        # width they are given. Only a change of shape needs the layout rebuilt,
        # and rebuilding on every motion event would stutter.
        if self._compact_layout() != before:
            self._render()
        else:
            self._shape = (width, height)
            chrome.round_window(self.root.winfo_id(), width, height, CORNER_RADIUS)

    def _resize_end(self):
        if not self.compact or not self.compact_size:
            return
        self.ui_state["compact_size"] = "{}x{}".format(*self.compact_size)
        self._save_ui()
        self._render()

    def _cool_button(self, widget, name: str):
        """Return a title-bar glyph to rest — pin and compact keep their state."""
        if name == "pin":
            self._sync_pin()
        elif name == "compact":
            widget.configure(fg=CYAN if self.compact else MUTED)
        else:
            widget.configure(fg=MUTED)

    def _button(self, master, text, command, primary=False, small=False, bg=None):
        background = ACCENT if primary else (bg or CARD)
        fg = "#04121b" if primary else TEXT
        button = tk.Label(master, text=text, bg=background, fg=fg,
                          font=F_SMALL if small else F_MAIN,
                          padx=8 if small else 12, pady=3 if small else 5, cursor="hand2")
        hover = mix(ACCENT, "#ffffff", 0.25) if primary else mix(background, CYAN, 0.25)
        button.bind("<Button-1>", lambda _e: command())
        button.bind("<Enter>", lambda e: e.widget.configure(bg=hover))
        button.bind("<Leave>", lambda e: e.widget.configure(bg=background))
        return button

    def _drag_start(self, event):
        self._drag_from = (event.x_root, event.y_root)
        self._win_from = (self.root.winfo_x(), self.root.winfo_y())
        try:
            event.widget.grab_set()
        except Exception:
            pass

    def _drag_move(self, event):
        dx = event.x_root - self._drag_from[0]
        dy = event.y_root - self._drag_from[1]
        nx = self._win_from[0] + dx
        ny = max(0, self._win_from[1] + dy)
        self.root.geometry(f"+{nx}+{ny}")

    def _drag_end(self, event=None):
        if event:
            try:
                event.widget.grab_release()
            except Exception:
                pass
        self.root.update_idletasks()
        self._save_ui()

    def _minimize_window(self):
        self._save_ui()
        self.hidden = True
        self.root.withdraw()

    def _toggle_pin(self):
        pinned = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", pinned)
        self.ui_state["pinned"] = pinned
        self._sync_pin()
        self._save_ui()

    def _sync_pin(self):
        pinned = bool(self.root.attributes("-topmost"))
        self.pin_button.configure(fg=NEON if pinned else DIM)
        if self.tray:
            self.tray.set_pinned(pinned)

    def _toggle_compact(self):
        """
        Swap the view, and put the window back where that view was last left.

        Each size remembers its own position. Without that, the small window
        would come back a little away from where it was parked every time —
        derived from wherever the big one happened to be — and "where I left it"
        is the whole point of a widget you glance at.
        """
        self._remember_position()
        self.compact = not self.compact
        self.ui_state["compact"] = self.compact
        self._sync_compact()

        remembered = self.ui_state.get(self._position_key())
        if remembered:
            self.root.geometry(remembered)
            self._restored = True
        self._save_ui()
        self._render()

    def _position_key(self) -> str:
        return "geometry_compact" if self.compact else "geometry_full"

    def _remember_position(self):
        position = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        self.ui_state[self._position_key()] = position
        self.ui_state["geometry"] = position

    def _saved_compact_size(self) -> tuple[int, int] | None:
        raw = str(self.ui_state.get("compact_size") or "")
        try:
            width, height = (int(part) for part in raw.split("x", 1))
        except ValueError:
            return None
        return max(width, COMPACT_MIN[0]), max(height, COMPACT_MIN[1])

    def _sync_compact(self):
        """
        Compact keeps the one thing worth glancing at — the active account —
        and drops the footer, the countdown and every other account with it.
        """
        self.compact_button.configure(text="▤" if self.compact else "▭",
                                      fg=CYAN if self.compact else MUTED)
        self.compact_tip.text = t("tip_expand") if self.compact else t("tip_compact")
        if self.compact:
            self.footer.pack_forget()
            self._width = MIN_WIDTH  # stop the wide layout from sticking
        else:
            self.footer.pack(fill="x", padx=8, pady=(4, 8))
        self._sync_grips()

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
            self._minimize_window()
            return
        # Once, on the first hide: an icon nobody can find reads as a crash.
        first_time = not self.ui_state.get("tray_hint_shown")
        self.ui_state["tray_hint_shown"] = True
        self._save_ui()  # geometry, while the window still reports it
        self.hidden = True
        self.root.withdraw()
        if first_time:
            self.tray.notify(t("product"), t("tray_hint"))

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

        spent = self._account_tokens(account["email"]).get("5h")
        if spent and spent.get("turns"):
            lines.append(f"5h: ↑{tokens.human(spent['sent'])} ↓{tokens.human(spent['received'])}")

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
        # Cancel first: a callback already queued would otherwise fire into a
        # destroyed interpreter, which Tk reports as "invalid command name".
        for timer in self._timers.values():
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(timer)
        self._timers.clear()
        with contextlib.suppress(tk.TclError, AttributeError):
            self.sky.stop()
        if self.tray:
            self.tray.stop()  # blocks until the icon is gone and its thread ended
        # Best effort: a worker still holding this object while Tk is torn down
        # is how a Tcl handler ends up deleted from the wrong thread.
        if self._worker_thread.is_alive():
            self._worker_thread.join(1.0)
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
        self._remember_position()
        self.ui_state["expanded"] = sorted(self.expanded)
        self.ui_state["collapsed"] = sorted(self.collapsed)
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
                    state = accounts.collect_state()
                    target = accounts.autoswitch_target(state)
                    if target:
                        # "auto", not "manual": `lagrange status` has to show
                        # that the widget took the slot, not a person.
                        accounts.switch_to(target, "auto")
                        in_place = session.request_restart(target)
                        self.results.put(("banner", (
                            "auto_switched_here" if in_place else "auto_switched", target)))
                        state = accounts.collect_state()
                    self.results.put(("state", state))
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
                    self.horizon.flash()  # fresh figures landed
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
            self._timers["drain"] = self.root.after(150, self._drain)

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
        self._timers["tick"] = self.root.after(1000, self._tick)

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
            self._render_totals()

        if self.busy_text:
            self.status.configure(text=self.busy_text)
        self._fit()

    def _on_wheel(self, event):
        """Scroll the account list, when there is more of it than fits."""
        if not self._scrollable:
            return
        with contextlib.suppress(tk.TclError):
            self.viewport.yview_scroll(-1 if event.delta > 0 else 1, "units")
            self._draw_thumb()

    def _on_wheel_button(self, event, step: int):
        if not self._scrollable:
            return
        with contextlib.suppress(tk.TclError):
            self.viewport.yview_scroll(step, "units")
            self._draw_thumb()

    def _draw_thumb(self):
        """
        A hairline showing how much of the list is off screen, and where.

        No scrollbar widget: one would cost eleven pixels of width on a window
        this narrow and would look nothing like the rest of it.
        """
        with contextlib.suppress(tk.TclError):
            self.viewport.delete("thumb")
            if not self._scrollable:
                return
            first, last = self.viewport.yview()
            height = self.viewport.winfo_height()
            width = self.viewport.winfo_width()
            top, bottom = round(first * height), round(last * height)
            self.viewport.create_rectangle(width - 3, top + 1, width - 1, bottom - 1,
                                           fill=mix(BG, CYAN, 0.45), outline="",
                                           tags="thumb")

    def _fit(self):
        """
        Resize to fit without losing position: geometry("") hands placement back
        to the window manager and the window jumps away from where it was put.

        Width is floored because the title bar has size propagation switched off
        — with little in the body it asks for almost no width at all, and the
        window would shrink to a strip too narrow to click. In the full view the
        widest layout so far is kept, so the window stops twitching sideways as
        accounts expand and collapse; compact starts over from its own floor.

        Height is capped at the work area. Everything above the list — title
        bar, horizon, footer — is measured rather than assumed, by asking the
        window how tall it wants to be while the viewport is one pixel high; the
        remainder is what the list may use, and anything past it scrolls.

        The rounded region is reapplied here because it is cut to an exact size:
        left over from the previous layout it would clip the new one.
        """
        self.root.update_idletasks()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        wanted = self.content.winfo_reqwidth() + 16  # the viewport's own padding
        chosen = self.compact_size if self.compact else None
        if chosen:
            # A size dragged out by hand is an instruction, not a suggestion:
            # the layout adapts to it rather than the window snapping back to
            # whatever the content would like.
            width = chosen[0]
        elif self.compact:
            width = max(self.root.winfo_reqwidth(), wanted, COMPACT_WIDTH)
        else:
            width = max(self.root.winfo_reqwidth(), wanted, MIN_WIDTH, self._width)
            self._width = width

        self.viewport.configure(height=1)
        self.root.update_idletasks()
        furniture = self.root.winfo_reqheight() - 1
        listing = self.content.winfo_reqheight()

        try:
            _left, top, _right, bottom = screens.work_area(x, y, width,
                                                           listing + furniture)
            room = bottom - top - 16
        except OSError:
            room = listing + furniture

        if chosen:
            visible = max(chosen[1] - furniture, 40)
        else:
            visible = max(min(listing, room - furniture), 60)
        self._scrollable = visible < listing
        self.viewport.configure(height=visible, scrollregion=(0, 0, width, listing))
        if not self._scrollable:
            self.viewport.yview_moveto(0)
        self.root.update_idletasks()
        self._draw_thumb()
        height = furniture + visible
        resized = (width, height) != self._shape
        if resized:
            # The widget just changed its own size — most visibly on the way out
            # of compact mode, where a small card becomes a column of accounts.
            # Nobody dragged it there, so it grows from whichever corner it is
            # parked against (down-left from the top right, up-right from the
            # bottom left) and is then pulled fully inside the work area. A
            # position restored from memory is a decision already made, and only
            # gets the second step.
            if self._shape != (0, 0) and not self._restored:
                x, y = screens.anchored(x, y, *self._shape, width, height)
            x, y = screens.fit(x, y, width, height)
            self._restored = False
            self.ui_state[self._position_key()] = f"+{x}+{y}"
            self.ui_state["geometry"] = f"+{x}+{y}"

        self.root.geometry(f"{width}x{height}+{x}+{y}")

        if resized:
            self._shape = (width, height)
            self.root.update_idletasks()
            chrome.round_window(self.root.winfo_id(), width, height, CORNER_RADIUS)

    def _render_banner(self):
        kind, value = self.banner
        color = {"switched": CYAN, "switched_here": NEON,
                 "auto_switched": AMBER, "auto_switched_here": AMBER,
                 "added": NEON, "error": RED}[kind]
        text = {"switched": t("switched", email=value),
                "switched_here": t("switched", email=value),
                "auto_switched": t("auto_switched", email=value),
                "auto_switched_here": t("auto_switched", email=value),
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

        if kind in ("switched_here", "auto_switched_here"):
            # A wrapper is running: leaving agy relaunches it in that console.
            tk.Label(box, text=t("restart_in_place"), bg=CARD, fg=MUTED, font=F_TINY,
                     wraplength=280, justify="left").pack(anchor="w", padx=8, pady=(0, 8))
        elif kind in ("switched", "auto_switched"):
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

    def _card(self, master, bg: str, border: str, accent: str | None = None):
        """
        A panel with a hairline border and, optionally, a lit edge on the left.

        The edge is what separates "this is the account in use" from "this is an
        account" at a glance, without spending a colour on the whole card.
        """
        frame = tk.Frame(master, bg=bg, highlightbackground=border, highlightthickness=1)
        if accent:
            tk.Frame(frame, bg=accent, width=2).pack(side="left", fill="y")
        inner = tk.Frame(frame, bg=bg)
        inner.pack(side="left", fill="both", expand=True)
        return frame, inner

    def _is_account_expanded(self, email: str, highlighted: bool | None = None, pending: bool = False) -> bool:
        if email in self.collapsed:
            return False
        if email in self.expanded:
            return True
        if highlighted is None:
            active = self._active_account()
            highlighted = bool(active and active.get("email") == email)
        return bool(highlighted or pending)

    def _render_account(self, account: dict):
        email = account["email"]
        running, loaded, pending = account["running"], account["loaded"], account["pending"]
        # A card is highlighted for what agy is really using; when nothing is
        # known to be running, the loaded account takes that role.
        highlighted = running or (loaded and not self.state.get("tracking"))
        expanded = self._is_account_expanded(email, highlighted, pending)
        bg = CARD_ACTIVE if highlighted else CARD

        border = mix(BORDER, CYAN, 0.5) if highlighted else (AMBER if pending else BORDER)
        accent = CYAN if highlighted else (AMBER if pending else None)
        outer, card = self._card(self.content, bg, border, accent)
        outer.pack(fill="x", pady=3)

        header = tk.Frame(card, bg=bg, cursor="hand2")
        header.pack(fill="x", padx=10, pady=(7, 2))
        tk.Label(header, text="◆" if highlighted else "◇", bg=bg,
                 fg=CYAN if highlighted else (AMBER if pending else DIM),
                 font=F_SMALL).pack(side="left")
        tk.Label(header, text=email, bg=bg, fg=TEXT if highlighted else MUTED,
                 font=F_MAIL if highlighted else F_MAIN).pack(side="left", padx=(6, 0))

        tk.Label(header, text="▾" if expanded else "▸", bg=bg, fg=DIM,
                 font=F_TINY, padx=3).pack(side="right")
        if running:
            tk.Label(header, text=t("running"), bg=bg, fg=CYAN,
                     font=F_TINY).pack(side="right")
        elif pending:
            tk.Label(header, text=t("next_start"), bg=bg, fg=AMBER,
                     font=F_TINY).pack(side="right")
        elif loaded:
            tk.Label(header, text=t("loaded"), bg=bg, fg=CYAN,
                     font=F_TINY).pack(side="right")

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
            self._render_tokens(card, bg, self._account_tokens(email))
        else:
            self._render_card_summary(card, account, bg)

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

            bar = Bar(row, bg=bg)
            bar.pack(side="left", padx=(0, 8))
            bar.set(bucket["remaining"])

            remaining = bucket["remaining"]
            tk.Label(row, text="—" if remaining is None else f"{remaining * 100:.0f}%",
                     bg=bg, fg=TEXT if remaining is None else bar_color(remaining),
                     font=F_TITLE, width=5, anchor="e").pack(side="left")

            # Packed right to left: the fixed clock time sits at the edge, the
            # ticking countdown just inside it.
            tk.Label(row, text=reset_brief(bucket["reset"]), bg=bg, fg=mix(DIM, CYAN, 0.3),
                     font=F_TINY, width=6, anchor="e").pack(side="right")
            countdown = tk.Label(row, text=human_left(bucket["reset"]), bg=bg, fg=DIM,
                                 font=F_TINY, width=8, anchor="e")
            countdown.pack(side="right")
            if bucket["reset"]:
                self.countdowns.append((countdown, bucket["reset"]))

    # ── tokens ──────────────────────────────────────────────────────────────
    def _ledger(self) -> dict:
        return (self.state or {}).get("tokens") or {}

    def _account_tokens(self, email: str) -> dict[str, dict]:
        return self._ledger().get("accounts", {}).get(email, {})

    @staticmethod
    def _ordered(windows: dict[str, dict]) -> list[tuple[str, dict]]:
        return sorted(windows.items(), key=lambda item: api.WINDOW_ORDER.get(item[0], 9))

    def _render_tokens(self, card, bg: str, windows: dict[str, dict], title: bool = True):
        """
        What was actually sent and received inside each quota window.

        The bars above say how much of the window is gone; these two numbers say
        what it went on — and because Google meters weighted tokens, a big
        number here beside a small dent in the bar is the cheap model earning
        its keep.
        """
        if not windows:
            return
        if title:
            tk.Label(card, text=t("tokens"), bg=bg, fg=MUTED,
                     font=F_TITLE).pack(anchor="w", padx=10, pady=(6, 1))

        for window, figures in self._ordered(windows):
            row = tk.Frame(card, bg=bg)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=window_label(window), bg=bg, fg=DIM, font=F_SMALL,
                     width=8, anchor="w").pack(side="left")
            if not figures.get("turns"):
                tk.Label(row, text=t("no_turns"), bg=bg, fg=DIM,
                         font=F_TINY).pack(side="left")
                continue
            tk.Label(row, text=f"↑ {tokens.human(figures['sent'])}", bg=bg, fg=NEON,
                     font=F_MONO, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=f"↓ {tokens.human(figures['received'])}", bg=bg, fg=CYAN,
                     font=F_MONO, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=f"{figures['turns']}×", bg=bg, fg=DIM, font=F_TINY,
                     anchor="e").pack(side="right")

    def _render_totals(self):
        """The whole-fleet card: every account's tokens added up, plus context."""
        ledger = self._ledger()
        if not ledger:
            return
        overall = ledger.get("total") or {}
        context = ledger.get("context")
        if not overall and not context:
            return

        outer, card = self._card(self.content, CARD, BORDER, VIOLET)
        outer.pack(fill="x", pady=(6, 3))
        tk.Label(card, text=t("all_accounts"), bg=CARD, fg=TEXT,
                 font=F_TITLE).pack(anchor="w", padx=10, pady=(7, 2))

        self._render_tokens(card, CARD, overall, title=False)

        # Only the widest window is worth a line: it contains the shorter ones,
        # and unattributed work is a footnote, not a second table.
        for _window, figures in self._ordered(ledger.get("unattributed") or {})[-1:]:
            if not figures.get("turns"):
                continue
            tk.Label(card, text=t("unattributed", sent=tokens.human(figures["sent"]),
                                  received=tokens.human(figures["received"])),
                     bg=CARD, fg=DIM, font=F_TINY, wraplength=280,
                     justify="left").pack(anchor="w", padx=10)

        if context:
            self._render_context(card, context, CARD)

        since = ledger.get("since")
        if since and (datetime.now(timezone.utc) - since).days < 7:
            tk.Label(card,
                     text=t("counted_since", date=since.astimezone().strftime("%d.%m %H:%M")),
                     bg=CARD, fg=DIM, font=F_TINY, wraplength=280,
                     justify="left").pack(anchor="w", padx=10, pady=(2, 0))

        tk.Frame(card, bg=CARD, height=6).pack()

    def _render_context(self, card, context: dict, bg: str):
        """
        How full the last active conversation's context window is.

        Quota answers "how much of the week is left"; this answers the question
        the person in the console actually has — how much room is left in the
        conversation before it gets compacted.
        """
        used, limit = context.get("used", 0), context.get("limit", 0)
        if not limit:
            return
        free = max(0.0, 1.0 - used / limit)

        row = tk.Frame(card, bg=bg)
        row.pack(fill="x", padx=10, pady=(4, 1))
        tk.Label(row, text=t("context"), bg=bg, fg=DIM, font=F_SMALL, width=8,
                 anchor="w").pack(side="left")
        bar = Bar(row, bg=bg)
        bar.pack(side="left", padx=(0, 8))
        bar.set(free)
        tk.Label(row, text=f"{tokens.human(used)} / {tokens.human(limit)}", bg=bg,
                 fg=bar_color(free), font=F_MONO, anchor="w").pack(side="left")

        note = context.get("model") or ""
        age = int(context.get("age", 0))
        if age > 900:
            note = f"{note} · {t('context_idle', age=human_age(age))}".strip(" ·")
        if note:
            tk.Label(card, text=note, bg=bg, fg=DIM, font=F_TINY,
                     wraplength=280, justify="left").pack(anchor="w", padx=10)

    # ── compact ─────────────────────────────────────────────────────────────
    def _compact_layout(self) -> str:
        """
        Which shape the compact view is currently in.

        Driven by the window the user has dragged out, not by a setting: short
        and wide is a strip along the top of a screen, anything else is the
        column. Reading it off the size is what makes the change feel like part
        of the drag rather than a mode you have to choose.
        """
        width, height = self.compact_size or (COMPACT_WIDTH, COMPACT_HEIGHT)
        return "row" if height < 132 and width > 300 else "column"

    def _render_compact_view(self):
        """
        The whole widget shrunk to a heads-up display of the account in use.

        Everything in it is a way back to the full view — the card, the header,
        and an explicit button — because a widget with no visible exit is a
        widget people close.
        """
        account = self._active_account()
        if account is None:
            self._render_empty()
            return

        outer, box = self._card(self.content, CARD_ACTIVE, mix(BORDER, CYAN, 0.5), CYAN)
        outer.pack(fill="both", expand=True, pady=(2, 2))
        if self._compact_layout() == "row":
            self._compact_row(box, account)
        else:
            self._compact_column(box, account)

        for widget in (outer, box):
            widget.bind("<Button-1>", lambda _e: self._toggle_compact())

    def _compact_header(self, box, account: dict):
        """Identity on the left, the tightest window as one large number right."""
        header = tk.Frame(box, bg=CARD_ACTIVE, cursor="hand2")
        header.pack(fill="x", padx=9, pady=(6, 0))
        tk.Label(header, text="◆", bg=CARD_ACTIVE, fg=CYAN, font=F_SMALL).pack(side="left")
        # Just the local part: the domain is the same on every account and eats
        # the width this view is trying to save.
        tk.Label(header, text=account["email"].split("@")[0], bg=CARD_ACTIVE, fg=TEXT,
                 font=F_MAIN).pack(side="left", padx=(5, 0))

        worst, worst_bucket = self._worst_bucket(account)
        if worst is not None:
            tk.Label(header, text=f"{worst * 100:.0f}%", bg=CARD_ACTIVE,
                     fg=bar_color(worst), font=F_BIG).pack(side="right")

        for widget in (header, *header.winfo_children()):
            widget.bind("<Button-1>", lambda _e: self._toggle_compact())
        return worst_bucket

    def _compact_reset(self, box, bucket: dict | None):
        """
        One line: how long is left, and the moment it lands.

        Both readings sit on the same row facing each other — the countdown
        beside the label it belongs to, the wall-clock time at the right edge
        where the eye already goes for numbers. Two stacked lines said the same
        thing and cost a fifth of the card.
        """
        if not bucket or not bucket["reset"]:
            return
        row = tk.Frame(box, bg=CARD_ACTIVE)
        row.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(row, text=t("resets_at"), bg=CARD_ACTIVE, fg=MUTED,
                 font=F_SMALL).pack(side="left")
        countdown = tk.Label(row, text=human_left(bucket["reset"]), bg=CARD_ACTIVE,
                             fg=mix(MUTED, CYAN, 0.4), font=F_SMALL)
        countdown.pack(side="left", padx=(6, 0))
        self.countdowns.append((countdown, bucket["reset"]))
        tk.Label(row, text=reset_stamp(bucket["reset"]), bg=CARD_ACTIVE, fg=TEXT,
                 font=F_MONO).pack(side="right")

    @staticmethod
    def _short_group(name: str, limit: int) -> str:
        """`Claude / GPT` in a column too narrow for it becomes `Claude`."""
        if len(name) <= limit:
            return name
        head = name.split("/")[0].strip()
        return head[:limit] if head else name[:limit]

    def _compact_meters(self, box, account: dict, label_width: int = 12):
        for group in account["groups"]:
            values = [b["remaining"] for b in group["buckets"]
                      if b["remaining"] is not None]
            if not values:
                continue
            lowest = min(values)
            row = tk.Frame(box, bg=CARD_ACTIVE)
            row.pack(fill="x", padx=10, pady=1)
            tk.Label(row, text=self._short_group(group["name"], label_width),
                     bg=CARD_ACTIVE, fg=MUTED, font=F_SMALL,
                     width=label_width, anchor="w").pack(side="left")
            tk.Label(row, text=f"{lowest * 100:.0f}%", bg=CARD_ACTIVE,
                     fg=bar_color(lowest), font=F_TITLE, width=5,
                     anchor="e").pack(side="right")
            bar = Bar(row, width=60, bg=CARD_ACTIVE)
            bar.pack(side="left", fill="x", expand=True, padx=(0, 7))
            bar.set(lowest)

    def _compact_tokens(self, box, account: dict, label_width: int = 12):
        for window, figures in self._ordered(self._account_tokens(account["email"]))[:1]:
            if not figures.get("turns"):
                continue
            row = tk.Frame(box, bg=CARD_ACTIVE)
            row.pack(fill="x", padx=10, pady=(3, 0))
            tk.Label(row, text=window_label(window), bg=CARD_ACTIVE, fg=MUTED,
                     font=F_SMALL, width=label_width, anchor="w").pack(side="left")
            tk.Label(row, text=f"↑ {tokens.human(figures['sent'])}", bg=CARD_ACTIVE,
                     fg=NEON, font=F_MONO).pack(side="left")
            tk.Label(row, text=f"↓ {tokens.human(figures['received'])}", bg=CARD_ACTIVE,
                     fg=CYAN, font=F_MONO).pack(side="left", padx=(8, 0))

    def _compact_context(self, box, label_width: int = 12):
        context = self._ledger().get("context") or {}
        if not context.get("limit"):
            return
        row = tk.Frame(box, bg=CARD_ACTIVE)
        row.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(row, text=t("context"), bg=CARD_ACTIVE, fg=MUTED, font=F_SMALL,
                 width=label_width, anchor="w").pack(side="left")
        tk.Label(row, text=tokens.human(context["used"]), bg=CARD_ACTIVE, fg=VIOLET,
                 font=F_MONO, width=6, anchor="e").pack(side="right")
        bar = Bar(row, width=50, height=6, bg=CARD_ACTIVE)
        bar.pack(side="left", fill="x", expand=True, padx=(0, 7))
        bar.set(max(0.0, 1.0 - context["used"] / context["limit"]))

    def _compact_column(self, box, account: dict):
        """The tall shape: identity, meters, tokens, context, one under another."""
        bucket = self._compact_header(box, account)
        self._compact_reset(box, bucket)

        if account["error"]:
            tk.Label(box, text=t("revoked") if account["error"] == "reauth"
                     else account["error"], bg=CARD_ACTIVE, fg=AMBER, font=F_SMALL,
                     wraplength=240, justify="left").pack(anchor="w", padx=10, pady=(2, 8))
        else:
            self._compact_meters(box, account)
            self._compact_tokens(box, account)
            self._compact_context(box)
            tk.Frame(box, bg=CARD_ACTIVE, height=5).pack()

        self._compact_footer()

    def _compact_row(self, box, account: dict):
        """
        The wide shape: a strip that can live along the top of a screen.

        The same readings, turned on their side — identity and the big number in
        one column, the meters in the next, tokens and reset in the last — so
        dragging the window wide gives back height instead of stretching one
        narrow card into a wide empty one.
        """
        strip = tk.Frame(box, bg=CARD_ACTIVE)
        strip.pack(fill="both", expand=True, padx=2, pady=4)

        left = tk.Frame(strip, bg=CARD_ACTIVE, cursor="hand2")
        left.pack(side="left", fill="y", padx=(6, 10))
        tk.Label(left, text=account["email"].split("@")[0], bg=CARD_ACTIVE, fg=TEXT,
                 font=F_SMALL).pack(anchor="w")
        worst, bucket = self._worst_bucket(account)
        if worst is not None:
            tk.Label(left, text=f"{worst * 100:.0f}%", bg=CARD_ACTIVE,
                     fg=bar_color(worst), font=F_BIG).pack(anchor="w")
        for widget in (left, *left.winfo_children()):
            widget.bind("<Button-1>", lambda _e: self._toggle_compact())

        # The way back sits at the far edge: in this shape there is no room for
        # the footer button, and a view you can only leave through the title bar
        # is a view people get stuck in.
        back = tk.Label(strip, text="▤", bg=CARD_ACTIVE, fg=MUTED, font=F_MAIN,
                        cursor="hand2", padx=4)
        back.pack(side="right", fill="y")
        back.bind("<Button-1>", lambda _e: self._toggle_compact())
        back.bind("<Enter>", lambda e: e.widget.configure(fg=CYAN))
        back.bind("<Leave>", lambda e: e.widget.configure(fg=MUTED))
        Tooltip(back, t("tip_expand"))

        middle = tk.Frame(strip, bg=CARD_ACTIVE)
        middle.pack(side="left", fill="both", expand=True)
        if account["error"]:
            tk.Label(middle, text=t("revoked") if account["error"] == "reauth"
                     else account["error"], bg=CARD_ACTIVE, fg=AMBER, font=F_SMALL,
                     wraplength=200, justify="left").pack(anchor="w")
            return
        self._compact_meters(middle, account, label_width=7)

        right = tk.Frame(strip, bg=CARD_ACTIVE)
        right.pack(side="left", fill="y", padx=(8, 4))
        if bucket and bucket["reset"]:
            countdown = tk.Label(right, text=human_left(bucket["reset"]), bg=CARD_ACTIVE,
                                 fg=mix(MUTED, CYAN, 0.4), font=F_SMALL, anchor="e")
            countdown.pack(anchor="e")
            self.countdowns.append((countdown, bucket["reset"]))
            tk.Label(right, text=reset_stamp(bucket["reset"]), bg=CARD_ACTIVE, fg=TEXT,
                     font=F_MONO, anchor="e").pack(anchor="e")

        # Tokens are the first thing to go when the strip is dragged thin:
        # three lines do not fit in ninety pixels, and the reset time is the
        # one people keep this shape open for.
        if (self.compact_size or (0, 0))[1] < 112:
            return
        for _window, figures in self._ordered(
                self._account_tokens(account["email"]))[:1]:
            if not figures.get("turns"):
                continue
            tk.Label(right, text=f"↑ {tokens.human(figures['sent'])}  "
                                 f"↓ {tokens.human(figures['received'])}",
                     bg=CARD_ACTIVE, fg=MUTED, font=F_MONO, anchor="e").pack(anchor="e")

    def _compact_footer(self):
        """The way out, spelled out, with hiding next to it."""
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(3, 5))
        self._button(row, t("expand_all"), self._toggle_compact,
                     small=True).pack(side="left")
        if self.tray:
            hide = tk.Label(row, text="▁", bg=BG, fg=MUTED, font=F_MAIN, cursor="hand2",
                            padx=6)
            hide.pack(side="right")
            hide.bind("<Button-1>", lambda _e: self._hide_to_tray())
            hide.bind("<Enter>", lambda e: e.widget.configure(fg=CYAN))
            hide.bind("<Leave>", lambda e: e.widget.configure(fg=MUTED))
            Tooltip(hide, t("tip_tray"))

    @staticmethod
    def _worst_bucket(account: dict) -> tuple[float | None, dict | None]:
        """The bucket closest to running out, across every group."""
        candidates = [(b["remaining"], b) for group in account.get("groups", [])
                      for b in group.get("buckets", []) if b.get("remaining") is not None]
        if not candidates:
            return None, None
        return min(candidates, key=lambda pair: pair[0])

    def _render_card_summary(self, card, account: dict, bg: str):
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
            bar = Bar(row, width=110, bg=bg)
            bar.pack(side="left", padx=(0, 8))
            bar.set(worst)
            tk.Label(row, text=f"{worst * 100:.0f}%", bg=bg, fg=bar_color(worst),
                     font=F_TITLE, width=5, anchor="e").pack(side="left")

        # One line of tokens even when the card is closed: an account resting at
        # 100 % that was hammered earlier in the week is worth seeing without
        # opening it.
        for _window, figures in self._ordered(self._account_tokens(account["email"]))[-1:]:
            if not figures.get("turns"):
                continue
            row = tk.Frame(card, bg=bg)
            row.pack(fill="x", padx=10, pady=(2, 0))
            tk.Label(row, text=t("tokens"), bg=bg, fg=DIM, font=F_TINY, width=14,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"↑ {tokens.human(figures['sent'])}   "
                               f"↓ {tokens.human(figures['received'])}",
                     bg=bg, fg=MUTED, font=F_MONO, anchor="w").pack(side="left")

    def _toggle_account(self, email: str):
        if self._is_account_expanded(email):
            self.collapsed.add(email)
            self.expanded.discard(email)
        else:
            self.collapsed.discard(email)
            self.expanded.add(email)
        self.ui_state["collapsed"] = sorted(self.collapsed)
        self.ui_state["expanded"] = sorted(self.expanded)
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
