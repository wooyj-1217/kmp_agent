import unittest
import tempfile
import json
import hashlib
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from harness.dashboard_workspace import requests, usage_slice


def message(eid, text, session='human', at='2026-10-28T10:00:00Z'):
    return {'event_id': eid, 'event_type': 'session_message', 'source': {'session_id': session},
            'observed': {'role': 'user', 'content': [{'type': 'input_text', 'text': text}], 'occurred_at': at}}


class RequestEvidence(unittest.TestCase):
    def test_same_session_and_title_do_not_merge_requests(self):
        records = requests([message('one', '저장 기능'), message('two', '저장 기능')])
        self.assertEqual({r['id'] for r in records}, {'one', 'two'})
        self.assertTrue(all(r['task_ids'] == [] for r in records))

    def test_only_explicit_source_event_connects_correction(self):
        events = [message('one', '저장 구현'), message('two', '오류 보완')]
        events.append({'event_id': 'link', 'event_type': 'human_intervention', 'task_id': 'FIX',
                       'agent_run_id': 'call', 'observed': {'source_event_id': 'two'},
                       'agent_summary': {'classification': 'CORRECTION', 'basis': '사용자 명시'}})
        r = {r['id']: r for r in requests(events)}
        self.assertEqual(r['one']['task_ids'], [])
        self.assertEqual(r['two']['task_ids'], ['FIX'])
        self.assertEqual(r['two']['links'][0]['execution_id'], 'call')
        self.assertEqual(r['two']['text'], '오류 보완')

    def test_worker_inputs_and_injected_instructions_are_not_requests(self):
        ev = [message('worker', '구현하라', 'worker'), message('agent', '# AGENTS.md instructions\n...'),
              message('environment', '<environment_context>...'), message('actual', '메모를 만들어줘')]
        self.assertEqual([r['id'] for r in requests(ev, {'worker'})], ['actual'])


class SameScopeUsage(unittest.TestCase):
    def setUp(self):
        rows = []
        for tid, amount, role in [('a', 178168, 'development'), ('b', 280738, 'verification'), (None, 55, 'unknown')]:
            rows.append({'task_id': tid, 'execution_id': tid, 'tokens': amount,
                         'role': role, 'development_owner': 'web' if role == 'development' else 'not_applicable',
                         'purpose': 'defect_fix', 'repetition': 'review_rework', 'actor': 'unknown',
                         'normal_input': amount, 'cached_input': 0, 'output': 0,
                         'collected_at': '2026-10-28T11:00:00Z', 'occurred_at': '2026-10-27T10:00:00Z'})
        self.data = {'rows': rows, 'tasks': [{'task_id': k, 'title': '같은 제목'} for k in ['a', 'b']],
                     'taxonomy': {k: {} for k in ['roles', 'development', 'purposes', 'repetitions', 'actors']}}

    def test_request_history_and_tokens_share_same_facts(self):
        selected = usage_slice(self.data, {'a', 'b'})
        self.assertEqual(selected['known_tokens'], 458906)
        self.assertEqual(sum(r['tokens'] for r in selected['roles']), selected['known_tokens'])
        self.assertEqual(sum(r['tokens'] for r in selected['purposes']), selected['known_tokens'])
        self.assertEqual([t['direct_tokens'] for t in selected['tasks']], [178168, 280738])

    def test_unlinked_and_unclassified_remain_in_total(self):
        result = usage_slice(self.data)
        self.assertEqual(result['known_tokens'], 458961)
        self.assertEqual(result['unlinked_tokens'], 55)
        self.assertEqual(result['unclassified_role_tokens'], 55)

    def test_missing_request_usage_does_not_fall_back_to_project(self):
        result = usage_slice(self.data, set())
        self.assertIsNone(result['known_tokens'])
        self.assertEqual(result['rows'], [])

    def test_period_filter_does_not_move_finish_usage_to_wrong_day(self):
        result = usage_slice(self.data, start='2026-10-28')
        self.assertIsNone(result['known_tokens'])
        self.assertEqual(usage_slice(self.data, end='2026-10-27')['known_tokens'], 458961)


class ArtifactHTTP(unittest.TestCase):
    def setUp(self):
        from harness.usage_dashboard import handler
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / '.harness/tasks').mkdir(parents=True)
        (self.root / '.kmp-agent').mkdir()
        (self.root / '.kmp-agent/project.json').write_text(json.dumps({'project_id': 'artifact-test'}))
        self.output = self.root / 'result.txt'; self.output.write_text('confirmed evidence')
        state = {'tasks': {'TASK': {'project_id': 'artifact-test', 'outputs': [{'path': 'result.txt', 'sha256': hashlib.sha256(self.output.read_bytes()).hexdigest()}]}}}
        (self.root / '.harness/tasks/tasks.yaml').write_text(json.dumps(state))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.root, self.root))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def test_output_requires_matching_evidence_and_downloads_without_html_execution(self):
        with urlopen(self.url+'/api/artifact?task=TASK&index=0') as response:
            self.assertEqual(response.read(), b'confirmed evidence')
            self.assertIn('attachment', response.headers['Content-Disposition'])
        self.output.write_text('changed')
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url+'/api/artifact?task=TASK&index=0')
        self.assertEqual(error.exception.code, 409)
        self.output.unlink()
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url+'/api/artifact?task=TASK&index=0')
        self.assertEqual(error.exception.code, 404)

    def test_host_and_unknown_artifact_are_rejected(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/api/projects', headers={'Host': 'external.example'}))
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url+'/api/artifact?task=TASK&index=5')
        self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
