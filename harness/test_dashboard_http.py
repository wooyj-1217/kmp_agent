"""Loopback HTTP checks use a disposable synthetic root, never a user server."""
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from harness.dashboard_fixture import write_fixture


class DashboardHTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);write_fixture(cls.root)
        cls.process=subprocess.Popen(['rtk','proxy','python3','-B','-m','harness.dashboard','--root',str(cls.root),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=Path(__file__).resolve().parents[1])
        cls.url=cls.process.stdout.readline().strip()
        if not cls.url.startswith('http://127.0.0.1:'):
            cls.process.terminate();raise RuntimeError('loopback bind unavailable: '+cls.process.stderr.read())

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stdout.close();cls.process.stderr.close();cls.temp.cleanup()

    def get(self,path):
        return urlopen(self.url+path,timeout=5)

    def test_assets_and_documents(self):
        for p in ('/','/app.js','/record-details.js','/style.css','/document?path=docs/prototype.html','/document?path=docs/requirements.md'):
            with self.get(p) as response:self.assertEqual(response.status,200)

    def test_scope_and_empty_selection(self):
        with self.get('/api/snapshot') as r:self.assertEqual(json.load(r)['stages'],[])
        with self.get('/api/snapshot?scope=parallel') as r:self.assertEqual(len(json.load(r)['tasks']),2)

    def test_no_raw_or_private_access(self):
        for p in ('/.harness/logs/events.jsonl','/document?path=.harness/tasks/tasks.yaml','/document?path=../outside.md','/document?path=data/memo.db'):
            with self.assertRaises(HTTPError) as e:self.get(p)
            self.assertIn(e.exception.code,(404,422))
            e.exception.close()

    def test_no_mutation_endpoint(self):
        with self.assertRaises(HTTPError) as e:urlopen(Request(self.url+'/api/snapshot',data=b'{}',method='POST'),timeout=5)
        self.assertEqual(e.exception.code,501)
        e.exception.close()

    def test_escaped_document_reader_with_registered_links(self):
        p=self.root/'docs/requirements.md';old=p.read_bytes()
        try:
            p.write_text('# Reader\n[Prototype](prototype.html)\n<script>bad()</script>')
            with self.get('/document?path=docs/requirements.md') as response:
                body=response.read().decode();self.assertIn('/document?path=docs/prototype.html',body);self.assertIn('&lt;script&gt;',body);self.assertNotIn('<script>',body)
        finally:p.write_bytes(old)

    def test_evidence_summary_excludes_private_bodies(self):
        path=self.root/'.harness/tasks/tasks.yaml';old=path.read_bytes()
        try:
            state=json.loads(old);task=state['tasks']['normal-work'];report=self.root/'.harness/evidence.txt';report.write_text(json.dumps({'result':'PASS','scope':'known test','response_body':'PRIVATE_MEMO_BODY','environment':{'TOKEN':'secret'}}));h=hashlib.sha256(report.read_bytes()).hexdigest()
            task['reviews']=[{'agent_run_id':'normal-attempt','results':[{'criterion_id':'STATE-1','result':'PASS','evidence':{'snapshot':'.harness/evidence.txt','snapshot_sha256':h}}]}];path.write_text(json.dumps(state))
            with self.get('/evidence?task=normal-work&review=normal-attempt&criterion=STATE-1') as response:
                body=response.read().decode();self.assertIn('known test',body);self.assertNotIn('PRIVATE_MEMO_BODY',body);self.assertNotIn('secret',body)
            with self.assertRaises(HTTPError) as e:self.get('/evidence?task=unrelated&review=x&criterion=x')
            self.assertEqual(e.exception.code,422);e.exception.close()
        finally:path.write_bytes(old)

    def test_interactive_preview_requires_exact_opt_in_hash(self):
        p=self.root/'.harness/dashboard-scopes.json';old=p.read_bytes();registry=json.loads(old)
        artifact=registry['scopes'][0]['artifacts'][1];artifact['interactive_preview']=True
        try:
            p.write_text(json.dumps(registry))
            with self.get('/document?path=docs/prototype.html') as response:
                csp=response.headers['Content-Security-Policy'];self.assertIn('sandbox allow-scripts;',csp);self.assertNotIn('allow-same-origin',csp);self.assertIn("default-src 'none'",csp)
            artifact['sha256']='stale';p.write_text(json.dumps(registry))
            with self.get('/document?path=docs/prototype.html') as response:
                self.assertNotIn('allow-scripts',response.headers['Content-Security-Policy'])
        finally:p.write_bytes(old)

    def test_legacy_observation_list_does_not_drop_connection(self):
        path=self.root/'.harness/tasks/tasks.yaml';old=path.read_bytes()
        try:
            state=json.loads(old);task=state['tasks']['normal-work'];report=self.root/'.harness/legacy.txt';report.write_text(json.dumps({'observations':['legacy note',{'tests':3,'failures':0,'instrumentation':{'tests':4,'reports':{'docs/requirements.md':hashlib.sha256((self.root/'docs/requirements.md').read_bytes()).hexdigest()}}}],'report_hashes':[]}));h=hashlib.sha256(report.read_bytes()).hexdigest()
            task['reviews']=[{'agent_run_id':'normal-attempt','results':[{'criterion_id':'STATE-1','result':'PASS','evidence':{'snapshot':'.harness/legacy.txt','snapshot_sha256':h}}]}];path.write_text(json.dumps(state))
            with self.get('/evidence?task=normal-work&review=normal-attempt&criterion=STATE-1') as response:
                body=response.read().decode();self.assertIn('&quot;tests&quot;: 3',body);self.assertIn('&quot;tests&quot;: 4',body);self.assertIn('현재 원본 해시 일치',body);self.assertEqual(response.status,200)
        finally:path.write_bytes(old)

    def test_documents_sandboxed_and_rebinding_blocked(self):
        with self.get('/document?path=docs/prototype.html') as r:self.assertIn('sandbox;',r.headers['Content-Security-Policy'])
        with self.assertRaises(HTTPError) as e:urlopen(Request(self.url,headers={'Host':'untrusted.example'}),timeout=5)
        self.assertEqual(e.exception.code,403)
        e.exception.close()

if __name__=='__main__':unittest.main()
