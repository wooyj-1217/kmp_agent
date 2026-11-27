"""Synthetic native authority and real commands in disposable repositories."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness.tasks import Tasks
from harness.logging import Logger
from harness.execution_plan import register
from harness.test_lineage_approval_progress import LineageApprovalProgressTests as Authority
from harness.test_execution_policy import ExecutionPolicyTests as Native


class CommandRunContinuationTests(unittest.TestCase):
    question = Authority.question
    approve = Authority.approve
    call = Authority.call
    entry = Authority.entry
    structured = Authority.structured
    reply = Native.reply
    write_native = Native.write_native
    write_code = Authority.write_code

    parent_has_log = True

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.native = self.root / '.harness/native/session.jsonl'
        self.native.parent.mkdir(parents=True)
        self.session = '00000000-0000-4000-8000-000000000811'
        self.records = [{'type':'session_meta','payload':{'id':self.session,'source':'cli'}}]
        self.write_native()
        store = patch('harness.decisions.native_store', return_value=self.native.parent)
        store.start(); self.addCleanup(store.stop)
        for name in ('scope.md', 'technical.md'):
            (self.root / name).write_text('Immutable synthetic source authority')
        (self.root / '.gitignore').write_text('.harness/\n')
        self.git('init', '-q'); self.git('add', 'scope.md', 'technical.md', '.gitignore')
        self.git('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid',
                 'commit','-qm','Synthetic source basis')
        self.logger = Logger(self.root)
        self.parent = (self.logger.start('HARNESS_IMPROVEMENT', 'improvement', 'Synthetic lifecycle')
                       if self.parent_has_log else 'synthetic-plan-run')
        self.m = Tasks(self.root, self.parent)
        register(self.m, 'HARNESS_IMPROVEMENT', 'local_change_validation', 'Synthetic whole flow',
            [dict(feature_id='F',task_id='T',role='improvement',title='Synthetic',scope='src only',
                  criteria=[dict(id='C',required=True)],inputs=['scope.md'],max_attempts=3,
                  work_type='HARNESS_IMPROVEMENT',execution_scope='code_implementation')], 'scope.md')
        self.m.configure_development('T', {'planning':'scope.md'}, code_paths=['src'])
        self.m.configure_execution_policy(str(self.native), self.session)
        fields = dict(completion_criteria=['Commands observed'], inputs=['scope.md'],
                      outputs=['src/First.kt'], verification=['Build and test subprocesses'])
        self.m.configure_task_plan('T',dict(version=1,owner='improvement',whole_plan_task_id='T',
            steps=[dict(id='S',action='Implement and verify',**fields)],**fields),'Synthetic plan')
        self.q = self.question(); self.approve(self.q)
        self.m.ready('T'); self.run = self.m.begin('T', 'improvement')
        self.write_code()

    def git(self, *args):
        return subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True)

    def stop_and_resume(self):
        self.m.checkpoint('T',self.run['agent_run_id'],'Synthetic handoff','scope.md')
        finished = self.logger.checkpoint(self.parent,'Synthetic handoff',finish=True,end_reason='handoff')
        self.m.resume('T',self.run['agent_run_id'],'scope.md')
        return finished

    def command(self, run_id, marker='build'):
        return self.logger.command(run_id,
            ['rtk','proxy',sys.executable,'-c',
             'from pathlib import Path; Path(".harness/'+marker+'.txt").write_text("executed")'],
            task_id='T',agent_run_id=self.run['agent_run_id'],attempt_id=self.run['attempt_id'],
            command_kind='build' if marker=='build' else 'test')

    def continuation(self, previous=None):
        return self.m.continue_command_run('T',self.run['agent_run_id'],
            previous_run_id=previous or self.parent, reason='Continue approved synthetic build/test',
            evidence='scope.md')

    def test_resume_keeps_attempt_but_closed_parent_command_is_rejected(self):
        self.stop_and_resume()
        with self.assertRaisesRegex(ValueError,'run already finished'):
            self.command(self.parent)
        self.assertFalse((self.root/'.harness/build.txt').exists())
        unrelated = self.logger.start('HARNESS_IMPROVEMENT','improvement','Unlinked new run')
        with self.assertRaises(ValueError): self.command(unrelated)
        self.assertFalse((self.root/'.harness/build.txt').exists())

    def test_explicit_continuation_runs_build_and_test_without_changing_authority_or_attempt(self):
        finished = self.stop_and_resume()
        original = copy.deepcopy(self.m.read()['required_questions'])
        native = self.native.read_bytes()
        record = self.continuation()
        self.assertEqual(self.command(record['command_run_id']),0)
        self.assertEqual(self.command(record['command_run_id'],'test'),0)
        state = self.m.read(); run = state['tasks']['T']['executions'][0]
        self.assertEqual(state['required_questions'],original)
        self.assertEqual(self.native.read_bytes(),native)
        self.assertEqual((run['run_id'],run['agent_run_id'],run['attempt_id']),
                         (self.parent,self.run['agent_run_id'],self.run['attempt_id']))
        self.assertEqual(len(state['tasks']['T']['executions']),1)
        self.assertEqual(state['tasks']['T']['max_attempts'],3)
        self.assertIn(finished,self.logger.read())
        self.assertEqual(self.continuation(),record)
        from harness.sequential import report
        commands = report(self.root)['commands']
        self.assertEqual(len(commands),2)
        self.assertTrue(all(c['link']['status']=='COLLECTED' for c in commands))
        self.assertTrue((self.root/'.harness/build.txt').exists())
        self.assertTrue((self.root/'.harness/test.txt').exists())

    def test_service_and_integration_command_share_one_managed_lease(self):
        service = ['rtk', 'proxy', sys.executable, '-c',
                   'from pathlib import Path; import os,time; '
                   'Path(".harness/service.pid").write_text(str(os.getpid())); time.sleep(60)']
        probe = ['rtk', 'proxy', sys.executable, '-c',
                 'from pathlib import Path; import os; '
                 'pid=int(Path(".harness/service.pid").read_text()); os.kill(pid,0); '
                 'Path(".harness/probe.txt").write_text("verified")']
        result = self.logger.command(self.parent, service, 'T', self.run['agent_run_id'],
                                     self.run['attempt_id'], 'integration',
                                     verification={'startup_seconds': 1, 'commands': [probe]})
        self.assertEqual(result, 0)
        self.assertEqual((self.root/'.harness/probe.txt').read_text(), 'verified')
        pid = int((self.root/'.harness/service.pid').read_text())
        from harness.process_ownership import owner_identity
        self.assertEqual(owner_identity(pid)['status'], 'DEAD')
        commands = [e for e in self.logger.read() if e['event_type'] == 'command_finished']
        self.assertEqual([e['observed']['returncode'] for e in commands], [0, 0])

    def test_failed_service_probe_stops_service_and_skips_later_commands(self):
        service = ['rtk', 'proxy', sys.executable, '-c',
                   'from pathlib import Path; import os,time; '
                   'Path(".harness/service.pid").write_text(str(os.getpid())); time.sleep(60)']
        fail_probe = ['rtk', 'proxy', sys.executable, '-c', 'raise SystemExit(9)']
        later = ['rtk', 'proxy', sys.executable, '-c',
                 'from pathlib import Path; Path(".harness/late").touch()']
        result = self.logger.command(self.parent, service, 'T', self.run['agent_run_id'],
                                     self.run['attempt_id'], 'integration', verification={
                                         'startup_seconds': 1, 'commands': [fail_probe, later]})
        self.assertEqual(result, 9)
        self.assertFalse((self.root/'.harness/late').exists())
        pid = int((self.root/'.harness/service.pid').read_text())
        from harness.process_ownership import owner_identity
        self.assertEqual(owner_identity(pid)['status'], 'DEAD')

    def test_open_parent_cannot_be_replaced_and_failed_attempt_cannot_continue(self):
        with self.assertRaises(ValueError): self.continuation()
        self.stop_and_resume()
        self.m.fail('T',self.run['agent_run_id'],'Synthetic failed attempt')
        with self.assertRaises(ValueError): self.continuation()

    def test_changed_source_is_rejected_before_command_launch(self):
        self.stop_and_resume(); record=self.continuation()
        (self.root/'technical.md').write_text('Unapproved source change')
        with self.assertRaises(ValueError):self.command(record['command_run_id'])
        self.assertFalse((self.root/'.harness/build.txt').exists())

    def test_changed_ownership_work_plan_and_native_bindings_reject_existing_link(self):
        self.stop_and_resume(); record=self.continuation()
        from harness.command_runs import linked
        original=self.m.read()
        for change in ('code_paths','role','work_plan','original_binding','command_binding','proof'):
            with self.subTest(change=change):
                state=copy.deepcopy(original); task=state['tasks']['T']; execution=task['executions'][0]
                if change=='code_paths':task['development_tracking']['code_paths']=['src','outside']
                elif change=='role':task['role']='development'
                elif change=='work_plan':task['work_plan']['steps'][0]['action']='Different work'
                elif change.endswith('binding'):
                    key=self.parent if change=='original_binding' else record['command_run_id']
                    state['execution_policy_bindings'][key]['root_session_id']='00000000-0000-4000-8000-000000000812'
                else:execution['command_run_continuations'][0]['scope_sha256']='0'*64
                self.assertFalse(linked(self.root,state,task,execution,record['command_run_id']))
        self.assertFalse((self.root/'.harness/build.txt').exists())

    def test_attempt_mismatch_and_concurrent_executor_cannot_continue_or_launch(self):
        self.stop_and_resume()
        from harness.process_ownership import TaskLease
        with TaskLease(self.root,'T'):
            with self.assertRaises((ValueError,RuntimeError)):self.continuation()
        record=self.continuation()
        with self.assertRaises(ValueError):
            self.logger.command(record['command_run_id'],['rtk','proxy',sys.executable,'-c','pass'],
                task_id='T',agent_run_id=self.run['agent_run_id'],attempt_id='wrong-attempt',command_kind='build')
        self.assertFalse((self.root/'.harness/build.txt').exists())

    def test_changed_native_binding_rejects_actual_command_before_launch(self):
        self.stop_and_resume(); record=self.continuation()
        self.m._mutate('synthetic_changed_native_binding', lambda state:
            state['execution_policy_bindings'][record['command_run_id']].update(
                root_session_id='00000000-0000-4000-8000-000000000812'))
        with self.assertRaises(ValueError):self.command(record['command_run_id'])
        self.assertFalse((self.root/'.harness/build.txt').exists())

    def test_changed_code_ownership_cannot_create_a_command_continuation(self):
        self.stop_and_resume()
        self.m._mutate('synthetic_changed_code_ownership', lambda state:
            state['tasks']['T']['development_tracking'].update(code_paths=['src','outside']))
        with self.assertRaises(ValueError):self.continuation()
        self.assertFalse(any(e['event_type']=='command_run_continued' for e in self.logger.read()))

    def test_guard_checks_equal_options_and_rejects_ambiguous_duplicate_forms(self):
        from harness.product_guard import evaluate
        control=self.root/'.kmp-agent'; control.mkdir(); (control/'installation.json').write_text('{}')
        base='python3 .kmp-agent/agent.py task '
        variants=[
            '--run-id '+self.parent+' --operation continue-command-run',
            '--run-id='+self.parent+' --operation=continue-command-run',
            '--run-id '+self.parent+' --operation show --operation=continue-command-run',
            '--run-id '+self.parent+' --operation=show --operation continue-command-run',
            '--run-id '+self.parent+' --run-id=other --operation=continue-command-run']
        for index, arguments in enumerate(variants):
            command=base+arguments+' --data docs/guard-inputs/continuation.json'
            for session in (self.session,'wrong-native-root'):
                with self.subTest(command=arguments,session=session):
                    result=evaluate(self.root,dict(hook_event_name='PreToolUse',cwd=str(self.root),
                        session_id=session,tool_name='exec_command',tool_input={'cmd':command}))
                    if index<2 and session==self.session:self.assertEqual(result,{})
                    else:self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')

    def test_second_continuation_retains_first_commands_and_closes_old_logging_context(self):
        self.stop_and_resume(); first=self.continuation()
        self.assertEqual(self.command(first['command_run_id']),0)
        self.logger.checkpoint(first['command_run_id'],'Synthetic second handoff',finish=True,end_reason='handoff')
        second=self.continuation(previous=first['command_run_id'])
        self.assertNotEqual(second['command_run_id'],first['command_run_id'])
        with self.assertRaisesRegex(ValueError,'run already finished'):
            self.command(first['command_run_id'],'stale')
        self.assertEqual(self.command(second['command_run_id'],'test'),0)
        from harness.sequential import report
        commands=report(self.root)['commands']
        self.assertEqual(len(commands),2)
        self.assertTrue(all(c['link']['status']=='COLLECTED' for c in commands))
        self.assertEqual(len(self.m.read()['tasks']['T']['executions']),1)


del Authority, Native


class MissingCommandRunTests(unittest.TestCase):
    setUp = CommandRunContinuationTests.setUp
    parent_has_log = False
    git = CommandRunContinuationTests.git
    question = CommandRunContinuationTests.question
    approve = CommandRunContinuationTests.approve
    call = CommandRunContinuationTests.call
    entry = CommandRunContinuationTests.entry
    structured = CommandRunContinuationTests.structured
    reply = CommandRunContinuationTests.reply
    write_native = CommandRunContinuationTests.write_native
    write_code = CommandRunContinuationTests.write_code
    command = CommandRunContinuationTests.command
    continuation = CommandRunContinuationTests.continuation

    def test_missing_log_recovers_same_active_attempt(self):
        with self.assertRaisesRegex(ValueError, 'unknown run_id'):
            self.command(self.parent)
        self.logger.append('command_started', self.parent, 'HARNESS_IMPROVEMENT',
                           task_id='QA', agent_run_id='independent-qa-attempt')
        before = self.m.read()
        link = self.continuation()
        self.assertTrue(link['previous_log_missing'])
        self.assertIsNone(link['previous_finished_event_id'])
        self.assertEqual(self.continuation(), link)
        self.assertEqual(self.command(link['command_run_id']), 0)
        after = self.m.read()
        self.assertEqual(after['required_questions'], before['required_questions'])
        execution, = after['tasks']['T']['executions']
        self.assertEqual(execution['attempt_id'], self.run['attempt_id'])
        self.assertEqual(execution['run_id'], self.parent)
        with self.assertRaisesRegex(ValueError, 'unknown run_id'):
            self.logger.run(self.parent)

    def test_late_predecessor_log_preserves_recovered_command_evidence(self):
        from harness.command_runs import linked
        from harness.sequential import report

        link = self.continuation()
        command_run = link['command_run_id']
        self.assertEqual(self.command(command_run), 0)
        self.logger.append('run_started', self.parent, 'HARNESS_IMPROVEMENT')
        with self.assertRaisesRegex(ValueError, 'explicitly link'):
            self.command(self.parent)
        self.logger.append('run_finished', self.parent, 'HARNESS_IMPROVEMENT')

        state = self.m.read()
        task = state['tasks']['T']
        execution, = task['executions']
        self.assertTrue(linked(self.root, state, task, execution, command_run, historical=True))
        command, = [row for row in report(self.root)["commands"] if row["run_id"] == command_run]
        self.assertEqual(command["link"]["status"], "COLLECTED")
        self.assertEqual(self.continuation(), link)
        self.assertEqual(self.command(command_run), 0)

    def test_partial_predecessor_log_is_not_replaced(self):
        self.logger.append('run_finished', self.parent, 'HARNESS_IMPROVEMENT')
        with self.assertRaisesRegex(ValueError, 'unknown run_id'):
            self.continuation()
