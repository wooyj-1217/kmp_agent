"""Regression cases from the real dashboard audit. No models are invoked."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
import shutil
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

from harness.usage_projection import project
from harness.dashboard_workspace import workspace
from harness.usage_dashboard import handler


class TargetBoundary(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required only for the browser renderer regression')
    def test_task_only_request_link_rendering(self):
        directory = Path(__file__).parent
        subprocess.run(['node', str(directory/'request_link_render_check.js'),
                        str(directory/'dashboard_assets/workspace.js')], check=True, capture_output=True, text=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.make(self.root, 'product', [('PRODUCT', 'product', 100, 'PRODUCT'),
                                        ('TRIAL', 'trial', 200, 'HARNESS_IMPROVEMENT')])

    def make(self, root, identity, specs):
        (root / '.kmp-agent').mkdir(parents=True)
        (root / '.harness/tasks').mkdir(parents=True)
        (root / '.harness/logs').mkdir(parents=True)
        (root / '.kmp-agent/project.json').write_text(json.dumps({'project_id': identity}))
        tasks = {}; events = []
        for tid, target, n, kind in specs:
            aid = tid+'-execution'; response = tid+'-response'
            tasks[tid] = {'task_id': tid, 'project_id': target, 'feature_id': 'same-feature',
                          'role': 'development', 'title': '같은 제목', 'scope': 'SYNTHETIC '+target,
                          'work_type': kind, 'state': 'TODO', 'criteria': [], 'inputs': [],
                          'outputs': [], 'reviews': [], 'dependencies': [], 'executions': [
                              {'agent_run_id': aid, 'run_id': 'fixture', 'role': 'development',
                               'kind': 'work', 'execution_mode': 'current_agent',
                               'started_at': '2026-10-28T00:00:00Z', 'ended_at': '2026-10-28T00:01:00Z',
                               'usage_bindings': [{'session_id': identity, 'response_id': response}]}]}
            events.append({'event_type': 'model_usage', 'event_id': tid+'-usage', 'project_id': identity,
                           'task_id': tid, 'agent_run_id': aid, 'run_id': 'fixture',
                           'recorded_at': '2026-10-28T00:00:01Z', 'source': {'session_id': identity},
                           'observed': {'response_id': response, 'usage': {'input_tokens': n, 'output_tokens': 0,
                                        'cached_input_tokens': 0, 'total_tokens': n},
                                        'usage_semantics': 'per_response_increment', 'model': 'SYNTHETIC'}})
            message = {'event_type': 'session_message', 'event_id': tid+'-request',
                       'source': {'session_id': identity+'-human'}, 'recorded_at': '2026-10-28T00:00:00Z',
                       'observed': {'role': 'user', 'content': [{'type': 'input_text', 'text': '같은 제목'}]}}
            events += [message, {'event_type': 'human_intervention', 'event_id': tid+'-link',
                                'task_id': tid, 'observed': {'source_event_id': message['event_id']},
                                'agent_summary': {'classification': 'CORRECTION', 'basis': 'synthetic exact link'}}]
            output = root / (tid+'.txt'); output.write_text(target)
            tasks[tid]['outputs'] = [{'path': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}]
        unknown = copy.deepcopy(events[0]); unknown.update(event_id='unknown-usage', task_id='UNKNOWN', agent_run_id='UNKNOWN')
        unknown['observed'].update(response_id='unknown-response', usage={'input_tokens': 7, 'cached_input_tokens': 0, 'output_tokens': 0, 'total_tokens': 7})
        events += [unknown, copy.deepcopy(events[0]), {'event_type': 'usage_snapshot', 'event_id': 'snapshot', 'observed': {'usage': {'total_tokens': 999999}}}]
        (root / '.harness/tasks/tasks.yaml').write_text(json.dumps({'tasks': tasks, 'issues': []}))
        (root / '.harness/logs/events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))

    def test_mixed_targets_conserve_total_without_cwd_attribution(self):
        before = (self.root / '.harness/logs/events.jsonl').read_bytes()
        raw = project(self.root); product = project(self.root, project_id='product'); trial = project(self.root, project_id='trial')
        self.assertEqual(raw['known_tokens'], 307)
        self.assertEqual(product['known_tokens'], 100); self.assertEqual(trial['known_tokens'], 200)
        b = product['target_scope']
        self.assertEqual([b[k]['tokens'] for k in ['selected_target', 'other_targets', 'unknown_target']], [100, 200, 7])
        self.assertEqual(b['repository_known_tokens'], sum(b[k]['tokens'] for k in ['selected_target', 'other_targets', 'unknown_target']))
        self.assertEqual(b['product_work_tokens'], 100); self.assertEqual(trial['target_scope']['product_work_tokens'], 0)
        unknown = next(r for r in raw['rows'] if r['task_id'] is None)
        self.assertEqual(unknown['project_id'], 'product')  # collector context is preserved
        self.assertEqual(unknown['target_project_id'], 'UNKNOWN')  # never promoted to product work
        self.assertEqual(product['snapshots_not_added'], 1); self.assertEqual(product['deduplicated_events'], 1)
        self.assertEqual(before, (self.root / '.harness/logs/events.jsonl').read_bytes())

    def test_unknown_target_and_cross_target_task_execution_are_rejected(self):
        for kwargs in [{'project_id': 'missing'}, {'project_id': 'UNKNOWN'},
                       {'project_id': 'product', 'task_id': 'TRIAL'},
                       {'project_id': 'product', 'execution_id': 'TRIAL-execution'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): project(self.root, **kwargs)

    def test_workspace_requests_and_artifacts_are_target_scoped(self):
        w = workspace(self.root, project_id='product')
        self.assertEqual([t['task_id'] for t in w['tasks']], ['PRODUCT'])
        self.assertEqual([r['id'] for r in w['requests']], ['PRODUCT-request'])
        self.assertEqual(w['tasks'][0]['request_ids'], ['PRODUCT-request'])
        self.assertEqual(w['requests'][0]['tokens'], 100)

    def http(self, catalog):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.root, self.root, catalog))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(thread.join); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:'+str(server.server_port)

    def test_old_and_workspace_api_share_exact_target_and_reject_bad_selection(self):
        url = self.http({'demo': {'name': 'demo', 'root': str(self.root)}})
        for target, expected in [('product', 100), ('trial', 200)]:
            for route in ['/api/usage', '/api/workspace-usage']:
                with urlopen(url+route+'?'+urlencode({'project': 'demo', 'project_id': target, 'mode': 'tasks'})) as response:
                    d = json.load(response)
                self.assertEqual(d['known_tokens'], expected)
                self.assertEqual(d['target_scope']['repository_known_tokens'], 307)
        for route in ['/api/usage', '/api/workspace', '/api/workspace-usage', '/api/task-record', '/api/artifact']:
            for q in ['project=missing', 'project=', 'project=demo&project_id=missing', 'project=demo&project_id=']:
                with self.subTest(route=route, q=q), self.assertRaises(HTTPError) as e:
                    urlopen(url+route+'?'+q)
                self.assertEqual(e.exception.code, 400)
        # Legacy no-project callers still use the configured primary root target.
        with urlopen(url+'/api/usage?mode=tasks') as response: self.assertEqual(json.load(response)['known_tokens'], 100)
        for route, q in [('/api/usage', 'mode=tasks&task=TRIAL'), ('/api/task-record', 'task=TRIAL'),
                         ('/api/workspace-usage', 'execution=TRIAL-execution'),
                         ('/api/artifact', 'task=TRIAL&index=0'), ('/api/usage-response', 'session=product&response=TRIAL-response')]:
            with self.assertRaises(HTTPError): urlopen(url+route+'?project=demo&'+q)

    def test_separate_roots_same_title_role_task_id_and_outputs(self):
        other = self.root/'other'; self.make(other, 'other', [('PRODUCT', 'other', 400, 'HARNESS_IMPROVEMENT')])
        url = self.http({'demo': {'name': 'demo', 'root': str(self.root)}, 'trial': {'name': 'trial', 'root': str(other)}})
        for key, expected, output in [('demo', 100, 'product'), ('trial', 400, 'other')]:
            for route in ['/api/usage', '/api/workspace-usage']:
                with urlopen(url+route+'?'+urlencode({'project': key, 'mode': 'tasks', 'task': 'PRODUCT'})) as response:
                    self.assertEqual(json.load(response)['known_tokens'], expected)
            with urlopen(url+'/api/artifact?'+urlencode({'project': key, 'task': 'PRODUCT', 'index': 0})) as response:
                self.assertEqual(response.read().decode(), output)

    def test_unconfirmed_root_target_never_silently_defaults(self):
        (self.root/'.kmp-agent/project.json').unlink()
        url = self.http({'demo': {'name': 'demo', 'root': str(self.root)}})
        with self.assertRaises(HTTPError): urlopen(url+'/api/usage?mode=tasks')
        with urlopen(url+'/api/usage?mode=tasks&project_id=product') as response:
            self.assertEqual(json.load(response)['known_tokens'], 100)
        (self.root/'.kmp-agent/project.json').write_text('[]')
        with self.assertRaises(HTTPError) as error: urlopen(url+'/api/usage?mode=tasks')
        self.assertEqual(error.exception.code, 400)
