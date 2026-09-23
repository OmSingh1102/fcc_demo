"""Runtime state, in SQLite, so it outlives the process.

Everything an analyst does to a case lives in module-level lists in app.py
that die with the worker. This store carries it across a restart.

Adapted from the ChargeShield demo's state_store. That one stores a per-case
delta against a CSV baseline, because there a re-uploaded sheet is the source
of truth and stored state must survive underneath it. Here the seed is static
code and the parts that change are nested lists — a screening case's alerts,
a watchlist case's match resolutions, every record's audit trail — so a
key-level delta would serialise the whole list on every write anyway. So this
store keeps it simple: the whole record, as JSON, for every record somebody has
touched. Untouched records are never written and come straight from the seed
on every boot.

restore() puts a stored record back by clearing and refilling the *same* dict
the seed produced. Assignment rather than merge, so a second restore is a
no-op, and identity is preserved, so the by-id indexes built at load stay
valid without a rebuild.

A SEED_VERSION is stamped in app_setting at boot. When the seed's shape changes
the stored records could be missing keys the templates expect, so a version
mismatch clears the store. That is the one place a code change can throw away
demo state, and it says so in the log.

Every method swallows sqlite errors and reports through `on_error`, because
the restore runs at import: an exception here would take the whole app down
rather than merely losing a decision.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime

DB_PATH = os.environ.get("FCC_STATE_DB") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fincrime_state.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS record_state (
    kind       TEXT NOT NULL,
    id         TEXT NOT NULL,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

SEED_VERSION_KEY = "seed_version"


class StateStore:
    """Record state that survives a restart. Never raises at the caller."""

    path = DB_PATH
    on_error = None          # set by the app to its logger

    # ── plumbing ────────────────────────────────────────────────────────────

    @classmethod
    def _warn(cls, message, exc):
        if cls.on_error:
            cls.on_error("%s: %s", message, exc)

    @classmethod
    def _connect(cls):
        # A connection per operation: the dev server is threaded and a sqlite3
        # connection may not cross threads. At a few dozen rows the cost of
        # opening one is not worth a pool.
        conn = sqlite3.connect(cls.path, timeout=5)
        # WAL lets a reader and a writer overlap, which a threaded server does.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        return conn

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── writing ─────────────────────────────────────────────────────────────

    @classmethod
    def save(cls, kind: str, record: dict) -> bool:
        """Store the whole record under (kind, id). Upsert."""
        rid = str(record.get("id", ""))
        if not rid:
            return False
        try:
            blob = json.dumps(record, default=str)
        except (TypeError, ValueError) as exc:
            cls._warn(f"could not serialise {kind} {rid}", exc)
            return False
        try:
            with closing(cls._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO record_state (kind, id, data, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(kind, id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                    (kind, rid, blob, cls._now()))
            return True
        except sqlite3.Error as exc:
            cls._warn(f"could not save {kind} {rid}", exc)
            return False

    @classmethod
    def save_many(cls, pairs) -> int:
        return sum(1 for kind, record in pairs if cls.save(kind, record))

    # ── reading ─────────────────────────────────────────────────────────────

    @classmethod
    def restore(cls, kind: str, by_id: dict) -> int:
        """Re-apply stored records of `kind` onto the freshly seeded `by_id`
        dicts, in place. Returns how many were applied. Unknown ids are skipped:
        a record the seed no longer produces has nowhere to go."""
        applied = 0
        try:
            with closing(cls._connect()) as conn, conn:
                rows = conn.execute("SELECT id, data FROM record_state WHERE kind = ?", (kind,)).fetchall()
        except sqlite3.Error as exc:
            cls._warn(f"could not read stored {kind} records", exc)
            return 0
        for rid, blob in rows:
            target = by_id.get(rid)
            if target is None:
                continue
            try:
                data = json.loads(blob)
            except ValueError as exc:
                cls._warn(f"stored {kind} {rid} is not valid JSON", exc)
                continue
            if isinstance(data, dict):
                target.clear()
                target.update(data)
                applied += 1
        return applied

    @classmethod
    def count(cls) -> int:
        try:
            with closing(cls._connect()) as conn, conn:
                return conn.execute("SELECT COUNT(*) FROM record_state").fetchone()[0]
        except sqlite3.Error as exc:
            cls._warn("could not count stored records", exc)
            return 0

    # ── settings ────────────────────────────────────────────────────────────

    @classmethod
    def _get_setting(cls, key: str) -> str:
        try:
            with closing(cls._connect()) as conn, conn:
                row = conn.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
            return row[0] if row else ""
        except sqlite3.Error as exc:
            cls._warn(f"could not read setting {key}", exc)
            return ""

    @classmethod
    def _set_setting(cls, key: str, value: str) -> bool:
        try:
            with closing(cls._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO app_setting (key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, value, cls._now()))
            return True
        except sqlite3.Error as exc:
            cls._warn(f"could not write setting {key}", exc)
            return False

    @classmethod
    def seed_version(cls) -> str:
        return cls._get_setting(SEED_VERSION_KEY)

    @classmethod
    def set_seed_version(cls, version: str) -> bool:
        return cls._set_setting(SEED_VERSION_KEY, version)

    # ── reset ───────────────────────────────────────────────────────────────

    @classmethod
    def clear(cls) -> bool:
        """Drop every stored record and setting. The seed reloads on top."""
        try:
            with closing(cls._connect()) as conn, conn:
                conn.execute("DELETE FROM record_state")
                conn.execute("DELETE FROM app_setting")
            return True
        except sqlite3.Error as exc:
            cls._warn("could not clear the state store", exc)
            return False
