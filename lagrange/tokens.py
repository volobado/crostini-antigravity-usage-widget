"""
The token ledger: what each account actually sent and received.

Two halves of one picture live apart. Google knows how much of a quota window
is gone but reports it only as a fraction, and Antigravity knows the tokens but
not which account they were spent on — it reads whatever credential the machine
holds at the time and never writes the address down. Lagrange is the only thing
that sees both, because it is what moves the credential.

So the ledger is built from three sources:

  * `agylog` — every model turn Antigravity recorded, with its token counts and
    the second it happened;
  * a timeline of which account was loaded when, written on every switch and on
    every refresh, so a turn can be attributed to the account that paid for it;
  * the quota buckets, which say where each window began — a weekly bucket
    resetting on Tuesday started seven days before that, and "spent this window"
    means the turns since.

Turns from before Lagrange started keeping the timeline — or from a stretch when
the widget was closed and the credential moved anyway — are kept as
unattributed rather than guessed at, and reported separately.

Everything here degrades quietly. The ledger is an addition to the widget, not
a precondition for it: if the database cannot be opened, quota still draws.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import agylog, config

LEDGER_FILE = os.path.join(config.DATA_DIR, "tokens.db")

# How far back a quota window reaches from its reset time. Anything Google adds
# later is skipped rather than mis-measured.
WINDOW_SECONDS = {
    "5h": 5 * 3600,
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
    "monthly": 30 * 24 * 3600,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    conversation TEXT NOT NULL,
    step         INTEGER NOT NULL,
    ts           INTEGER NOT NULL,
    model        INTEGER NOT NULL DEFAULT 0,
    sent         INTEGER NOT NULL DEFAULT 0,
    received     INTEGER NOT NULL DEFAULT 0,
    thinking     INTEGER NOT NULL DEFAULT 0,
    cached       INTEGER NOT NULL DEFAULT 0,
    account      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (conversation, step)
);
CREATE INDEX IF NOT EXISTS turns_ts ON turns(ts);
CREATE TABLE IF NOT EXISTS sources (
    conversation TEXT PRIMARY KEY,
    mtime        REAL NOT NULL,
    size         INTEGER NOT NULL,
    last_step    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS timeline (
    ts      INTEGER PRIMARY KEY,
    account TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS models (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
"""


def enabled() -> bool:
    return bool(config.get("track_tokens"))


def _connect() -> sqlite3.Connection:
    config.ensure_data_dir()
    connection = sqlite3.connect(LEDGER_FILE, timeout=5)
    connection.executescript(_SCHEMA)
    return connection


@contextlib.contextmanager
def _ledger():
    """
    An open ledger that always closes.

    sqlite3's own context manager commits but leaves the connection open, and
    the widget runs for days — a handle leaked per refresh adds up.
    """
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


# ─── who was loaded when ────────────────────────────────────────────────────

def record_account(email: str | None, when: float | None = None) -> None:
    """
    Note that `email` is the loaded account as of now.

    Called on every refresh and on every switch. Only a change is stored, so the
    timeline stays a handful of rows per day however often the widget polls.
    """
    if not enabled() or not email:
        return
    stamp = int(when or time.time())
    with contextlib.suppress(sqlite3.Error, OSError), _ledger() as connection:
        row = connection.execute(
            "select account from timeline order by ts desc limit 1").fetchone()
        if row and row[0].lower() == email.lower():
            return
        if row is None:
            stamp = _first_known(email, stamp)
        connection.execute("insert or replace into timeline(ts, account) values (?, ?)",
                           (stamp, email))


def _first_known(email: str, fallback: int) -> int:
    """
    How far back this account can honestly be said to have been loaded.

    On a first run the timeline is empty and everything already recorded would
    become unattributed — including the work of the last few days, which is the
    part anyone wants to see. The last switch Lagrange made is a fact it wrote
    down at the time, so when that switch put *this* account in place, the
    ledger can start there instead of at this second.
    """
    usage = config.read_json(config.USAGE_FILE, None)
    if not isinstance(usage, dict) or str(usage.get("account") or "").lower() != email.lower():
        return fallback
    try:
        switched = datetime.fromisoformat(str(usage.get("at")))
    except (TypeError, ValueError):
        return fallback
    if switched.tzinfo is None:
        switched = switched.astimezone()
    return min(int(switched.timestamp()), fallback)


def _timeline(connection: sqlite3.Connection) -> list[tuple[int, str]]:
    return connection.execute("select ts, account from timeline order by ts").fetchall()


def _account_at(timeline: list[tuple[int, str]], ts: int) -> str:
    """The account loaded at `ts`, or '' when the timeline does not reach back."""
    account = ""
    for stamp, email in timeline:
        if stamp > ts:
            break
        account = email
    return account


def tracking_since() -> datetime | None:
    """When attribution starts — turns before this cannot name an account."""
    try:
        with _ledger() as connection:
            row = connection.execute("select min(ts) from timeline").fetchone()
    except (sqlite3.Error, OSError):
        return None
    if not row or row[0] is None:
        return None
    return datetime.fromtimestamp(row[0], timezone.utc)


# ─── importing Antigravity's records ────────────────────────────────────────

def sync() -> int:
    """
    Pull in every turn recorded since the last run. Returns how many were new.

    Conversations are skipped whole unless their file changed, and a conversation
    that did change is read only past the step already stored — a full scan of
    five hundred files costs a second and a half, an incremental one costs
    almost nothing.
    """
    if not enabled():
        return 0
    files = agylog.conversation_files()
    if not files:
        return 0

    try:
        connection = _connect()
    except (sqlite3.Error, OSError):
        return 0

    added = 0
    try:
        known = {row[0]: row for row in connection.execute(
            "select conversation, mtime, size, last_step from sources")}
        timeline = _timeline(connection)
        names: dict[int, str] = {}

        for path in files:
            conversation = os.path.splitext(os.path.basename(path))[0]
            try:
                stat = os.stat(path)
            except OSError:
                continue
            previous = known.get(conversation)
            if previous and previous[1] == stat.st_mtime and previous[2] == stat.st_size:
                continue

            after = previous[3] if previous else -1
            turns = agylog.turns(path, after_step=after)
            highest = max([t.step for t in turns], default=after)
            # A file can change without adding a turn Lagrange cares about; the
            # step high-water mark still has to move so the next scan starts
            # past it rather than re-reading the tail forever.
            highest = max(highest, agylog.last_step(path))

            for turn in turns:
                connection.execute(
                    "insert or ignore into turns(conversation, step, ts, model, sent, "
                    "received, thinking, cached, account) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (conversation, turn.step, turn.ts, turn.model, turn.sent,
                     turn.received, turn.thinking, turn.cached,
                     _account_at(timeline, turn.ts)))
                added += 1

            if turns:
                names.update(agylog.model_names(path))
            connection.execute(
                "insert or replace into sources(conversation, mtime, size, last_step) "
                "values (?, ?, ?, ?)",
                (conversation, stat.st_mtime, stat.st_size, highest))

        for model_id, name in names.items():
            connection.execute("insert or replace into models(id, name) values (?, ?)",
                               (model_id, name))
        _reattribute(connection, timeline)
        connection.commit()
    except (sqlite3.Error, OSError):
        return added
    finally:
        connection.close()

    _prune()
    return added


def _reattribute(connection: sqlite3.Connection, timeline: list[tuple[int, str]]) -> None:
    """
    Give an account to turns that were stored before the timeline reached them.

    Antigravity writes a turn when it finishes, which can be after the widget
    imported the file, and a switch recorded moments later still applies to work
    that was already under way. Rather than freezing the first guess, every turn
    still marked unattributed is re-checked against the timeline as it stands.
    """
    if not timeline:
        return
    for index, (start, email) in enumerate(timeline):
        end = timeline[index + 1][0] if index + 1 < len(timeline) else None
        if end is None:
            connection.execute(
                "update turns set account = ? where account = '' and ts >= ?", (email, start))
        else:
            connection.execute(
                "update turns set account = ? where account = '' and ts >= ? and ts < ?",
                (email, start, end))


def _prune() -> None:
    """Drop turns older than the retention window, and sources that vanished."""
    days = int(config.get("token_history_days") or 0)
    if days <= 0:
        return
    cutoff = int(time.time()) - days * 24 * 3600
    with contextlib.suppress(sqlite3.Error, OSError), _ledger() as connection:
        # Only the turns age out. The timeline is a few rows a day and is what
        # dates the whole ledger, so it stays.
        connection.execute("delete from turns where ts < ?", (cutoff,))


# ─── reading the ledger ─────────────────────────────────────────────────────

EMPTY = {"sent": 0, "received": 0, "thinking": 0, "cached": 0, "turns": 0}


def totals(since: datetime | None = None, until: datetime | None = None,
           account: str | None = None) -> dict:
    """Summed usage over a period, optionally for one account."""
    query = ("select coalesce(sum(sent), 0), coalesce(sum(received), 0), "
             "coalesce(sum(thinking), 0), coalesce(sum(cached), 0), count(*) from turns")
    where, params = [], []
    if since is not None:
        where.append("ts >= ?")
        params.append(int(since.timestamp()))
    if until is not None:
        where.append("ts <= ?")
        params.append(int(until.timestamp()))
    if account is not None:
        where.append("lower(account) = ?")
        params.append(account.lower())
    if where:
        query += " where " + " and ".join(where)

    try:
        with _ledger() as connection:
            row = connection.execute(query, params).fetchone()
    except (sqlite3.Error, OSError):
        return dict(EMPTY)
    if not row:
        return dict(EMPTY)
    return {"sent": row[0], "received": row[1], "thinking": row[2],
            "cached": row[3], "turns": row[4]}


def by_day(days: int = 14, account: str | None = None) -> list[tuple[str, dict]]:
    """Daily usage, oldest first — what `lagrange usage --by-day` prints."""
    since = int(time.time()) - days * 24 * 3600
    query = ("select date(ts, 'unixepoch', 'localtime') as day, sum(sent), sum(received), "
             "sum(thinking), sum(cached), count(*) from turns where ts >= ?")
    params: list = [since]
    if account is not None:
        query += " and lower(account) = ?"
        params.append(account.lower())
    query += " group by day order by day"
    try:
        with _ledger() as connection:
            rows = connection.execute(query, params).fetchall()
    except (sqlite3.Error, OSError):
        return []
    return [(row[0], {"sent": row[1], "received": row[2], "thinking": row[3],
                      "cached": row[4], "turns": row[5]}) for row in rows]


def by_model(since: datetime | None = None, account: str | None = None) -> list[tuple[str, dict]]:
    """
    Usage split by model, heaviest first.

    Grouped by name rather than by id: Antigravity gives the same model a
    different numeric id per reasoning effort, and three rows reading
    "gemini-default" tell nobody anything. Ids no conversation file ever named
    are shown as themselves.
    """
    query = ("select coalesce(nullif(m.name, ''), 'model ' || t.model) as label, "
             "sum(t.sent), sum(t.received), sum(t.thinking), sum(t.cached), count(*) "
             "from turns t left join models m on m.id = t.model")
    where, params = [], []
    if since is not None:
        where.append("t.ts >= ?")
        params.append(int(since.timestamp()))
    if account is not None:
        where.append("lower(t.account) = ?")
        params.append(account.lower())
    if where:
        query += " where " + " and ".join(where)
    query += " group by label order by sum(t.sent) + sum(t.received) desc"
    try:
        with _ledger() as connection:
            rows = connection.execute(query, params).fetchall()
    except (sqlite3.Error, OSError):
        return []
    return [(row[0], {"sent": row[1], "received": row[2], "thinking": row[3],
                      "cached": row[4], "turns": row[5]}) for row in rows]


# ─── lining the ledger up with quota windows ────────────────────────────────

def window_start(window: str, reset: datetime | None, now: datetime) -> datetime | None:
    """
    When the window carrying this reset time began.

    Google gives the end of a window, not its start, so the start is the reset
    minus the window's length. Without a reset time the best available reading is
    the same length counted back from now.
    """
    length = WINDOW_SECONDS.get(window)
    if not length:
        return None
    if reset is None:
        return now - timedelta(seconds=length)
    start = reset - timedelta(seconds=length)
    # A reset already in the past means the bucket is refreshing; measure the
    # window that is starting rather than the one that just ended.
    return min(start, now)


# Used when an account has no quota figures to take window boundaries from —
# offline, or rate-limited. Sliding windows of the same length still answer
# "how much went out lately" instead of leaving the card blank.
FALLBACK_WINDOWS = ("5h", "weekly")


def _account_windows(entry: dict, now: datetime) -> dict[str, datetime]:
    """Earliest start per window across an account's buckets."""
    starts: dict[str, datetime] = {}
    for group in entry.get("groups", []):
        for bucket in group.get("buckets", []):
            window = bucket.get("window") or ""
            start = window_start(window, bucket.get("reset"), now)
            if start is None:
                continue
            if window not in starts or start < starts[window]:
                starts[window] = start
    if not starts:
        starts = {window: now - timedelta(seconds=WINDOW_SECONDS[window])
                  for window in FALLBACK_WINDOWS}
    return starts


def _add(into: dict, extra: dict) -> dict:
    for key in EMPTY:
        into[key] = into.get(key, 0) + extra.get(key, 0)
    return into


def summarise(state: dict) -> dict:
    """
    Per-account and overall usage for the windows the accounts' quotas use.

    Shape:
        {"accounts": {email: {window: totals}},
         "total":    {window: totals},
         "unattributed": {window: totals},
         "context":  {"used": int, "limit": int, "model": str, "age": seconds},
         "since":    datetime | None}

    The overall figure is the sum of the per-account ones, so the two always
    agree; turns that could not be attributed are reported beside it instead of
    inside it.
    """
    if not enabled():
        return {}
    now = datetime.now(timezone.utc)
    per_account: dict[str, dict[str, dict]] = {}
    overall: dict[str, dict] = {}
    unattributed: dict[str, dict] = {}
    seen_windows: dict[str, datetime] = {}

    for entry in state.get("accounts", []):
        email = entry["email"]
        windows = _account_windows(entry, now)
        per_account[email] = {}
        for window, start in windows.items():
            figures = totals(since=start, account=email)
            per_account[email][window] = figures
            _add(overall.setdefault(window, dict(EMPTY)), figures)
            if window not in seen_windows or start < seen_windows[window]:
                seen_windows[window] = start

    for window, start in seen_windows.items():
        unattributed[window] = totals(since=start, account="")

    return {
        "accounts": per_account,
        "total": overall,
        "unattributed": unattributed,
        "context": current_context(),
        "since": tracking_since(),
    }


# ─── the conversation in front of the user ──────────────────────────────────

def current_context(max_age_seconds: int = 6 * 3600) -> dict | None:
    """
    How full the most recently touched conversation's context window is.

    This is the depth reading: quota says how much of the week is left, and this
    says how close the conversation in the console is to being compacted. Older
    than `max_age_seconds` it is not the conversation anyone is looking at, so
    nothing is reported.
    """
    if not enabled():
        return None
    files = agylog.conversation_files()
    if not files:
        return None
    try:
        newest = max(files, key=os.path.getmtime)
        age = time.time() - os.path.getmtime(newest)
    except (OSError, ValueError):
        return None
    if age > max_age_seconds:
        return None
    context = agylog.context(newest)
    if not context:
        return None
    return {"used": context.used, "limit": context.limit, "model": context.model,
            "age": int(age), "conversation": os.path.splitext(os.path.basename(newest))[0]}


# ─── formatting ─────────────────────────────────────────────────────────────

def human(count: int) -> str:
    """Token counts at a glance: 812, 45.3k, 1.2M."""
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        value = count / 1000
        return f"{value:.0f}k" if value >= 100 else f"{value:.1f}k"
    value = count / 1_000_000
    return f"{value:.0f}M" if value >= 100 else f"{value:.1f}M"
