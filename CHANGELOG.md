# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

Entries under **Compatibility** name the Antigravity version that forced the
change, so it is possible to tell at a glance whether an upgrade is required.

## [1.1.0] — 2026-08-13

Verified against Antigravity CLI **1.1.12**.

### Added

- **Tray icon.** The widget can be hidden to the notification area and brought
  back with a click. The icon is a gauge of the tightest remaining window on the
  active account — green, amber or red — and its tooltip lists every number, so
  the state is readable with the widget closed. Right-click gives Show, Always
  on top, Refresh now and Quit.
- **Compact mode.** One button shrinks the widget to the account actually in
  use: one line of identity and one bar per model group, showing that group's
  tightest window and its reset. Clicking it goes back to the full view. The
  choice is remembered.
- **Two ready-to-run downloads**, neither needing Python: a single portable
  `.exe`, and a folder build zipped, which starts faster because it has nothing
  to unpack. `python scripts/build_exe.py --release` produces both.
- **A window that cannot open where no monitor is.** A position saved on one
  display arrangement used to be restored blindly onto another: the window
  opened outside every screen, reported itself visible, and was never seen.
  `screens.py` now moves it back into view — but only when no monitor shows any
  part of it, so a window dragged half off an edge is left where it was put.
- Hover labels on the title-bar buttons, which were previously bare glyphs.
- A balloon the first time the widget hides itself, because Windows 11 files new
  tray icons under the overflow chevron and an icon nobody can find reads as a
  crash. Restoring also forces the window to the front for a few seconds even
  when the pin is off — coming back behind a maximised console is
  indistinguishable from not coming back.
- `scripts/make_icon.py` builds `assets/lagrange.ico` from the same code that
  draws the tray gauge, so there is no binary icon in the repository.

### Changed

- The thing you download is called **Lagrange Widget**; the package, the CLI and
  the repository stay `lagrange`.
- The title bar is now 📌 pin, ▭ compact, ▁ hide to tray, ✕ quit. The old
  collapse-to-title-bar button is gone: compact does the same job and still
  shows the numbers.
- Quitting from the tray, or with ✕, shuts down in order: scheduled callbacks
  cancelled, icon removed, its thread joined, then the window destroyed. Before,
  the tray thread could be dispatching into a window procedure Python had
  already collected — an access violation on the way out.
- Launching Lagrange a second time re-opens a hidden window instead of only
  raising a visible one, which is the way back when the tray icon is not where
  you expect it.

## [1.0.0] — 2026-08-09

First release. Verified against Antigravity CLI **1.1.11**.

### Added

- Live quota from `v1internal:retrieveUserQuotaSummary` — the same call
  Antigravity uses for its own indicator. Five-hour and weekly windows for both
  model groups, with reset times.
- Quota for every stored account at once, refreshed offline with each account's
  own token, so you can see where you stand before switching.
- Account switching through the Windows Credential Manager entry `agy` actually
  reads.
- `lagrange run` — a wrapper that restarts Antigravity **in the same console**
  after a switch, resuming the conversation with `--continue`. A running session
  is never interrupted; the restart happens when you leave `agy`.
- Separate reporting of the **loaded** account and the **running** one, so the
  widget never claims a switch has taken effect while the console is still on
  the previous account.
- Browser sign-in for additional accounts that leaves the active account alone.
- `lagrange doctor` — per-assumption diagnostics with redacted output, meant to
  be pasted into an issue.
- `lagrange list`, `switch`, `add`, `forget`.
- PowerShell installer that creates a shortcut and wires existing Antigravity
  launchers, backing each one up first.
- Overrides in `~/.lagrange/config.json` for every value that could be renamed
  upstream.

### Security

- OAuth client credentials are read from the local `agy.exe` at runtime and
  validated against Google before use. They are not committed to this
  repository.
- All tokens stay in Windows Credential Manager. On disk Lagrange keeps only
  email addresses, window position, and cached discovery results.
