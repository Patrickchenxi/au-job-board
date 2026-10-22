"""Opt-in synthetic Streamable HTTP authentication, app lifecycle and capacity."""
import asyncio
from contextlib import closing
import http.client
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
import httpx2
from jobs import agent_api, mcp_http, panel
import test_mcp as fixtures

TOKEN = fixtures.TOKEN


class HTTPMCP(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = fixtures.MCPIntegration()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = dict(self.fixture.server.api.config)
        self.config['mcp'] = {'enabled': True, 'token_file': str(self.fixture.token_file)}
        self.panel = self.bind_panel()
        self.addCleanup(self.panel.server_close)
        self.config['panel'] = {'host': '127.0.0.1', 'port': self.panel.server_port}
        self.service = None
        self.addCleanup(self.stop)

    def bind_panel(self):
        for _ in range(30):
            server = ThreadingHTTPServer(('127.0.0.1', 0), panel.Handler)
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', server.server_port+1))
                    return server
                except OSError:
                    server.server_close()
        self.fail('Could not reserve adjacent synthetic ports')

    def stop(self):
        if self.service:
            self.service.close()

    def start(self):
        self.service = mcp_http.start(self.config, self.panel)
        self.assertEqual(self.service.port, self.panel.server_port+1)
        return self.service

    def request(self, *, headers=None, method='POST', body=b'{}'):
        connection = http.client.HTTPConnection('127.0.0.1', self.panel.server_port+1, timeout=5)
        value = {'Content-Type': 'application/json', 'Authorization': 'Bearer '+TOKEN}
        value.update(headers or {})
        connection.request(method, '/mcp', body=body, headers=value)
        response = connection.getresponse(); response.read()
        result = response.status, dict(response.getheaders())
        connection.close()
        return result

    async def test_real_http_tools_snapshot_and_full_body(self):
        service = self.start()
        async with httpx2.AsyncClient(headers={'Authorization': 'Bearer '+TOKEN}) as http:
            async with Client(streamable_http_client(service.url, http_client=http), mode='legacy') as client:
                self.assertEqual({t.name for t in (await client.list_tools()).tools},
                    {'list_jobs','get_job','list_batches','get_batch'})
                first = await client.call_tool('list_jobs', {'query': {'limit': 1}})
                self.assertFalse(first.is_error)
                page = first.structured_content
                uid, sid = page['items'][0]['uid'], page['snapshot_id']
                with closing(agent_api.read_connection(self.fixture.path)) as conn:
                    with self.assertRaises(sqlite3.OperationalError):
                        conn.execute('DELETE FROM jobs')
                next_page = await client.call_tool('list_jobs', {'query': {'cursor': page['next_cursor']}})
                self.assertEqual(next_page.structured_content['snapshot_id'], sid)
                detail = await client.call_tool('get_job', {'uid': uid, 'snapshot_id': sid})
                self.assertTrue(detail.structured_content['item']['description'])
                batches = await client.call_tool('list_batches', {'limit': 1})
                bid = batches.structured_content['items'][0]['batch_id']
                batch = await client.call_tool('get_batch', {'batch_id': bid})
                self.assertEqual(batch.structured_content['item']['batch_id'], bid)
                bad = await client.call_tool('list_jobs', {'query': {'view': 'recommend', 'geo': 'VIC'}})
                self.assertTrue(bad.is_error)

    async def test_auth_host_origin_and_request_size(self):
        self.start()
        for headers, status in [({'Authorization': ''}, 401),
                                ({'Authorization': 'Bearer wrong'}, 401),
                                ({'Host': 'evil.invalid'}, 403),
                                ({'Origin': 'null'}, 403)]:
            self.assertEqual(self.request(headers=headers)[0], status)
        status, headers = self.request(headers={'Authorization': ''})
        self.assertIn('www-authenticate', {k.lower():v for k,v in headers.items()})
        self.assertNotIn('access-control-allow-origin', {k.lower():v for k,v in headers.items()})
        self.assertEqual(self.request(body=b'x'*(65536+1))[0], 413)

    async def test_tls_certificate_verified(self):
        root = self.fixture.root
        cfg = root/'openssl.cnf'
        cfg.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n'
                       '[dn]\nCN=localhost\n[ext]\nsubjectAltName=IP:127.0.0.1\n')
        cert, key = root/'cert.pem', root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-config',str(cfg),'-keyout',str(key),'-out',str(cert)], check=True, capture_output=True)
        self.config['mcp'].update(tls_certfile=str(cert), tls_keyfile=str(key))
        service = self.start()
        async with httpx2.AsyncClient(verify=ssl.create_default_context(cafile=cert),
                headers={'Authorization': 'Bearer '+TOKEN}) as http:
            async with Client(streamable_http_client(service.url, http_client=http)) as client:
                self.assertEqual(len((await client.list_tools()).tools), 4)

    async def test_conflict_and_invalid_settings_cleanup(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',self.panel.server_port+1)); occupied.listen()
            with self.assertRaises(OSError):
                mcp_http.start(self.config,self.panel)
        for value in [{'enabled':'yes'}, {'enabled':True,'token_file':'missing'},
                      {'enabled':True,'host':'0.0.0.0'},
                      {'enabled':True,'token_file':str(self.fixture.token_file),'tls_certfile':'missing'}]:
            self.config['mcp'] = value
            with self.assertRaises((ValueError,OSError)):
                mcp_http.start(self.config,self.panel)
        self.assertIsNone(mcp_http.start({}, self.panel))

    async def test_application_start_stop_owns_mcp_and_cli_listener_overrides(self):
        # Start the actual CLI/panel entry, rather than just the sidecar class.
        port = self.panel.server_port
        self.panel.server_close()
        root = self.fixture.root
        config = dict(self.config)
        config['panel'] = {'host':'localhost','port':port+10}
        path = root/'config.json';path.write_text(json.dumps(config))
        output = self.enterContext((root/'app.log').open('w+'))
        proc = subprocess.Popen([sys.executable,'-B','-m','jobs.cli','--config',str(path),
            '--rules',str(root/'rules.yaml'),'--skills',str(root/'skills.yaml'),
            'panel','--host','127.0.0.1','--port',str(port)], cwd=ROOT,
            stdout=output,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1'))
        def cleanup():
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try: proc.wait(timeout=12)
                except subprocess.TimeoutExpired: proc.kill();proc.wait(timeout=5)
        self.addCleanup(cleanup)
        # Cold CI runners import the full CLI stack slowly; bound by wall time.
        deadline = time.monotonic() + 120
        while True:
            if proc.poll() is not None:
                self.fail('Application exited: '+(root/'app.log').read_text())
            try:
                if self.request(headers={'Authorization':''})[0] == 401:
                    break
            except OSError:
                pass
            if time.monotonic() > deadline:
                self.fail('Application MCP startup timed out: '+(root/'app.log').read_text())
            await asyncio.sleep(.05)
        connection = http.client.HTTPConnection('127.0.0.1',port,timeout=10)
        connection.request('GET','/?view=all')
        response = await asyncio.to_thread(connection.getresponse)
        response.read(); self.assertEqual(response.status,200);connection.close()
        proc.send_signal(signal.SIGINT)
        self.assertEqual(await asyncio.to_thread(proc.wait, timeout=12), 0)
        for value in (port,port+1):
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(('127.0.0.1',value)), 0)

    def test_shared_snapshot_settings_and_large_synthetic_input(self):
        store = agent_api.snapshot_store({})
        self.assertEqual((store.max_snapshot_bytes,store.max_bytes,store.max_rows),
                         (128*1024*1024,512*1024*1024,50000))
        cfg={'agent_api':{'snapshots':{'max_snapshot_mib':2,'max_total_mib':3,'max_rows':100,'ttl_seconds':10}}}
        configured=agent_api.AgentAPI(self.config | cfg).store
        self.assertEqual((configured.max_snapshot_bytes,configured.max_bytes,configured.max_rows,configured.ttl),
                         (2*1024*1024,3*1024*1024,100,10))
        for value in [{'ttl_seconds':0},{'max_rows':True},{'unknown':1},
                      {'max_snapshot_mib':3,'max_total_mib':2}]:
            with self.assertRaises(ValueError):
                agent_api.snapshot_store({'agent_api':{'snapshots':value}})
        body='x'*(17*1024*1024)
        snapshot=store.create(lambda: ({'query':{'limit':1}},['synthetic:large'],
                                      {'synthetic:large':{'uid':'synthetic:large','description':body}}))
        self.assertEqual(store.get(snapshot.snapshot_id).records['synthetic:large']['description'],body)


if __name__=='__main__':
    unittest.main(verbosity=2)
