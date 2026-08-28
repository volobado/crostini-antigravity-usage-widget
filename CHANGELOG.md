# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

Entries under **Compatibility** name the Antigravity version that forced the
change, so it is possible to tell at a glance whether an upgrade is required.

## [1.2.1] — 2026-08-28

### Changed

- **The product now says what it is: "Lagrange - Gemini CLI (agy) Usage".** One
  word named after a point in space is not something anyone finds when they go
  looking for a quota widget, so the full name — with what it measures and what
  it measures it for — is now in the window title, the tray, the shortcut, the
  executable's properties and the top of this README. The wordmark in the title
  bar keeps its `L A G R A N G E`, with a line under it saying which Lagrange
  this is. The package, the CLI and the repository stay `lagrange`.

## [1.2.0] — 2026-08-28

Verified against Antigravity CLI **1.1.22**.

### Added

- **Tokens, not just percentages.** Every card now says what the account
  actually sent and received inside each quota window, and a new *All accounts*
  card adds the fleet up. Google's quota endpoint reports only a remaining
  fraction and never a token count, so the figures come from Antigravity's own
  conversation files, where each model turn records what it cost. Field numbers
  were confirmed against `agy -p --output-format json`, whose `usage` block the
  per-turn readings reproduce exactly.
- **Attribution by account.** Antigravity has one credential slot and never
  writes down whose it is, so Lagrange — the thing that moves the credential —
  keeps a timeline of which account was loaded when, and attributes each turn to
  whoever paid for it. Work from before the ledger existed is reported as
  unattributed rather than guessed at. On first run the timeline starts at the
  last switch Lagrange recorded, so recent days are not thrown away.
- **Context depth.** The last active conversation's context window is shown as a
  bar: how full it is against the model's limit. Quota says how much of the week
  is left; this says how close the conversation in the console is to being
  compacted.
- **`lagrange usage`.** The same figures on the command line, with `--by-day [N]`
  and `--by-model` for a longer view. Models are grouped by name, because
  Antigravity gives one model a different numeric id per reasoning effort.
- Three configuration keys: `track_tokens` (on by default), `conversations_dir`
  (empty means "find it") and `token_history_days` (90; `0` keeps everything).

- **Account order, and optional auto-switching.** `account_priority` puts the
  accounts in the order you want them used — in the list and in the switch — and
  with `auto_switch` on, Lagrange loads the next account with headroom once the
  loaded one's five-hour window is nearly spent, so a session never drains an
  account to zero. Nothing is interrupted: the running console finishes on the
  account it started with, and the new one applies at the next `agy` start.
  `auto_switch_pool` keeps the widget away from accounts another tool is
  driving. Off by default; switches made this way are recorded as `auto`.

### Changed

- **A new face.** Deep-space ground, one neon accent per state, meters drawn as
  gradients over a ticked track, and a green-cyan-violet hairline under the
  title bar that pulses when fresh figures land. The title sits on a star field
  that breathes slowly, crossed every twelve seconds by a scan sweep. All of it
  is Tk primitives — no images, no dependencies — and `"effects": false` in
  `~/.lagrange/config.json` leaves the same layout drawn flat and completely
  still.
- **Rounded corners.** The borderless window is clipped to a rounded rectangle.
  Windows is asked for its own corner preference first, but the shape is
  guaranteed by a window region, reapplied whenever the layout changes size.
- **Compact mode is a heads-up display again.** The tightest window as one large
  number, a meter per model group, the tokens spent in the last five hours, and
  the conversation's context depth — in a window 268 pixels wide. It carries its
  own **All accounts** button and its own hide control, so the small view is a
  complete instrument rather than a dead end.
- **Compact resizes, and changes shape when it does.** Drag the right edge, the
  bottom, or the corner: the meters stretch with the window, the size is
  remembered, and short-and-wide switches to a strip layout — identity and the
  big number on the left, meters in the middle, reset time and tokens on the
  right — so a window dragged along the top of a screen reads as one line
  instead of a stretched card. Below ninety pixels of height the tokens step
  aside and the reset time stays.
- **The window grows in the right direction.** Opening the full view used to
  expand down and to the right from wherever the small one sat, which walked it
  off the bottom of the screen and had to be dragged back. It now keeps the
  corner it is parked against — from the bottom right it grows up and to the
  left — and each size remembers its own position, so collapsing puts the small
  window back exactly where it was left.
- **Reset times, not just countdowns.** Every window now carries the moment it
  actually refills beside the ticking countdown — the clock time when that falls
  today, a short date without the year (`Sep 4`) when it does not. Compact
  spells it out under the big number as *resets at 17:18 · today*. A countdown
  answers "how long do I wait"; this answers "can I start this tonight".
- **The account list scrolls.** On a work area shorter than the full list — six
  accounts already need a metre of screen — the window is capped at what fits
  and the list scrolls under the wheel, with a hairline showing where you are.
  Nothing is reachable only by dragging the window off the desktop any more.

### Notes

- Reading is incremental and read-only: a conversation whose file has not
  changed is skipped, and one that grew is read past the step already stored. A
  first full scan of five hundred conversations takes about a second and a half;
  every scan after that is negligible.
- The ledger is an addition, not a precondition. If Antigravity is not installed,
  its files move, or the ledger database cannot be opened, the quota bars draw
  exactly as before.

## [1.1.1] — 2026-08-13

Verified against Antigravity CLI **1.1.12**.

### Fixed

- **A dropped HTTPS connection no longer looks like a broken account.** Google's
  frontend — or anything inspecting TLS on the way to it: antivirus, a VPN, a
  home router — occasionally closes a connection mid-handshake, which OpenSSL
  reports as `[SSL: UNEXPECTED_EOF_WHILE_READING]`. That diagnostic used to land
  in the card where the quota bars belong. Every request is now retried three
  times with a short backoff, which is enough for a blip; requests that still
  fail report one line saying the connection is down, and the card keeps the
  last figures Google actually gave, labelled with their age. Retries cover
  timeouts, reset sockets, DNS failures and 5xx responses too. A `400`/`401` is
  still a verdict and is never retried, so a revoked account is reported as
  promptly as before.
- **A network blip during OAuth client validation no longer walks the whole
  candidate list.** It used to be able to end in "no credentials were accepted"
  on a good install; the search is now aborted instead.

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
