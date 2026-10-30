"""Real native filesystem and HTTP lifecycle tests (no simulated watcher)."""
import http.client
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from harness.dashboard import create_server
from harness.dashboard_events import NativeEvents


class DashboardEventsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / '.harness/tasks').mkdir(parents=True)
        self.task = self.root / '.harness/tasks/tasks.yaml'
        self.task.write_text('{"tasks": {}}')
        self.events = NativeEvents(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.events.close)
        self.assertEqual(self.events.status, 'native')

    def changed(self, old):
        deadline = time.monotonic() + 3
        while self.events.revision == old and time.monotonic() < deadline:
            self.events.wait(old, .1)
        self.assertNotEqual(self.events.revision, old)
        return self.events.revision

    def test_write_atomic_rename_and_new_directory(self):
        old = self.events.revision
        self.task.write_text('{"tasks": {}, "changed": true}')
        old = self.changed(old)
        replacement = self.task.with_name('replacement.tmp')
        replacement.write_text('{"tasks": {}, "atomic": true}')
        replacement.replace(self.task)
        old = self.changed(old)
        docs = self.root / 'docs/new'
        docs.mkdir(parents=True)
        (docs / 'spec.md').write_text('new document')
        old = self.changed(old)
        (docs / 'spec.md').write_text('updated document')
        self.changed(old)

    def test_idle_and_reader_artifacts_do_not_invalidate_or_scan_periodically(self):
        old = self.events.revision
        with patch.object(self.events, '_scan', wraps=self.events._scan) as scan:
            time.sleep(.35)
            self.assertEqual(scan.call_count, 0)
            self.task.touch()
            self.task.with_suffix('.lock').write_text('lock')
            cursor = self.root / '.harness/usage/cursors'
            cursor.mkdir(parents=True)
            (cursor / 'reader.json').write_text('{}')
            (self.root / 'build').mkdir()
            (self.root / 'build/generated').write_text('ignored')
            time.sleep(.5)
            self.assertEqual(self.events.revision, old)
            count = scan.call_count
            time.sleep(.35)
            self.assertEqual(scan.call_count, count)

    def test_registered_external_document_and_immutable_build_exclusion(self):
        spec = self.root / 'specifications/decision.md'
        spec.parent.mkdir()
        spec.write_text('registered')
        state = {'tasks': {'T': {'inputs': [{'path': 'specifications/decision.md'}]}}}
        old = self.events.revision
        self.task.write_text(json.dumps(state))
        old = self.changed(old)
        spec.write_text('revised')
        old = self.changed(old)
        for name in ('.harness/ios-derived/Build', '.kmp-agent/releases/v1'):
            directory = self.root / name
            directory.mkdir(parents=True)
            (directory / 'large.bin').write_bytes(b'ignored')
        time.sleep(.4)
        self.assertEqual(self.events.revision, old)
        self.assertFalse(any('ios-derived' in str(path) or 'releases' in path.parts
                             for path in self.events._handles))

    def test_burst_is_coalesced_and_same_content_atomic_replace_is_silent(self):
        old = self.events.revision
        number = self.events._number
        for value in range(20):
            self.task.write_text(json.dumps({'tasks': {}, 'sequence': value}))
        self.changed(old)
        time.sleep(.3)
        self.assertEqual(self.events._number, number + 1)
        old = self.events.revision
        replacement = self.task.with_name('replacement.tmp')
        replacement.write_bytes(self.task.read_bytes())
        replacement.replace(self.task)
        time.sleep(.4)
        self.assertEqual(self.events.revision, old)

    def test_shutdown_stops_native_thread(self):
        thread = self.events._thread
        self.events.close()
        self.assertFalse(thread.is_alive())

    def server(self):
        server = create_server(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(stop)
        return server

    def connect(self, server, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        client.request('GET', '/api/events', headers=headers or {})
        response = client.getresponse()
        self.addCleanup(client.close)
        return client, response

    def event(self, response):
        result = {}
        while True:
            line = response.readline().decode().strip()
            if not line:
                return result
            if ': ' in line:
                key, value = line.split(': ', 1)
                result[key] = value

    def test_sse_revision_reconnect_and_disconnect_without_snapshot(self):
        with patch('harness.dashboard.snapshot', return_value={'test': True}) as snapshot:
            server = self.server()
            initial = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            initial.request('GET', '/api/snapshot')
            self.assertEqual(initial.getresponse().read(), b'{"test": true}')
            initial.close()
            baseline = threading.active_count()
            client, response = self.connect(server)
            self.assertEqual(response.status, 200)
            first = self.event(response)
            self.assertEqual(first['event'], 'connected')
            self.assertEqual(json.loads(first['data'])['status'], 'native')
            self.task.write_text('{"tasks": {}, "sse": true}')
            changed = self.event(response)
            self.assertEqual(changed['event'], 'changed')
            self.assertNotEqual(changed['id'], first['id'])
            response.close()
            client.close()
            deadline = time.monotonic() + 3
            while threading.active_count() > baseline and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertLessEqual(threading.active_count(), baseline)
            _, second = self.connect(server)
            self.assertEqual(self.event(second)['id'], changed['id'])
            second.fp.raw._sock.settimeout(12)
            self.assertEqual(second.readline(), b': keepalive\n')
            self.assertEqual(second.readline(), b'\n')
            self.assertEqual(snapshot.call_count, 1)
            second.close()

    def test_sse_host_and_origin_guards(self):
        server = self.server()
        for headers in ({'Host': 'evil.example'}, {'Origin': 'http://evil.example'}):
            _, response = self.connect(server, headers)
            self.assertEqual(response.status, 403)
            response.read()


class DashboardLifecycleTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is needed for the real app lifecycle test')
    def test_bfcache_reconnects_once_and_preserves_network_error_semantics(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync('harness/dashboard_assets/app.js','utf8');
const lifecycle=app.slice(app.indexOf('// EventSource lifecycle:'),app.indexOf('// End EventSource lifecycle.'));
const listeners={},sources=[],error={textContent:''};let refreshes=0;
class Source{
 constructor(url){assert.equal(url,'/api/events');this.listeners={};this.readyState=0;sources.push(this);}
 addEventListener(kind,handler){assert(!this.listeners[kind]);this.listeners[kind]=handler;}
 close(){this.closed=true;this.readyState=2;}
 emit(kind,revision='r1'){if(kind==='connected')this.readyState=1;this.listeners[kind]({data:JSON.stringify({revision})});}
}
const context={window:{EventSource:Source,addEventListener:(kind,handler)=>{assert(!listeners[kind]);listeners[kind]=handler;}},EventSource:Source,
 $:()=>error,refresh:()=>refreshes++,clearTimeout:()=>{},activityExpiry:null,date:x=>x,lastSuccessAt:'known'};
vm.runInNewContext(lifecycle,context);
assert.equal(sources.length,1);
listeners.pageshow({persisted:false});assert.equal(sources.length,1);
sources[0].emit('connected');assert.equal(refreshes,1);
sources[0].onerror();assert.equal(refreshes,1);assert(error.textContent.includes('재연결'));
sources[0].emit('connected');assert.equal(refreshes,2);
sources[0].emit('changed','r2');assert.equal(refreshes,3);
sources[0].emit('changed','r2');assert.equal(refreshes,3);
for(let cycle=0;cycle<3;cycle++){
 const previous=sources.at(-1),before=refreshes;
 listeners.pagehide({persisted:true});assert(previous.closed);
 listeners.pagehide({persisted:true});
 previous.emit('changed','stale');assert.equal(refreshes,before);
 listeners.pageshow({persisted:true});
 listeners.pageshow({persisted:true});assert.equal(sources.length,cycle+2);
 sources.at(-1).emit('connected','restored'+cycle);assert.equal(refreshes,before+1);
}
sources.at(-1).emit('manual');assert(sources.at(-1).closed);assert(error.textContent.includes('새로고침 버튼'));
"""
        result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
