import json
from pathlib import Path
import sys
import tempfile
import unittest
from harness.qa import QA,validate_result,target_scope,scoped_manifest,RESULT_SCHEMA,KINDS,finding_return_stage
from harness.tasks import Tasks

class QATest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'request.md').write_text('Requirement: hello');(self.root/'product.txt').write_text('hello')
        self.m=Tasks(self.root,'qa-test');self.m.register('F','TARGET','development','target','fixture',[{'id':'T','description':'target','required':True}],['request.md','product.txt'],execution_scope='documentation')
        self.qa=QA(self.root,'qa-test');self.criteria=[{'id':'Q','description':'hello','required':True}]
    def configure(self,**kw):return self.qa.configure('QA','implementation','TARGET',['request.md'],self.criteria,**kw)
    def worker(self,w,p):
        (w/'qa-tools').mkdir(exist_ok=True);(w/'qa-tools'/'proof.txt').write_text('Read product.txt: hello; compare request.md')
        return {'criteria':[{'criterion_id':'Q','result':'PASS','observation':'exact expected content','evidence':'qa-tools/proof.txt'}],'findings':[],'recommendation':'PASS','summary':'read fixture'}
    def test_native_verification_role(self):
        self.configure();self.assertEqual(self.m.read()['tasks']['QA']['role'],'verification')
    def test_evidence_and_actual_command_pass(self):
        self.configure(commands=[[sys.executable,'-c','from pathlib import Path;assert Path("product.txt").read_text()=="hello"']]);r=self.qa.execute('QA',self.worker)
        self.assertEqual(r['outcome'],'PASS');self.assertEqual(self.m.read()['tasks']['QA']['state'],'DONE')
    def test_self_report_without_evidence_not_pass(self):
        self.configure()
        def missing(w,p):r=self.worker(w,p);r['criteria'][0]['evidence']='missing';return r
        self.assertNotEqual(self.qa.execute('QA',missing)['outcome'],'PASS')
    def test_product_modification_rejected(self):
        self.configure()
        def modify(w,p):(w/'product.txt').write_text('bad');return self.worker(w,p)
        self.assertEqual(self.qa.execute('QA',modify)['outcome'],'BLOCKED');self.assertEqual((self.root/'product.txt').read_text(),'hello')
    def test_actual_command_fail_not_pass(self):
        self.configure(commands=[[sys.executable,'-c','raise SystemExit(2)']]);self.assertNotEqual(self.qa.execute('QA',self.worker)['outcome'],'PASS')
    def test_missing_command_not_zero_success(self):
        self.configure(commands=[['/nonexistent-command']]);r=self.qa.execute('QA',self.worker)
        report=json.loads((self.root/r['report']['path']).read_text());self.assertEqual(report['commands'][0]['status'],'NOT_RUN');self.assertNotEqual(r['outcome'],'PASS')
    def test_changed_target_before_begin_rejected(self):
        self.configure();(self.root/'product.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'target changed'):self.qa.execute('QA',self.worker)
    def test_original_request_required(self):
        with self.assertRaises(ValueError):self.qa.configure('QA','planning','TARGET',[],self.criteria)
    def test_duplicate_completion_rejected(self):
        self.configure();self.qa.execute('QA',self.worker)
        with self.assertRaisesRegex(ValueError,'already completed'):self.qa.execute('QA',self.worker)
    def test_bounded_fail_attempts_preserved(self):
        self.configure(max_attempts=1)
        def fail(w,p):r=self.worker(w,p);r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK';return r
        self.qa.execute('QA',fail)
        with self.assertRaisesRegex(ValueError,'retry limit'):self.qa.execute('QA',fail)
        t=self.m.read()['tasks']['QA'];self.assertEqual(len(t['reviews']),1);self.assertEqual(len(t['qa_config']['attempts']),1)
    def test_blocking_baseline_gap_keeps_owner_decision_blocked(self):
        self.configure()
        def gap(w,p):
            r=self.worker(w,p);r['findings']=[{'kind':'baseline_gap','severity':'MAJOR','owner_role':'planning','requirement_ids':['R1'],'design_ids':[],'contract_ids':[],'expected':'Original request needs a policy decision','actual':'Policy absent','repro':['Read request.md'],'evidence':'qa-tools/proof.txt','blocking':True,'reason_code':'POLICY_UNDECIDED','code_ref':'product.txt','baseline_ref':'request.md'}];r['recommendation']='BLOCKED';return r
        a=self.qa.execute('QA',gap);self.assertEqual(a['outcome'],'BLOCKED')
        issue=self.m.read()['issues'][0];self.assertEqual(issue['owner'],'planning');self.assertEqual(issue['qa_finding']['kind'],'baseline_gap')
    def test_visual_requires_capture(self):
        self.criteria[0]['visual_required']=True;self.configure()
        self.assertNotEqual(self.qa.execute('QA',self.worker)['outcome'],'PASS')
    def test_repair_callback_then_actual_retest_keeps_old_failure(self):
        (self.root/'product.txt').write_text('bad');self.configure(commands=[[sys.executable,'-c','from pathlib import Path;assert Path("product.txt").read_text()=="hello"']])
        def fix(attempt,result,root):
            (root/'product.txt').write_text('hello');(root/'.harness'/'repair.md').write_text('owner repaired fixture only')
            return {'status':'COMPLETE','evidence':'.harness/repair.md'}
        a=self.qa.execute('QA',self.worker,repair=fix);self.assertEqual(a['outcome'],'PASS')
        task=self.m.read()['tasks']['QA'];self.assertEqual(len(task['qa_config']['attempts']),2);self.assertEqual(task['reviews'][0]['results'][0]['result'],'NOT_RUN')
    def test_unavailable_runtime_is_blocked_and_run_is_closed(self):
        self.configure();a=self.qa.execute('QA',None,executable='/no-such-codex')
        self.assertEqual(a['outcome'],'BLOCKED');self.assertTrue(all(r['ended_at'] for r in self.m.read()['tasks']['QA']['executions']))
    def test_verified_retest_closes_only_explicitly_reviewed_qa_issue(self):
        self.configure()
        count=[0]
        def worker(w,p):
            r=self.worker(w,p);count[0]+=1
            if count[0]==1:
                r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK'
                r['findings']=[{'kind':'specification_violation','severity':'MAJOR','owner_role':'development','requirement_ids':['R1'],'design_ids':[],'contract_ids':[],'expected':'hello','actual':'incorrect fixture','repro':['Read product.txt'],'evidence':'qa-tools/proof.txt','blocking':True,'reason_code':'FIXTURE','code_ref':'product.txt','baseline_ref':'request.md'}]
            else:
                self.assertTrue(p['previous_findings']);r['reviewed_issue_ids']=[i['id'] for i in p['previous_findings']]
            return r
        def fix(a,r,root):
            (root/'.harness'/'repair.md').write_text('actual fixture repair proof')
            return {'status':'COMPLETE','evidence':'.harness/repair.md'}
        a=self.qa.execute('QA',worker,repair=fix);self.assertEqual(a['outcome'],'PASS')
        issue=self.m.read()['issues'][0];self.assertEqual(issue['status'],'RESOLVED');self.assertEqual(issue['resolution']['qa_agent_run_id'],a['agent_run_id'])
    def test_retest_without_explicit_reviewed_ids_keeps_issue_open(self):
        self.configure()
        original=self.worker
        count=[0]
        def w(work,p):
            r=original(work,p);count[0]+=1
            if count[0]==1:
                r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK';r['findings']=[{'kind':'usability','severity':'MAJOR','owner_role':'development','requirement_ids':['R1'],'design_ids':[],'contract_ids':[],'expected':'readable','actual':'not readable','repro':['inspect'],'evidence':'qa-tools/proof.txt','blocking':True,'reason_code':'FIXTURE','code_ref':'product.txt','baseline_ref':'request.md'}]
            return r
        def fix(a,r,root):(root/'.harness'/'repair.md').write_text('proof');return {'status':'COMPLETE','evidence':'.harness/repair.md'}
        self.assertEqual(self.qa.execute('QA',w,repair=fix)['outcome'],'PASS');self.assertEqual(self.m.read()['issues'][0]['status'],'OPEN')
    def test_repair_rebases_inputs_but_preserves_original_request_and_reviews(self):
        (self.root/'baseline.md').write_text('old')
        self.m.register('F','DOC','planning','baseline','fixture',[{'id':'D','description':'D','required':True}],['baseline.md'],execution_scope='documentation')
        self.qa.configure('QA','planning','DOC',['request.md'],self.criteria)
        count=[0]
        def w(work,p):
            r=self.worker(work,p);count[0]+=1
            if count[0]==1:r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK'
            return r
        def fix(a,r,root):(root/'baseline.md').write_text('new');(root/'.harness'/'repair.md').write_text('proof');return {'status':'COMPLETE','evidence':'.harness/repair.md'}
        self.assertEqual(self.qa.execute('QA',w,repair=fix)['outcome'],'PASS');t=self.m.read()['tasks']['QA']
        self.assertNotEqual(t['input_rebases'][0]['before'],t['inputs']);self.assertEqual((self.root/'request.md').read_text(),'Requirement: hello')
        self.assertEqual(t['reviews'][0]['results'][0]['result'],'FAIL')
    def test_unauthorized_original_request_change_stops_retest(self):
        self.configure()
        def w(work,p):r=self.worker(work,p);r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK';return r
        def fix(a,r,root):(root/'request.md').write_text('invented policy');(root/'.harness'/'repair.md').write_text('proof');return {'status':'COMPLETE','evidence':'.harness/repair.md'}
        self.assertEqual(self.qa.execute('QA',w,repair=fix)['outcome'],'BLOCKED');self.assertEqual(len(self.m.read()['tasks']['QA']['qa_config']['attempts']),1)
    def test_unrelated_feature_change_does_not_invalidate_selected_target(self):
        (self.root/'unrelated.txt').write_text('before');self.configure();(self.root/'unrelated.txt').write_text('after')
        self.assertEqual(self.qa.execute('QA',self.worker)['outcome'],'PASS')
    def test_source_unrelated_change_during_qa_is_not_target_change(self):
        (self.root/'unrelated.txt').write_text('before');self.configure()
        def w(work,p):(self.root/'unrelated.txt').write_text('after');return self.worker(work,p)
        self.assertEqual(self.qa.execute('QA',w)['outcome'],'PASS')
    def test_unrelated_worker_product_write_is_still_rejected(self):
        (self.root/'unrelated.txt').write_text('before');self.configure()
        def w(work,p):(work/'unrelated.txt').write_text('bad');return self.worker(work,p)
        self.assertEqual(self.qa.execute('QA',w)['outcome'],'BLOCKED')
    def test_installation_and_private_settings_do_not_invalidate_target(self):
        self.configure()
        for directory in ('.kmp-agent','.codex','.agents'):
            (self.root/directory).mkdir();(self.root/directory/'local.json').write_text('{}')
        self.assertEqual(self.qa.execute('QA',self.worker)['outcome'],'PASS')
    def test_legacy_missing_target_scope_is_explicit_unknown_full_fallback(self):
        scope=target_scope({'inputs':[],'outputs':[]},[]);self.assertEqual(scope['mode'],'UNKNOWN')
        before=scoped_manifest(self.root,scope);(self.root/'unrelated.txt').write_text('change')
        self.assertNotEqual(before,scoped_manifest(self.root,scope))
    def test_declared_directory_scope_detects_new_descendant(self):
        scope=target_scope({'inputs':[],'outputs':[],'development_tracking':{'code_paths':['shared']}},[])
        before=scoped_manifest(self.root,scope);(self.root/'shared').mkdir();(self.root/'shared'/'New.kt').write_text('new')
        self.assertNotEqual(before,scoped_manifest(self.root,scope))
    def test_model_schema_constrains_finding_vocabulary_to_validator(self):
        props=RESULT_SCHEMA['properties']['findings']['items']['properties']
        self.assertEqual(set(props['kind']['enum']),KINDS)
        self.assertEqual(set(props['severity']['enum']),{'BLOCKER','MAJOR','MINOR'})
        self.assertEqual(set(props['owner_role']['enum']),{'planning','design','development','verification','improvement','orchestrator'})
        self.assertNotIn('implementation_violation',props['kind']['enum']);self.assertNotIn('high',props['severity']['enum'])
    def test_implementation_defect_does_not_return_to_development_plan(self):
        workflow={'stages':{'development_plan':{'task_id':'DP','task_history':['DP']}}}
        f={'blocking':True,'owner_role':'development','kind':'specification_violation'}
        self.assertIsNone(finding_return_stage(f,workflow,'CODE'));self.assertIsNone(finding_return_stage(f,workflow,'DP'))
    def test_only_explicit_plan_baseline_gap_returns_to_plan(self):
        workflow={'stages':{'development_plan':{'task_id':'DP.R1','task_history':['DP','DP.R1']}}}
        f={'blocking':True,'owner_role':'development','kind':'baseline_gap'}
        self.assertEqual(finding_return_stage(f,workflow,'DP'),'development_plan')
        self.assertIsNone(finding_return_stage(f,workflow,'CODE'))
        f['kind']='baseline_contradiction';self.assertEqual(finding_return_stage(f,workflow,'DP.R1'),'development_plan')
    def test_planning_design_owner_return_preserved(self):
        for owner in ('planning','design'):
            self.assertEqual(finding_return_stage({'blocking':True,'owner_role':owner,'kind':'baseline_gap'},None,'CODE'),owner)
    def test_invalid_finding_schema(self):
        r=self.worker(self.root,{})
        r['findings']=[{'kind':'guess'}]
        with self.assertRaises(ValueError):validate_result(r)

if __name__=='__main__':unittest.main()
