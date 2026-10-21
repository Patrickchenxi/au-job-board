"""Small, transaction-owned upgrades for local databases.

The caller owns BEGIN/COMMIT. No production connection, backup, network or
heuristic re-analysis is performed here.
"""
from __future__ import annotations

import datetime as dt
import re

SCHEMA_VERSION = 1
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


def _migrate_labels(conn):
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
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
        if not found:
            continue
        note_event = conn.execute("""SELECT 1 FROM label_events WHERE uid=? AND field='note'
            AND (source IS NULL OR source!='tidy')
            AND event_id > COALESCE((SELECT MAX(event_id) FROM label_events
                WHERE uid=? AND field='__row__' AND source='row_reset'),0) LIMIT 1""",
            (uid, uid)).fetchone()
        if not note_event:
            # Retain legacy note ownership even when removing the tag leaves NULL.
            conn.execute("""INSERT INTO label_events
                (uid,field,old_value,new_value,source,rules_version,at)
                VALUES (?,'note',NULL,?,'legacy_snapshot',?,?)""",
                (uid, row["note"], row["rules_version"], stamp))
        conn.execute("UPDATE labels SET priority=1,note=? WHERE uid=?", (new_note, uid))
        for field, old, new in (("priority", None, "1"), ("note", row["note"], new_note)):
            conn.execute("""INSERT INTO label_events
                (uid,field,old_value,new_value,source,rules_version,at)
                VALUES (?,?,?,?, 'migration',?,?)""",
                (uid, field, old, new, row["rules_version"], now))


def upgrade(conn):
    if check_version(conn) == SCHEMA_VERSION:
        return
    existing = _columns(conn, "labels")
    for name, definition in LABEL_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE labels ADD COLUMN {name} {definition}")
    if "analysis_snapshot" not in _columns(conn, "label_events"):
        conn.execute("ALTER TABLE label_events ADD COLUMN analysis_snapshot TEXT")
    _migrate_labels(conn)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
