"""PR #1 regressions. Synthetic QA/owner claims; real tasks, files and commands."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from harness import test_qa as fixture
from harness import test_qa_repair as repair_fixture
from harness.execution_plan import attach_existing
from harness.qa_repair import execute_with_owner


class QARegressions(unittest.TestCase):
    def setUp(self):
        self.case=fixture.QATest();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root.resolve();self.qa=self.case.qa;self.manager=self.case.m

    def execute(self,**settings):
        self.case.configure(**settings)
        return self.qa.execute('QA',self.case.worker)

    def proof(self,result):return json.loads((self.root/result['report']['path']).read_text())

    def assert_closed_failure(self,result,phase):
        self.assertEqual(result['outcome'],'BLOCKED')
        task=self.manager.read()['tasks']['QA']
        self.assertEqual(task['state'],'BLOCKED')
        self.assertTrue(task['executions'])
        self.assertTrue(all(r.get('ended_at') for r in task['executions']))
        self.assertEqual(task['qa_failures'][-1]['phase'],phase)
        self.assertEqual(task['qa_failures'][-1]['execution_status'],'RECORDED_ENDED')
        self.assertEqual(self.proof(result)['phase'],phase)
        self.assertEqual(task['qa_config']['attempts'][-1]['outcome'],'BLOCKED')

    def test_explicit_generated_outputs_allow_success_but_are_recorded(self):
        argv=[sys.executable,'-c','from pathlib import Path;Path("build").mkdir();Path("build/out.txt").write_text("generated")']
        result=self.execute(commands=[argv],generated_paths=['build'])
        self.assertEqual(result['outcome'],'PASS')
        proof=self.proof(result);self.assertEqual(proof['generated_paths'],['build'])
        self.assertEqual([r['path'] for r in proof['generated_changes']],['build/out.txt'])
        self.assertFalse((self.root/'build').exists())

    def test_build_name_and_gitignore_alone_are_not_authority(self):
        (self.root/'.gitignore').write_text('build/\n')
        argv=[sys.executable,'-c','from pathlib import Path;Path("build").mkdir();Path("build/out").write_text("generated")']
        result=self.execute(commands=[argv])
        self.assertEqual(result['outcome'],'BLOCKED')
        self.assertIn('QA changed product files',str(self.proof(result)['problems']))

    def test_allowed_generated_path_does_not_hide_source_edit(self):
        argv=[sys.executable,'-c','from pathlib import Path;Path("build").mkdir();Path("build/out").write_text("generated");Path("product.txt").write_text("wrong")']
        self.assertEqual(self.execute(commands=[argv],generated_paths=['build'])['outcome'],'BLOCKED')
        self.assertEqual((self.root/'product.txt').read_text(),'hello')

    def test_source_deletion_is_not_hidden_by_generated_exclusion(self):
        argv=[sys.executable,'-c','from pathlib import Path;Path("product.txt").unlink()']
        self.assertEqual(self.execute(commands=[argv],generated_paths=['build'])['outcome'],'BLOCKED')
        self.assertTrue((self.root/'product.txt').is_file())

    def test_generated_path_is_revalidated_against_new_declared_source(self):
        self.case.configure(generated_paths=['build'])
        (self.root/'build').mkdir();(self.root/'build/New.kt').write_text('newly declared source')
        ref=self.manager.artifact('build/New.kt')
        self.manager._mutate('fixture_source_change',lambda s:s['tasks']['QA']['inputs'].append(ref),'QA')
        with self.assertRaises(ValueError):self.qa.execute('QA',self.case.worker)
        self.assertEqual(self.manager.read()['tasks']['QA']['qa_failures'][-1]['phase'],'preflight')

    def test_new_source_declared_during_qa_is_not_hidden_as_generated(self):
        self.case.configure(generated_paths=['build'])
        def worker(w,p):
            (self.root/'build').mkdir();(self.root/'build/New.kt').write_text('new declared source')
            ref=self.manager.artifact('build/New.kt')
            self.manager._mutate('fixture_concurrent_source',lambda s:s['tasks']['TARGET']['inputs'].append(ref),'TARGET')
            return self.case.worker(w,p)
        result=self.qa.execute('QA',worker)
        self.assert_closed_failure(result,'verify_workspace')
        self.assertTrue((self.root/'build/New.kt').exists())

    def test_declared_input_inside_generated_path_is_rejected(self):
        (self.root/'build').mkdir();(self.root/'build/Source.kt').write_text('product source')
        ref=self.manager.artifact('build/Source.kt')
        self.manager._mutate('fixture_input',lambda s:s['tasks']['TARGET']['inputs'].append(ref),'TARGET')
        with self.assertRaisesRegex(ValueError,'source/input/output'):self.case.configure(generated_paths=['build'])

    def test_tracked_source_inside_generated_path_is_rejected(self):
        for argv in [['git','init','-q'],['git','add','product.txt']]:subprocess.run(argv,cwd=self.root,check=True,capture_output=True)
        with self.assertRaises(ValueError):self.case.configure(generated_paths=['.'])
        (self.root/'build').mkdir();(self.root/'build/Tracked.kt').write_text('tracked source')
        subprocess.run(['git','add','build/Tracked.kt'],cwd=self.root,check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'source/input/output'):self.case.configure(generated_paths=['build'])

    def test_generated_path_cannot_escape_or_hide_private_state(self):
        for value in ['.','../outside','/tmp/build','build/*','.harness','build/../src']:
            with self.subTest(path=value),self.assertRaises(ValueError):self.case.configure(generated_paths=[value])

    def test_generated_symlink_does_not_bypass_source_guard(self):
        argv=[sys.executable,'-c','from pathlib import Path;Path("build").mkdir();Path("build/link").symlink_to("../product.txt")']
        self.assertEqual(self.execute(commands=[argv],generated_paths=['build'])['outcome'],'BLOCKED')

    def test_invalid_image_is_rejected_before_begin_and_preserved(self):
        (self.root/'capture.png').write_bytes(b'invalid image')
        self.case.configure(images=['capture.png'])
        with patch('harness.delegation_runtime.run_codex') as worker:
            with self.assertRaisesRegex(ValueError,'image bytes'):self.qa.execute('QA')
            worker.assert_not_called()
        task=self.manager.read()['tasks']['QA']
        self.assertFalse(task['executions']);self.assertEqual(task['state'],'BLOCKED')
        self.assertEqual(task['qa_failures'][-1]['phase'],'preflight')
        self.assertTrue(self.manager._valid_artifact(task['qa_failures'][-1]['report']))

    def test_workspace_preparation_failure_closes_work(self):
        self.case.configure()
        with patch('harness.qa.shutil.copytree',side_effect=OSError('copy failed')):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'prepare_workspace')

    def test_frozen_input_copy_failure_closes_work(self):
        self.case.configure();original=__import__('shutil').copyfile
        def fail(src,dest,*args,**kw):
            if 'frozen-inputs' in str(dest):raise OSError('input materialization failed')
            return original(src,dest,*args,**kw)
        with patch('harness.qa.shutil.copyfile',side_effect=fail):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'materialize_inputs')

    def test_runtime_setup_exception_records_original_cause_not_none_error(self):
        self.case.configure();attach_existing(self.manager,['QA'],'VERIFY','evidence_validation','fixture QA','request.md','explicit test plan')
        with patch('harness.delegation_runtime.run_codex',side_effect=ValueError('runtime preparation failed')):
            result=self.qa.execute('QA')
        self.assertEqual(result['outcome'],'BLOCKED')
        proof=self.proof(result);self.assertIn('runtime preparation failed',str(proof['problems']))
        self.assertNotIn('NoneType',str(proof['problems']))
        self.assertTrue(all(r.get('ended_at') for r in self.manager.read()['tasks']['QA']['executions']))

    def test_command_result_recording_failure_closes_work(self):
        self.case.configure(commands=[[sys.executable,'-c','print("actual command")']]);original=self.manager.logger.append
        def fail(*args,**kw):
            if args and args[0]=='qa_command_finished':raise OSError('command receipt failed')
            return original(*args,**kw)
        # QA and fixture managers share storage but use separate Logger objects.
        self.qa.tasks.logger.append=fail
        result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'commands')

    def test_evidence_copy_failure_closes_work(self):
        self.case.configure();original=__import__('shutil').copyfile
        def fail(src,dest,*args,**kw):
            if '/evidence/' in str(dest):raise OSError('evidence copy failed')
            return original(src,dest,*args,**kw)
        with patch('harness.qa.shutil.copyfile',side_effect=fail):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'result_processing')

    def test_report_write_failure_has_separate_failure_receipt(self):
        self.case.configure();original=Path.write_text
        def fail(path,*args,**kw):
            if path.name=='report.json' and '/failures/' not in str(path):raise OSError('report publish failed')
            return original(path,*args,**kw)
        with patch.object(Path,'write_text',fail):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'publish_report')

    def test_submit_failure_closes_work(self):
        self.case.configure()
        with patch.object(self.qa.tasks,'submit',side_effect=ValueError('submit failed')):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'submit')

    def test_review_failure_closes_review_and_work(self):
        self.case.configure()
        with patch.object(self.qa.tasks,'review',side_effect=ValueError('review failed')):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'review')

    def test_failure_after_review_commit_preserves_pass_but_invalidates_completion(self):
        self.case.configure();original=self.qa.tasks.review
        def fail(*args,**kw):original(*args,**kw);raise OSError('after review commit')
        with patch.object(self.qa.tasks,'review',side_effect=fail):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'review')
        task=self.manager.read()['tasks']['QA'];self.assertEqual(task['reviews'][0]['results'][0]['result'],'PASS')
        self.assertEqual(task['validation_status'][task['reviews'][0]['agent_run_id']]['state'],'RECHECK_REQUIRED')

    def test_attempt_save_failure_is_not_reported_as_pass(self):
        self.case.configure()
        with patch.object(self.qa,'_save',side_effect=ValueError('attempt save failed')):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'save_attempt')

    def test_owner_repair_exception_is_terminal_and_retains_prior_review(self):
        self.case.configure()
        def failed(w,p):r=self.case.worker(w,p);r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK';return r
        def repair(*args):raise ValueError('owner callback failed')
        result=self.qa.execute('QA',failed,repair=repair)
        self.assert_closed_failure(result,'owner_repair')
        self.assertEqual(self.manager.read()['tasks']['QA']['qa_config']['attempts'][0]['prior_outcome'],'REWORK')

    def test_rejected_concurrent_invocation_does_not_close_foreign_work(self):
        self.case.configure();self.manager.ready('QA');run=self.manager.begin('QA','verification')
        with self.assertRaisesRegex(ValueError,'active execution'):self.qa.execute('QA',self.case.worker)
        task=self.manager.read()['tasks']['QA'];self.assertEqual(task['state'],'IN_PROGRESS')
        self.assertIsNone(task['executions'][0]['ended_at'])
        self.assertEqual(task['qa_failures'][-1]['owned_runs'],[])

    def test_interruption_records_failure_then_propagates(self):
        self.case.configure()
        def interrupt(*args):raise KeyboardInterrupt('explicit interruption')
        with self.assertRaises(KeyboardInterrupt):self.qa.execute('QA',interrupt)
        task=self.manager.read()['tasks']['QA'];self.assertEqual(task['state'],'BLOCKED')
        self.assertTrue(all(r['ended_at'] for r in task['executions']))
        self.assertEqual(task['qa_failures'][-1]['phase'],'worker')

    def test_rebase_failure_is_terminal_and_does_not_lose_original_review(self):
        self.case.configure()
        def failed(w,p):r=self.case.worker(w,p);r['criteria'][0]['result']='FAIL';r['recommendation']='REWORK';return r
        def repaired(*args):return {'status':'COMPLETE','evidence':'missing-repair-evidence.txt'}
        result=self.qa.execute('QA',failed,repair=repaired)
        self.assert_closed_failure(result,'rebase')
        self.assertEqual(self.manager.read()['tasks']['QA']['reviews'][0]['results'][0]['result'],'FAIL')

    def test_unpersistable_cleanup_never_returns_success_on_python310_contract(self):
        class LegacyError(Exception):add_note=None
        self.case.configure();original=self.qa.tasks._mutate
        def fail(action,*args,**kw):
            if action=='qa_failure_cleanup':raise OSError('storage unavailable')
            return original(action,*args,**kw)
        with patch('harness.qa.shutil.copytree',side_effect=LegacyError('copy failed')),patch.object(self.qa.tasks,'_mutate',side_effect=fail):
            with self.assertRaises(LegacyError) as error:self.qa.execute('QA',self.case.worker)
        self.assertIsInstance(error.exception.__cause__,OSError)
        self.assertTrue(list((self.root/'.harness/qa/failures').glob('*/report.json')))

    def test_begin_rejection_without_created_execution_does_not_consume_attempt(self):
        self.case.configure()
        with patch.object(self.qa.tasks,'begin',side_effect=ValueError('dispatch never started')):result=self.qa.execute('QA',self.case.worker)
        self.assertEqual(result['outcome'],'BLOCKED');self.assertEqual(result['failure']['execution_status'],'NOT_STARTED')
        task=self.manager.read()['tasks']['QA']
        self.assertEqual(task['executions'],[]);self.assertEqual(task['qa_config']['attempts'],[])

    def test_begin_flush_failure_closes_exact_reserved_execution(self):
        self.case.configure();original=self.qa.tasks.logger.append;failed=[False]
        def fail(*args,**kw):
            if kw.get('event_type')=='agent_run_started' and not failed[0]:failed[0]=True;raise OSError('start event flush failed')
            return original(*args,**kw)
        with patch.object(self.qa.tasks.logger,'append',side_effect=fail):result=self.qa.execute('QA',self.case.worker)
        self.assert_closed_failure(result,'begin')


class OwnerCoverage(unittest.TestCase):
    def setUp(self):
        self.case=repair_fixture.QARepairSafety();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root;self.manager=self.case.manager;self.qa=self.case.qa

    def run_flow(self,links=None,extra=False,after_qa=None):
        self.case.documentation(repair_criteria=links)
        if extra:self.manager._mutate('extra_unreviewed_criterion',lambda s:s['tasks']['DOC-REPAIR']['criteria'].append({'id':'AC-UNREVIEWED','required':True,'text':'unreviewed.txt must exist'}),'DOC-REPAIR')
        attach_existing(self.manager,['QA-DOC'],'VERIFY','evidence_validation','fixture owner review','design.md','explicit test plan')
        count=[0]
        def qa_worker(*args,**kw):
            ws=args[3];(ws/'qa-tools/proof.txt').write_text('observed only original behavior QA-AC')
            count[0]+=1;result='FAIL' if count[0]==1 else 'PASS'
            return {'returncode':0,'result':{'criteria':[{'criterion_id':'QA-AC','result':result,'observation':'original behavior','evidence':'qa-tools/proof.txt'}],'findings':[],'reviewed_issue_ids':[],'recommendation':'REWORK' if result=='FAIL' else 'PASS','summary':'synthetic QA'}}
        original=self.qa.execute
        def execute(*args,**kw):
            result=original(*args,**kw)
            if after_qa:after_qa(result)
            return result
        with patch('harness.delegation_runtime.run_codex',qa_worker),patch('harness.qa_repair.run_codex',self.case.worker),patch.object(self.qa,'execute',side_effect=execute):
            return execute_with_owner(self.qa,'QA-DOC')

    def test_invalid_criterion_ids_are_rejected_at_configuration(self):
        with self.assertRaisesRegex(ValueError,'criterion IDs'):
            self.case.documentation(repair_criteria={'AC-REPAIR':['NOT-A-QA-ID']})

    def test_owner_begin_flush_failure_closes_reserved_owner_run(self):
        original=self.qa.tasks.logger.append;failed=[False]
        def fail(*args,**kw):
            if kw.get('event_type')=='agent_run_started' and kw.get('task_id')=='DOC-REPAIR' and not failed[0]:failed[0]=True;raise OSError('owner start event flush failed')
            return original(*args,**kw)
        with patch.object(self.qa.tasks.logger,'append',side_effect=fail):result=self.run_flow({'AC-REPAIR':['QA-AC']})
        self.assertEqual(result['outcome'],'BLOCKED')
        owner=self.manager.read()['tasks']['DOC-REPAIR']
        self.assertEqual(owner['qa_failures'][-1]['phase'],'owner_begin')
        self.assertEqual(owner['state'],'BLOCKED');self.assertTrue(all(r.get('ended_at') for r in owner['executions']))

    def test_owner_result_publication_failure_is_terminal(self):
        original=Path.write_text
        def fail(path,*args,**kw):
            if '/owner-review/' in str(path):raise OSError('owner proof failed')
            return original(path,*args,**kw)
        with patch.object(Path,'write_text',fail):result=self.run_flow({'AC-REPAIR':['QA-AC']})
        self.assertEqual(result['outcome'],'PASS') # QA evidence remains valid, owner acceptance did not finish.
        self.assertEqual(result['owner_review']['outcome'],'BLOCKED')
        owner=self.manager.read()['tasks']['DOC-REPAIR']
        self.assertEqual(owner['state'],'BLOCKED');self.assertEqual(owner['qa_failures'][-1]['phase'],'owner_result_processing')
        self.assertTrue(all(r.get('ended_at') for r in owner['executions']))

    def test_no_link_does_not_copy_global_pass(self):
        result=self.run_flow();owner=self.manager.read()['tasks']['DOC-REPAIR']
        self.assertEqual(result['outcome'],'PASS');self.assertEqual(owner['state'],'BLOCKED')
        self.assertEqual(owner['reviews'][-1]['results'][0]['result'],'NOT_RUN')

    def test_only_mapped_criteria_with_evidence_pass(self):
        result=self.run_flow({'AC-REPAIR':['QA-AC']},extra=True)
        owner=self.manager.read()['tasks']['DOC-REPAIR'];rows=owner['reviews'][-1]['results']
        self.assertEqual({r['criterion_id']:r['result'] for r in rows},{'AC-REPAIR':'PASS','AC-UNREVIEWED':'NOT_RUN'})
        self.assertEqual(owner['state'],'BLOCKED');self.assertFalse((self.root/'unreviewed.txt').exists())
        proof=json.loads((self.root/rows[0]['evidence']['snapshot']).read_text())
        self.assertEqual(proof['qa_criterion_ids'],['QA-AC']);self.assertTrue(self.manager._valid_artifact(proof['qa_evidence']['QA-AC']))

    def test_complete_mapping_can_finish_with_current_evidence(self):
        result=self.run_flow({'AC-REPAIR':['QA-AC']})
        self.assertEqual(result['owner_review']['outcome'],'DONE')
        self.assertEqual(self.manager.read()['tasks']['DOC-REPAIR']['state'],'DONE')

    def test_changed_owner_output_does_not_inherit_qa_pass(self):
        def change(result):(self.root/'planning.md').write_text('changed after QA')
        result=self.run_flow({'AC-REPAIR':['QA-AC']},after_qa=change)
        self.assertEqual(result['owner_review']['criteria'][0]['result'],'NOT_RUN')

    def test_missing_per_criterion_evidence_does_not_inherit_pass(self):
        def change(result):
            proof=json.loads((self.root/result['report']['snapshot']).read_text());(self.root/proof['evidence_refs']['QA-AC']['snapshot']).unlink()
        result=self.run_flow({'AC-REPAIR':['QA-AC']},after_qa=change)
        self.assertEqual(result['owner_review']['criteria'][0]['result'],'NOT_RUN')

    def test_foreign_owner_is_not_reviewed_or_modified(self):
        def change(result):self.manager._mutate('foreign_owner_scope',lambda s:s['tasks']['DOC-REPAIR'].update(project_id='foreign-project'),'DOC-REPAIR')
        result=self.run_flow({'AC-REPAIR':['QA-AC']},after_qa=change)
        self.assertEqual(result['owner_acceptance'],'NOT_PASSED')
        owner=self.manager.read()['tasks']['DOC-REPAIR']
        self.assertEqual(owner['state'],'IN_REVIEW');self.assertFalse(owner['reviews']);self.assertNotIn('qa_failures',owner)

    def test_changed_mapping_after_qa_requires_new_review(self):
        def change(result):self.manager._mutate('change_mapping',lambda s:s['tasks']['QA-DOC']['qa_config'].update(repair_criteria={}),'QA-DOC')
        result=self.run_flow({'AC-REPAIR':['QA-AC']},after_qa=change)
        self.assertEqual(result['owner_review']['criteria'][0]['result'],'NOT_RUN')

    def test_changed_owner_criterion_definition_requires_new_qa(self):
        def change(result):self.manager._mutate('change_owner_contract',lambda s:s['tasks']['DOC-REPAIR']['criteria'][0].update(text='new unreviewed requirement'),'DOC-REPAIR')
        result=self.run_flow({'AC-REPAIR':['QA-AC']},after_qa=change)
        self.assertEqual(result['owner_review']['criteria'][0]['result'],'NOT_RUN')


if __name__=='__main__':unittest.main()
