"""Durable collection facts, independent of analysis and pipeline publication.

Writers never commit: the fetch caller owns each source transaction. Readers
only SELECT, including the optional mapping of old fetch runs without members.
"""
from __future__ import annotations

import uuid

from . import db


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS fetch_batches (
        batch_id TEXT PRIMARY KEY NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        collection_state TEXT NOT NULL CHECK (collection_state IN
            ('running','success','partial','error','timeout','interrupted')),
        pipeline_task_id TEXT,
        trigger TEXT NOT NULL,
        error TEXT,
        fetch_run_id INTEGER UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS fetch_batch_members (
        batch_id TEXT NOT NULL REFERENCES fetch_batches(batch_id),
        uid TEXT NOT NULL,
        is_new INTEGER NOT NULL CHECK (is_new IN (0,1)),
        seen_at TEXT NOT NULL,
        PRIMARY KEY (batch_id, uid)
    )""",
)


def start_batch(conn, *, pipeline_task_id=None, trigger="unknown") -> str:
    batch_id = uuid.uuid4().hex
    conn.execute("""INSERT INTO fetch_batches
        (batch_id,started_at,collection_state,pipeline_task_id,trigger)
        VALUES (?,?,'running',?,?)""",
        (batch_id, db.utcnow(), pipeline_task_id, trigger))
    return batch_id


def record_member(conn, batch_id: str, uid: str, is_new: bool) -> None:
    """Call immediately after upsert_job, within the same source transaction."""
    conn.execute("""INSERT INTO fetch_batch_members(batch_id,uid,is_new,seen_at)
        VALUES (?,?,?,?) ON CONFLICT(batch_id,uid) DO UPDATE SET
        is_new=MAX(fetch_batch_members.is_new,excluded.is_new),
        seen_at=excluded.seen_at""", (batch_id, uid, int(is_new), db.utcnow()))


def finish_batch(conn, batch_id: str, state: str, *, error=None, fetch_run_id=None) -> None:
    if state not in {"success", "partial", "error", "timeout", "interrupted"}:
        raise ValueError("Invalid terminal collection state")
    # Terminal collection facts cannot be overwritten by a later pipeline error
    # or an interrupt after the collection's final commit.
    conn.execute("""UPDATE fetch_batches SET finished_at=?,collection_state=?,
        error=?,fetch_run_id=? WHERE batch_id=? AND collection_state='running'""",
        (db.utcnow(), state, error, fetch_run_id, batch_id))


# No raw exception text, config, JD payload or runtime-file recovery is exposed.
_READ = """SELECT batch_id,started_at,finished_at,collection_state,
    'available' AS membership,pipeline_task_id,trigger,error,
    (SELECT COUNT(*) FROM fetch_batch_members m WHERE m.batch_id=b.batch_id) AS seen,
    (SELECT COALESCE(SUM(is_new),0) FROM fetch_batch_members m
        WHERE m.batch_id=b.batch_id) AS inserted,
    1 AS precise,b.rowid AS sequence
    FROM fetch_batches b
    UNION ALL
    SELECT 'legacy-' || run_id,started_at,finished_at,'unknown',
        'unavailable',NULL,'unknown',NULL,NULL,NULL,0,run_id
    FROM runs r WHERE kind='fetch' AND NOT EXISTS
        (SELECT 1 FROM fetch_batches b WHERE b.fetch_run_id=r.run_id)"""


def _public(row) -> dict:
    return {
        "batch_id": row["batch_id"], "started_at": row["started_at"],
        "finished_at": row["finished_at"], "collection_state": row["collection_state"],
        "membership": row["membership"], "pipeline_task_id": row["pipeline_task_id"],
        "trigger": row["trigger"], "error": row["error"],
        "counts": None if row["membership"] == "unavailable" else {
            "seen": row["seen"], "inserted": row["inserted"],
            "updated": row["seen"] - row["inserted"],
        },
    }


def list_batches(conn, limit=50, offset=0) -> list[dict]:
    """Newest starts first; counts are unique committed UIDs, not observations."""
    if not isinstance(limit, int) or not isinstance(offset, int) or limit < 0 or offset < 0:
        raise ValueError("limit and offset must be nonnegative integers")
    rows = conn.execute("SELECT * FROM (" + _READ + """
        ) ORDER BY started_at DESC,precise DESC,sequence DESC LIMIT ? OFFSET ?""",
        (limit, offset))
    return [_public(row) for row in rows]


def get_batch(conn, batch_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM (" + _READ + ") WHERE batch_id=?", (batch_id,)).fetchone()
    return _public(row) if row else None
