"""Small, transaction-owned upgrades for local databases.

The caller owns BEGIN/COMMIT. No production connection, backup, network or
heuristic re-analysis is performed here.
"""
from __future__ import annotations

import datetime as dt
import re

SCHEMA_VERSION = 3
LABEL_COLUMNS = {
    "priority": "INTEGER CHECK (priority IN (0,1))",
    "action_at": "TEXT",
    "eligibility_source": "TEXT",
    "eligibility_at": "TEXT",
    "eligibility_analysis": "TEXT",
}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def check_version(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError("Database is newer than this program; use its matching version")
    return version


def priority_note_conversion(raw):
    """Return (found, remaining text) for the legacy canonical tag only."""
    parts = re.split(r"([；;])", raw or "")
    remaining, found = [], False
    for index in range(0, len(parts), 2):
        text = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if text.strip() == "优先投递":
            found = True
        else:
            remaining.append(text + separator)
    note = "".join(remaining)
    return found, note if note.strip(" ;；\t\r\n") else None


def _reconcile_legacy_deletions(conn):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    # Old clear_label deleted the row without an event. Reconcile only absent
    # rows; never rewrite the audit trail or invent a historical deletion date.
    conn.execute("""INSERT INTO label_events(uid,field,new_value,source,at)
        SELECT e.uid,'action',NULL,'legacy_deleted',? FROM label_events e
        WHERE e.field='action' AND e.new_value IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.uid=e.uid)
        AND e.event_id=(SELECT MAX(b.event_id) FROM label_events b
                        WHERE b.uid=e.uid AND b.field='action')""", (now,))


def _migrate_labels(conn):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _reconcile_legacy_deletions(conn)
    from .labels import normalize_note

    for row in conn.execute("SELECT * FROM labels").fetchall():
        uid, stamp = row["uid"], row["labeled_at"] or ""
        # Snapshot old action identity before note conversion adds newer events.
        event = conn.execute("""SELECT * FROM label_events WHERE uid=? AND field='action'
            AND event_id > COALESCE((SELECT MAX(event_id) FROM label_events
                WHERE uid=? AND field='__row__' AND source='row_reset'),0)
            ORDER BY event_id DESC LIMIT 1""", (uid, uid)).fetchone()
        action_stamp = (event["at"] if event and event["new_value"] == row["action"]
                        else stamp)
        if row["action"] and not event:
            conn.execute("""INSERT INTO label_events
                (uid,field,old_value,new_value,source,rules_version,at)
                VALUES (?,'action',NULL,?,'legacy_snapshot',?,?)""",
                (uid, row["action"], row["rules_version"], action_stamp))
        if row["action"] or event:
            conn.execute("UPDATE labels SET action_at=? WHERE uid=?", (action_stamp, uid))
        if row["eligibility"] in ("eligible", "ineligible"):
            # Today's analysis does not prove the analysis at the original edit.
            conn.execute("""UPDATE labels SET eligibility_source='legacy',
                         eligibility_at=? WHERE uid=?""", (stamp, uid))
        found, new_note = priority_note_conversion(row["note"])
        note_event = conn.execute("""SELECT * FROM label_events WHERE uid=? AND field='note'
            AND (source IS NULL OR source NOT IN ('tidy','migration'))
            AND event_id > COALESCE((SELECT MAX(event_id) FROM label_events
                WHERE uid=? AND field='__row__' AND source='row_reset'),0)
            ORDER BY event_id DESC LIMIT 1""", (uid, uid)).fetchone()
        if not note_event or normalize_note(note_event["new_value"]) != normalize_note(row["note"]):
            if not row["note"]:
                continue
            # Preserve fallback ownership for a snapshot without a matching edit.
            conn.execute("""INSERT INTO label_events
                (uid,field,old_value,new_value,source,rules_version,at)
                VALUES (?,'note',NULL,?,'legacy_snapshot',?,?)""",
                (uid, row["note"], row["rules_version"], stamp))
            note_event = conn.execute('SELECT * FROM label_events WHERE event_id=last_insert_rowid()').fetchone()
        # A replacement or explicit clear owns false just as its old note owned
        # the absence of the tag. Do not assign upgrade-time ownership.
        conn.execute("UPDATE labels SET priority=?,note=? WHERE uid=?", (int(found), new_note if found else row["note"], uid))
        conn.execute("""INSERT INTO label_events
            (uid,field,old_value,new_value,source,rules_version,at)
            VALUES (?,'priority',NULL,?,'migration',?,?)""",
            (uid, str(int(found)), row["rules_version"], note_event["at"]))
        if found:
            conn.execute("""INSERT INTO label_events
                (uid,field,old_value,new_value,source,rules_version,at)
                VALUES (?,'note',?,?,'migration',?,?)""",
                (uid, row["note"], new_note, row["rules_version"], now))


def upgrade(conn):
    version = check_version(conn)
    if version == SCHEMA_VERSION:
        return
    if version < 2:
        existing = _columns(conn, "labels")
        for name, definition in LABEL_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE labels ADD COLUMN {name} {definition}")
        if "analysis_snapshot" not in _columns(conn, "label_events"):
            conn.execute("ALTER TABLE label_events ADD COLUMN analysis_snapshot TEXT")
        if version < 1:
            _migrate_labels(conn)
    from .batches import SCHEMA as BATCH_SCHEMA
    for statement in BATCH_SCHEMA:
        conn.execute(statement)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
