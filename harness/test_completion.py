"""Synthetic completion contracts; no model/API process is executed."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from harness.tasks import Tasks
from harness.logging import Logger
from harness.usage_collection import register


class CompletionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('input.md', 'output.md', 'review.md', 'AGENTS.md'):
            (self.root / name).write_text('SYNTHETIC ' + name)
        self.logger = Logger(self.root)
        self.run = self.logger.start('HARNESS_IMPROVEMENT', 'orchestrator', 'synthetic completion tests')
        self.manager = Tasks(self.root, self.run)

    def task(self, tid='T', configured=True, usage=True, context=True, mode='current_agent'):
        self.manager.register('F', tid, 'planning', 'completion test', 'synthetic documents',
                              [{'id': 'AC', 'required': True}], ['input.md'], execution_scope='documentation')
        if configured:
            self.manager.configure_completion(tid, ['AGENTS.md'], usage, context,
                                              exception_reason='synthetic non-model/local check exception' if not usage or not context else None)
        self.manager.ready(tid)
        work = self.manager.begin(tid, 'planning', execution_mode=mode)
        self.manager.submit(tid, work['agent_run_id'], ['output.md'], 'synthetic work')
        return work

    def usage(self, work, tid='T', session='s', turn='t', response='r', amount=10, registration=True):
        if registration:
            register(self.manager, tid, work['agent_run_id'], session, turn_id=turn)
        self.logger.append('model_usage', self.run, task_id=tid, agent_run_id=work['agent_run_id'],
                           source={'kind': 'SYNTHETIC', 'session_id': session},
                           observed={'response_id': response, 'turn_id': turn, 'usage_semantics': 'per_response_increment',
                                     'model': 'synthetic', 'usage': {'input_tokens': amount, 'cached_input_tokens': 0,
                                                                 'output_tokens': 2, 'total_tokens': amount + 2}})
        self.manager.bind_usage(tid, work['agent_run_id'], session, response, 'synthetic exact attribution')

    def context(self, work, tid='T', accepted=True, result='NO_CHANGE', **extra):
        report = {'task_id': tid, 'work_execution_id': work['agent_run_id'],
                  'context_paths': [{'path': 'AGENTS.md', 'sha256': hashlib.sha256((self.root/'AGENTS.md').read_bytes()).hexdigest()}],
                  'maintainer': {'result': result, 'reason': 'existing instructions already describe this task',
                                 'independence': 'agent_declared', 'proposals': ['future improvement needs main review']},
                  'main_review': {'accepted': accepted, 'reason': 'main checked the current instruction content'}, **extra}
        (self.root / 'maintenance.json').write_text(json.dumps(report))
        return self.manager.record_context_maintenance(tid, work['agent_run_id'], 'maintenance.json')

    def review(self, tid='T', result='PASS'):
        review = self.manager.begin(tid, 'verification', review=True)
        return self.manager.review(tid, review['agent_run_id'],
                                   [{'criterion_id': 'AC', 'result': result, 'evidence': 'review.md'}], 'synthetic review')

    def test_missing_usage_blocks_required_pass_and_records_unknown(self):
        work = self.task(); self.context(work)
        with self.assertRaisesRegex(ValueError, 'usage UNKNOWN'):
            self.review()
        self.assertEqual(self.manager.read()['tasks']['T']['state'], 'IN_REVIEW')
        event = self.logger.read()[-1]
        self.assertEqual(event['event_type'], 'task_action_rejected')
        self.assertIn('UNKNOWN', event['observed']['reason'])

    def test_legacy_parent_session_with_child_native_thread_cannot_complete(self):
        work = self.task(context=False)
        self.usage(work)
        self.logger.append('model_usage', self.run, task_id='T', agent_run_id=work['agent_run_id'],
                           source={'kind': 'SYNTHETIC', 'session_id': 's'},
                           observed={'thread_id': 'native-child', 'response_id': 'r', 'turn_id': 't',
                                     'usage_semantics': 'per_response_increment', 'model': 'synthetic',
                                     'usage': {'input_tokens': 10, 'cached_input_tokens': 0,
                                               'output_tokens': 2, 'total_tokens': 12}})
        with self.assertRaisesRegex(ValueError, 'native thread identity conflict'):
            self.review()

    def test_pending_turn_and_missing_binding_block(self):
        work = self.task(context=False)
        register(self.manager, 'T', work['agent_run_id'], 's', turn_id='pending')
        with self.assertRaisesRegex(ValueError, 'missing bound|pending'):
            self.review()

    def test_bound_usage_without_registration_rejected(self):
        work = self.task(context=False); self.usage(work, registration=False)
        with self.assertRaisesRegex(ValueError, 'registration'):
            self.review()

    def test_mismatched_turn_binding_rejected(self):
        work = self.task(context=False); self.usage(work)
        path = self.root / '.harness/usage/sessions.jsonl'
        entry = json.loads(path.read_text()); entry['turn_id'] = 'other-turn'; path.write_text(json.dumps(entry)+'\n')
        with self.assertRaisesRegex(ValueError, 'pending|mismatched'):
            self.review()

    def test_ambiguous_registration_or_conflicting_original_usage_rejects(self):
        for conflict in ('owner', 'values'):
            with self.subTest(conflict=conflict):
                tid='T'+conflict; work=self.task(tid, context=False); self.usage(work, tid, session=tid)
                if conflict == 'owner':
                    other=self.task('OTHER', configured=False)
                    register(self.manager, 'OTHER', other['agent_run_id'], tid, turn_id='t')
                else:
                    self.logger.append('model_usage', self.run, source={'session_id':tid},
                                       observed={'response_id':'r', 'turn_id':'t', 'usage_semantics':'per_response_increment',
                                                 'usage':{'input_tokens':999,'cached_input_tokens':0,'output_tokens':2,'total_tokens':1001}})
                with self.assertRaisesRegex(ValueError, 'ambiguous|conflicting'):
                    self.review(tid)

    def test_invalid_usage_is_unknown_not_zero(self):
        work=self.task(context=False); self.usage(work, amount=-3)
        with self.assertRaisesRegex(ValueError, 'UNKNOWN.*invalid'):
            self.review()

    def test_registered_unbound_response_is_not_silently_omitted(self):
        work=self.task(context=False);self.usage(work)
        self.logger.append('model_usage', self.run, source={'session_id':'s'}, observed={'response_id':'unbound','turn_id':'t'})
        with self.assertRaisesRegex(ValueError, 'missing or mismatched'):
            self.review()

    def test_explicit_response_list_pending_member_blocks(self):
        work=self.task(context=False);self.usage(work)
        register(self.manager,'T',work['agent_run_id'],'s',response_ids=['r','not-yet-collected'])
        with self.assertRaisesRegex(ValueError,'explicit registered response still pending'):
            self.review()

    def test_conflicting_native_task_identity_rejects(self):
        work=self.task(context=False);self.usage(work)
        self.logger.append('model_usage',self.run,task_id='OTHER',agent_run_id=work['agent_run_id'],
                           source={'session_id':'s'},observed={'response_id':'r','turn_id':'t','usage_semantics':'per_response_increment',
                           'model':'synthetic','usage':{'input_tokens':10,'cached_input_tokens':0,'output_tokens':2,'total_tokens':12}})
        with self.assertRaisesRegex(ValueError,'conflicting execution'):
            self.review()

    def test_no_change_and_updated_context_with_reason_are_accepted(self):
        for outcome in ('NO_CHANGE','UPDATED'):
            work=self.task(outcome);self.usage(work,outcome,session=outcome);receipt=self.context(work,outcome,result=outcome)
            self.assertEqual(receipt['independence'],'agent_declared')
            self.assertEqual(self.review(outcome),'DONE')

    def test_stale_context_hash_blocks(self):
        work=self.task(usage=False);self.context(work)
        (self.root/'AGENTS.md').write_text('changed after main review')
        with self.assertRaisesRegex(ValueError,'stale context hash'):
            self.review()

    def test_maintenance_proposals_are_not_main_approval(self):
        work=self.task(usage=False);self.context(work,accepted=False)
        with self.assertRaisesRegex(ValueError,'separate main accepted'):
            self.review()

    def test_context_identity_and_missing_reason_rejected(self):
        work=self.task(usage=False)
        with self.assertRaisesRegex(ValueError,'mismatch'):
            self.context(work,task_id='OTHER')
        with self.assertRaisesRegex(ValueError,'reason'):
            self.context(work,maintainer={'result':'NO_CHANGE','reason':'','independence':'agent_declared'})

    def test_no_context_evidence_for_local_check_needs_declared_exception(self):
        self.manager.register('F','T','planning','local check','test',[{'id':'AC','required':True}],['input.md'])
        with self.assertRaisesRegex(ValueError,'exception_reason'):
            self.manager.configure_completion('T',[],usage_required=False,context_required=False)
        self.manager.configure_completion('T',[],False,False,'non-model deterministic local check')
        self.manager.ready('T');work=self.manager.begin('T','planning',execution_mode='local_check')
        self.manager.submit('T',work['agent_run_id'],['output.md'],'check complete')
        self.assertEqual(self.review(),'DONE')

    def test_legacy_task_and_failed_review_unchanged(self):
        self.task(configured=False);self.assertEqual(self.review(),'DONE')
        self.task('FAIL');self.assertEqual(self.review('FAIL',result='FAIL'),'BLOCKED')

    def test_configuration_cannot_be_added_during_execution(self):
        work=self.task(configured=False)
        with self.assertRaisesRegex(ValueError,'inactive TODO/READY'):
            self.manager.configure_completion('T',['AGENTS.md'])

    def test_report_is_frozen_without_rereading_mutable_report(self):
        work=self.task(usage=False);self.context(work)
        report=json.loads((self.root/'maintenance.json').read_text());report['main_review']['accepted']=False
        (self.root/'maintenance.json').write_text(json.dumps(report))
        self.assertEqual(self.review(),'DONE')  # Frozen receipt was accepted and still hashes current docs.

    def test_receipt_cannot_be_a_configured_context_path(self):
        self.manager.register('F','T','planning','recursive report','synthetic',[{'id':'AC','required':True}],['input.md'])
        (self.root/'maintenance.json').write_text('{}')
        self.manager.configure_completion('T',['maintenance.json'],usage_required=False,exception_reason='local fixture')
        self.manager.ready('T');work=self.manager.begin('T','planning')
        with self.assertRaisesRegex(ValueError,'recursively'):
            self.manager.record_context_maintenance('T',work['agent_run_id'],'maintenance.json')

    def test_done_receipt_cannot_be_replaced(self):
        work=self.task(usage=False);self.context(work)
        self.assertEqual(self.review(),'DONE')
        before=copy.deepcopy(self.manager.read()['tasks']['T']['context_maintenance'])
        with self.assertRaisesRegex(ValueError,'completed evidence is immutable'):
            self.context(work,accepted=False)
        self.assertEqual(self.manager.read()['tasks']['T']['context_maintenance'],before)

    def test_old_attempt_cannot_replace_current_receipt(self):
        work=self.task(usage=False)
        # A synthetic later current attempt; no execution/model process is claimed.
        state=json.loads(self.manager.path.read_text());task=state['tasks']['T']
        newer=copy.deepcopy(task['executions'][-1]);newer['agent_run_id']='later-synthetic-attempt'
        task['executions'].append(newer);self.manager.path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'current latest work'):
            self.context(work)

    def test_attribution_quarantine_is_not_treated_as_bound_success(self):
        work=self.task(context=False);self.usage(work)
        p=self.root/'.harness/usage/attribution-limits.jsonl';p.write_text(json.dumps({'session_id':'s','response_id':'r','reason':'existing_binding_conflict'})+'\n')
        with self.assertRaisesRegex(ValueError,'unresolved attribution conflict'):
            self.review()

    def test_unsafe_or_duplicate_context_paths_are_rejected(self):
        self.manager.register('F','T','planning','paths','synthetic',[{'id':'AC','required':True}],['input.md'])
        for paths in (['../outside'],['AGENTS.md','AGENTS.md'],[]):
            with self.subTest(paths=paths),self.assertRaises(ValueError):
                self.manager.configure_completion('T',paths)



class CompletionPolicyTests(unittest.TestCase):
    setUp = CompletionTests.setUp
    task = CompletionTests.task
    usage = CompletionTests.usage
    context = CompletionTests.context
    review = CompletionTests.review

    def policy(self, **updates):
        policy={'version':1,'apply_to_work_types':['HARNESS_BUILD'],
                'context_paths':['AGENTS.md'],'usage_required':True,'context_required':True}
        policy.update(updates)
        path=self.root/'.harness/completion-policy.json'
        path.write_text(json.dumps(policy))
        return policy

    def test_project_policy_inherits_and_missing_usage_blocks(self):
        self.policy();work=self.task(configured=False)
        task=self.manager.read()['tasks']['T'];config=task['completion_contract']
        self.assertEqual(config['configuration_source'],'project_policy')
        self.assertEqual(config['context_paths'],['AGENTS.md'])
        self.assertEqual(config['policy']['sha256'],hashlib.sha256((self.root/'.harness/completion-policy.json').read_bytes()).hexdigest())
        self.context(work)
        with self.assertRaisesRegex(ValueError,'usage UNKNOWN'):
            self.review()

    def test_absent_policy_preserves_legacy_and_excluded_type_is_not_configured(self):
        self.task(configured=False);self.assertEqual(self.review(),'DONE')
        self.policy(apply_to_work_types=['PRODUCT'])
        self.task('OTHER',configured=False)
        self.assertNotIn('completion_contract',self.manager.read()['tasks']['OTHER'])
        self.assertEqual(self.review('OTHER'),'DONE')

    def test_malformed_unknown_policy_rejects_without_partial_task(self):
        policies=[{'version':2},{'unknown_setting':True},{'usage_required':'true'},
                  {'apply_to_work_types':['NOT_A_WORK_TYPE']},{'context_paths':['AGENTS.md','AGENTS.md']}]
        for index,updates in enumerate(policies):
            with self.subTest(updates=updates):
                self.policy(**updates)
                with self.assertRaises(ValueError):self.task('BAD'+str(index),configured=False)
                self.assertNotIn('BAD'+str(index),self.manager.read()['tasks'])
        (self.root/'.harness/completion-policy.json').write_text('{broken')
        with self.assertRaisesRegex(ValueError,'invalid completion policy JSON'):
            self.task('BROKEN',configured=False)
        self.assertNotIn('BROKEN',self.manager.read()['tasks'])

    def test_changed_policy_does_not_relabel_existing_contract(self):
        self.policy();work=self.task(configured=False)
        old=copy.deepcopy(self.manager.read()['tasks']['T']['completion_contract'])
        self.policy(context_paths=['review.md'])
        self.assertEqual(self.manager.read()['tasks']['T']['completion_contract'],old)
        self.usage(work);self.context(work)
        self.assertEqual(self.review(),'DONE')
        self.task('NEW',configured=False)
        new=self.manager.read()['tasks']['NEW']['completion_contract']
        self.assertEqual(new['context_paths'],['review.md'])
        self.assertNotEqual(new['policy']['sha256'],old['policy']['sha256'])
        self.assertTrue(self.manager._valid_artifact(old['policy']))

    def test_explicit_override_requires_audited_reason_and_preserves_policy_origin(self):
        self.policy()
        self.manager.register('F','T','planning','maintainer','context maintenance',
                              [{'id':'AC','required':True}],['input.md'])
        with self.assertRaisesRegex(ValueError,'override requires explicit exception_reason'):
            self.manager.configure_completion('T',['AGENTS.md'])
        old=copy.deepcopy(self.manager.read()['tasks']['T']['completion_contract'])
        config=self.manager.configure_completion('T',[],usage_required=True,context_required=False,
                    exception_reason='context maintainer task does not recursively delegate itself')
        self.assertTrue(config['usage_required']);self.assertFalse(config['context_required'])
        self.assertEqual(config['configuration_source'],'explicit_override')
        self.assertEqual(config['policy'],old['policy'])
        event=[e for e in self.logger.read() if e['event_type']=='completion_configured'][-1]
        self.assertEqual(event['observed']['previous_contract'],old)
        self.assertEqual(event['observed']['override_reason'],config['exception_reason'])


if __name__ == '__main__':
    unittest.main()
