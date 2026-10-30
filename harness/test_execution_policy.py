import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from harness.tasks import Tasks
from harness.execution_plan import register
from harness.decisions import digest
from harness.execution_policy import WorkerGate, managed_command

SESSION = '00000000-0000-4000-8000-000000000001'


class ExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.native = self.home / '.codex/sessions/root.jsonl'
        self.native.parent.mkdir(parents=True)
        self.records = [{'type': 'session_meta', 'payload': {'id': SESSION, 'source': 'cli'}}]
        self.write_native()
        self.addCleanup(patch.stopall)
        patch('harness.decisions.native_store', return_value=self.native.parent).start()
        (self.root / 'scope.md').write_text('approved scope')
        self.m = Tasks(self.root, 'run')
        register(self.m, 'HARNESS_IMPROVEMENT', 'local_change_validation', 'goal',
                 [self.step('T'), self.step('D', ['T']), self.step('U')], 'scope.md')

    def step(self, tid, deps=None):
        return dict(feature_id='F', task_id=tid, role='improvement', title=tid,
                    scope='scope', criteria=[dict(id='C', required=True, description='check')],
                    inputs=['scope.md'], dependencies=deps or [], execution_scope='documentation', max_attempts=3)

    def write_native(self):
        self.native.write_text(''.join(json.dumps(r) + '\n' for r in self.records))

    def activate(self, active=None):
        self.m.configure_execution_policy(str(self.native), SESSION, grandfather_active_ids=active)

    def plan(self, tid='T'):
        fields = dict(completion_criteria=['verified'], inputs=['scope'], outputs=['artifact'], verification=['unittest'])
        return self.m.configure_task_plan(tid, dict(version=1, owner='improvement', whole_plan_task_id=tid,
                  steps=[dict(id='S', action='do work', **fields)], **fields), 'registered before work')

    def question(self, qid='Q', affected=None, options=None, **extra):
        return self.m.open_question(qid, 'Choose the policy', affected or ['T'],
                                   options or [{'id': 'yes', 'label': 'Apply strict policy'}], **extra)

    def reply(self, text):
        event = {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': text}}
        user = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                  'content': [{'type': 'input_text', 'text': text}]}}
        self.records.extend([event, user]); self.write_native()
        return dict(record_ordinal=len(self.records) - 1, payload_sha256=digest(event['payload']),
                    user_input_record_ordinal=len(self.records), user_input_payload_sha256=digest(user['payload']))

    def test_opt_in_and_legacy_unstarted_cannot_bypass(self):
        self.m.ready('T')
        self.activate()
        with self.assertRaisesRegex(ValueError, 'detailed work plan'):
            self.m.begin('T', 'improvement')
        self.plan(); run = self.m.begin('T', 'improvement')
        self.assertTrue(run)
        with self.assertRaises(ValueError):
            self.m.configure_execution_policy(str(self.native), SESSION)

    def test_ready_direct_cli_and_custom_role_dispatch_require_plan(self):
        self.activate()
        with self.assertRaisesRegex(ValueError, 'detailed work plan'):
            self.m.ready('T')
        from harness.roles import Roles
        role = Roles.__new__(Roles); role.tasks = self.m; role.root = self.root
        with patch('harness.roles.subprocess.Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'detailed work plan'):
                role.execute('T', 'improvement', worker=['echo'])
            spawn.assert_not_called()
        data = self.root / 'args.json'; data.write_text(json.dumps({'task_id': 'T'}))
        proc = subprocess.run([sys.executable, '-m', 'harness.tasks', '--root', str(self.root),
                               '--run-id', 'run', 'ready', '--data', str(data)], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('detailed work plan', proc.stderr)
        from harness.qa import QA
        from harness.delegation import Development
        for cls, role in [(QA, 'verification'), (Development, 'development')]:
            manager = cls.__new__(cls); manager.tasks = self.m; manager.root = self.root
            worker = unittest.mock.Mock()
            with self.assertRaisesRegex(ValueError, 'detailed work plan'):
                manager.execute('T', worker=worker)
            worker.assert_not_called()

    def test_plan_schema_and_membership(self):
        self.activate()
        self.m.register(**self.step('OUT'))
        with self.assertRaisesRegex(ValueError, 'member'):
            self.plan('OUT')
        self.plan(); self.m.ready('T')
        with self.assertRaises(ValueError):
            self.m.configure_task_plan('U', {'version': 1}, 'missing fields')

    def test_question_blocks_active_and_dependents_but_not_unrelated(self):
        self.activate(); self.plan(); self.plan('U'); self.m.ready('T')
        aid = self.m.begin('T', 'improvement')['agent_run_id']
        self.question()
        state = self.m.read()
        self.assertEqual(state['tasks']['T']['state'], 'BLOCKED')
        self.assertEqual(state['tasks']['D']['state'], 'BLOCKED')
        self.assertTrue(state['tasks']['T']['executions'][0]['checkpoint'])
        for action in [lambda: self.m.resume('T', aid, 'scope.md'),
                       lambda: self.m.submit('T', aid, ['scope.md'], 'done'),
                       lambda: self.m.require_dispatch('T')]:
            with self.assertRaisesRegex(ValueError, 'human answer'):
                action()
        self.m.ready('U'); self.m.begin('U', 'improvement')

    def test_idless_actual_native_choice_and_no_reuse(self):
        self.activate(); self.question()
        proof = self.reply('Apply strict policy')
        answer = self.m.answer_question('Q', **proof)
        self.assertEqual(answer['status'], 'ANSWERED')
        self.question('Q2')
        with self.assertRaises(ValueError): self.m.answer_question('Q2', **proof)

    def test_actual_app_user_message_and_structured_prompt_binding(self):
        self.activate(); self.question()
        call = {'type': 'response_item', 'payload': {'type': 'function_call',
                'name': 'request_user_input_async', 'call_id': 'call_real',
                'arguments': json.dumps({'questions': [{'title': 'Choose the policy',
                    'options': ['Apply strict policy']}]})}}
        self.records.append(call)
        item_id = json.dumps(['request_user_input_async', 'call_real', 0], separators=(',', ':'))
        text = '<send_user_message_question_reply>\n' + json.dumps([{'answer': 'Apply strict policy',
                'question': 'Choose the policy', 'questionItemId': item_id}]) + '\n</send_user_message_question_reply>'
        proof = self.reply(text)
        # Actual app emits the companion after response_item and uses item_completed.
        user, event = self.records[-1], {'type': 'event_msg', 'payload': {'type': 'item_completed',
                    'thread_id': SESSION, 'turn_id': 'turn', 'item': {'type': 'UserMessage',
                    'id': 'message', 'content': [{'type': 'text', 'text': text}]}}}
        self.records[-2:] = [user, event]; self.write_native()
        proof = dict(record_ordinal=len(self.records), payload_sha256=digest(event['payload']),
                     user_input_record_ordinal=len(self.records)-1, user_input_payload_sha256=digest(user['payload']))
        result = self.m.answer_question('Q', **proof)
        self.assertEqual(result['status'], 'ANSWERED')
        self.assertEqual(result['answer']['structured_prompt']['question_item_id'], item_id)

    def test_new_dependency_after_question_cannot_bypass(self):
        self.activate(); self.question()
        self.m.register(**self.step('LATE', ['T']))
        with self.assertRaisesRegex(ValueError, 'human answer'):
            self.m.require_dispatch('LATE')
        self.m.register(**self.step('QA'));self.m.register(**self.step('REPAIR'))
        self.m._mutate('synthetic_qa_repair_links',lambda s:s['tasks']['QA'].update(qa_config={'target_task_id':'T','repair_task_id':'REPAIR'}))
        with self.assertRaisesRegex(ValueError,'human answer'):
            self.m.require_dispatch('REPAIR')
        self.assertEqual(self.m.read()['tasks']['REPAIR']['state'],'BLOCKED')

    def test_multiple_structured_items_in_one_human_reply_have_distinct_provenance(self):
        self.activate(); self.question()
        self.m.open_question('Q2', 'Choose another policy', ['U'], [{'id': 'yes', 'label': 'Apply strict policy'}])
        questions = [{'title': title, 'options': ['Apply strict policy']}
                     for title in ('Choose the policy', 'Choose another policy')]
        self.records.append({'type':'response_item','payload':{'type':'function_call',
            'name':'functions.request_user_input_async','call_id':'call_multi',
            'arguments':json.dumps({'questions':questions})}})
        replies = [{'answer':'Apply strict policy','question':q['title'],
                    'questionItemId':json.dumps(['request_user_input_async','call_multi',i])}
                   for i,q in enumerate(questions)]
        proof=self.reply('<send_user_message_question_reply>\n'+json.dumps(replies)+'\n</send_user_message_question_reply>')
        self.assertEqual(self.m.answer_question('Q',**proof)['status'],'ANSWERED')
        self.assertEqual(self.m.answer_question('Q2',**proof)['status'],'ANSWERED')

    def test_fabricated_logger_user_event_has_no_native_answer_authority(self):
        self.activate(); self.question()
        self.m.logger.append('session_message','run',observed={'role':'user','text':'Apply strict policy'},
                             source={'kind':'codex_session_import','session_id':SESSION,'line':999})
        with self.assertRaisesRegex(ValueError,'actually received'):
            self.m.answer_question('Q',record_ordinal=999,payload_sha256='fabricated',
                user_input_record_ordinal=1000,user_input_payload_sha256='fabricated')
        self.assertEqual(self.m.question_status()['Q']['status'],'OPEN')

    def test_new_run_requires_immutable_own_binding(self):
        self.activate(); self.plan()
        later = Tasks(self.root, 'later-run')
        with self.assertRaisesRegex(ValueError, 'bind the current run'):
            later.ready('T')
        later.bind_execution_session(str(self.native), SESSION)
        # A distinct run still needs its own explicit whole-plan connection.
        with self.assertRaisesRegex(ValueError, 'membership'):
            later.ready('T')
        from harness.execution_plan import attach_existing
        attach_existing(later, ['T'], 'HARNESS_IMPROVEMENT', 'local_change_validation',
                        'explicit continuation', 'scope.md', 'same task, new run')
        with self.assertRaisesRegex(ValueError, 'detailed work plan'):
            later.ready('T')
        later.configure_task_plan('T', self.m.read()['tasks']['T']['work_plan'], 'explicit current-run reconfirmation')
        later.ready('T'); run = later.begin('T', 'improvement')
        self.assertEqual(run['execution_contract']['run_id'], 'later-run')
        other = self.native.with_name('other.jsonl'); other.write_bytes(self.native.read_bytes())
        with self.assertRaisesRegex(ValueError, 'immutable'):
            later.bind_execution_session(str(other), SESSION)
        self.question()
        self.assertEqual(self.m.answer_question('Q', **self.reply('Apply strict policy'))['status'], 'ANSWERED')

    def test_managed_failure_preserves_question_checkpoint_until_explicit_cancel(self):
        self.activate(); self.plan(); self.m.ready('T')
        aid = self.m.begin('T', 'improvement')['agent_run_id']; self.question()
        self.m.fail('T', aid, 'owned worker interrupted')
        self.assertIsNone(self.m.read()['tasks']['T']['executions'][0]['ended_at'])
        self.m.fail('T', aid, 'operator cancels paused attempt', cancel_question_wait=True)
        self.assertIsNotNone(self.m.read()['tasks']['T']['executions'][0]['ended_at'])

    def test_review_can_resume_after_required_answer(self):
        self.activate(); self.plan(); self.m.ready('T')
        aid = self.m.begin('T', 'improvement')['agent_run_id']
        self.m.submit('T', aid, ['scope.md'], 'ready for independent review')
        review = self.m.begin('T', 'verification', review=True)['agent_run_id']
        self.question()
        with self.assertRaisesRegex(ValueError, 'human answer'):
            self.m.resume('T', review, 'scope.md')
        self.m.answer_question('Q', **self.reply('Apply strict policy'))
        self.m.resume('T', review, 'scope.md')
        self.assertEqual(self.m.read()['tasks']['T']['state'], 'IN_REVIEW')

    def test_prior_logger_fake_hash_and_ambiguous_answers_rejected(self):
        prior = self.reply('Apply strict policy')
        self.activate(); self.question()
        with self.assertRaises(ValueError): self.m.answer_question('Q', **prior)
        proof = self.reply('Apply strict policy'); bad = dict(proof, payload_sha256='fake')
        with self.assertRaises(ValueError): self.m.answer_question('Q', **bad)
        self.question('Q2', affected=['U'])
        proof = self.reply('Apply strict policy')
        with self.assertRaisesRegex(ValueError, 'uniquely'):
            self.m.answer_question('Q', **proof)
        self.assertEqual(self.m.question_status()['Q']['status'], 'OPEN')

    def test_freeform_and_injected_message_do_not_answer(self):
        self.activate(); self.question(answer_mode='FREEFORM')
        self.assertEqual(self.m.answer_question('Q', **self.reply('I think yes'))['status'], 'OPEN')
        with self.assertRaises(ValueError):
            self.m.answer_question('Q', **self.reply('Message Type: MESSAGE\nApply strict policy'))

    def test_subagent_and_env_store_are_rejected(self):
        self.records[0]['payload']['source'] = {'subagent': {'parent_thread_id': SESSION}}
        self.write_native()
        with self.assertRaises(ValueError): self.activate()
        outside = self.root / 'fake.jsonl'; outside.write_bytes(self.native.read_bytes())
        with patch.dict('os.environ', {'CODEX_HOME': str(self.root)}):
            with self.assertRaises(ValueError):
                self.m.configure_execution_policy(str(outside), SESSION)

    def test_grandfather_current_attempt_only_and_new_question_still_blocks(self):
        self.m.ready('T'); aid = self.m.begin('T', 'improvement')['agent_run_id']
        self.activate([aid])
        self.m.checkpoint('T', aid, 'pause', 'scope.md')
        self.m.resume('T', aid, 'scope.md')
        with self.assertRaisesRegex(ValueError, 'detailed work plan'):
            self.m.require_dispatch('T')
        self.question()
        with self.assertRaisesRegex(ValueError, 'human answer'):
            self.m.submit('T', aid, ['scope.md'], 'done')

    def test_worker_cache_is_readonly_and_owned_process_stops(self):
        self.activate(); self.plan(); self.m.ready('T'); self.m.begin('T','improvement')
        watch = WorkerGate(self.m, 'T')
        with patch.object(self.m, 'read', side_effect=AssertionError('mutating read forbidden')):
            watch.check(); watch.check()
        def ask():
            time.sleep(.3); self.question()
        thread = threading.Thread(target=ask); thread.start()
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            managed_command(self.m, 'T', [sys.executable, '-c', 'import time; time.sleep(20)'], self.root, 30)
        thread.join(); self.assertLess(time.monotonic() - started, 5)

    def test_direct_managed_command_needs_plan_and_question_interrupts_descendants(self):
        self.activate()
        with self.assertRaisesRegex(ValueError, 'explicit planned task'):
            self.m.logger.command('run', ['rtk', 'proxy', 'echo', 'no'])
        with self.assertRaisesRegex(ValueError, 'detailed work plan'):
            self.m.logger.command('run', ['rtk', 'proxy', 'echo', 'no'], task_id='T')
        self.plan(); self.m.ready('T'); self.m.begin('T','improvement')
        marker = self.root / 'descendant.txt'
        descendant = 'import pathlib,time;time.sleep(1);pathlib.Path(' + repr(str(marker)) + ').write_text("escaped")'
        parent = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",' + repr(descendant) + ']);time.sleep(20)'
        def ask():
            time.sleep(.3); self.question()
        thread = threading.Thread(target=ask); thread.start()
        with self.assertRaisesRegex(ValueError, 'interrupted'):
            managed_command(self.m, 'T', [sys.executable, '-c', parent], self.root, 30)
        thread.join(); time.sleep(1.1)
        self.assertFalse(marker.exists())

    def test_nonexistent_done_and_unstarted_task_cannot_spawn_managed_command(self):
        self.activate(); self.plan()
        with patch('harness.execution_policy.subprocess.Popen') as spawn:
            for tid,reason in [('MISSING','existing task'),('T','active unblocked')]:
                with self.assertRaisesRegex(ValueError,reason):
                    managed_command(self.m,tid,[sys.executable,'-c','print(123)'],self.root)
            self.m._mutate('synthetic_historical_done',lambda s:s['tasks']['T'].update(state='DONE'))
            with self.assertRaisesRegex(ValueError,'completed task history'):
                managed_command(self.m,'T',[sys.executable,'-c','print(456)'],self.root)
            spawn.assert_not_called()
        self.assertEqual(self.m.read()['tasks']['T']['state'],'DONE')
        self.assertEqual(self.m.report()['tasks']['T']['execution_gate']['start_status'],'BLOCKED')

    def test_role_interrupt_kills_term_ignoring_pipe_detached_descendant(self):
        self.activate(); self.plan(); self.m.ready('T')
        aid=self.m.begin('T','improvement')['agent_run_id']
        from harness.roles import Roles
        role=Roles.__new__(Roles);role.tasks=self.m;role.root=self.root
        directory=self.root/'.harness/fake';directory.mkdir(parents=True)
        (directory/'context.json').write_text('test context')
        ready=self.root/'child-ready';marker=self.root/'escaped-marker'
        descendant='import os,pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);os.close(1);os.close(2);pathlib.Path('+repr(str(ready))+').write_text("ready");time.sleep(1);pathlib.Path('+repr(str(marker))+').write_text("escaped")'
        parent='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(descendant)+']);time.sleep(20)'
        def ask():
            deadline=time.monotonic()+5
            while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.question()
        thread=threading.Thread(target=ask);thread.start()
        prepared={'task_id':'T','agent_run_id':aid,'context':'.harness/fake/context.json'}
        with patch.object(role,'prepare',return_value=prepared):
            with self.assertRaisesRegex(ValueError,'human answer pending'):
                role.execute('T','improvement',worker=[sys.executable,'-c',parent],timeout=5)
        thread.join();time.sleep(1.1)
        self.assertFalse(marker.exists())

    def test_native_runtime_interrupt_kills_term_ignoring_pipe_detached_descendant(self):
        self.activate();self.plan();self.m.ready('T')
        aid=self.m.begin('T','improvement')['agent_run_id']
        from harness.delegation_runtime import run_codex
        ready=self.root/'native-ready';marker=self.root/'native-escaped'
        descendant='import os,pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);os.close(1);os.close(2);pathlib.Path('+repr(str(ready))+').write_text("ready");time.sleep(1);pathlib.Path('+repr(str(marker))+').write_text("escaped")'
        worker=self.root/'native-worker.py'
        worker.write_text('#!'+sys.executable+'\nimport subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",'+repr(descendant)+'])\ntime.sleep(20)\n')
        worker.chmod(0o700)
        def ask():
            deadline=time.monotonic()+5
            while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
            self.question()
        thread=threading.Thread(target=ask);thread.start()
        result=run_codex(self.m,'T',aid,self.root,{},self.root/'native-result',str(worker),5)
        thread.join();time.sleep(1.1)
        self.assertIn('human answer pending',result['error'])
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
