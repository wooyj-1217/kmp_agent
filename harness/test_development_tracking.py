"""Real Git commits only in disposable target repositories; no product implementation."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from harness.tasks import Tasks
from harness.development_tracking import capture, baseline
from harness.deliverables import change


class DevelopmentTracking(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Temporary Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.write('.gitignore', '.harness/\n')
        self.write('src/app.py', 'value = 1\n')
        for name in ['planning', 'design', 'api', 'policy']:
            self.write(name + '.md', name + ' original contract\n')
        self.commit('initial fixture')
        self.t = Tasks(self.root, 'temporary-development-test')
        self.refs = {k:k+'.md' for k in ['planning','design','api','policy']}

    def git(self, *args):
        return subprocess.run(['rtk','proxy','git',*args], cwd=self.root, check=True, capture_output=True).stdout.decode().strip()

    def write(self, path, content):
        p = self.root/path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def task(self, tid='CLIENT', api=True, paths=None):
        self.t.register('F',tid,'development','fixture','test', [{'id':'AC','required':True,'text':'actual fixture assertion'}],[])
        self.t.configure_development(tid, self.refs if api else {'planning':'planning.md'},
                                     ['src'] if paths is None else paths, api_required=api, service_version='/v1')
        self.t.ready(tid)
        return self.t.begin(tid,'development')

    def submitted(self, committed=False):
        run = self.task()
        self.write('src/app.py','value = 2\n')
        if committed:
            self.commit('fixture implementation')
        self.t.submit('CLIENT',run['agent_run_id'],['src/app.py'],'fixture')
        return run

    def passed(self):
        self.submitted()
        review = self.t.begin('CLIENT','verification',review=True)
        task = self.t.read()['tasks']['CLIENT']
        # Execute the actual submitted fixture before writing evidence.
        scope = {}
        exec((self.root/'src/app.py').read_text(), scope)
        self.assertEqual(scope['value'],2)
        self.write('proof.json',json.dumps({'code_state_sha256':capture(self.t,task)['state_sha256'],
                                          'baseline':baseline(task),'observations':'executed value == 2'}))
        self.assertEqual(self.t.review('CLIENT',review['agent_run_id'],
                         [{'criterion_id':'AC','result':'PASS','evidence':'proof.json'}],'actual fixture check'),'DONE')
        return review['agent_run_id']

    def test_uncommitted_submission_and_target_identity(self):
        run = self.submitted()
        task = self.t.read()['tasks']['CLIENT']
        result = task['executions'][0]
        self.assertEqual(result['code_state_start']['repository_root'],str(self.root))
        self.assertEqual(result['code_state_result']['state_kind'],'WORKING_TREE')
        self.assertFalse(result['submitted_content_in_head'])
        self.assertIn('src/app.py',result['code_state_result']['changed_files'])
        self.assertFalse(result['code_state_result']['code_restore_supported'])

    def test_committed_result_is_in_recorded_head(self):
        self.submitted(True)
        result = self.t.read()['tasks']['CLIENT']['executions'][0]
        self.assertTrue(result['submitted_content_in_head'])
        self.assertEqual(result['code_state_result']['state_kind'],'COMMITTED')
        self.assertNotEqual(result['code_state_start']['head'],result['code_state_result']['head'])

    def test_client_server_mismatch_rejected(self):
        self.task()
        self.write('api.md','changed response and authentication\n')
        self.t.register('F','SERVER','development','server fixture','test',[{'id':'AC','required':True,'text':'fixture'}],[])
        self.t.configure_development('SERVER',self.refs,['src'],api_required=True)
        with self.assertRaisesRegex(ValueError,'baseline mismatch'):
            self.t.ready('SERVER')

    def test_no_server_does_not_require_api(self):
        self.task(api=False)
        self.assertFalse(self.t.read()['tasks']['CLIENT']['development_tracking']['api_required'])

    def test_code_change_invalidates_without_rewriting_pass(self):
        rid = self.passed()
        before = copy.deepcopy(self.t.read()['tasks']['CLIENT']['reviews'])
        self.write('src/extra.py','new_dependency = True\n')
        task = self.t.refresh_validation()['tasks']['CLIENT']
        self.assertEqual(task['validation_status'][rid]['state'],'RECHECK_REQUIRED')
        self.assertEqual(task['reviews'],before)
        self.assertEqual(task['reviews'][0]['results'][0]['result'],'PASS')
        self.t.register('F','NEXT','development','dependent fixture','test',
                        [{'id':'AC','required':True,'text':'fixture'}],[],dependencies=['CLIENT'])
        with self.assertRaisesRegex(ValueError,'requires recheck'):
            self.t.ready('NEXT')
        with self.assertRaisesRegex(ValueError,'requires recheck'):
            self.t.handoff('CLIENT','NEXT')

    def test_stage_requires_api_even_when_flag_is_false(self):
        from harness.project_contract import FIELDS, DOCUMENTS
        self.t.register('F','SERVER','development','server','fixture',[{'id':'AC','required':True,'text':'fixture'}],[])
        settings={k:{'status':'CONFIRMED','value':'fixture','reason':'temporary test'} for k in FIELDS}
        settings['implementation_targets']['value']=['fixture-client']
        settings['server_mode']['value']='new'
        for k in DOCUMENTS:
            settings[k]['value']='policy.md'
        settings['api_contract'].update(value='api.md', mode='real')
        self.write('settings.json',json.dumps(settings))
        self.t.configure_stage('SERVER','server_implementation','settings.json')
        with self.assertRaisesRegex(ValueError,'API and policy'):
            self.t.configure_development('SERVER',{'planning':'planning.md'},['src'])
        self.t.configure_development('SERVER',self.refs,['src'])
        self.assertTrue(self.t.read()['tasks']['SERVER']['development_tracking']['api_required'])

    def test_checkpoint_is_execution_resume_not_code_restore(self):
        run=self.task()
        self.write('checkpoint.json','{"completed":["analysis"],"pending":["implementation"]}')
        self.t.checkpoint('CLIENT',run['agent_run_id'],'decision needed','checkpoint.json')
        self.write('src/app.py','value = 99\n')
        self.write('decision.md','continue using current tree')
        self.t.resume('CLIENT',run['agent_run_id'],'decision.md')
        task=self.t.read()['tasks']['CLIENT']
        self.assertFalse(task['executions'][0]['checkpoint_capabilities']['code_restore'])
        self.assertEqual((self.root/'src/app.py').read_text(),'value = 99\n')

    def test_unknown_scope_is_conservatively_recheck_required(self):
        run = self.task(paths=[])
        self.t.submit('CLIENT', run['agent_run_id'], ['src/app.py'], 'fixture')
        review = self.t.begin('CLIENT', 'verification', review=True)
        task = self.t.read()['tasks']['CLIENT']
        # Ignored evidence cannot perturb the full repository fingerprint.
        self.write('.harness/proof.json', json.dumps({'code_state_sha256':capture(self.t, task)['state_sha256'], 'baseline':baseline(task)}))
        self.t.review('CLIENT', review['agent_run_id'], [{'criterion_id':'AC','result':'PASS','evidence':'.harness/proof.json'}], 'unknown scope')
        task = self.t.read()['tasks']['CLIENT']
        self.assertEqual(task['validation_status'][review['agent_run_id']]['state'], 'RECHECK_REQUIRED')

    def test_contract_working_change_invalidates(self):
        rid = self.passed()
        self.write('api.md','breaking change\n')
        task = self.t.read()['tasks']['CLIENT']
        self.assertEqual(task['validation_status'][rid]['state'],'RECHECK_REQUIRED')

    def test_verification_rejects_wrong_code_proof(self):
        self.submitted()
        rid=self.t.begin('CLIENT','verification',review=True)['agent_run_id']
        self.write('proof.json',json.dumps({'code_state_sha256':'wrong','baseline':{}}))
        with self.assertRaisesRegex(ValueError,'exact code state'):
            self.t.review('CLIENT',rid,[{'criterion_id':'AC','result':'PASS','evidence':'proof.json'}],'bad proof')

    def test_cr_preserves_old_baseline_and_requires_compatibility(self):
        self.task()
        self.t.fail('CLIENT',self.t.read()['tasks']['CLIENT']['executions'][0]['agent_run_id'],'baseline update')
        old=self.t.read()['tasks']['CLIENT']['development_tracking']['baselines']
        self.write('api.md','new API\n');self.write('reason.md','explicit contract change analysis')
        args=dict(folder='feature',request='change API',reason='new authentication requirement',before=[],
                  impacts={'requirements':[],'screens':[],'checks':['AC'],'tasks':['CLIENT']},evidence='reason.md',
                  before_baselines=old,after_baselines=self.refs)
        with self.assertRaisesRegex(ValueError,'compatibility'):
            change(self.t,**args)
        run=self.t.read()['tasks']['CLIENT']['executions'][0]
        declaration=self.t.intervention('CLIENT',run['agent_run_id'],'fixture-session','fixture-turn',
            'REQUIREMENT_CHANGE','New auth requirement',['reason.md'],'fixture-message','contract-change')
        args['intervention_ids']=[declaration['pending_event_id']]
        cr=change(self.t,**args,compatibility='BREAKING',compatibility_basis='old clients omit required auth',service_version='/v1')
        self.t.configure_development('CLIENT',self.refs,['src'],True,'/v1',cr['id'])
        state=self.t.read()
        saved=state['deliverables']['feature']['changes'][0]['development_change']
        self.assertEqual(saved['before_baselines'],old)
        self.assertNotEqual(saved['before_baselines']['api']['sha256'],saved['after_baselines']['api']['sha256'])
        self.assertEqual(saved['service_version'],'/v1')
        self.assertEqual(saved['compatibility'],'BREAKING')
        self.assertEqual(saved['intervention_ids'],args['intervention_ids'])
        self.assertTrue(self.t._valid_artifact(saved['before_baselines']['api']))

if __name__ == '__main__':
    unittest.main()
