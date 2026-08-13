# Architecture

What Lagrange assumes about Antigravity, how each assumption was established,
and where it lives in the code. Read this before changing anything that touches
credentials or the quota API.

## What was found in Antigravity

None of this is documented by Google. It was established by reading `agy.exe`
1.1.11, its logs, and its network calls on a live install.

### Credentials are in Windows Credential Manager, not in a file

`agy` keeps its OAuth token in the Windows vault under the generic credential
`gemini:antigravity`, as UTF-8 JSON:

```json
{
  "token": {
    "access_token": "...",
    "token_type": "Bearer",
    "refresh_token": "1//...",
    "expiry": "2026-08-09T17:14:21.836549+02:00"
  },
  "auth_method": "consumer"
}
```

The `~/.gemini/oauth_creds.json` and `~/.gemini/google_accounts.json` files that
older tooling copies around belong to the separate `gemini` CLI. On a machine
where both are installed they drift apart within days — the observation that
started this project was `oauth_creds.json` naming one account while the log of
a running `agy` reported another.

Code: `credstore.py`, `accounts.py`.

### Quota comes from an internal Cloud Code endpoint

```
POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary
Authorization: Bearer <access_token>
{}
```

```json
{
  "groups": [
    {
      "displayName": "Gemini Models",
      "description": "Models within this group: Gemini Flash, Gemini Pro",
      "buckets": [
        { "bucketId": "gemini-weekly", "window": "weekly",
          "resetTime": "2026-08-12T11:46:47Z", "remainingFraction": 0.9797244,
          "description": "You have used some of your weekly limit..." },
        { "bucketId": "gemini-5h", "window": "5h",
          "resetTime": "2026-08-09T19:15:32Z", "remainingFraction": 0.9678946 }
      ]
    },
    { "displayName": "Claude and GPT models", "buckets": [ ... ] }
  ]
}
```

Two model groups, each metered over a five-hour and a weekly window, in weighted
tokens (`tokenType: "WTUS"`). There is **no** daily request limit, and no
meaningful relationship between one prompt and one unit of anything — a single
agent turn produces dozens of internal calls.

A sibling endpoint, `v1internal:retrieveUserQuota`, returns the same picture
broken down per model. Lagrange exposes it as `api.fetch_quota_detail` for
diagnosis but does not show it.

Both endpoints also answer on `daily-cloudcode-pa.googleapis.com`, which appears
to be a staging ring. Lagrange prefers the plain host.

Code: `api.py`.

### The OAuth client is an installed-app client inside the binary

`agy.exe` carries a client id and secret and uses a loopback redirect
(`http://localhost:<port>/callback`). Lagrange authenticates with the same
client, which is why the tokens it mints are accepted by the Antigravity
backend.

**The repository ships neither value.** They are read out of the copy of
`agy.exe` on the user's machine at runtime and validated against Google before
use. That keeps Google's credentials out of a public repo and survives rotation:
if Google changes them, the next run finds the new pair.

Code: `discovery.py`.

### A running `agy` never re-reads its credential

Verified directly: start `agy`, swap the vault entry underneath it, wait through
a quota refresh cycle, and its log still contains exactly one
`applyAuthResult: email=...` — the account it started with. The credential is
read once, at launch.

This is the reason `lagrange run` exists. Switching accounts requires a restart;
the only question is whether the user loses the console they were working in.

Code: `runner.py`, `session.py`.

## The pieces

```
config.py      paths, defaults, ~/.lagrange/config.json overrides
credstore.py   CredRead / CredWrite / CredDelete / CredEnumerate via ctypes
discovery.py   find agy.exe, lift + validate OAuth client, locate the vault entry
api.py         Google endpoints, credential blob format, response normalisation
accounts.py    account store, switching, offline refresh, state for the UI
session.py     handshake between widget and wrapper; which console runs what
runner.py      `lagrange run` — restarts agy in place after a switch
ui.py          the Tkinter widget
tray.py        notification-area icon and its message loop, via ctypes
i18n.py        interface strings
doctor.py      per-assumption diagnostics
__main__.py    CLI
```

Dependency direction is one way: `ui` and `runner` depend on `accounts`, which
depends on `api`, `discovery` and `credstore`, all of which depend on `config`.
`ui` also owns `tray`, which depends on nothing. Nothing depends on `ui`.

## The tray

Windows delivers notification-area callbacks to a window, and a window belongs
to the thread that created it — so `tray.py` runs its own thread with its own
message loop, and the only thing it does with an event is put a name on the
queue the Tk loop already drains. Nothing outside that thread calls
`Shell_NotifyIcon`, and nothing inside it touches Tk.

Three details that are easy to get wrong:

- **Not a message-only window.** `HWND_MESSAGE` windows are skipped by the
  `TaskbarCreated` broadcast, so the icon would never return after an Explorer
  restart. An ordinary window that is simply never shown does receive it.
- **Every ctypes prototype is declared.** Without `restype`, ctypes assumes a C
  int, and a 64-bit `HBITMAP` comes back truncated — `int too long to convert`
  at best, a silently wrong handle at worst.
- **The icon is drawn, not shipped.** `gauge_pixels` renders a ring filled
  clockwise by the tightest remaining window, supersampled for anti-aliasing,
  and the same function builds `assets/lagrange.ico` for the executable. One
  mark, no binary asset in the repository.

If the tray cannot start, the widget simply does not offer to hide: a borderless
window has no taskbar button either, and a widget you cannot get back is worse
than one that is always on screen.

## Packaging

`scripts/build_exe.py` freezes `scripts/widget_entry.py` with PyInstaller into a
single windowed executable. PyInstaller is a build-time tool only — the widget
itself still imports nothing outside the standard library. The CLI stays a
console program installed with pip: `lagrange run` needs a console to run
Antigravity in, which a windowed executable does not have.

## Two truths about "the current account"

The widget reports these separately, because merging them produced the first
bug this project shipped:

- **loaded** — the account written into `gemini:antigravity`. A switch changes
  it immediately.
- **running** — the account an open Antigravity console actually started under.
  It only changes when `agy` restarts.

Right after a switch these disagree, and the console banner still shows the old
address. The widget marks that state `NEXT START` rather than claiming the new
account is active.

`running` is known because `lagrange run` records the account into its session
file at every launch. Session files carry the wrapper's pid and are ignored —
and deleted — once that process is gone, so a console closed with the X button
cannot leave a ghost claiming to run something.

## Switching, end to end

1. Widget calls `accounts.switch_to(email)`: the stored copy is written over
   `gemini:antigravity`, after syncing the outgoing account's latest token back
   into its own slot.
2. `session.request_restart(email)` raises a flag — but only if a wrapper is
   actually running, so a switch made with no console open cannot surprise the
   next one.
3. Nothing is interrupted. The running `agy` keeps its account and finishes
   whatever it was doing.
4. When the user leaves `agy`, `runner` sees the flag, clears it, and relaunches
   in the same console with `--continue`.

## Reading quota for accounts that are not active

Each stored copy carries its own refresh token, so `accounts.valid_access_token`
can mint an access token for any account without touching the live entry. That
is what makes it possible to see where every account stands before switching —
the feature the whole widget exists for.

Refreshed tokens are written back to that account's slot, and to
`gemini:antigravity` as well when it happens to be the active one, so `agy` and
Lagrange never fight over an expiring token.

## Where secrets live

| | |
|---|---|
| Windows Credential Manager | every account's tokens, in Antigravity's own format |
| `~/.lagrange/accounts.json` | email addresses and display names |
| `~/.lagrange/config.json` | overrides; `client_id`/`client_secret` only if set by hand |
| `~/.lagrange/discovered.json` | agy signature, endpoint names, validated client pair |
| `~/.lagrange/ui.json` | window position |
| `~/.lagrange/sessions/` | pid and account per open console |

`discovered.json` is the one file that can hold a client secret, and only
because it caches what was read from the local binary. It never leaves the
machine, and `lagrange doctor` prints lengths and last characters rather than
values.

## Testing against a live install

There are no unit tests worth the name here: everything interesting is an
assumption about somebody else's binary, and a mock would only assert that the
assumption matches itself. What is worth doing before a release:

```
lagrange doctor              every layer, end to end
lagrange list                quota for each account
lagrange run                 switch from the widget, /exit, confirm the same
                             console comes back on the new account
```

For the switch, the check that matters is the newest log in
`~/.gemini/antigravity-cli/log/`: it must show `applyAuthResult` with the new
address, and no new console window may have appeared.
