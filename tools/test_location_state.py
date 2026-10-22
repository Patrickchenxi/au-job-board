"""Synthetic location migration, ownership, retry and query integration."""
from pathlib import Path
import sqlite3,sys,tempfile,unittest,threading
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jobs import db,location_store as store,labels,panel_data,panel,report,migrations
class LocationState(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.db';self.c=db.connect(self.path)
        for id,loc in [('a','Melbourne VIC / Sydney NSW'),('b','Sydney NSW')]:
            db.upsert_job(self.c,dict(source='synthetic',source_id=id,title='Synthetic Graduate Developer',company='Synthetic Workshop',location=loc,description='Handwritten sample developer role.'))
            db.set_dedupe(self.c,'synthetic:'+id,'same','synthetic:a');db.replace_decision(self.c,'synthetic:'+id,False);db.replace_score(self.c,'synthetic:'+id,'T1',0,0,0,2 if id=='a' else 8,[],1)
        self.c.commit();self.locs=store.locations_for(self.c,'synthetic:a');self.a,self.b=[x['location_id'] for x in self.locs]
        self.patch=patch('jobs.skills.load_skills',return_value={'skills':[]});self.patch.start()
    def tearDown(self):self.patch.stop();self.c.close();self.tmp.cleanup()
    def edit(self,lid,field,value):
        self.c.execute('BEGIN IMMEDIATE');out=store.set_label(self.c,'synthetic:a',lid,field,value);self.c.commit();return out
    def test_no_inherit_and_clear(self):
        labels.set_label(self.c,'synthetic:a',action='applied',note='Synthetic old scope')
        self.assertIsNone(store.label_for(self.c,'synthetic:a',self.a).get('action'))
        self.edit(self.a,'action','saved');self.assertIsNone(store.label_for(self.c,'synthetic:a',self.b).get('action'))
        self.edit(self.a,'action',None);self.assertIsNone(store.label_for(self.c,'synthetic:a',self.a).get('action'))
        self.assertEqual(labels.get_labels(self.c)['synthetic:a']['action'],'applied')
    def test_stable_reorder_and_history(self):
        self.edit(self.a,'note','Synthetic note')
        self.c.execute("UPDATE jobs SET location='Sydney NSW / Melbourne VIC' WHERE uid='synthetic:a'");store.sync_job(self.c,'synthetic:a');self.c.commit()
        self.assertEqual([x['location_id'] for x in store.locations_for(self.c,'synthetic:a')],[self.b,self.a])
        self.c.execute("UPDATE jobs SET location='Victoria' WHERE uid='synthetic:a'");store.sync_job(self.c,'synthetic:a');self.c.commit()
        historical=[x for x in store.locations_for(self.c,'synthetic:a') if not x['active']]
        self.assertEqual(historical[0]['location_id'],self.a)
    def test_correction_survives_rerun_and_clear(self):
        self.c.execute('BEGIN IMMEDIATE');store.set_correction(self.c,'synthetic:a',self.a,'Melbourne VIC 3000','remote');self.c.commit()
        store.sync_job(self.c,'synthetic:a');self.c.commit();loc=store.locations_for(self.c,'synthetic:a')[0]
        self.assertTrue(loc['corrected']);self.assertEqual(loc['postcode'],'3000')
        self.c.execute('BEGIN IMMEDIATE');store.set_correction(self.c,'synthetic:a',self.a,None);self.c.commit()
        self.assertEqual(store.locations_for(self.c,'synthetic:a')[0]['precision'],'city')
    def test_rollback_and_retry(self):
        self.c.execute('BEGIN IMMEDIATE');store.set_label(self.c,'synthetic:a',self.a,'priority',1);self.c.rollback()
        self.assertFalse(store.label_for(self.c,'synthetic:a',self.a).get('_has_record'))
        self.edit(self.a,'priority',1);self.edit(self.a,'priority',0)
        self.assertEqual(store.label_for(self.c,'synthetic:a',self.a)['priority'],0)
    def test_invalid_scope_rejected(self):
        with self.assertRaises(ValueError):store.set_label(self.c,'synthetic:b',self.a,'action','saved')
        with self.assertRaises(ValueError):store.set_correction(self.c,'synthetic:a',self.a,'Melbourne VIC / Sydney NSW')
        self.c.rollback()
    def test_frozen_same_second_action(self):
        with patch('jobs.db.utcnow',return_value='2026-10-22T00:00:00+00:00'):
            marker=store.freeze_marker(self.c);self.edit(self.a,'action','saved')
            self.assertIsNone(store.label_for(self.c,'synthetic:a',self.a,marker).get('action'))
            marker=store.freeze_marker(self.c);self.edit(self.a,'action',None)
            self.assertEqual(store.label_for(self.c,'synthetic:a',self.a,marker)['action'],'saved')
    def test_filter_before_representative_and_default(self):
        rows,total=panel_data._query(self.c,{},'all',0,20,{'geo':'Melbourne VIC'})
        self.assertEqual(total,1);self.assertEqual(rows[0]['uid'],'synthetic:a')
        self.assertEqual(rows[0]['_location']['location_id'],self.a)
        self.assertEqual(panel._find(self.c,{},'synthetic:a',filters={'geo':'Melbourne VIC'})['_location']['location_id'],self.a)
    def test_exact_folded_source_readable(self):self.assertEqual(panel._find(self.c,{},'synthetic:a')['uid'],'synthetic:a')
    def test_upgrade_idempotent_and_old_fields_unchanged(self):
        labels.set_label(self.c,'synthetic:a',note='Synthetic old note',action='saved')
        before=[tuple(r) for r in self.c.execute('SELECT * FROM labels')];events=[tuple(r) for r in self.c.execute('SELECT * FROM label_events')]
        self.c.execute('PRAGMA user_version=1');self.c.commit();self.c.close();self.c=db.connect(self.path)
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM labels')]);self.assertEqual(events,[tuple(r) for r in self.c.execute('SELECT * FROM label_events')])
        ids=[r[0] for r in self.c.execute('SELECT location_id FROM job_locations ORDER BY location_id')];self.c.close();self.c=db.connect(self.path)
        self.assertEqual(ids,[r[0] for r in self.c.execute('SELECT location_id FROM job_locations ORDER BY location_id')])
    def test_failed_migration_is_atomic(self):
        for table in ('location_labels','location_events','job_locations'):self.c.execute('DROP TABLE '+table)
        self.c.execute('PRAGMA user_version=1');self.c.commit();self.c.close()
        with patch('jobs.location_store.sync_all',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):db.connect(self.path)
        self.c=sqlite3.connect(self.path);self.c.row_factory=sqlite3.Row
        self.assertEqual(self.c.execute('PRAGMA user_version').fetchone()[0],1)
        self.assertIsNone(self.c.execute("SELECT name FROM sqlite_master WHERE name='job_locations'").fetchone())
    def test_summary_export_keep_scope_and_null(self):
        import json
        self.edit(self.a,'action','saved');self.edit(self.a,'priority',0);self.edit(self.b,'action','applied')
        self.assertEqual(store.summary(self.c)['已处理'],2)
        info=labels.export(self.c,Path(self.tmp.name)/'out')
        data=json.loads(Path(info['locations']).read_text());self.assertEqual(info['location_count'],2)
        self.assertEqual(len(data['fields']),3);self.assertEqual(len(data['events']),3)
        self.assertEqual([tuple(r) for r in self.c.execute('SELECT * FROM labels')],[])
    def test_applied_date_survives_idempotent_retry(self):
        with patch('jobs.db.utcnow',return_value='2026-10-22T00:00:00+00:00'):self.edit(self.a,'action','applied')
        with patch('jobs.db.utcnow',return_value='2026-10-23T00:00:00+00:00'):self.edit(self.a,'action','applied')
        self.assertEqual(store.label_for(self.c,'synthetic:a',self.a)['applied_at'],'2026-10-22T00:00:00+00:00')
    def test_scoped_records_findable_without_region(self):
        self.edit(self.a,'note','Synthetic scoped note')
        rows,total=panel_data._query(self.c,{},'labelled',0,20,{})
        self.assertIn('synthetic:a',[r['uid'] for r in rows]);row=next(r for r in rows if r['uid']=='synthetic:a')
        self.assertEqual(row['_scoped_records'],1);self.assertFalse(row['location_scope'])
        self.assertIsNone(row['_label'].get('action'))
    def test_cross_state_postcode_query(self):
        db.upsert_job(self.c,dict(source='synthetic',source_id='border',title='Synthetic role',company='Synthetic Border Team',location='2620'));self.c.commit()
        rows,total=panel_data._query(self.c,{},'all',0,20,{'geo':'2620'})
        self.assertIn('synthetic:border',[r['uid'] for r in rows])
    def test_all_matching_places_checked_before_status_filter(self):
        self.c.execute("UPDATE jobs SET location='Melbourne VIC / Geelong VIC' WHERE uid='synthetic:a'");store.sync_job(self.c,'synthetic:a');self.c.commit()
        geelong=next(l for l in store.locations_for(self.c,'synthetic:a') if l.get('locality')=='Geelong')
        self.edit(geelong['location_id'],'action','saved')
        labels.set_label(self.c,'synthetic:a',note='Synthetic historical group note')
        for view,filters in [('labelled',{'geo':'VIC'}),('all',{'geo':'VIC','action':'saved'})]:
            rows,total=panel_data._query(self.c,{},view,0,20,filters)
            self.assertEqual(rows[0]['_location']['location_id'],geelong['location_id'])
        self.edit(self.a,'action','applied')
        rows,total=panel_data._query(self.c,{},'recommend',0,20,{'geo':'VIC'})
        self.assertEqual(total,0)
        self.edit(geelong['location_id'],'action',None)
        rows,total=panel_data._query(self.c,{},'recommend',0,20,{'geo':'VIC'})
        self.assertEqual(rows[0]['_location']['location_id'],geelong['location_id'])
    def test_first_write_does_not_expand_frozen_dedupe(self):
        db.upsert_job(self.c,dict(source='synthetic',source_id='peer',title='Synthetic Graduate Developer',company='Synthetic Workshop',location='Melbourne VIC'))
        db.set_dedupe(self.c,'synthetic:peer','same','synthetic:a');db.replace_decision(self.c,'synthetic:peer',False);db.replace_score(self.c,'synthetic:peer','T1',0,0,0,1,[],1);self.c.commit()
        marker=store.freeze_marker(self.c)
        before,total=panel_data._query(self.c,{},'recommend',0,20,{'geo':'Melbourne VIC'},marker)
        self.edit(self.a,'action','saved')
        after,total_after=panel_data._query(self.c,{},'recommend',0,20,{'geo':'Melbourne VIC'},marker)
        self.assertEqual([r['uid'] for r in before],[r['uid'] for r in after]);self.assertEqual(total,total_after)
    def test_cleared_correction_history_stays_reachable(self):
        self.c.execute('BEGIN IMMEDIATE');store.set_correction(self.c,'synthetic:a',self.a,'Melbourne VIC 3000');store.set_correction(self.c,'synthetic:a',self.a,None);self.c.commit()
        self.c.execute("UPDATE jobs SET location='Victoria' WHERE uid='synthetic:a'");store.sync_job(self.c,'synthetic:a');self.c.commit()
        row=panel._find(self.c,{},'synthetic:a',location_id=self.a)
        self.assertEqual(row['_location']['location_id'],self.a);self.assertFalse(row['_location']['active'])
    def test_partial_fields_serialize_two_writers(self):
        self.c.close();errors=[]
        def writer(field,value):
            c=db.connect(self.path)
            try:
                c.execute('BEGIN IMMEDIATE');store.set_label(c,'synthetic:a',self.a,field,value);c.commit()
            except Exception as e:errors.append(str(e))
            finally:c.close()
        ts=[threading.Thread(target=writer,args=args) for args in [('note','Synthetic concurrent note'),('action','saved')]]
        for t in ts:t.start()
        for t in ts:t.join()
        self.c=db.connect(self.path);self.assertEqual(errors,[]);state=store.label_for(self.c,'synthetic:a',self.a)
        self.assertEqual(state['action'],'saved');self.assertIn('Synthetic concurrent note',state['note'])
if __name__=='__main__':unittest.main(verbosity=2)
