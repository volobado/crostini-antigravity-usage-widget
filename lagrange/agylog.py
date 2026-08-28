"""
Antigravity's own record of what every turn cost.

Google's quota endpoint answers in fractions — how much of a window is left —
and never in tokens, so "how much did this account send and receive" cannot come
from there. Antigravity keeps that figure itself: one SQLite file per
conversation under `~/.gemini/antigravity-cli/conversations`, where every model
turn carries the token counts of that turn and the moment it happened.

Nothing about those files is a documented format — they hold bare protobuf with
no field names — so the numbers below were confirmed against a source that does
name them: `agy -p --output-format json` prints a `usage` block for the
conversation it just ran, and summing the per-turn fields read here reproduces
it exactly (input, output and thinking all matched to the token across a
two-turn conversation).

Reading is strictly read-only and best effort: a database Antigravity is
mid-write into, a schema change, an unknown field — each of those costs one
conversation's figures, never the widget.
"""

from __future__ import annotations

import glob
import io
import os
import sqlite3
from typing import NamedTuple

from . import config

# ─── where Antigravity keeps conversations ──────────────────────────────────

_DIR_CANDIDATES = [
    r"%USERPROFILE%\.gemini\antigravity-cli\conversations",
    r"%USERPROFILE%\.antigravity\conversations",
    r"%LOCALAPPDATA%\antigravity\conversations",
]


def conversations_dir() -> str | None:
    """The directory holding one .db per conversation, or None."""
    override = config.get("conversations_dir")
    if override:
        return override if os.path.isdir(override) else None
    for template in _DIR_CANDIDATES:
        path = os.path.expandvars(template)
        if os.path.isdir(path):
            return path
    return None


def conversation_files(directory: str | None = None) -> list[str]:
    directory = directory or conversations_dir()
    if not directory:
        return []
    return glob.glob(os.path.join(directory, "*.db"))


# ─── just enough protobuf ───────────────────────────────────────────────────
#
# A full decoder is not needed and not wanted: without a schema the only honest
# reading is "field number N of this message", which is exactly what a
# single-level walk gives. Anything unparseable ends the walk and the caller
# sees the fields read so far.

_WIRE_VARINT, _WIRE_64, _WIRE_BYTES, _WIRE_32 = 0, 1, 2, 5


def _read_varint(buf: io.BytesIO) -> int:
    shift = 0
    value = 0
    while True:
        byte = buf.read(1)
        if not byte:
            raise EOFError
        piece = byte[0]
        value |= (piece & 0x7F) << shift
        if not piece & 0x80:
            return value
        shift += 7
        if shift > 70:  # far past a 64-bit varint — the blob is not what we think
            raise ValueError("varint too long")


def fields(blob: bytes) -> list[tuple[int, int | bytes]]:
    """Top-level (field number, value) pairs; ints for varints, bytes otherwise."""
    out: list[tuple[int, int | bytes]] = []
    buf = io.BytesIO(blob)
    size = len(blob)
    while buf.tell() < size:
        try:
            key = _read_varint(buf)
            number, wire = key >> 3, key & 7
            if wire == _WIRE_VARINT:
                out.append((number, _read_varint(buf)))
            elif wire == _WIRE_BYTES:
                length = _read_varint(buf)
                raw = buf.read(length)
                if len(raw) != length:
                    break
                out.append((number, raw))
            elif wire == _WIRE_64:
                if len(buf.read(8)) != 8:
                    break
            elif wire == _WIRE_32:
                if len(buf.read(4)) != 4:
                    break
            else:
                break
        except (EOFError, ValueError):
            break
    return out


def _submessage(blob: bytes, number: int) -> bytes | None:
    for field, value in fields(blob):
        if field == number and isinstance(value, bytes):
            return value
    return None


def _numbers(blob: bytes) -> dict[int, int]:
    return {f: v for f, v in fields(blob) if isinstance(v, int)}


# ─── one model turn ─────────────────────────────────────────────────────────

# `steps.metadata`: field 1 is a timestamp {1: seconds, 2: nanoseconds} and
# field 9 the generation's usage. Inside usage: 1 model id, 2 tokens sent,
# 3 tokens received, 5 tokens read from cache, 9 of the received ones spent
# thinking. Received already includes thinking — field 10 is the remainder,
# and 9 + 10 == 3 in every sample.
_TIMESTAMP_FIELD = 1
_USAGE_FIELD = 9
_U_MODEL, _U_SENT, _U_RECEIVED, _U_CACHED, _U_THINKING = 1, 2, 3, 5, 9


class Turn(NamedTuple):
    step: int
    ts: int          # unix seconds
    model: int       # Antigravity's numeric model id; names come from gen_metadata
    sent: int
    received: int
    thinking: int
    cached: int


def _turn(step: int, metadata: bytes) -> Turn | None:
    usage_blob = _submessage(metadata, _USAGE_FIELD)
    if not usage_blob:
        return None
    usage = _numbers(usage_blob)
    sent, received = usage.get(_U_SENT, 0), usage.get(_U_RECEIVED, 0)
    cached = usage.get(_U_CACHED, 0)
    if not (sent or received or cached):
        return None

    ts = 0
    stamp = _submessage(metadata, _TIMESTAMP_FIELD)
    if stamp:
        ts = _numbers(stamp).get(1, 0)

    return Turn(step=step, ts=ts, model=usage.get(_U_MODEL, 0), sent=sent,
                received=received, thinking=usage.get(_U_THINKING, 0), cached=cached)


def _connect(path: str) -> sqlite3.Connection:
    # Read-only, and never left waiting: Antigravity may hold the write lock.
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.5)


def turns(path: str, after_step: int = -1) -> list[Turn]:
    """
    Model turns recorded in one conversation, newest work last.

    `after_step` skips what a previous scan already stored — steps are appended
    with a rising index, so a conversation that grew by two turns costs two rows
    instead of a re-read of the whole file.
    """
    try:
        connection = _connect(path)
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "select idx, metadata from steps where idx > ? order by idx",
            (after_step,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    found = []
    for idx, metadata in rows:
        if not isinstance(metadata, bytes) or not metadata:
            continue
        turn = _turn(idx, metadata)
        if turn:
            found.append(turn)
    return found


def last_step(path: str) -> int:
    try:
        connection = _connect(path)
    except sqlite3.Error:
        return -1
    try:
        row = connection.execute("select max(idx) from steps").fetchone()
        return int(row[0]) if row and row[0] is not None else -1
    except (sqlite3.Error, TypeError, ValueError):
        return -1
    finally:
        connection.close()


# ─── conversation-level metadata ────────────────────────────────────────────

# `gen_metadata.data`: field 1 is the last generation's request, holding the
# model id (4.1) and the context accounting (9.10 → {1: tokens in context,
# 4: the model's context window}); field 19 of that same message spells the
# model out, which is the only place a name appears at all.
_GEN_REQUEST, _GEN_MODEL_NAME = 1, 19
_REQ_INFO, _REQ_CONTEXT = 4, 9
_CTX_BLOCK = 10
_CTX_USED, _CTX_LIMIT = 1, 4


class Context(NamedTuple):
    used: int
    limit: int
    model: str


def context(path: str) -> Context | None:
    """
    How full the conversation's context window is, from its last generation.

    This is the depth question — a conversation at 240k of 256k is one prompt
    away from being compacted, and nothing in the quota API hints at it.
    """
    try:
        connection = _connect(path)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute(
            "select data from gen_metadata order by idx desc").fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()

    for (blob,) in rows:
        if not isinstance(blob, bytes) or not blob:
            continue
        request = _submessage(blob, _GEN_REQUEST)
        if not request:
            continue
        name = ""
        for field, value in fields(request):
            if field == _GEN_MODEL_NAME and isinstance(value, bytes):
                name = value.decode("utf-8", "ignore")
        block = _submessage(request, _REQ_CONTEXT)
        block = _submessage(block, _CTX_BLOCK) if block else None
        if not block:
            continue
        numbers = _numbers(block)
        used, limit = numbers.get(_CTX_USED, 0), numbers.get(_CTX_LIMIT, 0)
        if used and limit:
            return Context(used=used, limit=limit, model=name)
    return None


def model_names(path: str) -> dict[int, str]:
    """Numeric model id → the name Antigravity prints for it, if this file says."""
    try:
        connection = _connect(path)
    except sqlite3.Error:
        return {}
    try:
        rows = connection.execute("select data from gen_metadata").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()

    names: dict[int, str] = {}
    for (blob,) in rows:
        if not isinstance(blob, bytes) or not blob:
            continue
        request = _submessage(blob, _GEN_REQUEST)
        if not request:
            continue
        name = ""
        model_id = 0
        for field, value in fields(request):
            if field == _GEN_MODEL_NAME and isinstance(value, bytes):
                name = value.decode("utf-8", "ignore")
        info = _submessage(request, _REQ_INFO)
        if info:
            model_id = _numbers(info).get(1, 0)
        if model_id and name:
            names[model_id] = name
    return names
