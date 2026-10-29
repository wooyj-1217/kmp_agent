"""Synthetic owner-worker claims; real disposable Git, native tasks and diffs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.qa import QA
from harness.qa_repair import owner_repair
from harness.test_delegation import build_fixture,mock_worker


class QARepairSafety(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.manager,self.coordinator,self.spec=build_fixture(self.root)
        self.qa=QA(self.root,self.manager.run_id)
        self.attempt={};self.result={'findings':[{'blocking':True,'owner_role':'planning','kind':'baseline_gap'}]}
    def documentation(self,include_original=False,owner_role='planning',owner_feature='DELEGATION-FIXTURE'):
        m=self.manager
        m.register('DELEGATION-FIXTURE','DOC-TARGET','planning','Synthetic planning outputs','test target only',
                   [{'id':'AC-DOC','required':True,'text':'required original behavior missing'}],['design.md'],
                   work_type='HARNESS_BUILD',execution_scope='documentation')
        m.ready('DOC-TARGET');run=m.begin('DOC-TARGET','planning',execution_mode='local_check')
        (self.root/'planning.md').write_text('missing original behavior A\n')
        (self.root/'policy.md').write_text('missing original behavior B\n')
        paths=['planning.md','policy.md']+(['design.md'] if include_original else [])
        m.submit('DOC-TARGET',run['agent_run_id'],paths,'synthetic omissions for repair safety test')
        review=m.begin('DOC-TARGET','verification',review=True,execution_mode='local_check')
        (self.root/'failure-proof.json').write_text(json.dumps({'actual':'missing original behavior','fixture':True}))
        m.review('DOC-TARGET',review['agent_run_id'],[{'criterion_id':'AC-DOC','result':'FAIL','evidence':'failure-proof.json'}],'synthetic actual omission')
        self.prior_reviews=copy.deepcopy(m.read()['tasks']['DOC-TARGET']['reviews'])
        m.register(owner_feature,'DOC-REPAIR',owner_role,'Explicit author repair revision','repair only scoped documents',
                   [{'id':'AC-REPAIR','required':True,'text':'scoped artifact must be independently retested'}],
                   ['design.md','planning.md','policy.md'],work_type='HARNESS_BUILD',execution_scope='documentation')
        self.qa.configure('QA-DOC','planning','DOC-TARGET',['design.md'],
                          [{'id':'QA-AC','description':'original behavior present','required':True}],
                          repair_task_id='DOC-REPAIR',executable='not-invoked',timeout=5)
        self.qa._workflow_task_id='QA-DOC'
        self.attempt={'report':m.artifact('failure-proof.json')}
        return owner_repair(self.qa)
    def worker(self,*args):
        ws=args[3];paths=['planning.md','policy.md']
        for name in paths:(ws/name).write_text('restored explicitly requested behavior '+name+'\n')
        return {'returncode':0,'result':{'status':'COMPLETE','summary':'synthetic scoped repair',
                'changed_files':paths,'verifications':[],'unresolved':[],
                'contract_change_required':False,'contract_impact':[],'change_reference':None},
                'usage_status':'UNKNOWN','thread_ids':[]}
    def test_immutable_original_in_outputs_rejected_before_worker(self):
        repair=self.documentation(include_original=True)
        original=(self.root/'design.md').read_bytes()
        with patch('harness.qa_repair.run_codex') as worker:
            with self.assertRaisesRegex(ValueError,'immutable original'):repair(self.attempt,self.result,self.root)
            worker.assert_not_called()
        self.assertEqual((self.root/'design.md').read_bytes(),original)
        self.assertFalse(self.manager.read()['tasks']['DOC-REPAIR']['executions'])
    def test_second_file_external_conflict_prevents_first_file_apply(self):
        repair=self.documentation();before=(self.root/'planning.md').read_bytes()
        def conflict(*args):
            value=self.worker(*args);(self.root/'policy.md').write_text('external author change preserved\n');return value
        with patch('harness.qa_repair.run_codex',conflict):
            with self.assertRaisesRegex(ValueError,'changed concurrently'):repair(self.attempt,self.result,self.root)
        self.assertEqual((self.root/'planning.md').read_bytes(),before)
        self.assertEqual((self.root/'policy.md').read_text(),'external author change preserved\n')
        state=self.manager.read();self.assertEqual(state['tasks']['DOC-TARGET']['reviews'],self.prior_reviews)
        self.assertTrue(all(r.get('ended_at') for r in state['tasks']['DOC-REPAIR']['executions']))
    def test_valid_repair_only_submits_for_review_never_quality_pass(self):
        repair=self.documentation()
        with patch('harness.qa_repair.run_codex',self.worker):result=repair(self.attempt,self.result,self.root)
        self.assertEqual(result['status'],'COMPLETE')
        state=self.manager.read();owner=state['tasks']['DOC-REPAIR']
        self.assertEqual(owner['state'],'IN_REVIEW');self.assertFalse(owner['reviews'])
        self.assertEqual(state['tasks']['DOC-TARGET']['reviews'],self.prior_reviews)
        proof=json.loads((self.root/result['evidence']).read_text())
        self.assertEqual(proof['result'],'REPORTED_COMPLETE_NOT_QUALITY_PASS')
        self.assertEqual(state['tasks']['QA-DOC']['qa_config']['attempts'],[])
    def test_accepted_delegated_code_is_not_a_new_complete_repair(self):
        self.coordinator.configure(**self.spec)
        outcome=self.coordinator.execute('PARENT',mock_worker)
        self.assertEqual(outcome.get('handoff'),'READY_FOR_VERIFICATION',outcome)
        self.qa.configure('QA-IMPL','implementation','PARENT',['design.md'],
                          [{'id':'QA-AC','description':'separate actual QA','required':True}],repair_task_id='PARENT')
        self.qa._workflow_task_id='QA-IMPL'
        with patch('harness.qa_repair.Roles.execute') as execute,patch('harness.qa_repair.run_codex') as worker:
            result=owner_repair(self.qa)({'report':None},{'findings':[{'blocking':True,'owner_role':'development'}]},self.root)
            execute.assert_not_called();worker.assert_not_called()
        self.assertEqual(result['status'],'BLOCKED');self.assertIn('not a new repair',result['reason'])
    def test_wrong_owner_role_rejected_without_dispatch(self):
        repair=self.documentation(owner_role='verification')
        with patch('harness.qa_repair.run_codex') as worker:
            with self.assertRaisesRegex(ValueError,'responsible author role'):repair(self.attempt,self.result,self.root)
            worker.assert_not_called()
    def test_finding_assigned_to_another_role_is_blocked(self):
        repair=self.documentation();self.result['findings'][0]['owner_role']='design'
        with patch('harness.qa_repair.run_codex') as worker:
            result=repair(self.attempt,self.result,self.root);worker.assert_not_called()
        self.assertEqual(result['status'],'BLOCKED')
    def test_cross_feature_repair_owner_rejected(self):
        repair=self.documentation(owner_feature='DIFFERENT-FEATURE')
        with patch('harness.qa_repair.run_codex') as worker:
            with self.assertRaisesRegex(ValueError,'scope|feature'):repair(self.attempt,self.result,self.root)
            worker.assert_not_called()
    def test_cross_project_or_work_type_repair_owner_rejected(self):
        repair=self.documentation()
        original=copy.deepcopy(self.manager.read()['tasks']['DOC-REPAIR'])
        for field,value in (('project_id','foreign-project'),('work_type','CONNECTION_TEST')):
            with self.subTest(field=field):
                def set_scope(state):
                    state['tasks']['DOC-REPAIR'][field]=value
                self.manager._mutate('synthetic_foreign_owner_scope',set_scope,'DOC-REPAIR')
                with patch('harness.qa_repair.run_codex') as worker:
                    with self.assertRaisesRegex(ValueError,'scope|project|work.type'):repair(self.attempt,self.result,self.root)
                    worker.assert_not_called()
                def restore(state):state['tasks']['DOC-REPAIR'][field]=original[field]
                self.manager._mutate('synthetic_restore_owner_scope',restore,'DOC-REPAIR')
    def test_worker_extra_file_is_rejected_without_source_changes(self):
        repair=self.documentation();before=(self.root/'planning.md').read_bytes()
        def extra(*args):
            value=self.worker(*args);(args[3]/'api.md').write_text('out of scope\n');value['result']['changed_files'].append('api.md');return value
        with patch('harness.qa_repair.run_codex',extra):
            with self.assertRaisesRegex(ValueError,'outside declared'):repair(self.attempt,self.result,self.root)
        self.assertEqual((self.root/'planning.md').read_bytes(),before)


if __name__=='__main__':unittest.main()
