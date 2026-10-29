import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from harness.dashboard import snapshot
from harness.dashboard_fixture import write_fixture
from harness.dashboard_usage import token_parts


class UsageTrustTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);write_fixture(self.root)

    def test_cache_and_reasoning_are_subsets(self):
        self.assertEqual(token_parts({'input_tokens':100,'cached_input_tokens':90,'output_tokens':20,'reasoning_output_tokens':15,'total_tokens':120}),[10,90,20])

    def test_cumulative_unknown_or_inconsistent_usage_excluded(self):
        u={'input_tokens':100,'cached_input_tokens':90,'output_tokens':20}
        for semantics in ('thread_cumulative',None,'UNKNOWN'):
            self.assertIsNone(token_parts(u,semantics))
        for extra in ({'cached_input_tokens':101},{'reasoning_output_tokens':21},{'cache_write_input_tokens':1},{'total_tokens':210},{'output_tokens':True}):
            self.assertIsNone(token_parts({**u,**extra}))

    def test_missing_response_classification_not_task_stage(self):
        u=snapshot(self.root,'normal')['usage']
        self.assertEqual({r['stage'] for r in u['rows']},{'귀속 불명'})
        self.assertEqual(u['totals']['tokens'],2400)
        self.assertTrue(all(r['rework']=='재작업 귀속 불명' for r in u['rows']))
        self.assertTrue(all(r['scenario_cost'] is None for r in u['rows']))

    def test_identical_duplicate_deduplicated_semantic_conflict_quarantined(self):
        p=self.root/'.harness/logs/events.jsonl';e=json.loads(p.read_text().splitlines()[0])
        with p.open('a') as f:f.write(json.dumps(e)+'\n')
        self.assertEqual(snapshot(self.root,'normal')['usage']['totals']['tokens'],2400)
        e['observed']['usage_semantics']='thread_cumulative'
        with p.open('a') as f:f.write(json.dumps(e)+'\n')
        u=snapshot(self.root,'normal')['usage'];self.assertEqual(u['totals']['tokens'],1200);self.assertEqual(u['excluded'],1)

    def test_document_criteria_do_not_inherit_product_gate_and_changes_still_block(self):
        p=self.root/'.harness/tasks/tasks.yaml';state=json.loads(p.read_text());t=state['tasks']['normal-work']
        artifact={**t['inputs'][0],'snapshot':'docs/requirements.md','snapshot_sha256':t['inputs'][0]['sha256']}
        t.update(state='DONE', inputs=[artifact],reviews=[{'agent_run_id':'normal-attempt','results':[{'criterion_id':'STATE-1','result':'PASS','evidence':artifact,'tested_outputs':[artifact]}]}], validation_status={'normal-attempt':{'state':'RECHECK_REQUIRED','reasons':['legacy gate']}})
        p.write_text(json.dumps(state));p=self.root/'.harness/dashboard-scopes.json';reg=json.loads(p.read_text());m=reg['scopes'][0]['tasks']['normal-work'];m.update(assessment_scope='document_configuration',assessment_basis=t['inputs'][0]);p.write_text(json.dumps(reg))
        view=snapshot(self.root,'normal')['tasks'][0]
        self.assertEqual(view['verdict'],'RECHECK_REQUIRED');self.assertEqual(view['raw_state'],'DONE')
        self.assertEqual(view['criterion_applicability']['checks'][0]['state'],'PASS')
        (self.root/'docs/requirements.md').write_text('changed')
        # Update only the explanation reference; original reviewed inputs/outputs remain frozen.
        m['assessment_basis']['sha256']=hashlib.sha256((self.root/'docs/requirements.md').read_bytes()).hexdigest();p.write_text(json.dumps(reg))
        view=snapshot(self.root,'normal')['tasks'][0]
        self.assertEqual(view['criterion_applicability']['checks'][0]['state'],'RECHECK_REQUIRED')


if __name__=='__main__':unittest.main()
