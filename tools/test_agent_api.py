"""Authenticated loopback API, source scope and immutable snapshot regressions.

Every record and token here is handwritten synthetic data. No production paths.
"""
from pathlib import Path
from contextlib import closing
import datetime as dt
import hashlib
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobs import agent_api as api, agent_client, batches, db, labels, location_store, panel_data

TOKEN = 'synthetic-api-token-not-a-real-secret-000000'


class AgentAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root/'synthetic.db'
        self.skills = self.root/'skills.yaml'; self.skills.write_text('skills: []\n')
        self.config = {'db_path': str(self.path), 'skills_path': str(self.skills), 'panel': {'page_size': 40}}
        with closing(db.connect(self.path)) as conn:
            for uid, loc, score in [('a', 'Sydney NSW / Melbourne VIC', 9), ('b', 'Sydney NSW', 20), ('c', 'Undisclosed', 2)]:
                self.job(conn, uid, loc, score)
            db.set_dedupe(conn, 'synthetic:a', 'synthetic-group', 'synthetic-group')
            db.set_dedupe(conn, 'synthetic:b', 'synthetic-group', 'synthetic-group')
            labels.set_label(conn, 'synthetic:a', action='applied', note='Synthetic legacy context')
            self.lid = next(x['location_id'] for x in location_store.locations_for(conn, 'synthetic:a') if 'Melbourne' in x['raw'])
            conn.execute('BEGIN IMMEDIATE'); location_store.set_label(conn, 'synthetic:a', self.lid, 'note', 'Synthetic Melbourne note'); conn.commit()
        self.clock = [100.]
        self.store = api.SnapshotStore(clock=lambda: self.clock[0])
        self.server = api.make_server(self.config, TOKEN, port=0, store=self.store, panel_url='http://127.0.0.1:8299/')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def job(self, conn, ident, location='Melbourne VIC', score=5):
        db.upsert_job(conn, dict(source='synthetic', source_id=ident, title='Synthetic Developer '+ident,
                               company='Synthetic Company', location=location, url='https://example.invalid/jobs/'+ident,
                               description='Handwritten synthetic full job description '+ident, listing_date='2026-10-22'))
        db.set_dedupe(conn, 'synthetic:'+ident, ident, ident)
        db.replace_decision(conn, 'synthetic:'+ident, False)
        db.replace_score(conn, 'synthetic:'+ident, 'T1', 0, 0, 0, score, [], 1)
        conn.commit()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, path, *, method='GET', token=TOKEN, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        h = {} if token is None else {'Authorization': 'Bearer '+token}
        h.update(headers or {})
        c.request(method, path, headers=h)
        response = c.getresponse(); body = response.read(); status = response.status
        out = json.loads(body) if body else None
        hs = dict(response.getheaders()); c.close()
        return status, out, hs

    def first(self, query=''):
        status, data, _ = self.request('/api/v1/jobs'+query)
        self.assertEqual(status, 200, data)
        return data

    def test_auth_origin_host_and_write_routes(self):
        for path in ['/api/v1/jobs', '/api/v1/batches', '/api/v1/jobs/synthetic%3Aa', '/api/config-settings']:
            self.assertEqual(self.request(path, token=None)[0], 401)
            self.assertEqual(self.request(path, token='wrong')[0], 401)
        for headers in [{'Origin': 'http://evil.invalid'}, {'Origin': 'null'}, {'Host': 'evil.invalid'}]:
            self.assertEqual(self.request('/api/v1/jobs', headers=headers)[0], 403)
        for method in ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE']:
            self.assertEqual(self.request('/api/label', method=method)[0], 405)
        self.assertEqual(self.request('/api/label')[0], 404)
        _, _, headers = self.request('/api/v1/jobs')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(headers['Cache-Control'], 'no-store')

    def test_complete_337_pagination_stable_detail_and_changes(self):
        with closing(db.connect(self.path)) as conn:
            conn.execute('DELETE FROM labels'); conn.execute('DELETE FROM label_events')
            for i in range(337): self.job(conn, 'page-'+str(i), score=i)
        result = self.first('?limit=100'); seen = list(result['items']); sid = result['snapshot_id']
        first_uid = seen[0]['uid']
        with closing(db.connect(self.path)) as conn:
            self.job(conn, 'later', score=999)
            conn.execute('UPDATE jobs SET description=? WHERE uid=?', ('Changed after snapshot', first_uid)); conn.commit()
        while result['next_cursor']:
            result = self.first('?cursor='+quote(result['next_cursor'], safe=''))
            self.assertEqual(result['snapshot_id'], sid); seen.extend(result['items'])
        self.assertEqual(len(seen), 339)
        self.assertEqual(len({r['uid'] for r in seen}), 339)
        self.assertNotIn('synthetic:later', {r['uid'] for r in seen})
        status, detail, _ = self.request('/api/v1/jobs/'+quote(first_uid,safe='')+'?snapshot_id='+sid)
        self.assertEqual(status, 200); self.assertIn('Handwritten synthetic', detail['item']['description'])
        self.assertEqual(self.request('/api/v1/jobs/synthetic%3Alater?snapshot_id='+sid)[0], 404)
        self.assertEqual(self.request('/api/v1/jobs/'+quote(first_uid,safe=''))[1]['item']['description'], 'Changed after snapshot')

    def test_filter_parity_folded_source_and_human_scope(self):
        result = self.first('?geo=Melbourne%20VIC')
        with closing(api.read_connection(self.path)) as conn:
            expected, total = panel_data._query(conn, self.config, 'all', 0, 100, {'geo':'Melbourne VIC'})
        self.assertEqual([r['uid'] for r in result['items']], [r['uid'] for r in expected])
        self.assertEqual(result['total'], total)
        row = next(r for r in result['items'] if r['uid']=='synthetic:a')
        self.assertEqual(row['selected_location_id'], self.lid); self.assertIsNone(row['human']['action'])
        self.assertIn('Synthetic Melbourne note', row['human']['note'])
        self.assertEqual(row['legacy_reference']['human']['action'], 'applied')
        self.assertIn('synthetic%3Aa&location_id='+self.lid, row['panel_url'])
        all_result = self.first()
        self.assertNotIn('synthetic:a', {r['uid'] for r in all_result['items']})
        status, detail, _ = self.request('/api/v1/jobs/synthetic%3Aa?snapshot_id='+all_result['snapshot_id'])
        self.assertEqual(status, 200); self.assertEqual(detail['item']['uid'], 'synthetic:a')
        status, detail, _ = self.request('/api/v1/jobs/synthetic%3Aa?snapshot_id='+all_result['snapshot_id']+'&location_id='+self.lid)
        self.assertEqual(status, 200); self.assertIsNone(detail['item']['human']['action'])

    def test_cursor_tampering_query_binding_expiry_and_restart(self):
        result = self.first('?limit=1'); cursor = result['next_cursor']
        self.assertEqual(self.request('/api/v1/jobs?cursor='+quote(cursor)+'&limit=2')[0], 400)
        bad = ('A' if cursor[0]!='A' else 'B')+cursor[1:]
        self.assertEqual(self.request('/api/v1/jobs?cursor='+quote(bad))[0], 400)
        self.clock[0] += 301
        self.assertEqual(self.request('/api/v1/jobs?cursor='+quote(cursor))[0], 410)
        self.assertEqual(self.request('/api/v1/jobs/synthetic%3Aa?snapshot_id='+result['snapshot_id'])[0], 410)
        self.server.api.store = api.SnapshotStore()
        self.assertEqual(self.request('/api/v1/jobs?cursor='+quote(cursor))[0], 400)

    def test_readonly_missing_schema_and_no_runtime_repair(self):
        before = self.path.read_bytes()
        runtime = self.root/'.synthetic.db.panel-update'; runtime.mkdir()
        marker = runtime/'latest.json'; marker.write_text('{"state":"running","task_id":"synthetic-pipeline"}')
        old = marker.read_bytes()
        with patch('jobs.db.connect', side_effect=AssertionError('writer forbidden')), patch('jobs.run_state.latest', side_effect=AssertionError('repair forbidden')):
            self.first(); self.request('/api/v1/jobs/synthetic%3Aa')
            self.assertEqual(api._pipeline(self.config, 'synthetic-pipeline')['state'], 'unknown')
        self.assertEqual(self.path.read_bytes(), before); self.assertEqual(marker.read_bytes(), old)
        with closing(api.read_connection(self.path)) as conn:
            with self.assertRaises(sqlite3.OperationalError): conn.execute('DELETE FROM jobs')
        missing = self.root/'missing'/'absent.db'
        with self.assertRaises(sqlite3.OperationalError): api.read_connection(missing)
        self.assertFalse(missing.parent.exists())
        with closing(sqlite3.connect(self.path)) as conn: conn.execute('PRAGMA user_version=0'); conn.commit()
        self.assertEqual(self.request('/api/v1/jobs')[0], 503)

    def test_invalid_queries_and_capacity_are_explicit(self):
        for query in ['?limit=0','?limit=201','?limit=no','?view=invalid','?q=a&q=b','?mode=office','?geo=not-a-real-place',
                      '?scope=batch_new&day=2026-10-22','?scope=first_seen_day','?scope=legacy_new&view=all','?salary=0', '?action=bogus', '?view=recommend&action=saved']:
            self.assertEqual(self.request('/api/v1/jobs'+query)[0], 400, query)
        self.server.api.store = api.SnapshotStore(max_snapshots=1)
        original = self.first('?limit=1')
        self.assertEqual(self.request('/api/v1/jobs')[0],429)
        self.assertEqual(self.request('/api/v1/jobs?cursor='+quote(original['next_cursor']))[0],200)
        self.server.api.store = api.SnapshotStore(max_snapshot_bytes=10)
        self.assertEqual(self.request('/api/v1/jobs')[0],413)

    def test_melbourne_day_boundaries_and_dst(self):
        start,end=api.day_window('2026-10-04');self.assertEqual((end-start).total_seconds(),23*3600)
        start,end=api.day_window('2026-04-05');self.assertEqual((end-start).total_seconds(),25*3600)
        start,end=api.day_window('2026-10-22')
        with closing(db.connect(self.path)) as conn:
            conn.execute('UPDATE jobs SET first_seen_at=? WHERE uid=?',(start.isoformat(),'synthetic:a'))
            conn.execute('UPDATE jobs SET first_seen_at=? WHERE uid=?',(end.isoformat(),'synthetic:b'))
            conn.execute('UPDATE jobs SET first_seen_at=? WHERE uid=?',((start-dt.timedelta(seconds=1)).isoformat(),'synthetic:c'));conn.commit()
        result=self.first('?scope=first_seen_day&day=2026-10-22')
        self.assertEqual([r['uid'] for r in result['items']],['synthetic:a'])
        self.assertEqual(result['time_window']['timezone'],'Australia/Melbourne')

    def test_token_file_permissions_and_panel_url_validation(self):
        token=self.root/'token';token.write_text(TOKEN);token.chmod(0o600)
        self.assertEqual(api.read_token(token),TOKEN)
        token.chmod(0o644)
        with self.assertRaises(ValueError):api.read_token(token)
        for value in ['short','x'*32+' space','é'*32]:
            with self.assertRaises(ValueError):api.make_server(self.config,value,port=0)
        for url in ['javascript:alert(1)','http://user:pass@example.invalid','http://example.invalid/#fragment']:
            with self.assertRaises(ValueError):api.AgentAPI(self.config,panel_url=url)

    def test_exact_batch_filters_before_grouping_and_legacy_is_unavailable(self):
        with closing(db.connect(self.path)) as conn:
            bid=batches.start_batch(conn,pipeline_task_id='synthetic-task')
            batches.record_member(conn,bid,'synthetic:a',True)
            batches.record_member(conn,bid,'synthetic:c',False)
            batches.finish_batch(conn,bid,'partial',error='source_failed');conn.commit()
            db.log_run(conn,'fetch','2020-01-01T00:00:00+00:00',{});legacy='legacy-'+str(conn.execute('SELECT last_insert_rowid()').fetchone()[0]);conn.commit()
        result=self.first('?scope=batch_new&batch_id='+bid)
        self.assertEqual([r['uid'] for r in result['items']],['synthetic:a'])
        self.assertEqual(result['batch']['collection_state'],'partial')
        self.assertEqual(result['batch']['pipeline']['state'],'unknown')
        self.assertTrue(result['items'][0]['batch_membership']['is_new'])
        result=self.first('?scope=batch_seen&batch_id='+bid)
        self.assertEqual({r['uid'] for r in result['items']},{'synthetic:a','synthetic:c'})
        self.assertEqual(self.request('/api/v1/jobs?scope=batch_new&batch_id='+legacy)[0],409)
        status,data,_=self.request('/api/v1/batches/'+legacy)
        self.assertEqual(status,200);self.assertEqual(data['item']['membership'],'unavailable')
        status,data,_=self.request('/api/v1/batches?limit=1')
        self.assertEqual(status,200);self.assertEqual(len(data['items']),1);self.assertEqual(data['next_offset'],1)

    def test_unfinished_batch_rejected_and_new_batch_does_not_mix_snapshot(self):
        with closing(db.connect(self.path)) as conn:
            bid=batches.start_batch(conn)
            batches.record_member(conn,bid,'synthetic:a',True);conn.commit()
        self.assertEqual(self.request('/api/v1/jobs?scope=batch_seen&batch_id='+bid)[0],409)
        with closing(db.connect(self.path)) as conn:
            batches.record_member(conn,bid,'synthetic:c',True)
            batches.finish_batch(conn,bid,'success');conn.commit()
        first=self.first('?scope=batch_new&limit=1')
        self.assertEqual(first['resolved_batch_id'],bid)
        with closing(db.connect(self.path)) as conn:
            later=batches.start_batch(conn)
            batches.record_member(conn,later,'synthetic:b',True);batches.finish_batch(conn,later,'success');conn.commit()
        page=self.first('?cursor='+quote(first['next_cursor']))
        self.assertEqual(page['resolved_batch_id'],bid)
        self.assertEqual(page['total'],2)
        self.assertEqual(self.first('?scope=batch_new')['resolved_batch_id'],later)

    def test_external_client_complete_export_and_failure_preserves_old_file(self):
        base='http://127.0.0.1:'+str(self.server.server_port)
        value=agent_client.read_jobs(base,TOKEN,{'limit':1})
        self.assertTrue(value['complete']);self.assertEqual(value['total'],2)
        self.assertTrue(all(r['description'] for r in value['items']))
        target=self.root/'export.json';agent_client.export(target,value);old=target.read_bytes()
        self.assertEqual(target.stat().st_mode&0o077,0)
        original=self.server.api.jobs
        def fail_later(qs):
            if 'cursor' in qs:raise api.APIError('synthetic_failure',503)
            return original(qs)
        with patch.object(self.server.api,'jobs',side_effect=fail_later):
            with self.assertRaises(agent_client.ClientError):agent_client.read_jobs(base,TOKEN,{'limit':1})
        self.assertEqual(target.read_bytes(),old)
        with self.assertRaises(agent_client.ClientError):agent_client.export(target,{'complete':False,'total':0,'items':[]})
        self.assertEqual(target.read_bytes(),old)
        with self.assertRaises(agent_client.ClientError):agent_client.read_jobs('http://example.invalid',TOKEN,{})
        with self.assertRaises(agent_client.ClientError):agent_client.read_jobs(base,'wrong',{})

    def test_location_qualification_recomputed_from_frozen_machine_and_human(self):
        with closing(db.connect(self.path)) as conn:
            conn.execute('BEGIN IMMEDIATE');location_store.set_label(conn,'synthetic:a',self.lid,'eligibility','ineligible');conn.commit()
        first=self.first();sid=first['snapshot_id']
        for suffix in ['', '&snapshot_id='+sid]:
            status,value,_=self.request('/api/v1/jobs/synthetic%3Aa?location_id='+self.lid+suffix)
            self.assertEqual(status,200);item=value['item']
            self.assertEqual(item['human']['eligibility'],'ineligible')
            self.assertEqual(item['qualification']['effective'],'ineligible')
            self.assertTrue(item['qualification']['corrected'])
        with closing(db.connect(self.path)) as conn:
            conn.execute('BEGIN IMMEDIATE');location_store.set_label(conn,'synthetic:a',self.lid,'eligibility',None);conn.commit()
        item=self.request('/api/v1/jobs/synthetic%3Aa?location_id='+self.lid+'&snapshot_id='+sid)[1]['item']
        self.assertEqual(item['qualification']['effective'],'ineligible')
        legacy=self.request('/api/v1/jobs/synthetic%3Aa?location_id=&snapshot_id='+sid)[1]['item']
        self.assertEqual(legacy['qualification']['effective'],'eligible');self.assertFalse(legacy['qualification']['corrected'])

    def test_first_failed_pipeline_without_generation_remains_confirmed(self):
        runtime=self.root/'.synthetic.db.panel-update';runtime.mkdir()
        for state in ('error','timeout','interrupted'):
            (runtime/'latest.json').write_text(json.dumps({'state':state,'task_id':'synthetic-task','completion_ready':True,'refresh_available':False}))
            self.assertEqual(api._pipeline(self.config,'synthetic-task')['state'],state)
        (runtime/'latest.json').write_text(json.dumps({'state':'success','task_id':'synthetic-task','completion_ready':True,'refresh_available':True}))
        self.assertEqual(api._pipeline(self.config,'synthetic-task')['state'],'unknown')


if __name__=='__main__':unittest.main(verbosity=2)
