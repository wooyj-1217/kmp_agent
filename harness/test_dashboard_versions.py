import json
import tempfile
import unittest
from pathlib import Path
from harness.dashboard import snapshot
from harness.dashboard_fixture import write_fixture
from harness.dashboard_versions import version_identity, select


class VersionTests(unittest.TestCase):
    def test_commit_and_dirty_fingerprint_are_distinct(self):
        run={'agent_run_id':'a'}
        def key(identity):
            return version_identity({},run,[{'agent_run_id':'a','event_type':'agent_run_started','harness':identity}])[0]
        clean={'version':'0.3.0','commit':'abc','dirty':False}
        self.assertNotEqual(key(clean),key(dict(clean,commit='def')))
        self.assertNotEqual(key(dict(clean,dirty=True,source_sha256='one')),key(dict(clean,dirty=True,source_sha256='two')))
        self.assertEqual(key(dict(clean,dirty=True)),'UNKNOWN')

    def test_collector_never_supplies_execution_identity(self):
        self.assertEqual(version_identity({}, {'agent_run_id':'a'}, [{'agent_run_id':'a','event_type':'model_usage','harness':{'version':'0.3.0','commit':'abc','dirty':False}}]),('UNKNOWN',None))

    def test_conflicting_starts_unknown(self):
        events=[{'agent_run_id':'a','event_type':'agent_run_started','harness':{'version':'0.3.0','commit':c,'dirty':False}} for c in ['one','two']]
        self.assertEqual(version_identity({}, {'agent_run_id':'a'}, events),('UNKNOWN',None))

    def test_scope_period_version_intersection_and_partial_task(self):
        tasks={'t':{'task_id':'t','state':'DONE','executions':[{'agent_run_id':'a','started_at':'2026-10-27T00:00:00Z','ended_at':'2026-10-27T01:00:00Z'},{'agent_run_id':'b','started_at':'2026-10-28T00:00:00Z'}]}}
        events=[{'agent_run_id':a,'event_type':'agent_run_started','timestamp':'2026-10-27T00:00:00Z','harness':{'version':'0.3.0','commit':a,'dirty':False}} for a in ['a','b']]
        key=version_identity(tasks['t'],tasks['t']['executions'][0],events)[0]
        selected,kept,scope,_,_,_=select(tasks,events,{'tasks':{'t':{}},'agent_run_ids':['a','b']},key,end='2026-10-28T00:00:00Z')
        self.assertEqual(scope['agent_run_ids'],['a']);self.assertTrue(selected['t']['_filter_partial']);self.assertNotEqual(selected['t']['state'],'DONE')
        self.assertEqual({e['agent_run_id'] for e in kept},{'a'})
        self.assertEqual(tasks['t']['state'],'DONE')

    def test_snapshot_unknown_and_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_fixture(root)
            original=snapshot(root,'normal')
            self.assertEqual(original['harness_identities'],[])
            self.assertIn('UNKNOWN',{o['key'] for o in original['agent_versions']})
            filtered=snapshot(root,'normal',None,None,'UNKNOWN')
            self.assertTrue(filtered['filtered_subset']);self.assertFalse(filtered['readiness'])
            self.assertEqual(filtered['usage']['universe']['responses'],filtered['usage']['scope_info']['responses'])
            self.assertEqual({r['agent_run_id'] for r in filtered['usage']['rows']},set(r['id'] for t in filtered['tasks'] for r in t['runs']))
            with self.assertRaisesRegex(ValueError,'unknown agent_version'):snapshot(root,'normal',agent_version='missing')
            with self.assertRaisesRegex(ValueError,'unknown project'):snapshot(root,project_id='missing')

    def test_ui_selection_survives_refresh(self):
        js=(Path(__file__).parent/'dashboard_assets/app.js').read_text()
        self.assertIn("q.set('agent_version',agentVersion)",js)
        self.assertIn("['agent_version',agentVersion]",js)
        self.assertIn("get('agent_version')",js)
        self.assertIn("pageshow",js)

    def test_project_unknown_excludes_unbound_and_preserves_gate(self):
        tasks={'t':{'task_id':'t','state':'IN_PROGRESS','execution_gate':{'status':'WAITING','questions':['q']},'executions':[{'agent_run_id':'a','started_at':'2026-10-27T00:00:00Z'}]}}
        events=[{'event_type':'model_usage','agent_run_id':'foreign','project_id':'other'}]
        selected,kept,_,_,_,_=select(tasks,events,None,'UNKNOWN',project_selected=True)
        self.assertEqual(kept,[])
        self.assertEqual(selected['t']['execution_gate'],tasks['t']['execution_gate'])

    def test_dictionary_fingerprints_have_distinct_labels(self):
        tasks={'t':{'task_id':'t','executions':[{'agent_run_id':a} for a in ['a','b']]}}
        events=[{'event_type':'agent_run_started','agent_run_id':a,'harness':{'version':'0.3.0','commit':'same','dirty':False,'source_sha256':{'VERSION':'same','file':a}}} for a in ['a','b']]
        options=select(tasks,events,None)[3]
        self.assertEqual(len({o['label'] for o in options}),2)

    def test_filter_preserves_foreign_binding_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_fixture(root)
            p=root/'.harness/tasks/tasks.yaml';state=json.loads(p.read_text())
            for tid in ['normal-work','parallel-work']:
                state['tasks'][tid]['executions'][0]['usage_bindings']=[{'session_id':'fixture','response_id':'normal0'}]
            p.write_text(json.dumps(state))
            before=snapshot(root,'normal');after=snapshot(root,'normal',agent_version='UNKNOWN')
            self.assertEqual(before['usage']['totals']['tokens'],after['usage']['totals']['tokens'])
            self.assertEqual(len(after['usage']['conflicts']),1)
            self.assertEqual(after['usage']['universe']['responses'],1)
            p=root/'.harness/logs/events.jsonl';events=[json.loads(l) for l in p.read_text().splitlines()]
            events[0]['agent_run_id']='UNKNOWN';events[0]['task_id']='UNKNOWN'
            p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            imported=snapshot(root,'normal',agent_version='UNKNOWN')
            self.assertEqual(len(imported['usage']['conflicts']),1)
            self.assertEqual(imported['usage']['totals']['tokens'],after['usage']['totals']['tokens'])

    def test_filter_scopes_questions_without_changing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_fixture(root)
            p=root/'.harness/dashboard-scopes.json';before=p.read_bytes()
            d=snapshot(root,'normal',agent_version='UNKNOWN')
            self.assertEqual(d['project_progress']['decisions'],[])
            self.assertEqual(d['agent_flow']['decisions'],[])
            self.assertEqual(p.read_bytes(),before)

    def test_outside_usage_collision_remains_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_fixture(root)
            p=root/'.harness/logs/events.jsonl';events=[json.loads(l) for l in p.read_text().splitlines()]
            duplicate=dict(events[0]);duplicate['agent_run_id']='foreign';duplicate['observed']=dict(duplicate['observed'])
            duplicate['observed']['usage']=dict(duplicate['observed']['usage'],output_tokens=999)
            events.append(duplicate);p.write_text(''.join(json.dumps(e)+'\n' for e in events))
            d=snapshot(root,'normal',agent_version='UNKNOWN')
            self.assertEqual(len(d['usage']['rows']),1)
            self.assertEqual(len(d['usage']['conflicts']),1)
