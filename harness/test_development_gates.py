"""Lifecycle bypass tests in disposable Git targets; no code written in product repositories."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from harness.tasks import Tasks
from harness.development_tracking import baseline, capture
from harness.project_contract import FIELDS, DOCUMENTS, SERVER, API
from harness import test_development_tracking as fixtures


class DevelopmentGates(unittest.TestCase):
    setUp = fixtures.DevelopmentTracking.setUp
    git = fixtures.DevelopmentTracking.git
    write = fixtures.DevelopmentTracking.write
    commit = fixtures.DevelopmentTracking.commit
    task = fixtures.DevelopmentTracking.task
    submitted = fixtures.DevelopmentTracking.submitted
    passed = fixtures.DevelopmentTracking.passed
    def settings(self, mode='none'):
        data={k:{'status':'CONFIRMED','value':'fixture','reason':'temporary fixture'} for k in FIELDS}
        data['implementation_targets']['value']=['fixture']
        data['server_mode']['value']=mode
        for k in DOCUMENTS:
            data[k]['value']='policy.md'
        data['api_contract'].update(value='api.md',mode='real')
        if mode == 'none':
            for k in SERVER | API:
                data[k].update(status='NOT_APPLICABLE',value=None,reason='no server')
        return data

    def register_code(self, tid='AUTO', stage='ui', mode='none', *, write_requirements=True):
        if write_requirements:
            self.write('requirements.md','frozen implementation requirements\n')
        self.write(tid+'.json',json.dumps(self.settings(mode)))
        self.t.register('F',tid,'development','fixture implementation','explicit stage',
                        [{'id':'AC','required':True,'text':'fixture proof'}],['requirements.md'])
        self.t.configure_stage(tid,stage,tid+'.json')

    def edit_task(self, tid, edit):
        # Simulate a retained legacy record or damaged task metadata, never a supported mutation API.
        state=json.loads(self.t.path.read_text())
        edit(state['tasks'][tid])
        self.t._save(state)

    def test_auto_at_ready_uses_target_and_frozen_inputs(self):
        self.register_code()
        original=self.t.read()['tasks']['AUTO']['inputs'][0]
        self.write('requirements.md','changed working copy must not replace baseline\n')
        self.t.ready('AUTO')
        task=self.t.read()['tasks']['AUTO']
        self.assertTrue(task['development_tracking']['automatic'])
        self.assertEqual(task['development_tracking']['baselines']['planning'],original)
        self.assertEqual(task['development_tracking']['repository_root'],str(self.root))
        self.assertFalse(task['development_tracking']['api_required'])
        run=self.t.begin('AUTO','development')
        self.assertEqual(run['baseline']['references']['planning'],original)
        self.assertEqual(run['code_state_start']['repository_root'],str(self.root))

    def test_automatic_configuration_survives_submit_review_handoff(self):
        self.register_code()
        self.t.ready('AUTO');run=self.t.begin('AUTO','development')
        self.write('src/app.py','value = 7\n')
        self.t.submit('AUTO',run['agent_run_id'],['src/app.py'],'automatic tracked result')
        review=self.t.begin('AUTO','verification',review=True)
        task=self.t.read()['tasks']['AUTO']
        observed={}
        exec((self.root/'src/app.py').read_text(),observed)
        self.assertEqual(observed['value'],7)
        self.write('.harness/proof.json',json.dumps({'code_state_sha256':capture(self.t,task)['state_sha256'],
            'baseline':baseline(task),'observations':'executed fixture value == 7'}))
        self.t.review('AUTO',review['agent_run_id'],[{'criterion_id':'AC','result':'PASS','evidence':'.harness/proof.json'}],'actual fixture execution')
        self.assertEqual(self.t.read()['tasks']['AUTO']['validation_status'][review['agent_run_id']]['state'],'CURRENT')
        self.t.register('F','NEXT','planning','handoff receiver','docs',[{'id':'AC','required':True,'text':'fixture'}],[],dependencies=['AUTO'])
        self.t.handoff('AUTO','NEXT')
        self.assertEqual(self.t.read()['tasks']['NEXT']['state'],'READY')

    def test_auto_at_direct_begin_and_api_mismatch(self):
        self.register_code('CLIENT','client_integration','new')
        self.edit_task('CLIENT',lambda t:t.update(state='READY'))
        self.t.begin('CLIENT','development')
        self.write('api.md','new incompatible API\n')
        self.register_code('SERVER','server_implementation','new')
        with self.assertRaisesRegex(ValueError,'baseline mismatch'):
            self.t.ready('SERVER')
        self.assertNotIn('development_tracking',self.t.read()['tasks']['SERVER'])
        self.assertEqual(self.t.read()['tasks']['SERVER']['state'],'TODO')

    def test_missing_inputs_fail_before_start_with_actionable_list(self):
        self.t.register('F','MISSING','development','source work','code',
                        [{'id':'AC','required':True,'text':'fixture'}],[])
        for direct in (False,True):
            if direct:
                self.edit_task('MISSING',lambda t:t.update(state='READY'))
            with self.assertRaisesRegex(ValueError,'planning/design.*stage_contract'):
                self.t.begin('MISSING','development') if direct else self.t.ready('MISSING')
        self.assertFalse(self.t.read()['tasks']['MISSING']['executions'])

    def test_missing_git_head_and_mismatched_target_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            t=Tasks(root,'no-git-fixture')
            (root/'requirements.md').write_text('requirements')
            (root/'policy.md').write_text('policy fixture')
            (root/'settings.json').write_text(json.dumps(self.settings()))
            t.register('F','NO-GIT','development','fixture','code',[{'id':'AC','required':True,'text':'fixture'}],['requirements.md'])
            t.configure_stage('NO-GIT','ui','settings.json')
            with self.assertRaisesRegex(ValueError,'Git root and existing HEAD'):
                t.ready('NO-GIT')
        self.register_code()
        self.edit_task('AUTO',lambda t:t.update(target_repository='/different/target'))
        with self.assertRaisesRegex(ValueError,'target_repository'):
            self.t.ready('AUTO')

    def test_ambiguous_planning_does_not_choose_latest(self):
        self.register_code()
        self.write('other/requirements.md','ambiguous requirements')
        self.edit_task('AUTO',lambda t:t['inputs'].append(self.t.artifact('other/requirements.md')))
        with self.assertRaisesRegex(ValueError,'unambiguous frozen'):
            self.t.ready('AUTO')

    def test_documentation_is_exempt_but_cannot_publish_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();t=Tasks(root,'doc-only-no-git')
            t.register('F','DOC','development','documentation','write instructions',
                       [{'id':'AC','required':True,'text':'fixture'}],[],execution_scope='documentation')
            t.ready('DOC');run=t.begin('DOC','development')
            (root/'source.py').write_text('forbidden = True')
            with self.assertRaisesRegex(ValueError,'non-code task cannot submit'):
                t.submit('DOC',run['agent_run_id'],['source.py'],'wrong scope')
            (root/'guide.md').write_text('documentation')
            t.submit('DOC',run['agent_run_id'],['guide.md'],'document only')
            self.assertNotIn('code_state_start',run)
            reviewer=t.begin('DOC','verification',review=True)
            self.assertEqual(t.review('DOC',reviewer['agent_run_id'],
                             [{'criterion_id':'AC','result':'PASS','evidence':'guide.md'}],'doc check'),'DONE')

    def test_interpretation_role_scope_is_exempt_without_new_field(self):
        self.t.register('F','READ','development','interpretation','inputs only',
                        [{'id':'AC','required':True,'text':'fixture'}],[])
        self.edit_task('READ',lambda t:t.update(role_contract={'scope':'input_interpretation_only'}))
        self.t.ready('READ');run=self.t.begin('READ','development')
        self.write('development-plan.md','analysis only')
        self.t.submit('READ',run['agent_run_id'],['development-plan.md'],'input interpretation')
        self.assertNotIn('code_state_start',run)

    def test_partial_configuration_has_actionable_error_and_invalidates_pass(self):
        self.passed()
        self.edit_task('CLIENT',lambda t:t['development_tracking'].pop('code_paths'))
        task=self.t.read()['tasks']['CLIENT']
        key=task['reviews'][-1]['agent_run_id']
        self.assertEqual(task['validation_status'][key]['state'],'RECHECK_REQUIRED')
        self.t.register('F','NEXT','planning','next','document',[{'id':'AC','required':True,'text':'fixture'}],[],dependencies=['CLIENT'])
        with self.assertRaisesRegex(ValueError,'development tracking missing: code_paths'):
            self.t.handoff('CLIENT','NEXT')

    def test_submit_cannot_bypass_deleted_configuration_or_start(self):
        for what in ('config','start'):
            tid='SUBMIT-'+what
            run=self.task(tid,api=False)
            def remove(task):
                if what == 'config': task.pop('development_tracking')
                else: task['executions'][0].pop('code_state_start')
            self.edit_task(tid,remove)
            with self.assertRaisesRegex(ValueError,'development.*missing'):
                self.t.submit(tid,run['agent_run_id'],['src/app.py'],'bypass attempt')
            self.assertEqual(self.t.read()['tasks'][tid]['state'],'IN_PROGRESS')

    def test_verification_begin_and_review_cannot_bypass_configuration(self):
        self.submitted()
        config=copy.deepcopy(self.t.read()['tasks']['CLIENT']['development_tracking'])
        self.edit_task('CLIENT',lambda t:t.pop('development_tracking'))
        with self.assertRaisesRegex(ValueError,'development_tracking missing'):
            self.t.begin('CLIENT','verification',review=True)
        self.edit_task('CLIENT',lambda t:t.update(development_tracking=config))
        review=self.t.begin('CLIENT','verification',review=True)
        self.edit_task('CLIENT',lambda t:t.pop('development_tracking'))
        self.write('claim.md','unsupported PASS')
        with self.assertRaisesRegex(ValueError,'development_tracking missing'):
            self.t.review('CLIENT',review['agent_run_id'],[{'criterion_id':'AC','result':'PASS','evidence':'claim.md'}],'bypass')

    def test_no_reconstruction_of_legacy_submission(self):
        self.submitted()
        self.edit_task('CLIENT',lambda t:t['executions'][0].pop('code_state_result'))
        with self.assertRaisesRegex(ValueError,'work start/submission evidence'):
            self.t.begin('CLIENT','verification',review=True)

    def test_code_scope_cannot_be_downgraded_after_start(self):
        run=self.task(api=False)
        def downgrade(task):
            task.pop('development_tracking')
            task['execution_scope']='documentation'
        self.edit_task('CLIENT',downgrade)
        self.write('guide.md','attempt to bypass code tracking')
        with self.assertRaisesRegex(ValueError,'cannot be downgraded'):
            self.t.submit('CLIENT',run['agent_run_id'],['guide.md'],'downgrade')

    def test_handoff_requires_validation_proof_even_with_configuration(self):
        self.passed()
        self.t.register('F','NEXT','planning','next','document',[{'id':'AC','required':True,'text':'fixture'}],[],dependencies=['CLIENT'])
        self.edit_task('CLIENT',lambda t:t['reviews'][-1].pop('development_evidence'))
        with self.assertRaisesRegex(ValueError,'validation unavailable'):
            self.t.handoff('CLIENT','NEXT')
        with self.assertRaisesRegex(ValueError,'dependency development tracking missing'):
            self.t.ready('NEXT')

    def test_handoff_source_cannot_bypass_deleted_configuration(self):
        self.passed()
        self.t.register('F','NEXT','planning','next','document',[{'id':'AC','required':True,'text':'fixture'}],[],dependencies=['CLIENT'])
        self.edit_task('CLIENT',lambda t:t.pop('development_tracking'))
        self.assertEqual(self.t.read()['tasks']['CLIENT']['validation_status'][self.t.read()['tasks']['CLIENT']['reviews'][-1]['agent_run_id']]['state'],'RECHECK_REQUIRED')
        with self.assertRaisesRegex(ValueError,'development_tracking missing'):
            self.t.handoff('CLIENT','NEXT')
        self.assertFalse(self.t.read()['tasks']['NEXT']['handoffs'])

    def test_handoff_to_code_auto_configures_or_rejects_missing_inputs(self):
        self.t.register('F','SOURCE','planning','planning','document',[{'id':'AC','required':True,'text':'fixture'}],[])
        self.t.ready('SOURCE');run=self.t.begin('SOURCE','planning')
        self.write('requirements.md','handoff requirements')
        self.t.submit('SOURCE',run['agent_run_id'],['requirements.md'],'requirements')
        review=self.t.begin('SOURCE','verification',review=True)
        self.t.review('SOURCE',review['agent_run_id'],[{'criterion_id':'AC','result':'PASS','evidence':'requirements.md'}],'review')
        reviewed_content=(self.root/'requirements.md').read_bytes()
        self.register_code(write_requirements=False)
        self.assertEqual((self.root/'requirements.md').read_bytes(),reviewed_content)
        self.edit_task('AUTO',lambda t:t.update(dependencies=['SOURCE'],inputs=[r for r in t['inputs'] if r['path']!='requirements.md']))
        self.t.handoff('SOURCE','AUTO')
        self.assertTrue(self.t.read()['tasks']['AUTO']['development_tracking']['automatic'])
        self.t.register('F','MISSING','development','code','missing applicability',[{'id':'AC','required':True,'text':'fixture'}],[],dependencies=['SOURCE'])
        with self.assertRaisesRegex(ValueError,'stage_contract'):
            self.t.handoff('SOURCE','MISSING')
        target=self.t.read()['tasks']['MISSING']
        self.assertEqual(target['state'],'TODO');self.assertFalse(target['inputs'])

    def test_changed_reviewed_source_blocks_handoff_and_preserves_history(self):
        self.t.register('F','SOURCE','planning','planning','document',[{'id':'AC','required':True,'text':'fixture'}],[])
        self.t.ready('SOURCE');run=self.t.begin('SOURCE','planning')
        self.write('requirements.md','handoff requirements')
        self.t.submit('SOURCE',run['agent_run_id'],['requirements.md'],'requirements')
        review=self.t.begin('SOURCE','verification',review=True)
        self.t.review('SOURCE',review['agent_run_id'],[{'criterion_id':'AC','result':'PASS','evidence':'requirements.md'}],'review')
        prior=copy.deepcopy(self.t.read()['tasks']['SOURCE'])
        frozen=prior['outputs'][0]
        # The ordinary helper deliberately writes a different working baseline.
        # That is an actual source change, not a reason to weaken handoff gates.
        self.register_code()
        self.edit_task('AUTO',lambda t:t.update(dependencies=['SOURCE']))
        with self.assertRaisesRegex(ValueError,'requires recheck'):
            self.t.handoff('SOURCE','AUTO')
        state=self.t.read();source=state['tasks']['SOURCE'];target=state['tasks']['AUTO']
        self.assertEqual(source['state'],'DONE')
        self.assertEqual(source['reviews'],prior['reviews'])
        self.assertEqual(source['reviews'][-1]['results'][0]['result'],'PASS')
        self.assertEqual(source['validation_status'][review['agent_run_id']]['state'],'RECHECK_REQUIRED')
        self.assertEqual(source['outputs'],prior['outputs'])
        self.assertTrue(self.t._valid_artifact(frozen))
        self.assertEqual((self.root/frozen['snapshot']).read_text(),'handoff requirements')
        self.assertEqual(target['state'],'TODO')
        self.assertFalse(target['handoffs'])


if __name__ == '__main__':
    unittest.main()
