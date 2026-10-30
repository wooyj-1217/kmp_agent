import copy
import json
import tempfile
import unittest
from pathlib import Path
from harness.tasks import Tasks
from harness.logging import Logger
from harness.verification import artifact_status, context
from harness.test_verification_procedure import example
from harness.interruptions import Interruptions


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name,body in [('input.md','user goal'),('output.md','result'),('env.json','{"browser":"fixture-1"}'),('trace.txt','actual synthetic user trace')]:
            (self.root/name).write_text(body)
        (self.root/'procedure.json').write_text(json.dumps(example()))
        self.run=Logger(self.root).start('HARNESS_BUILD','orchestrator','synthetic receipt test')
        self.m=Tasks(self.root,self.run)
        self.criteria=[{'id':x,'required':True,'text':x} for x in ('A','B')]
        self.m.register('F','T','planning','task','synthetic only',self.criteria,['input.md'],max_attempts=2)
        self.m.configure_verification('T',procedure='procedure.json',environment='env.json',criteria=[{'id':c['id'],'platforms':['web'],'method':'user journey','evidence_required':True,'kind':'execution'} for c in self.criteria],writable_paths=['output.md'],forbidden_paths=['input.md'],integrator='orchestrator',goal='verify all criteria')
        self.m.configure_collection('T',shared_resources=[])

    def prepare(self,actor='reviewer'):
        self.m.ready('T');work=self.m.begin('T','planning',actor_id='builder')
        self.m.submit('T',work['agent_run_id'],['output.md'],'self report is not DONE')
        self.assertEqual(self.m.read()['tasks']['T']['state'],'IN_REVIEW')
        self.review=self.m.begin('T','verification',review=True,actor_id=actor)
        return work

    def receipts(self):
        task=self.m.read()['tasks']['T'];rows=[]
        for c in self.criteria:
            report={**context(self.m,task),'task_id':'T','criterion_id':c['id'],'review_run_id':self.review['agent_run_id'],'actor_id':self.review['actor_id'],'tested_outputs':{a['path']:a['sha256'] for a in task['outputs']},'code_state_sha256':None,'kind':'execution','method':'user journey','platform_results':[{'platform':'web','result':'PASS','environment':'synthetic browser fixture-1','command_or_steps':'open create save reload','expected':'saved after reload','observed':'saved after reload','doctor':'PASS','drive':'PASS','cleanup':'PASS','evidence':[self.m.artifact('trace.txt')]}]}
            path=c['id']+'.json';(self.root/path).write_text(json.dumps(report));rows.append({'criterion_id':c['id'],'result':'PASS','evidence':path})
        return rows

    def finish(self,rows):
        return self.m.review('T',self.review['agent_run_id'],rows,'synthetic verification')

    def test_full_flow_cleanup_evidence_and_resume_reuse(self):
        self.prepare();self.assertEqual(self.finish(self.receipts()),'DONE')
        plan=Interruptions(self.root).resume_plan(self.run)
        self.assertEqual(plan['completed_tasks_to_skip'],['T'])
        self.assertTrue((self.root/'trace.txt').exists())

    def test_unreviewed_criterion_and_partial_pass_cannot_complete(self):
        self.prepare();rows=self.receipts()
        with self.assertRaises(ValueError):self.finish(rows[:1])
        rows[1]={'criterion_id':'B','result':'NOT_RUN'}
        self.assertEqual(self.finish(rows),'BLOCKED')

    def test_one_criterion_receipt_cannot_spread(self):
        self.prepare();rows=self.receipts();rows[1]['evidence']=rows[0]['evidence']
        with self.assertRaisesRegex(ValueError,'exact task, criterion'):self.finish(rows)

    def test_actor_separation_required(self):
        self.prepare('builder')
        with self.assertRaisesRegex(ValueError,'separately identified'):self.finish(self.receipts())

    def test_platform_build_only_and_target_mismatch_blocked(self):
        for key,value in [('platform_results',[]),('code_state_sha256','other-code'),('task_id','other-task')]:
            with self.subTest(key=key):
                if not hasattr(self,'review'):self.prepare()
                rows=self.receipts();p=self.root/'A.json';data=json.loads(p.read_text());data[key]=value;p.write_text(json.dumps(data))
                with self.assertRaises(ValueError):self.finish(rows)
        rows=self.receipts();p=self.root/'A.json';d=json.loads(p.read_text());d['platform_results'][0]['drive']='NOT_RUN';p.write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,'build/API'):self.finish(rows)

    def test_missing_or_corrupt_observation_blocked_after_cleanup(self):
        self.prepare();rows=self.receipts();p=self.root/'A.json';data=json.loads(p.read_text());ref=data['platform_results'][0]['evidence'][0]
        (self.root/ref['snapshot']).write_text('corrupt')
        with self.assertRaisesRegex(ValueError,'observation evidence'):self.finish(rows)
        self.assertEqual(artifact_status(self.root,ref)['state'],'HASH_MISMATCH')
        (self.root/ref['snapshot']).unlink();(self.root/'trace.txt').unlink()
        self.assertEqual(artifact_status(self.root,ref),{'state':'MISSING','recovery':'UNAVAILABLE','archive':'NOT_ESTABLISHED','automatic_restore':False})

    def test_environment_change_invalidates_preserves_history_and_resume(self):
        self.prepare();self.assertEqual(self.finish(self.receipts()),'DONE')
        (self.root/'env.json').write_text('{"browser":"fixture-2"}')
        task=self.m.read()['tasks']['T'];rid=task['reviews'][0]['agent_run_id']
        self.assertEqual(task['reviews'][0]['results'][0]['result'],'PASS')
        self.assertEqual(task['validation_status'][rid]['state'],'RECHECK_REQUIRED')
        plan=Interruptions(self.root).resume_plan(self.run)
        self.assertEqual(plan['completed_tasks_to_skip'],[]);self.assertIn('T',plan['revalidation_required'])

    def test_missing_evidence_invalidates_done(self):
        self.prepare();rows=self.receipts();self.finish(rows)
        task=self.m.read()['tasks']['T'];ref=task['reviews'][0]['verification_evidence']['evidence'][0]
        (self.root/ref['snapshot']).unlink()
        self.assertIn('T',Interruptions(self.root).resume_plan(self.run)['revalidation_required'])

    def test_required_project_policy_blocks_unconfigured_new_task(self):
        (self.root/'.harness/verification-policy.json').write_text(json.dumps({'required_work_types':['HARNESS_BUILD']}))
        self.m.register('F','U','planning','next','synthetic',self.criteria,['input.md'])
        with self.assertRaisesRegex(ValueError,'contract missing'):self.m.ready('U')

    def test_requirements_review_cannot_cover_required_platform_execution(self):
        self.m.register('F','U','planning','mapping','synthetic',self.criteria,['input.md'])
        with self.assertRaisesRegex(ValueError,'required platform'):
            self.m.configure_verification('U',procedure='procedure.json',environment='env.json',criteria=[{'id':c['id'],'platforms':['web'],'method':'requirements mapping','evidence_required':True,'kind':'requirements'} for c in self.criteria],writable_paths=['output.md'],forbidden_paths=[],integrator='main',goal='mapping only')

    def test_contract_submission_enforces_path_ownership(self):
        self.m.ready('T');work=self.m.begin('T','planning',actor_id='builder')
        with self.assertRaisesRegex(ValueError,'ownership'):
            self.m.submit('T',work['agent_run_id'],['input.md'],'changed forbidden')

    def test_live_shared_resource_change_rejected(self):
        self.m.ready('T');self.m.begin('T','planning',actor_id='builder')
        self.m.register('F','U','planning','parallel','fixture',self.criteria,['input.md'])
        self.m.configure_collection('U',shared_resources=['device:B'])
        self.m.ready('U');self.m.begin('U','planning')
        run=self.m.read()['tasks']['T']['executions'][0]
        with self.assertRaisesRegex(ValueError,'ownership conflict'):
            self.m.configure_collection('T',shared_resources=['device:B'],agent_run_id=run['agent_run_id'])

    def test_forbidden_change_outside_output_scope_is_rejected(self):
        self.m.ready('T');work=self.m.begin('T','planning',actor_id='builder')
        (self.root/'input.md').write_text('forbidden alteration outside output')
        with self.assertRaisesRegex(ValueError,'ownership'):
            self.m.submit('T',work['agent_run_id'],['output.md'],'report only allowed output')

    def test_dashboard_partial_scope_never_reports_all_required_passed(self):
        from harness.dashboard import task_view
        self.prepare();self.finish(self.receipts())
        task=self.m.read()['tasks']['T'];task['_filter_partial']=True
        scope={'agent_run_ids':[r['agent_run_id'] for r in task['executions']]}
        view=task_view(self.root,task,scope,{'T':task})
        self.assertEqual(view['verdict'],'UNKNOWN')
        self.assertEqual(view['verification_summary']['passed'],0)
        self.assertTrue(all(c['result']=='UNKNOWN' for c in view['verification_summary']['criteria']))

    def test_same_root_cause_reuses_issue_preserves_observations(self):
        data=dict(task_id='T',kind='requirements',screen='screen',ui_state='state',observed='missing',expected='present',severity='MAJOR',recheck='compare requirement',evidence='trace.txt',root_cause='missing-R1')
        first=self.m.issue(**data);second=self.m.issue(**{**data,'observed':'still missing'})
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(self.m.read()['issues']),1)
        self.assertEqual(second['history'][-1]['observed'],'still missing')

    def test_contract_cannot_be_weakened_after_start(self):
        self.prepare()
        with self.assertRaises(ValueError):self.m.configure_verification('T',procedure='procedure.json',environment='env.json',criteria=[],writable_paths=['output.md'],forbidden_paths=[],integrator='main',goal='skip')


if __name__=='__main__':unittest.main()
