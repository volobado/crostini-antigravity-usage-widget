# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

Entries under **Compatibility** name the Antigravity version that forced the
change, so it is possible to tell at a glance whether an upgrade is required.

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
