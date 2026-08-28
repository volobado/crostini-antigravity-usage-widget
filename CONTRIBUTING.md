# Contributing

Thanks for looking. Lagrange is small on purpose, so most changes are small too.

## Before anything else

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Everything here rests on
undocumented details of somebody else's binary, and knowing which parts are
assumptions saves you from breaking them by accident.

## Running from a clone

```
git clone https://github.com/Vovka666/antigravity-gemini-usage.git
cd lagrange
bin\lagrange.cmd doctor
bin\lagrange.cmd widget
```

No dependencies to install. Python 3.10+ with tkinter, on Windows.

## House rules

- **Standard library only.** A status widget that breaks because of someone
  else's release is not doing its job.
- **Degrade, never disappear.** A failed network call, a revoked account or a
  renamed endpoint must leave the widget standing and say what happened. The
  broad `except` clauses in the worker thread and in discovery are deliberate.
- **Never print a secret.** Not in the UI, not in logs, not in `doctor`.
  Lengths and last characters only.
- **Assume upstream changed.** If you add a constant that comes from
  Antigravity, add a `doctor` check for it and a `config` key to override it.
- **English in the interface.** Translations live in `i18n.py` and are opt-in
  through `"language"` in `~/.lagrange/config.json`; the default stays English
  so a screenshot in an issue matches the code.

## Testing

There is no unit test suite. Nearly every interesting behaviour is an assumption
about `agy.exe`, and a mock would only assert that the assumption agrees with
itself. What a change needs instead:

```
lagrange doctor        every layer against a live install
lagrange list          quota reads for each account
```

If you touched switching, do the real thing: start `lagrange run`, switch in the
widget, `/exit`, and confirm two things — the newest log in
`~/.gemini/antigravity-cli/log/` shows `applyAuthResult` with the new address,
and **no new console window appeared**.

If you touched the widget, check it compact as well as full, hidden to the tray
and brought back, and with a fresh profile (no `~/.lagrange/ui.json`).

Regenerate the documentation screenshot with fabricated accounts — never a real
one:

```
python scripts/make_screenshot.py
```

## Reporting a compatibility break

Antigravity updates will break things. Open a **compatibility** issue with
`lagrange doctor --json` attached; that report is redacted by design and usually
contains the whole diagnosis. [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)
lists each failure and how to patch it locally in the meantime.

## Pull requests

- One change per PR.
- Say which Antigravity version you tested against.
- Update `CHANGELOG.md`. Upstream-driven fixes go under **Compatibility** and
  name the version that forced them.
- If you moved a default, bump `VERIFIED_AGY_VERSION` in `lagrange/__init__.py`
  when it reflects a newer build.

## Scope

In scope: quota, accounts, switching, and staying compatible.

Out of scope, unless it earns its keep: anything that adds a dependency, a
background service, telemetry, or a second thing to configure. The tool should
stay something you can read in an afternoon.
