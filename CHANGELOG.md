# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

Entries under **Compatibility** name the Antigravity version that forced the
change, so it is possible to tell at a glance whether an upgrade is required.

## [1.1.0] — 2026-08-13

Verified against Antigravity CLI **1.1.11**.

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
- **A portable executable.** `python scripts/build_exe.py` produces
  `dist/Lagrange.exe` — one file, no console, no Python needed on the machine
  that runs it. `--onedir` builds a folder instead, which starts faster.
- Hover labels on the title-bar buttons, which were previously bare glyphs.
- A balloon the first time the widget hides itself, because Windows 11 files new
  tray icons under the overflow chevron and an icon nobody can find reads as a
  crash. Restoring also forces the window to the front for a few seconds even
  when the pin is off — coming back behind a maximised console is
  indistinguishable from not coming back.
- `scripts/make_icon.py` builds `assets/lagrange.ico` from the same code that
  draws the tray gauge, so there is no binary icon in the repository.

### Changed

- The title bar is now 📌 pin, ▭ compact, ▁ hide to tray, ✕ quit. The old
  collapse-to-title-bar button is gone: compact does the same job and still
  shows the numbers.
- Quitting from the tray, or with ✕, shuts the refresh loop down cleanly instead
  of leaving a scheduled callback to fire into a destroyed window.

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
