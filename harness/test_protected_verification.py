"""Real review entrypoint + real signatures. OS authority is an explicit fixture.

These tests do not provision an administrator account or certify a product.
"""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from harness import protected_verification as pv
from harness.logging import Logger
from harness.tasks import Tasks


class ProtectedVerificationTests(unittest.TestCase):
    def test_root_rejects_untrusted_runner_before_import(self):
        with patch.object(pv.os, 'geteuid', return_value=0), \
                patch.object(pv, '_protected', side_effect=[Path('/trusted/__init__.py'), PermissionError('untrusted runner')]), \
                patch.object(pv.importlib.util, 'spec_from_file_location') as load:
            with self.assertRaisesRegex(PermissionError, 'untrusted runner'):
                pv._runner()
            load.assert_not_called()

    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory()
        cls.key = Path(cls.keys.name)/'key.pem'
        subprocess.run(['rtk','proxy','openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(cls.key)],check=True,capture_output=True)
        cls.public = subprocess.check_output(['rtk','proxy','openssl','pkey','-in',str(cls.key),'-pubout']).decode()

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.criteria = [{'id':'SAVE','required':True,'description':'unique note survives restart'}]
        self.definition = {'schema_version':1,'plan_version':'DP-001','checks':[
            {'id':'SAVE-ANDROID','criterion_id':'SAVE','platform':'android','kind':'ui','required':True,
             'command':['rtk','proxy','python3','approved_test.py'], 'expected':'same unique title and body after restart',
             'expected_tests':['save_restore'],'results':[{'path':'verification/results.xml','format':'junit'}]},
            {'id':'SAVE-IOS','criterion_id':'SAVE','platform':'ios','kind':'ui','required':True,
             'command':['rtk','proxy','python3','approved_test.py'],'expected':'same unique title and body after restart',
             'expected_tests':['save_restore'],'results':[{'path':'verification/results.xml','format':'junit'}]}]}
        for name,content in {'.gitignore':'.harness/\nverification/\n','code.py':'saved = True\n','approved_test.py':'assert True\n',
                             'baseline.png':'synthetic baseline','plan.md':'approved DP-001 SAVE Android and iOS',
                             'build.gradle.kts':'// approved build config','output.md':'submitted product scope'}.items():
            (self.root/name).write_text(content)
        (self.root/'verification-plan.json').write_text(json.dumps(self.definition))
        self.git('init'); self.git('config','user.email','fixture@example.invalid'); self.git('config','user.name','Fixture')
        self.git('add','.'); self.git('commit','-m','approved fixture')
        self.contract = {'approved_commit':self.git('rev-parse','HEAD').strip(),'definition_path':'verification-plan.json',
                         'definition':self.definition,'criteria':self.criteria,
                         'plan':{'path':'plan.md','sha256':pv.sha((self.root/'plan.md').read_bytes())},
                         'protected_paths':['approved_test.py','baseline.png','verification-plan.json','plan.md'],
                         'configuration_paths':['build.gradle.kts'],
                         'validation_inputs':{'approved_test.py':pv.sha((self.root/'approved_test.py').read_bytes())}}
        self.policy = {'schema_version':1,'project_root':str(self.root),'agent_uid':os.getuid(),
                       'publisher_uid':0,'issuer':'SYNTHETIC-PROTECTED-JOB','public_key_pem':self.public,'tasks':{'T':self.contract}}
        self.policy_patch = patch.object(pv,'load_policy',return_value=self.policy); self.policy_patch.start(); self.addCleanup(self.policy_patch.stop)
        run = Logger(self.root).start('HARNESS_BUILD','orchestrator','synthetic protected completion test')
        self.manager = Tasks(self.root,run)
        self.manager.register('F','T','planning','Fixture','synthetic protected completion',self.criteria,['plan.md'],execution_scope='documentation')
        self.manager._mutate('fixture protected contract',lambda s:s['tasks']['T'].update(protected_verification_required=True),'T')
        self.manager.ready('T'); work=self.manager.begin('T','planning')
        self.manager.submit('T',work['agent_run_id'],['output.md'],'synthetic submitted commit')
        self.review = self.manager.begin('T','verification',review=True)
        (self.root/'verification').mkdir(exist_ok=True)
        (self.root/'verification/review.json').write_text('{}')

    def git(self,*args):
        return subprocess.check_output(['rtk','proxy','git',*args],cwd=self.root,stderr=subprocess.DEVNULL).decode()

    def sign(self,mutate=None):
        current=pv.candidate(self.root,self.contract)
        (self.root/'verification/results.xml').write_text('<testsuite><testcase name="save_restore"/></testsuite>')
        (self.root/'verification/stdout.txt').write_text('protected test execution output')
        checks=[]
        for c in self.definition['checks']:
            checks.append({**c,'result':'OBSERVED_PASS','exit_code':0,'scenarios':[{'id':'save_restore','result':'PASS'}],
                           'result_files':[{'path':'verification/results.xml','sha256':pv.sha((self.root/'verification/results.xml').read_bytes())}],
                           'outputs':[{'path':'verification/stdout.txt','sha256':pv.sha((self.root/'verification/stdout.txt').read_bytes())}]})
        self._job_number=getattr(self,'_job_number',0)+1
        payload={**current,'project_root':str(self.root),'task_id':'T','issuer':self.policy['issuer'],
                 'publisher_uid':0,'job_id':'synthetic-job-'+str(self._job_number),'checks':checks,'issued_at':time.time()}
        if mutate:mutate(payload)
        signed=subprocess.run(['rtk','proxy','openssl','dgst','-sha256','-sign',str(self.key)],input=pv.canonical(payload),capture_output=True,check=True).stdout
        envelope={'payload':payload,'signature':base64.b64encode(signed).decode()}
        path=pv._envelope(self.root,'T'); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(envelope))
        pv._history_envelope(self.root,'T',payload['job_id']).write_text(json.dumps(envelope))
        return path

    def complete(self):
        return self.manager.review('T',self.review['agent_run_id'],[{'criterion_id':'SAVE','result':'PASS','evidence':'verification/review.json'}],'agent reports success')

    def status(self):
        return self.manager.verification_status('T')

    def test_signed_job_all_required_platforms_allows_real_completion_entrypoint(self):
        self.sign(); self.assertEqual(self.complete(),'DONE'); self.assertEqual(self.status()['result'],'PASS')

    def test_direct_pass_and_raw_done_injection_do_not_complete(self):
        with self.assertRaisesRegex(ValueError,'protected verification'):self.complete()
        state=json.loads(self.manager.path.read_text()); state['tasks']['T']['state']='DONE'
        state['tasks']['T']['official_verification']={'result':'PASS'}
        state['tasks']['T'].pop('protected_verification_required',None)
        state['tasks']['T']['execution_scope']='documentation'
        self.manager.path.write_text(json.dumps(state))
        self.assertEqual(self.manager.read()['tasks']['T']['state'],'BLOCKED')

    def test_unsigned_or_modified_envelope_cannot_issue_pass(self):
        path=self.sign(); value=json.loads(path.read_text()); value['payload']['job_id']='agent-forgery'; path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'signature invalid'):self.complete()

    def test_required_platform_not_run_and_partial_qa_block_completion(self):
        for mode in ('missing','skip','wrong-platform'):
            with self.subTest(mode=mode):
                def change(p):
                    if mode=='missing':p['checks'].pop()
                    elif mode=='skip':p['checks'][1]['scenarios'][0]['result']='SKIP'
                    else:p['checks'][1]['platform']='android'
                self.sign(change)
                with self.assertRaisesRegex(ValueError,'REQUIRED_CHECKS_INCOMPLETE'):self.complete()

    def test_code_change_invalidates_old_job_and_fresh_job_can_complete(self):
        self.sign(); (self.root/'code.py').write_text('saved = False\n'); self.git('add','code.py'); self.git('commit','-m','different candidate')
        with self.assertRaisesRegex(ValueError,'stale'):self.complete()
        self.sign(lambda p:p['checks'][0].update(result='FAIL',reason='SCENARIO_FAILED',exit_code=1))
        with self.assertRaisesRegex(ValueError,'REQUIRED_CHECKS_INCOMPLETE'):self.complete()
        (self.root/'code.py').write_text('saved = True\n'); self.git('add','code.py'); self.git('commit','-m','repair')
        self.sign(); self.assertEqual(self.complete(),'DONE')

    def test_approved_tests_baseline_ci_and_plan_changes_require_reapproval(self):
        self.sign()
        for name in ('approved_test.py','baseline.png','build.gradle.kts','plan.md','verification-plan.json'):
            before=self.git('rev-parse','HEAD').strip()
            with self.subTest(path=name):
                (self.root/name).write_text('weakened acceptance'); self.git('add',name); self.git('commit','-m','candidate changes approval')
                with self.assertRaisesRegex(ValueError,'reapproval'):self.complete()
            self.git('revert','--no-edit','HEAD')
        folder=self.root/'.github/workflows';folder.mkdir(parents=True);(folder/'skip.yml').write_text('skip all tests')
        self.git('add','.github'); self.git('commit','-m','new CI bypass')
        with self.assertRaisesRegex(ValueError,'configuration changed'):self.complete()

    def test_new_tests_allowed_but_do_not_replace_mandatory_scenarios(self):
        (self.root/'new_test.py').write_text('assert True'); self.git('add','new_test.py'); self.git('commit','-m','additional test')
        self.sign(); self.assertEqual(self.complete(),'DONE')

    def test_agent_cannot_change_completion_configuration_or_publish(self):
        with self.assertRaises(PermissionError):self.manager.configure_completion('T',[],False,False,'agent bypass')
        with self.assertRaises(PermissionError):pv.publish(self.root,'T',self.key,'agent-job')
        self.sign()
        self.manager._mutate('tamper configuration',lambda s:s['tasks']['T'].update(completion_contract={'usage_required':False,'context_required':False}),'T')
        with self.assertRaisesRegex(ValueError,'settings differ'):self.complete()

    def test_missing_authority_and_mutable_candidate_policy_are_untrusted(self):
        self.policy_patch.stop()
        with patch.object(pv,'POLICY_DIRECTORY',self.root/'agent-policy'):
            self.assertEqual(self.status()['result'],'BLOCKED')
            with self.assertRaises(ValueError):pv._protected(self.root/'plan.md')

    def test_raw_result_tamper_after_completion_invalidates_current_state(self):
        self.sign(); self.assertEqual(self.complete(),'DONE')
        (self.root/'verification/results.xml').write_text('forged')
        self.assertEqual(self.manager.read()['tasks']['T']['state'],'BLOCKED')

    def test_old_job_and_revoked_approval_require_fresh_protected_execution(self):
        self.sign(lambda p:p.update(issued_at=0))
        with self.assertRaisesRegex(ValueError,'expired'):self.complete()
        self.sign(); self.contract['approval_revision']='owner-reviewed-revision-2'
        with self.assertRaisesRegex(ValueError,'stale'):self.complete()

    def test_deleted_or_renamed_protected_ledger_identity_is_not_an_opt_out(self):
        state=json.loads(self.manager.path.read_text())
        state['tasks']['T']['task_id']='AGENT-BYPASS'
        self.manager.path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.manager.read()
        state['tasks'].pop('T'); self.manager.path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'missing from ledger'):self.manager.read()


if __name__=='__main__':unittest.main()
