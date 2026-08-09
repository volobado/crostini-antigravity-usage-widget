# When Antigravity changes

Lagrange depends on internals Google never promised to keep. It is built so that
a change upstream costs you a config line, not a working tool — and so that
`lagrange doctor` tells you which line.

Start here:

```
lagrange doctor
```

Every check below maps to one line of that report. Each says what broke, what
still works, and how to patch it yourself before a release lands.

---

## `[FAIL] agy.exe — not found`

**Means.** Antigravity moved, or was installed somewhere unusual.

**Still works.** Nothing. The OAuth client is read from this binary.

**Patch.** Point at it:

```json
{ "agy_path": "D:\\tools\\agy\\bin\\agy.exe" }
```

in `~/.lagrange/config.json`. If it now lives in a location that others would
hit too, please open an issue — the search list in `discovery._AGY_CANDIDATES`
should learn it.

---

## `[warn] agy.exe — version X (verified against 1.1.11)`

**Means.** Antigravity updated. This is a notice, not a fault.

**What to do.** Nothing, unless another check also complains. If everything else
is green, the new build is compatible; mention the version in an issue so the
README can say so.

---

## `[FAIL] credential entry — no Credential Manager entry ...`

**Means.** Either Antigravity is not signed in, or it renamed the vault entry.

**Check first.** Start `agy` and sign in, then re-run doctor. Most of the time
that is all it is.

**If it is a rename.** Lagrange already sweeps the vault for an entry with
Antigravity's token shape, so this only fires when the *shape* changed too —
worth an issue. Find the entry by hand:

```powershell
cmdkey /list | Select-String -Pattern "gemini|antigravity"
```

and set it:

```json
{ "agy_cred_target": "gemini:antigravity-v2" }
```

---

## `[warn] credential entry — found 'X', expected 'Y'`

**Means.** The entry was renamed and Lagrange found it anyway.

**Still works.** Everything.

**What to do.** Open an issue with both names so the default can be updated.

---

## `[FAIL] live token — blob is missing ...`

**Means.** The credential format changed — different field names, or a different
structure entirely.

**Still works.** Nothing that needs a token.

**Patch.** Not configurable; the shape is parsed in `api.build_cred` and read in
`accounts.read_live_cred`. Open an issue and paste the *shape* of the blob, keys
only, never values:

```powershell
python -c "import json;from lagrange import accounts;c=accounts.read_live_cred();print(sorted(c),sorted(c['token']))"
```

---

## `[FAIL] oauth client — could not read client credentials from agy.exe`

**Means.** The client id or secret is no longer a plain string in the binary —
obfuscated, moved to a resource, or fetched at runtime.

**Still works.** Nothing that needs a token refresh, which is nearly everything.

**Patch.** Supply the pair yourself. You can recover it from a network capture
of Antigravity signing in, or from your own Google Cloud OAuth client if you are
prepared to consent again:

```json
{
  "client_id": "...apps.googleusercontent.com",
  "client_secret": "..."
}
```

Keep it out of screenshots and issues.

---

## `[FAIL] oauth client validated — no credentials were accepted by Google`

**Means.** Candidates were found but Google rejected all of them — usually a
rotation, sometimes a revoked account being used as the test subject.

**Patch.** Clear the cached pair so discovery starts over:

```
python -c "from lagrange import discovery; discovery.forget_validated_client()"
```

Then re-run doctor. If it still fails on a fresh Antigravity install, that is a
genuine rotation — open an issue.

---

## `[warn] quota endpoint — binary offers [...], config uses '...'`

**Means.** The quota RPC was renamed. Lagrange read the new name out of the
binary but is still calling the old one, because silently switching endpoints is
not a decision a status widget should make on its own.

**Still works.** Everything except quota, which will start failing.

**Patch.** Adopt the name doctor printed:

```json
{ "quota_summary_method": "v1internal:retrieveUserQuotaSummaryV2" }
```

Host changes go in `quota_host` the same way.

---

## `[warn] quota · account — response had no groups; top-level keys: [...]`

**Means.** The response schema changed.

**Still works.** Everything else; that account shows no bars.

**Already handled.** A payload with bare `buckets` instead of `groups` is
wrapped automatically, and unknown window names render as themselves. So this
only fires on a genuinely new shape.

**Patch.** Not configurable. Open an issue with the key structure — no values:

```
lagrange doctor --json
```

---

## `[warn] quota · account — refresh token rejected`

**Means.** That one account revoked access, changed its password, or went
untouched long enough for Google to expire the grant.

**Still works.** Every other account.

**Fix.** Press **Sign in again** in the widget, or `lagrange add`, and pick the
same account.

---

## `[warn] config overrides — {...}`

Not a fault: a reminder that you are running with a patch applied. When a
release makes it unnecessary, delete the key so you go back to tracking
upstream.

---

## Reporting a break

Open a **compatibility** issue with:

1. `lagrange doctor --json` — redacted by design, safe to paste.
2. Your Antigravity version (`agy --version`).
3. What you were doing.

The report is usually the whole diagnosis: it says which layer moved, and the
sections above say what to change.

## For maintainers

A release that adapts to an upstream change should:

1. Move the default in `config.DEFAULTS`, so nobody needs the override.
2. Bump `VERIFIED_AGY_VERSION` in `lagrange/__init__.py`.
3. Add a `doctor` check if the break was silent — every failure mode above
   exists because something once failed without saying so.
4. Note it in `CHANGELOG.md` under **Compatibility**, naming the Antigravity
   version that forced it.
