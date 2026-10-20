import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.roles import Roles, CODE


class Connections(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'input.md').write_text('synthetic test input')
        self.roles = Roles(self.root, 'synthetic-connection-test')
        self.t = self.roles.tasks

    def register(self, tid, role, deps=None, p=None, d=None):
        self.t.register('F', tid, role, 'synthetic', 'synthetic fixture only', [{'id':'C','required':True,'text':'semantic review fixture'}], ['input.md'], dependencies=deps, max_attempts=2, visual_required=role=='design')
        self.roles.setup(tid, 'feature', p, design_version=d)

    def execute(self, tid, role):
        return self.roles.execute(tid, role, [sys.executable, str(CODE/'harness/role_example_worker.py')])

    def report(self, tid, kind='structure', targets=None, issues=None):
        task=self.t.read()['tasks'][tid]
        (self.root/'fake.png').write_bytes(b'\x89PNGsynthetic-unit-fixture-NOT-browser')
        payload={'kind':kind,'result':'PASS','tested_outputs':{r['path']:r['sha256'] for r in task['outputs']},
                 'observations':'synthetic unit observation, not real rendering', 'screenshots':['fake.png'], 'resolved_issues':issues or []}
        if targets:
            payload['target_results']={k:{'result':'PASS','coverage':['synthetic target case'],'screenshots':['fake.png']} for k in targets}
        path=kind+'.json'; (self.root/path).write_text(json.dumps(payload)); return path

    def review(self, tid, resolves=None, targets=None):
        run=self.t.begin(tid,'verification',review=True)
        task=self.t.read()['tasks'][tid]
        evidence=self.report(tid,issues=resolves)
        for issue in resolves or []:
            self.t.resolve_issue(task_id=tid,agent_run_id=run['agent_run_id'],issue_id=issue,evidence=evidence)
        checks=None
        if task['role']=='design':
            checks={k:{'result':'PASS','evidence':self.report(tid,k,targets),'environment':'synthetic unit fixture','coverage':['fixture']} for k in ['structure','interaction','visual']}
        return self.t.review(tid,run['agent_run_id'],[{'criterion_id':'C','result':'PASS','evidence':evidence}],'synthetic fixture review',checks)

    def planning(self):
        self.register('P','planning'); self.execute('P','planning'); self.review('P')

    def design(self):
        self.planning(); self.register('D','design',['P'],'P-001'); self.t.handoff('P','D'); self.execute('D','design')

    def issue(self, tid, kind='design'):
        return self.t.issue(task_id=tid,kind=kind,screen='SCREEN-001',ui_state='ERROR',observed='synthetic missing control',expected='synthetic visible control',severity='MAJOR',recheck='rerender same synthetic target',evidence='input.md',synthetic=True,impacts=['D'])

    def test_blocker_retry_rerender_resolution_and_handoff(self):
        self.design(); old=copy.deepcopy(self.t.read()['tasks']['D']['outputs']); issue=self.issue('D')
        self.assertEqual(self.review('D'),'BLOCKED')
        self.t.route_issue(issue_id=issue['id'],target_id='D')
        self.execute('D','design')
        self.assertEqual(self.review('D',[issue['id']]),'DONE')
        state=self.t.read(); self.assertEqual(state['issues'][0]['status'],'RESOLVED')
        self.assertTrue(all(self.t._valid_artifact(a) for a in old))
        self.register('DEV','development',['D'],'P-001','D-001'); self.t.handoff('D','DEV')
        inputs=self.t.read()['tasks']['DEV']['inputs']
        self.assertTrue(any(r['path']=='feature/requirements.md' for r in inputs))
        self.assertEqual(self.t.read()['tasks']['DEV']['state'],'READY')
        self.assertNotIn('input_confirmation', self.t.read()['tasks']['DEV'])

    def test_policy_routes_to_planning_and_blocks_affected_design(self):
        self.design(); self.review('D'); issue=self.issue('D','policy')
        self.assertEqual(issue['owner'],'planning')
        self.register('P2','planning'); self.t.route_issue(issue_id=issue['id'],target_id='P2')
        with self.assertRaises(ValueError): self.t.route_issue(issue_id=issue['id'],target_id='D')
        self.register('DEV','development',['D'],'P-001','D-001')
        with self.assertRaises(ValueError): self.t.handoff('D','DEV')

    def test_checkpoint_return_keeps_active_run_inputs_and_attempt_budget(self):
        self.planning()
        self.register('D','design',['P'],'P-001')
        self.t.handoff('P','D')
        ctx=self.roles.prepare('D','design')
        before=copy.deepcopy(self.t.read()['tasks']['D'])
        self.roles.accept('D',ctx['agent_run_id'],{'status':'waiting','summary':'synthetic review pause','files':[],
            'completed':['retained draft'],'questions':[{'question':'review?', 'recommended':'repair','alternative':'stop'}]})
        issue=self.issue('D')
        self.t.route_issue(issue_id=issue['id'],target_id='D')
        (self.root/'decision.md').write_text('Synthetic reviewer decision: repair')
        self.t.resume('D',ctx['agent_run_id'],'decision.md')
        self.roles.prepare('D','design')
        after=self.t.read()['tasks']['D']
        packet=json.loads((self.root/ctx['context']).read_text())
        self.assertEqual(after['inputs'],before['inputs'])
        self.assertEqual(len(after['executions']),1)
        self.assertEqual(after['max_attempts'],2)
        self.assertEqual(after['executions'][0]['agent_run_id'],ctx['agent_run_id'])
        self.assertIn(issue['id'],str(packet['returned_issues']))

    def test_partial_target_review_cannot_complete(self):
        self.design()
        # Configure targets in the registry before review; a one-target report cannot pass all targets.
        def configure(state): state['tasks']['D']['role_contract']['design_targets']=['app','web-mobile','web-desktop']
        self.t._mutate('synthetic-target-fixture',configure,'D')
        with self.assertRaises(ValueError): self.review('D',targets=['app'])
        self.assertEqual(self.t.read()['tasks']['D']['state'],'IN_REVIEW')

    def test_stale_validation_overlay_does_not_rewrite_old_reviews(self):
        self.design(); self.review('D'); old=copy.deepcopy(self.t.read()['tasks']['D']['reviews'])
        self.register('P2','planning')
        ctx=self.roles.prepare('P2','planning')
        self.roles.accept('P2',ctx['agent_run_id'],{'status':'submitted','summary':'synthetic new specification','files':[{'path':'requirements.md','content':'changed requirement'}]})
        state=self.t.read(); self.assertEqual(state['deliverables']['feature']['validation_status']['D-001']['state'],'RECHECK_REQUIRED')
        self.assertEqual(state['tasks']['D']['reviews'],old)

    def test_development_receipt_must_match_all_inputs(self):
        self.design(); self.review('D'); self.register('DEV','development',['D'],'P-001','D-001'); self.t.handoff('D','DEV')
        ctx=self.roles.prepare('DEV','development')
        response={'status':'submitted','summary':'synthetic bad receipt','files':[{'path':'development-plan.md','content':'synthetic plan'}],
                  'input_receipt':{'planning_version':'P-001','design_version':'D-001','artifacts':[],'acceptance_ids':['AC'],'interpretation':'synthetic'}}
        with self.assertRaises(ValueError): self.roles.accept('DEV',ctx['agent_run_id'],response)
        self.assertFalse((self.root/'feature/development-plan.md').exists())
        task=self.t.read()['tasks']['DEV']; response['input_receipt']['artifacts']=[{'path':r['path'],'sha256':r['sha256']} for r in task['inputs']]
        self.roles.accept('DEV',ctx['agent_run_id'],response)
        self.assertEqual(self.t.read()['tasks']['DEV']['input_confirmation']['state'],'CONFIRMED_BY_AGENT')
        self.assertEqual(self.review('DEV'),'DONE')
        self.assertEqual(self.t.read()['tasks']['DEV']['input_confirmation']['state'],'INTERPRETATION_REVIEWED')


if __name__=='__main__': unittest.main()
