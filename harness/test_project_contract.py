"""Stage gate tests using the retained memo example, never a product/API/DB run."""
import copy
import json
import subprocess
from pathlib import Path
import tempfile
import unittest

from harness.tasks import Tasks
from harness.project_contract import FIELDS, SERVER, API, DOCUMENTS

ROOT = Path(__file__).resolve().parents[1]


class ProjectContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.t = Tasks(self.root, 'memo-project-contract-fixture')
        (self.root/'requirements.md').write_text((ROOT/'docs/examples/role-execution/requirements.md').read_text())
        (self.root/'contract.md').write_text('Synthetic fixture: API/policy/runbook/migration/AC contents are NOT product decisions or actual execution.')
        (self.root/'.gitignore').write_text('.harness/\n')
        for args in [('init','-q'),('config','user.name','Fixture'),('config','user.email','fixture@example.invalid'),('add','.'),('commit','-qm','temporary baseline')]:
            subprocess.run(['rtk','proxy','git',*args], cwd=self.root, check=True, capture_output=True)

    def settings(self, mode):
        data = {k:{'status':'CONFIRMED','value':'synthetic fixture only','reason':'test, not product decision'} for k in FIELDS}
        data['implementation_targets']['value'] = ['app-fixture','web-fixture']
        data['server_mode']['value'] = mode
        for k in DOCUMENTS:
            data[k]['value'] = 'contract.md'
        data['api_contract']['mode'] = 'real'
        if mode == 'none':
            for k in SERVER | API:
                data[k].update(status='NOT_APPLICABLE',value=None,reason='no server in this branch fixture')
        elif mode == 'existing':
            for k in SERVER:
                data[k].update(status='NOT_APPLICABLE',value=None,reason='owned by existing server, outside client scope')
        return data

    def task(self, tid, stage, data, deps=None):
        self.t.register('MEMO',tid,'development','memo stage fixture','harness validation only',
                        [{'id':'C','required':True,'text':'fixture evidence'}],['requirements.md'],dependencies=deps)
        self.configure(tid, stage, data)
        task = self.t.read()['tasks'][tid]
        baselines = {'planning':'requirements.md'}
        if stage != 'ui' and data['server_mode']['value'] != 'none':
            baselines.update(api='contract.md',policy='contract.md')
        # Preserve these tests' stage-gate focus; automatic enrolment is tested separately.
        if stage == 'ui' or all(data[k]['status'] in {'CONFIRMED','PROPOSED'} for k in ['api_contract','policy_responsibility']):
            self.t.configure_development(tid,baselines,['out.md'])

    def configure(self, tid, stage, data):
        path=tid+'.json'
        (self.root/path).write_text(json.dumps(data))
        self.t.configure_stage(tid,stage,path)

    def done(self, tid, report=None):
        self.t.ready(tid)
        run=self.t.begin(tid,'development')
        (self.root/'out.md').write_text('synthetic local fixture result, no product execution')
        self.t.submit(tid,run['agent_run_id'],['out.md'],'fixture')
        review=self.t.begin(tid,'verification',review=True)
        from harness.development_tracking import baseline, capture
        task = self.t.read()['tasks'][tid]
        if report is None:
            report = {}
        report['code_state_sha256'] = capture(self.t,task)['state_sha256']
        report['baseline'] = baseline(task)
        if report is not None:
            report['tested_outputs']={a['path']:a['sha256'] for a in self.t.read()['tasks'][tid]['outputs']}
            (self.root/'evidence.json').write_text(json.dumps(report))
        return review['agent_run_id']

    def test_no_server_marks_na_and_no_server_task(self):
        data=self.settings('none')
        self.task('UI','ui',data);self.t.ready('UI')
        self.task('SERVER','server_implementation',data)
        with self.assertRaisesRegex(ValueError,'NOT_APPLICABLE'): self.t.ready('SERVER')
        bad=copy.deepcopy(data);bad['database']['status']='UNDECIDED'
        with self.assertRaisesRegex(ValueError,'NOT_APPLICABLE'):self.configure('SERVER','server_implementation',bad)

    def test_existing_server_requires_api_not_internal_db(self):
        data=self.settings('existing');data['api_contract']['status']='UNDECIDED'
        self.task('CLIENT','client_integration',data)
        with self.assertRaisesRegex(ValueError,'api_contract'):self.t.ready('CLIENT')
        data['api_contract']['status']='CONFIRMED'
        self.configure('CLIENT','client_integration',data);self.t.ready('CLIENT')
        self.assertEqual(self.t.read()['tasks']['CLIENT']['state'],'READY')

    def test_new_server_requires_migration_not_ui_decisions(self):
        data=self.settings('new');data['migration_plan']['status']='PROPOSED'
        data['ui_technology']['status']='UNDECIDED'
        self.task('SERVER','server_implementation',data)
        with self.assertRaisesRegex(ValueError,'migration_plan'):self.t.ready('SERVER')
        data['migration_plan']['status']='CONFIRMED'
        self.configure('SERVER','server_implementation',data);self.t.ready('SERVER')
        self.assertEqual(self.t.read()['tasks']['SERVER']['state'],'READY')

    def test_unknown_api_allows_ui_but_blocks_only_client_handoff(self):
        data=self.settings('new');data['api_contract']['status']='UNDECIDED'
        self.task('SOURCE','ui',data)
        review=self.done('SOURCE')
        self.assertEqual(self.t.review('SOURCE',review,[{'criterion_id':'C','result':'PASS','evidence':'evidence.json'}],'fixture'),'DONE')
        self.task('UI','ui',data,['SOURCE']);self.task('CLIENT','client_integration',data,['SOURCE'])
        self.t.handoff('SOURCE','UI')
        with self.assertRaisesRegex(ValueError,'api_contract'):self.t.handoff('SOURCE','CLIENT')
        state=self.t.read()['tasks']
        self.assertEqual(state['UI']['state'],'READY');self.assertEqual(state['CLIENT']['state'],'TODO')
        self.assertFalse(state['CLIENT']['handoffs'])

    def test_mock_cannot_be_actual_integration_and_snapshots_are_frozen(self):
        data=self.settings('existing');data['api_contract']['mode']='mock'
        self.task('CLIENT','client_integration',data)
        data['api_contract']['mode']='real'
        (self.root/'CLIENT.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'mock API'):self.t.ready('CLIENT')
        self.configure('CLIENT','client_integration',data);self.t.ready('CLIENT')
        docs=self.t.read()['tasks']['CLIENT']['stage_contract']['documents']
        self.assertTrue(docs and all(self.t._valid_artifact(d) for d in docs))

    def test_integration_evidence_rejects_mock_and_missing_target(self):
        self.task('VERIFY','integration_verification',self.settings('new'))
        report={'mode':'mock','result':'PASS','target_results':{'app-fixture':'PASS','web-fixture':'PASS'},
                'end_to_end':'PASS','environment':'synthetic unit test','observations':'schema fixture, not actual E2E'}
        review=self.done('VERIFY',report)
        result=[{'criterion_id':'C','result':'PASS','evidence':'evidence.json'}]
        with self.assertRaisesRegex(ValueError,'real-mode'):self.t.review('VERIFY',review,result,'fixture')
        report=json.loads((self.root/'evidence.json').read_text());report['mode']='real';del report['target_results']['web-fixture']
        (self.root/'evidence.json').write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'every implementation target'):self.t.review('VERIFY',review,result,'fixture')
        report['target_results']['web-fixture']='PASS';(self.root/'evidence.json').write_text(json.dumps(report))
        self.assertEqual(self.t.review('VERIFY',review,result,'synthetic schema acceptance only'),'DONE')


if __name__ == '__main__':
    unittest.main()
