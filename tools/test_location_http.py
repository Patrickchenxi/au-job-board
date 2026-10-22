"""Synthetic loopback HTTP checks for scoped writes and origin ownership."""
import unittest,tempfile,sys,threading,json,http.client,sqlite3
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jobs import db,labels,location_store,panel
class LocationHTTP(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.db';c=db.connect(self.path)
        db.upsert_job(c,dict(source='synthetic',source_id='a',title='Synthetic Developer',company='Synthetic Team',location='Sydney NSW / Melbourne VIC',description='Newly written synthetic text.'));db.replace_decision(c,'synthetic:a',False);c.commit()
        self.ids=[x['location_id'] for x in location_store.locations_for(c,'synthetic:a')];labels.set_label(c,'synthetic:a',action='applied',note='Synthetic legacy note');c.close()
        class Handler(panel.Handler):config={'db_path':str(self.path),'panel':{'host':'127.0.0.1'}}
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.patch=patch('jobs.skills.load_skills',return_value={'skills':[]});self.patch.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop();self.temp.cleanup()
    def request(self,method,url,data=None,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port);headers={}
        if data is not None:headers['Content-Type']='application/json'
        if origin:headers['Origin']=origin
        c.request(method,url,body=json.dumps(data) if data is not None else None,headers=headers);r=c.getresponse();out=(r.status,r.read().decode());c.close();return out
    def test_scoped_write_does_not_change_legacy_or_other_place(self):
        status,body=self.request('POST','/api/label',{'uid':'synthetic:a','location_id':self.ids[1],'field':'action','value':'saved'})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['location_id'],self.ids[1])
        c=db.connect(self.path);self.assertEqual(labels.get_labels(c)['synthetic:a']['action'],'applied');self.assertIsNone(location_store.label_for(c,'synthetic:a',self.ids[0]).get('action'));c.close()
    def test_foreign_origin_blocks_correction_and_state(self):
        for path,data in [('/api/label',{'uid':'synthetic:a','location_id':self.ids[1],'field':'priority','value':True}),('/api/location',{'uid':'synthetic:a','location_id':self.ids[1],'raw':'Melbourne VIC 3000'})]:
            self.assertEqual(self.request('POST',path,data,'http://foreign.invalid')[0],403)
    def test_explicit_empty_scope_reads_legacy(self):
        status,body=self.request('GET','/api/job?uid=synthetic%3Aa&geo=Melbourne%20VIC&location_id=')
        self.assertEqual(status,200);self.assertIn('Synthetic legacy note',body)
    def test_missing_correction_payload_does_not_clear(self):
        self.assertEqual(self.request('POST','/api/location',{'uid':'synthetic:a','location_id':self.ids[1]})[0],400)
    def test_invalid_region_is_editable_html_but_json_detail_stays_strict(self):
        status,body=self.request('GET','/?view=all&geo=not-a-real-place')
        self.assertEqual(status,200);self.assertIn('id="geo-error"',body);self.assertIn('not-a-real-place',body)
        self.assertIn('aria-invalid="true"',body)
        self.assertEqual(self.request('GET','/api/job?uid=synthetic%3Aa&geo=not-a-real-place')[0],400)
        self.assertEqual(self.request('GET','/?view=all&geo=not-a-real-place&mode=office')[0],400)
    def test_invalid_scope_rejected_and_no_partial_write(self):
        self.assertEqual(self.request('POST','/api/label',{'uid':'synthetic:a','location_id':'missing','field':'action','value':'saved'})[0],400)
        c=db.connect(self.path);self.assertEqual(c.execute('SELECT count(*) FROM location_events').fetchone()[0],0);c.close()
    def test_location_summary_is_separate(self):
        self.request('POST','/api/label',{'uid':'synthetic:a','location_id':self.ids[1],'field':'action','value':'saved'})
        legacy=json.loads(self.request('GET','/api/stats')[1]);scoped=json.loads(self.request('GET','/api/stats?scope=location')[1]);self.assertEqual(legacy['applied'],1);self.assertEqual(scoped['saved'],1);self.assertEqual(scoped['applied'],0)
if __name__=='__main__':unittest.main(verbosity=2)
