import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from harness.dashboard import snapshot, safe_file, usage_view
from harness.dashboard_fixture import write_fixture


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);write_fixture(self.root)

    def test_no_selection_no_funnel(self):
        d=snapshot(self.root);self.assertEqual(d['stages'],[]);self.assertEqual(d['tasks'],[]);self.assertEqual(len(d['history']),7)

    def test_scope_isolation(self):
        d=snapshot(self.root,'normal');self.assertEqual(len(d['tasks']),1);self.assertNotIn('연결 시험',str(d['tasks']));self.assertEqual(sum(r['tokens'] for r in d['usage']['rows']),2400)

    def test_parallel_and_missing_completion(self):
        d=snapshot(self.root,'parallel');self.assertEqual(sum(s['active'] for s in d['stages']),0);self.assertTrue(all(t['activity']['kind']=='unknown' for t in d['tasks']));self.assertIn('완료 여부 확인 불가',[s['status'] for s in d['stages']])

    def test_recheck_not_done(self):
        d=snapshot(self.root,'recheck');self.assertNotEqual(d['tasks'][0]['verdict'],'PASS');self.assertIn('재검증',d['tasks'][0]['status'])

    def test_decision_and_blocked(self):
        self.assertTrue(snapshot(self.root,'decision')['scope']['decisions'][0]['requires_human']);self.assertEqual(snapshot(self.root,'blocked')['scope']['outcome']['status'],'BLOCKED')

    def test_unknown_usage_is_not_zero_and_no_cache_double_count(self):
        d=snapshot(self.root,'normal');r=d['usage']['rows'][0];self.assertEqual((r['normal_input'],r['cached_input'],r['output'],r['tokens']),(600,400,200,1200));self.assertIsNone(r['cost'])

    def test_conflicting_duplicate_excluded(self):
        path=self.root/'.harness/logs/events.jsonl';events=[json.loads(l) for l in path.read_text().splitlines()];duplicate=copy.deepcopy(events[0]);duplicate['observed']['usage']['output_tokens']=300
        with path.open('a') as f:f.write(json.dumps(duplicate)+'\n')
        d=snapshot(self.root,'normal');self.assertEqual(d['usage']['excluded'],1);self.assertEqual(len(d['usage']['rows']),1)

    def test_read_only_bytes(self):
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        for case in (None,'normal','parallel','recheck','decision','blocked'):snapshot(self.root,case)
        after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()};self.assertEqual(before,after)

    def test_private_files_and_traversal(self):
        for name in ('../secret.txt','.harness/logs/events.jsonl','data/memo.db','docs/../../secret.md'):
            with self.assertRaises(ValueError):safe_file(self.root,name)
        (self.root/'docs/link.md').symlink_to(self.root/'.harness/tasks/tasks.yaml')
        with self.assertRaises(ValueError):safe_file(self.root,'docs/link.md')

    def test_mixed_membership_rejected(self):
        p=self.root/'.harness/dashboard-scopes.json';r=json.loads(p.read_text());r['scopes'][0]['tasks']['unrelated']={};p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):snapshot(self.root,'normal')

    def test_foreign_attempt_rejected(self):
        p=self.root/'.harness/dashboard-scopes.json';r=json.loads(p.read_text());r['scopes'][0]['agent_run_ids'].append('blocked-attempt');p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):snapshot(self.root,'normal')

    def test_changed_approved_input_is_recheck(self):
        (self.root/'docs/requirements.md').write_text('changed')
        t=snapshot(self.root,'normal')['tasks'][0]
        self.assertEqual(t['verdict'],'NOT_RUN')
        self.assertEqual(t['input_alignment'],'MISMATCH')

    def test_canonical_response_binding_without_event_task(self):
        p=self.root/'.harness/tasks/tasks.yaml';state=json.loads(p.read_text());state['tasks']['normal-work']['executions'][0]['usage_bindings']=[{'session_id':'fixture','response_id':'normal0'}];p.write_text(json.dumps(state))
        p=self.root/'.harness/logs/events.jsonl';events=[json.loads(l) for l in p.read_text().splitlines()];events[0]['agent_run_id']='UNKNOWN';events[0]['task_id']='UNKNOWN';p.write_text(''.join(json.dumps(e)+'\n' for e in events))
        d=snapshot(self.root,'normal');self.assertEqual(len(d['usage']['rows']),2);self.assertEqual(d['usage']['rows'][0]['task'],'저장 상태 화면 구현')

    def test_reported_success_not_overall_success(self):
        p=self.root/'.harness/dashboard-scopes.json';r=json.loads(p.read_text());r['scopes'][0]['outcome']={'status':'PASS'};p.write_text(json.dumps(r))
        self.assertEqual(snapshot(self.root,'normal')['overall'],'전체 완료 여부 확인 불가')

    def test_native_recorded_time_and_null_harness(self):
        p=self.root/'.harness/logs/events.jsonl';events=[json.loads(l) for l in p.read_text().splitlines()]
        for e in events:
            e['recorded_at']=e.pop('timestamp');e['harness']=None
        events[0]['observed']['occurred_at']='2026-10-26T22:15:00Z'
        p.write_text(''.join(json.dumps(e)+'\n' for e in events));d=snapshot(self.root,'normal')
        self.assertEqual(d['usage']['rows'][0]['hour'],'2026-10-26T22');self.assertEqual(d['versions'],[])
        self.assertEqual(d['last_activity'],'2026-10-27T01:00:00Z')

    def test_known_noncompliance_is_not_unknown_or_pass(self):
        p=self.root/'.harness/dashboard-scopes.json';r=json.loads(p.read_text());scope=r['scopes'][0];scope['tasks']['normal-work']['compliance_result']='NON_COMPLIANT';scope['tasks']['normal-work']['compliance_basis']=scope['approved_baselines'][0];p.write_text(json.dumps(r))
        self.assertEqual(snapshot(self.root,'normal')['tasks'][0]['compliance'],'NON_COMPLIANT')

    def test_direct_execution_label_joins_missing_task_id(self):
        p=self.root/'.harness/logs/events.jsonl';es=[json.loads(l) for l in p.read_text().splitlines()];es[0]['task_id']='UNKNOWN';p.write_text(''.join(json.dumps(e)+'\n' for e in es))
        row=snapshot(self.root,'normal')['usage']['rows'][0]
        self.assertEqual(row['task_id'],'normal-work');self.assertEqual(row['role'],'개발 담당')

    def test_direct_execution_and_task_conflict_is_not_guessed(self):
        p=self.root/'.harness/logs/events.jsonl';es=[json.loads(l) for l in p.read_text().splitlines()];es[0]['task_id']='unrelated';p.write_text(''.join(json.dumps(e)+'\n' for e in es))
        u=snapshot(self.root,'normal')['usage'];self.assertEqual(u['excluded'],1);self.assertEqual(u['totals']['tokens'],1200);self.assertTrue(u['conflicts'])

if __name__=='__main__':unittest.main()
