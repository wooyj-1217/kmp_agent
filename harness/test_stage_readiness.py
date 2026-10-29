import json
from pathlib import Path
import tempfile
import unittest
from harness.tasks import Tasks
from harness.stage_readiness import STAGES,DOMAINS,assess,gate


class StageReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'.harness').mkdir();(self.root/'.harness/project.json').write_text(json.dumps({'project_id':'synthetic-stage-review','project_path':'..'}))
        (self.root/'req.md').write_text('approved input; temporary synthetic product')
        self.t=Tasks(self.root,"SYNTHETIC-STAGED-REVIEW");self.contract={}
        for stage,role in [('planning','planning'),('design','design'),('development_plan','development')]:
            checks={k:stage+'-'+k for k in DOMAINS[stage]}
            self.t.register('F',stage,role,stage,'independent '+stage,
                [{'id':v,'required':True,'text':k} for k,v in checks.items()],['req.md'],max_attempts=3,work_type='PRODUCT',execution_scope='documentation')
            self.contract[stage]={'task_id':stage,'checks':checks}
        self.t.configure_stage_workflow('F',self.contract)
        self.t.register('F','CODE','development','implementation','not plan approval',[{'id':'code','required':True,'text':'implementation'}],['req.md'],work_type='PRODUCT',execution_scope='code_implementation')

    def approve(self,stage,fail=None,return_stage=None,issue_id=None,no_failure_evidence=False):
        state=self.t.read();tid=state['stage_workflows']['F']['stages'][stage]['task_id'];task=state['tasks'][tid]
        refs=['req.md']
        for before in STAGES[:STAGES.index(stage)]:
            current=state['stage_workflows']['F']['stages'][before]['task_id'];refs += [a['path'] for a in state['tasks'][current]['outputs']]
        self.t.bind_stage_inputs(tid,refs,'explicit latest upstream versions')
        if task['state']!='READY':self.t.ready(tid)
        work=self.t.begin(tid,task['role']);name=stage+'.md';(self.root/name).write_text('synthetic revised '+tid)
        self.t.submit(tid,work['agent_run_id'],[name],'synthetic stage output',**({'design_status':{'specification':'COMPLETE','mockup':'NOT_PRODUCED','visual_review':'NOT_RUN'}} if stage=='design' else {}))
        reviewer=self.t.begin(tid,'verification',review=True)
        issue_ids=task.get('returned_issues',[]) if fail is None and return_stage is None else []
        evidence='proof-'+tid+'.json';(self.root/evidence).write_text(json.dumps({'result':'PASS','tested_outputs':{a['path']:a['sha256'] for a in self.t.read()['tasks'][tid]['outputs']},'resolved_issues':issue_ids,'observations':['synthetic issue-specific repaired omission'],'method':'synthetic criterion report'}))
        results=[{'criterion_id':c['id'],'result':'FAIL' if c['id']==fail else 'PASS','evidence':evidence} for c in task['criteria']]
        if no_failure_evidence:
            for r in results:
                if r['result']!='PASS':r.pop('evidence',None)
        if return_stage:
            results[0].update(result='FAIL',return_stage=return_stage,reason='upstream omission found during this review')
        for pending in issue_ids:self.t.resolve_issue(task_id=tid,agent_run_id=reviewer['agent_run_id'],issue_id=pending,evidence=evidence)
        self.t.review(tid,reviewer['agent_run_id'],results,'explicit synthetic review')
        return tid

    def test_planning_and_design_do_not_confirm_development_plan(self):
        self.approve('planning');self.approve('design')
        status=assess(self.root,self.t.read(),'F');self.assertEqual([s['status'] for s in status['stages']],['PASS','PASS','NOT_RUN'])
        with self.assertRaisesRegex(ValueError,'development_plan'):self.t.ready('CODE')

    def test_product_code_cannot_bypass_unregistered_plan_contract(self):
        self.t.register('OTHER','NO-PLAN','development','no plan','code',[{'id':'AC','required':True}],[],work_type='PRODUCT',execution_scope='code_implementation')
        with self.assertRaisesRegex(ValueError,'개발계획'):self.t.ready('NO-PLAN')

    def test_independent_plan_and_exact_input_versions_required(self):
        for stage in STAGES:self.approve(stage)
        state=self.t.read();self.assertEqual(assess(self.root,state,'F')['status'],'PASS')
        self.assertIn('입력',gate(self.t,state,state['tasks']['CODE']))
        self.t.bind_stage_inputs('CODE',['req.md','planning.md','design.md','development_plan.md'],'exact reviewed versions')
        state=self.t.read();self.assertIsNone(gate(self.t,state,state['tasks']['CODE']))

    def test_missing_check_retries_same_stage_without_approving_it(self):
        self.approve('planning');self.approve('design')
        self.approve('development_plan',fail='development_plan-verification_commands')
        state=self.t.read();self.assertEqual(state['tasks']['development_plan']['state'],'BLOCKED');self.assertEqual(state['tasks'][state['stage_workflows']['F']['stages']['development_plan']['task_id']]['state'],'READY')
        self.assertEqual(assess(self.root,self.t.read(),'F')['stages'][-1]['status'],'REWORK_REQUIRED')
        self.approve('development_plan')
        self.assertEqual(assess(self.root,self.t.read(),'F')['status'],'PASS')

    def test_typed_return_routes_upstream_and_preserves_old_approval(self):
        self.approve('planning');self.approve('design',return_stage='planning')
        state=self.t.read();p=state['stage_workflows']['F']['stages']['planning']['task_id']
        self.assertNotEqual(p,'planning');self.assertEqual(state['tasks']['planning']['state'],'DONE');self.assertEqual(state['tasks'][p]['state'],'READY')
        self.assertEqual(state['tasks'][p]['role'],'planning')
        self.assertEqual(assess(self.root,state,'F')['stages'][1]['status'],'WAITING_UPSTREAM')
        issue_id=state['tasks'][p]['returned_issues'][0]
        self.approve('planning',issue_id=issue_id);self.approve('design')
        self.assertEqual(assess(self.root,self.t.read(),'F')['stages'][1]['status'],'PASS')

    def test_input_edit_invalidates_downstream_without_rewriting_past_results(self):
        for stage in STAGES:self.approve(stage)
        before=json.dumps(self.t.read()['tasks']['design']['reviews'],sort_keys=True)
        (self.root/'planning.md').write_text('changed unreviewed planning')
        status=assess(self.root,self.t.read(),'F')
        self.assertEqual(status['stages'][0]['status'],'RECHECK_REQUIRED');self.assertEqual(status['stages'][1]['status'],'WAITING_UPSTREAM')
        self.assertEqual(before,json.dumps(self.t.read()['tasks']['design']['reviews'],sort_keys=True))

    def test_budget_is_across_repairs_not_reset_by_new_task_ids(self):
        for _ in range(3):self.approve('planning',fail='planning-acceptance')
        status=assess(self.root,self.t.read(),'F')['stages'][0]
        self.assertEqual(status['status'],'BLOCKED_RETRY_LIMIT');self.assertTrue(status['requires_human'])
        with self.assertRaisesRegex(ValueError,'한도'):self.t.begin(self.t.read()['stage_workflows']['F']['stages']['planning']['task_id'],'planning')

    def test_last_allowed_attempt_is_not_prematurely_reported_exhausted(self):
        state=self.t.read();state['tasks']['planning']['max_attempts']=1;self.t._save(state)
        self.t.ready('planning');self.t.begin('planning','planning')
        self.assertNotEqual(assess(self.root,self.t.read(),'F')['stages'][0]['status'],'BLOCKED_RETRY_LIMIT')

    def test_return_does_not_discard_active_work_without_checkpoint(self):
        self.t.ready('planning');run=self.t.begin('planning','planning')
        with self.assertRaisesRegex(ValueError,'checkpoint'):self.t.return_to_stage('F','planning','missing acceptance','req.md')
        self.assertEqual(self.t.read()['tasks']['planning']['executions'][0]['ended_at'],None)
        (self.root/'checkpoint.md').write_text('synthetic progress preserved')
        self.t.checkpoint('planning',run['agent_run_id'],'explicit safe return','checkpoint.md')
        repair=self.t.return_to_stage('F','planning','missing acceptance','req.md')
        self.assertEqual(repair['status'],'REPAIR_READY');self.assertEqual(self.t.read()['tasks'][repair['task_id']]['state'],'READY')
        self.assertEqual(self.t.read()['tasks']['planning']['executions'][0]['outcome'],'RETURNED')

    def test_not_passed_without_evidence_still_creates_auditable_repair(self):
        self.approve('planning',fail='planning-acceptance',no_failure_evidence=True)
        state=self.t.read();tid=state['stage_workflows']['F']['stages']['planning']['task_id']
        self.assertNotEqual(tid,'planning');self.assertEqual(state['tasks'][tid]['state'],'READY')
        self.assertEqual(json.loads((self.root/state['issues'][0]['evidence']['path']).read_text())['result'],'NOT_PASSED')

    def test_old_pass_without_contract_binding_is_not_inherited(self):
        self.approve('planning')
        state=self.t.read();state['tasks']['planning']['reviews'][-1].pop('stage_readiness_contract_sha256')
        self.assertEqual(assess(self.root,state,'F')['stages'][0]['status'],'RECHECK_REQUIRED')

    def test_configure_rejects_interpretation_receipt(self):
        state=self.t.read();state.pop('stage_workflows');state['tasks']['development_plan']['execution_scope']='input_interpretation_only';self.t._save(state)
        with self.assertRaisesRegex(ValueError,'input interpretation'):self.t.configure_stage_workflow('F',self.contract)

    def test_interpretation_receipt_is_not_a_plan(self):
        state=self.t.read();state['tasks']['development_plan']['execution_scope']='input_interpretation_only'
        self.t._save(state)
        self.assertIsNotNone(gate(self.t,state,state['tasks']['CODE']))


if __name__=='__main__':unittest.main()
