"""Stable source/location identity and audited, transaction-owned human edits.

Legacy labels are reference data, never copied into a location's current state.
Derived locations may be rebuilt; their identities and human records survive.
"""
from __future__ import annotations

import json
import re
import uuid

SCHEMA = '''
CREATE TABLE IF NOT EXISTS job_locations (
    location_id TEXT PRIMARY KEY,
    uid TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    raw TEXT NOT NULL,
    derived_json TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    correction_json TEXT,
    correction_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(uid,identity_key),
    UNIQUE(uid,location_id)
);
CREATE INDEX IF NOT EXISTS idx_locations_uid ON job_locations(uid,active,ordinal);
CREATE TABLE IF NOT EXISTS location_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    location_id TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    at TEXT NOT NULL,
    analysis_snapshot TEXT,
    FOREIGN KEY(uid,location_id) REFERENCES job_locations(uid,location_id)
);
CREATE INDEX IF NOT EXISTS idx_location_events_scope ON location_events(uid,location_id,event_id);
CREATE TABLE IF NOT EXISTS location_labels (
    uid TEXT NOT NULL,
    location_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    at TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    analysis_snapshot TEXT,
    PRIMARY KEY(uid,location_id,field),
    FOREIGN KEY(uid,location_id) REFERENCES job_locations(uid,location_id)
);
'''


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _identity(raw):
    # Case/spacing are spelling, not a new workplace. No fuzzy/geographic guesses.
    return re.sub(r'\s+', ' ', (raw or '').casefold()).strip()


def sync_job(conn, uid):
    """Caller owns the transaction, including the source upsert. No commit here."""
    from . import db, locations
    row = conn.execute('SELECT location,work_type FROM jobs WHERE uid=?', (uid,)).fetchone()
    if row is None:
        return
    parts = locations.parse_locations(row[0], row[1])
    conn.execute('UPDATE job_locations SET active=0 WHERE uid=?', (uid,))
    seen = set()
    for ordinal, part in enumerate(parts):
        identity = _identity(part.get('raw'))
        if identity in seen:
            continue
        seen.add(identity)
        conn.execute('''INSERT INTO job_locations
            (location_id,uid,identity_key,raw,derived_json,ordinal,active,created_at)
            VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(uid,identity_key) DO UPDATE SET
            raw=excluded.raw,derived_json=excluded.derived_json,
            ordinal=excluded.ordinal,active=1''',
            (uuid.uuid4().hex, uid, identity, part.get('raw') or '', _dump(part), ordinal, db.utcnow()))


def sync_all(conn):
    for row in conn.execute('SELECT uid FROM jobs').fetchall():
        sync_job(conn, row[0])


def locations_for(conn, uid, *, include_history=True):
    rows = conn.execute('''SELECT * FROM job_locations WHERE uid=?
        ORDER BY active DESC,ordinal,created_at,location_id''', (uid,)).fetchall()
    out = []
    for row in rows:
        historical = not row['active']
        if historical and not include_history:
            continue
        if historical and not row['correction_json'] and not conn.execute(
                '''SELECT 1 FROM location_labels WHERE location_id=? UNION ALL
                   SELECT 1 FROM location_events WHERE location_id=? LIMIT 1''',
                (row['location_id'], row['location_id'])).fetchone():
            continue
        # Corruption is explicit; a malformed record must not become a guess.
        item = json.loads(row['correction_json'] or row['derived_json'])
        item.update(location_id=row['location_id'], uid=uid,
                    raw_original=row['raw'], active=bool(row['active']),
                    corrected=row['correction_json'] is not None,
                    correction_at=row['correction_at'])
        out.append(item)
    return out


def require_location(conn, uid, location_id):
    row = conn.execute('SELECT * FROM job_locations WHERE uid=? AND location_id=?',
                       (uid, location_id)).fetchone()
    if row is None:
        raise ValueError('Unknown location for this source record')
    return row


def set_correction(conn, uid, location_id, raw, work_mode='unknown'):
    """Audit and correction are atomic; outer caller owns commit/rollback."""
    from . import db, locations
    row = require_location(conn, uid, location_id)
    if not row['active']:
        raise ValueError('This historical location is no longer the current source location')
    if work_mode not in ('unknown', 'remote', 'hybrid', 'onsite'):
        raise ValueError('Invalid work mode')
    value = None
    if raw is not None:
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 300:
            raise ValueError('Enter a location of 1 to 300 characters')
        parts = locations.parse_locations(raw.strip())
        if len(parts) != 1 or parts[0]['precision'] == 'unknown':
            raise ValueError('Use one unambiguous Australian location')
        value = parts[0]
        value['work_mode'] = work_mode if work_mode != 'unknown' else value.get('work_mode', 'unknown')
        value['source'] = 'manual'
    now = db.utcnow()
    conn.execute('''INSERT INTO location_events
        (uid,location_id,field,old_value,new_value,source,at)
        VALUES (?,?,'__location__',?,?,'panel',?)''',
        (uid, location_id, row['correction_json'], _dump(value) if value else None, now))
    conn.execute('UPDATE job_locations SET correction_json=?,correction_at=? WHERE location_id=?',
                 (_dump(value) if value else None, now, location_id))


def label_for(conn, uid, location_id, since=None):
    """Full current label or frozen action at a scoped event watermark."""
    require_location(conn, uid, location_id)
    rows = conn.execute('SELECT * FROM location_labels WHERE uid=? AND location_id=?',
                        (uid, location_id)).fetchall()
    out = {r['field']: json.loads(r['value']) if r['value'] is not None else None for r in rows}
    latest = max(rows, key=lambda r: r['event_id'], default=None)
    out['labeled_at'] = latest['at'] if latest else None
    out['_has_record'] = bool(rows)
    if since is not None:
        marker = since.rsplit('|', 1)
        watermark = int(marker[1]) if len(marker) == 2 and marker[1].isdigit() else 0
        event = conn.execute('''SELECT new_value,at FROM location_events
            WHERE uid=? AND location_id=? AND field='action' AND event_id<=?
            ORDER BY event_id DESC LIMIT 1''', (uid, location_id, watermark)).fetchone()
        out['action'] = json.loads(event['new_value']) if event and event['new_value'] is not None else None
        out['_has_record_at'] = conn.execute(
            "SELECT 1 FROM location_events WHERE uid=? AND location_id=? AND field!='__location__' AND event_id<=? LIMIT 1",
            (uid, location_id, watermark)).fetchone() is not None
    for r in rows:
        if r['field'] == 'action':
            out['action_at'] = r['at']
            out['applied_at'] = None
            if out.get('action') == 'applied':
                first = conn.execute("""SELECT at FROM location_events WHERE uid=?
                    AND location_id=? AND field='action' AND new_value=? AND event_id >
                    COALESCE((SELECT MAX(event_id) FROM location_events WHERE uid=?
                        AND location_id=? AND field='action' AND new_value!=?),0)
                    ORDER BY event_id LIMIT 1""",
                    (uid, location_id, _dump('applied'), uid, location_id, _dump('applied'))).fetchone()
                out['applied_at'] = first['at'] if first else r['at']
        if r['field'] == 'eligibility':
            active = out.get('eligibility') in ('eligible', 'ineligible')
            out.update(eligibility_source='panel' if active else None,
                       eligibility_at=r['at'] if active else None,
                       eligibility_analysis=r['analysis_snapshot'] if active else None)
    return out


def set_label(conn, uid, location_id, field, value):
    """One field, one audit event. Explicit null/false never falls back to legacy."""
    from . import db, labels
    require_location(conn, uid, location_id)
    if field not in labels.WRITABLE:
        raise ValueError('Invalid label field')
    value = labels.normalize_note(value) if field == 'note' else labels._validate(field, value)
    old = conn.execute('SELECT value FROM location_labels WHERE uid=? AND location_id=? AND field=?',
                       (uid, location_id, field)).fetchone()
    snapshot = None
    if field == 'eligibility':
        decision = conn.execute('SELECT * FROM decisions WHERE uid=?', (uid,)).fetchone()
        if decision:
            snapshot = _dump(dict(decision))
    now = db.utcnow()
    event_id = conn.execute('''INSERT INTO location_events
        (uid,location_id,field,old_value,new_value,source,at,analysis_snapshot)
        VALUES (?,?,?,?,?,'panel',?,?)''',
        (uid, location_id, field, old['value'] if old else None, _dump(value), now, snapshot)).lastrowid
    conn.execute('''INSERT INTO location_labels
        (uid,location_id,field,value,at,event_id,analysis_snapshot) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(uid,location_id,field) DO UPDATE SET value=excluded.value,
        at=excluded.at,event_id=excluded.event_id,analysis_snapshot=excluded.analysis_snapshot''',
        (uid, location_id, field, _dump(value), now, event_id, snapshot))
    return label_for(conn, uid, location_id)


def freeze_marker(conn):
    from . import db
    watermark = conn.execute('SELECT COALESCE(MAX(event_id),0) FROM location_events').fetchone()[0]
    return f'{db.utcnow()}|{watermark}'


def summary(conn):
    """Counts of location records, deliberately separate from legacy UID counts."""
    records = {}
    for row in conn.execute('SELECT * FROM location_labels'):
        state = records.setdefault((row['uid'], row['location_id']), {})
        state[row['field']] = json.loads(row['value']) if row['value'] is not None else None
    states = list(records.values())
    decisions = {r['uid']: r['is_excluded'] for r in conn.execute('SELECT uid,is_excluded FROM decisions')}
    def n(predicate): return sum(bool(predicate(s)) for s in states)
    return {'已标注': len(states), '已处理': n(lambda s: s.get('action')),
            '待投': n(lambda s: s.get('action') == 'saved'),
            '想投': n(lambda s: s.get('action') == 'saved'),
            '已投递': n(lambda s: s.get('action') == 'applied'),
            '优先待投': n(lambda s: s.get('action') == 'saved' and s.get('priority')),
            '漏杀候选': sum(s.get('eligibility') == 'ineligible' and decisions.get(uid) == 0 for (uid, _), s in records.items()),
            '误杀候选': sum(s.get('eligibility') == 'eligible' and decisions.get(uid) == 1 for (uid, _), s in records.items())}


def export(conn, out_dir):
    """Lossless local supplement to legacy labels.csv/md; not a public fixture."""
    rows = [dict(r) for r in conn.execute('SELECT * FROM location_labels ORDER BY uid,location_id,field')]
    events = [dict(r) for r in conn.execute('SELECT * FROM location_events ORDER BY event_id')]
    places = [dict(r) for r in conn.execute('''SELECT * FROM job_locations WHERE
        correction_json IS NOT NULL OR location_id IN (SELECT location_id FROM location_labels)
        OR location_id IN (SELECT location_id FROM location_events) ORDER BY uid,location_id''')]
    path = out_dir / 'location-records.json'
    path.write_text(_dump({'format_version': 1, 'locations': places, 'fields': rows, 'events': events}), encoding='utf-8')
    return {'location_count': len({r['location_id'] for r in rows}), 'locations': str(path)}
