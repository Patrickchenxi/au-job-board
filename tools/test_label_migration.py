"""Synthetic migration and manual-state regressions; no private inputs or network."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobs import db, labels, migrations

OLD = '2000-01-01T00:00:00+00:00'
NOW = '2000-01-02T00:00:00+00:00'


def seed_job(conn, uid='synthetic:a', excluded=0):
    source, source_id = uid.split(':', 1)
    db.upsert_job(conn, {'source': source, 'source_id': source_id,
                        'title': 'Synthetic support role', 'company': 'Example Workshop',
                        'description': 'Australian citizenship is required.'})
    conn.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?,?)',
                 (uid, excluded, 'synthetic_rule', 'exclude' if excluded else 'none',
                  'Australian citizenship is required.', 7, OLD))
    conn.commit()


def old_database(path):
    schema = db.SCHEMA
    # Generate a legacy-shaped database without importing archived/private code.
    import re
    schema = re.sub(r'^\s*(priority|action_at|eligibility_source|eligibility_at|eligibility_analysis)\s+[^\n]*\n', '', schema, flags=re.M)
    schema = re.sub(r'^\s*analysis_snapshot\s+[^\n]*\n', '', schema, flags=re.M)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    seed_job(conn)
    conn.execute('INSERT INTO labels(uid,note,action,interest,eligibility,applied_at,labeled_at,rules_version) VALUES (?,?,?,?,?,?,?,?)',
                 ('synthetic:a', '优先投递；搬迁；', 'applied', 'want', 'unsure', OLD, OLD, 3))
    conn.commit()
    return conn


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_conversion_preserves_dates_and_unknown_judgment(self):
        c = old_database(self.path); c.close()
        c = db.connect(self.path)
        row = labels.get_labels(c)['synthetic:a']
        self.assertEqual((row['action'], row['interest'], row['eligibility']), ('applied', 'want', 'unsure'))
        self.assertEqual((row['applied_at'], row['labeled_at']), (OLD, OLD))
        self.assertTrue(row['priority']); self.assertEqual(row['note'], '搬迁；')
        self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], migrations.SCHEMA_VERSION)
        self.assertEqual(c.execute('SELECT old_value FROM label_events WHERE field="note" AND source="migration"').fetchone()[0], '优先投递；搬迁；')
        self.assertEqual(c.execute('SELECT rules_version FROM decisions').fetchone()[0], 7)
        c.close()

    def test_reopen_is_idempotent_and_does_not_resurrect_priority(self):
        c = old_database(self.path); c.close()
        c = db.connect(self.path); labels.set_label(c, 'synthetic:a', priority=False)
        before = list(c.execute('SELECT * FROM label_events')); c.close()
        c = db.connect(self.path)
        self.assertFalse(labels.get_labels(c)['synthetic:a']['priority'])
        self.assertEqual([tuple(x) for x in c.execute('SELECT * FROM label_events')], [tuple(x) for x in before]); c.close()

    def test_only_complete_canonical_tag_is_migrated(self):
        c = old_database(self.path)
        c.execute('UPDATE labels SET note=?', ('希望优先投递但待确认；Prioritize；',)); c.commit(); c.close()
        c = db.connect(self.path); row = labels.get_labels(c)['synthetic:a']
        self.assertFalse(row['priority']); self.assertEqual(row['note'], '希望优先投递但待确认；Prioritize；'); c.close()

    def test_failed_migration_rolls_back_schema_data_and_version(self):
        c = old_database(self.path); c.close()
        original = migrations._migrate_labels
        def fail(conn):
            original(conn)
            raise RuntimeError('synthetic interruption')
        with patch.object(migrations, '_migrate_labels', side_effect=fail):
            with self.assertRaises(RuntimeError): db.connect(self.path)
        c = sqlite3.connect(self.path)
        self.assertNotIn('priority', [r[1] for r in c.execute('PRAGMA table_info(labels)')])
        self.assertEqual(c.execute('SELECT note FROM labels').fetchone()[0], '优先投递；搬迁；')
        self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 0); c.close()
        c = db.connect(self.path); self.assertTrue(labels.get_labels(c)['synthetic:a']['priority']); c.close()

    def test_future_schema_fails_closed(self):
        c = old_database(self.path); c.execute('PRAGMA user_version=999'); c.close()
        with self.assertRaises(ValueError): db.connect(self.path)
        c = sqlite3.connect(self.path)
        self.assertNotIn('priority', [r[1] for r in c.execute('PRAGMA table_info(labels)')]); c.close()

    def test_note_migration_preserves_group_ownership_including_same_second_clear(self):
        for newer in ('clear', 'note'):
            with self.subTest(newer=newer):
                path = self.path.with_name(newer + '.db')
                c = old_database(path)
                c.execute('UPDATE labels SET action=NULL, note=?, labeled_at=?',
                          ('优先投递；搬迁；', NOW))
                c.execute('INSERT INTO labels(uid,note,labeled_at) VALUES (?,?,?)',
                          ('synthetic:b', None, NOW))
                events = [('synthetic:a', '优先投递；搬迁；'), ('synthetic:b', None)]
                if newer == 'note': events.reverse()
                for uid, value in events:
                    c.execute("INSERT INTO label_events(uid,field,new_value,source,at) VALUES (?,'note',?,'panel',?)",
                              (uid, value, NOW))
                c.commit(); c.close()
                c = db.connect(path)
                expected = None if newer == 'clear' else '搬迁；'
                self.assertEqual(labels.merge_labels(list(labels.get_labels(c, with_events=True).values()))['note'], expected)
                labels.set_label(c, 'synthetic:a', priority=False)
                self.assertEqual(labels.merge_labels(list(labels.get_labels(c, with_events=True).values()))['note'], expected)
                c.close()

    def test_priority_only_legacy_note_does_not_revive_older_group_note(self):
        c = old_database(self.path)
        c.execute('UPDATE labels SET note=?,labeled_at=?', ('优先投递；', NOW))
        c.execute('INSERT INTO labels(uid,note,labeled_at) VALUES (?,?,?)', ('synthetic:b','Old note；',OLD))
        c.commit(); c.close()
        c = db.connect(self.path)
        self.assertIsNone(labels.merge_labels(list(labels.get_labels(c, with_events=True).values()))['note'])
        labels.set_label(c, 'synthetic:a', priority=False)
        self.assertIsNone(labels.merge_labels(list(labels.get_labels(c, with_events=True).values()))['note'])
        c.close()

    def test_fresh_database_and_existing_action_values(self):
        c = db.connect(self.path); seed_job(c)
        for action in ('saved', 'applied', 'skipped'):
            labels.set_label(c, 'synthetic:a', action=action)
            self.assertEqual(labels.get_labels(c)['synthetic:a']['action'], action)
        self.assertEqual(labels.display('action', 'saved'), '想投'); c.close()


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.path = Path(self.tmp.name) / 'test.db'
        self.c = db.connect(self.path); seed_job(self.c)
    def tearDown(self):
        self.c.close(); self.tmp.cleanup()

    def test_partial_writes_and_action_cancel_preserve_other_fields(self):
        labels.set_label(self.c, 'synthetic:a', action='saved', note='Keep this', priority=True)
        labels.set_label(self.c, 'synthetic:a', action=None)
        row = labels.get_labels(self.c)['synthetic:a']
        self.assertIsNone(row['action']); self.assertTrue(row['priority']); self.assertEqual(row['note'], 'Keep this；')
        labels.set_label(self.c, 'synthetic:a', note='Next note')
        self.assertTrue(labels.get_labels(self.c)['synthetic:a']['priority'])

    def test_invalid_priority_rolls_back_all_fields(self):
        labels.set_label(self.c, 'synthetic:a', note='Original', priority=True)
        with self.assertRaises(ValueError): labels.set_label(self.c, 'synthetic:a', note='Wrong', priority='yes')
        self.assertEqual(labels.get_labels(self.c)['synthetic:a']['note'], 'Original；')

    def test_parallel_partial_writes_preserve_priority_and_note(self):
        gate = threading.Barrier(2); errors=[]
        def write(fields):
            c = db.connect(self.path)
            try:
                gate.wait(); labels.set_label(c, 'synthetic:a', **fields)
            except BaseException as e: errors.append(e)
            finally: c.close()
        ts = [threading.Thread(target=write, args=(f,)) for f in ({'priority':True}, {'note':'Concurrent note'})]
        for t in ts: t.start()
        for t in ts: t.join(10)
        self.assertFalse(errors); self.assertFalse(any(t.is_alive() for t in ts))
        r = labels.get_labels(self.c)['synthetic:a']; self.assertTrue(r['priority']); self.assertEqual(r['note'], 'Concurrent note；')

    def test_qualification_read_does_not_create_manual_label(self):
        machine = dict(self.c.execute('SELECT * FROM decisions').fetchone())
        before = self.c.total_changes
        q = labels.qualification(machine, {})
        self.assertEqual(q['analysis'], 'eligible'); self.assertFalse(q['corrected']); self.assertEqual(q['effective'], 'eligible')
        self.assertEqual(self.c.total_changes, before); self.assertEqual(labels.get_labels(self.c), {})

    def test_correction_snapshot_survives_reanalysis_and_note_edit(self):
        labels.set_label(self.c, 'synthetic:a', eligibility='ineligible', source='panel')
        old = labels.get_labels(self.c)['synthetic:a']
        snapshot = json.loads(old['eligibility_analysis'])
        self.assertEqual(snapshot['is_excluded'], 0); self.assertEqual(snapshot['rules_version'], 7)
        self.c.execute('UPDATE decisions SET is_excluded=1,rules_version=8'); self.c.commit()
        labels.set_label(self.c, 'synthetic:a', note='Later note', rules_version=99)
        new = labels.get_labels(self.c)['synthetic:a']
        self.assertEqual(new['eligibility_analysis'], old['eligibility_analysis']); self.assertEqual(new['eligibility_source'], 'panel')
        event = self.c.execute('SELECT analysis_snapshot FROM label_events WHERE field="eligibility"').fetchone()
        self.assertEqual(json.loads(event[0])['rules_version'], 7)
        self.assertEqual(labels.summary(self.c)['漏杀候选'], 0)

    def test_unmatched_analysis_snapshot_keeps_displayed_qualification_excerpt(self):
        text = 'A current driving licence is required.'
        self.c.execute('UPDATE jobs SET description=?', (text,))
        self.c.execute('UPDATE decisions SET rule_id=NULL,rule_kind="none",matched_text=NULL')
        self.c.commit()
        labels.set_label(self.c, 'synthetic:a', eligibility='ineligible', source='panel')
        row = labels.get_labels(self.c)['synthetic:a']
        snapshot = json.loads(row['eligibility_analysis'])
        self.assertEqual(snapshot['eligibility_snippet'], text)
        self.c.execute('UPDATE jobs SET description="A different later description"'); self.c.commit()
        labels.set_label(self.c, 'synthetic:a', note='Later note')
        event = self.c.execute('SELECT analysis_snapshot FROM label_events WHERE field="eligibility"').fetchone()
        self.assertEqual(json.loads(event[0])['eligibility_snippet'], text)

    def test_correction_cancel_preserves_event_and_restores_machine(self):
        labels.set_label(self.c, 'synthetic:a', eligibility='ineligible')
        self.assertEqual(labels.summary(self.c)['漏杀候选'], 1)
        labels.set_label(self.c, 'synthetic:a', eligibility=None)
        row = labels.get_labels(self.c)['synthetic:a']
        self.assertFalse(labels.qualification({'is_excluded':0}, row)['corrected'])
        self.assertEqual(labels.summary(self.c)['漏杀候选'], 0)
        self.assertGreaterEqual(self.c.execute('SELECT COUNT(*) FROM label_events WHERE field="eligibility"').fetchone()[0], 2)

    def test_unsure_rejected_for_new_writes_but_legacy_readable(self):
        with self.assertRaises(ValueError): labels.set_label(self.c, 'synthetic:a', eligibility='unsure')
        self.c.execute('INSERT INTO labels(uid,eligibility) VALUES (?,?)', ('synthetic:a','unsure')); self.c.commit()
        q=labels.qualification({'is_excluded':0}, labels.get_labels(self.c)['synthetic:a'])
        self.assertFalse(q['corrected']); self.assertEqual(q['effective'], 'eligible')
        self.assertEqual(labels.summary(self.c)['漏杀候选'], 0)

    def test_missing_analysis_is_unknown(self):
        q=labels.qualification({}, {})
        self.assertIsNone(q['analysis']); self.assertIsNone(q['effective']); self.assertFalse(q['corrected'])

    def test_missing_historical_application_date_not_filled_by_note_edit(self):
        self.c.execute('INSERT INTO labels(uid,action,labeled_at) VALUES (?,?,?)', ('synthetic:a','applied',OLD)); self.c.commit()
        labels.set_label(self.c, 'synthetic:a', note='Only a note')
        self.assertIsNone(labels.get_labels(self.c)['synthetic:a']['applied_at'])

    def test_current_want_count_uses_action_not_interest(self):
        labels.set_label(self.c, 'synthetic:a', interest='want')
        self.assertEqual(labels.summary(self.c)['想投'], 0)
        labels.set_label(self.c, 'synthetic:a', action='saved')
        self.assertEqual(labels.summary(self.c)['想投'], 1)

    def test_frozen_action_survives_same_second_cancel_and_switch(self):
        with patch.object(db, 'utcnow', return_value=NOW):
            labels.set_label(self.c, 'synthetic:a', action='saved')
            marker=labels.freeze_marker(self.c)
            labels.set_label(self.c, 'synthetic:a', action=None)
            self.assertEqual(labels.action_states_at(self.c, marker)['synthetic:a']['action'], 'saved')
            labels.set_label(self.c, 'synthetic:a', action='applied')
            self.assertEqual(labels.action_states_at(self.c, marker)['synthetic:a']['action'], 'saved')
            self.assertEqual(labels.get_labels(self.c)['synthetic:a']['action'], 'applied')

    def test_unprocessed_at_entry_stays_unprocessed_in_frozen_snapshot(self):
        with patch.object(db, 'utcnow', return_value=NOW):
            labels.set_label(self.c, 'synthetic:a', note='Before entry')
            marker=labels.freeze_marker(self.c)
            labels.set_label(self.c, 'synthetic:a', action='saved')
            self.assertIsNone(labels.action_states_at(self.c, marker).get('synthetic:a', {}).get('action'))

    def test_priority_false_event_wins_group_merge(self):
        seed_job(self.c, 'synthetic:b')
        labels.set_label(self.c, 'synthetic:b', priority=True)
        labels.set_label(self.c, 'synthetic:a', priority=False)
        all_labels=labels.get_labels(self.c, with_events=True)
        self.assertFalse(labels.merge_labels(list(all_labels.values()))['priority'])
        labels.set_label(self.c, 'synthetic:b', note='Unrelated later note')
        self.assertFalse(labels.merge_labels(list(labels.get_labels(self.c, with_events=True).values()))['priority'])


if __name__ == '__main__': unittest.main()
