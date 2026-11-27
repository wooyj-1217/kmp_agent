"""Sequential command ownership in disposable tasks; no worker recovery bypass."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from harness.execution_policy import managed_command
from harness.process_ownership import TaskLease
from harness.recovery import claim
from harness.test_execution_policy import ExecutionPolicyTests as Fixture


class CommandOwnershipTests(unittest.TestCase):
    _fixture_setup = Fixture.setUp
    step = Fixture.step
    write_native = Fixture.write_native
    activate = Fixture.activate
    plan = Fixture.plan

    def setUp(self):
        self._fixture_setup()
        self.activate(); self.plan(); self.m.ready('T')
        self.run = self.m.begin('T', 'improvement')

    def command(self, code=0):
        return managed_command(self.m, 'T', [sys.executable, '-c',
            'import sys; print("owned command"); sys.exit(' + str(code) + ')'], self.root)

    def active(self):
        return self.m.read()['tasks']['T']['executions'][0]

    def receipt(self):
        return Path(self.active()['process_owner']['receipt_path'])

    def test_sequential_commands_preserve_attempt_and_prior_receipts(self):
        self.assertEqual(self.command().returncode, 0)
        first = self.active()
        original = self.receipt().read_bytes()
        self.assertEqual(self.command().returncode, 0)
        after = self.active()
        self.assertEqual(after['agent_run_id'], self.run['agent_run_id'])
        self.assertEqual(after['attempt_id'], self.run['attempt_id'])
        self.assertEqual(len(after['command_owner_completions']), 2)
        self.assertNotEqual(after['process_owner']['token'], first['process_owner']['token'])
        self.assertEqual(after['process_owner_history'], [first['process_owner']])
        self.assertEqual(Path(first['process_owner']['receipt_path']).read_bytes(), original)
        self.assertEqual(len(self.m.read()['tasks']['T']['executions']), 1)

    def test_repeated_claims_preserve_one_opening_basis_without_rescanning(self):
        from harness.recovery import workspace_basis
        with patch('harness.recovery.workspace_basis',wraps=workspace_basis) as capture:
            self.assertEqual(self.command().returncode,0)
            opening=copy.deepcopy(self.active()['recovery_start_basis'])
            self.assertEqual(self.command().returncode,0)
            self.assertEqual(capture.call_count,1)
        self.assertEqual(self.active()['recovery_start_basis'],opening)

    def test_nonzero_normal_return_allows_authorized_retest(self):
        self.assertEqual(self.command(7).returncode, 7)
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual([p['returncode'] for p in self.active()['command_owner_completions']], [7, 0])

    def test_foreground_interrupt_allows_next_command_after_child_exits(self):
        original = subprocess.Popen.communicate

        def communicate(child, *args, **kwargs):
            if kwargs.get('timeout') == .2:
                raise KeyboardInterrupt
            return original(child, *args, **kwargs)

        with patch.object(subprocess.Popen, 'communicate', communicate):
            result = managed_command(self.m, 'T', [sys.executable, '-c',
                'import time; time.sleep(10)'], self.root)
        self.assertLess(result.returncode, 0)
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual(self.active()['command_owner_completions'][0]['returncode'], result.returncode)

    def test_thrown_timeout_is_not_clean_command_completion(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            managed_command(self.m, 'T', [sys.executable, '-c',
                'import time; time.sleep(10)'], self.root, timeout=.1)
        self.assertFalse(self.active().get('command_owner_completions'))
        with self.assertRaisesRegex(ValueError, 'explicit recovery'):
            self.command()

    def resumed_command_interruption(self, prior_command):
        if prior_command:
            self.command()
        self.m.checkpoint('T', self.run['agent_run_id'], 'Explicit pause', 'scope.md')
        self.m.resume('T', self.run['agent_run_id'], 'scope.md')
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual(len(self.active()['owner_resume_claims']), 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            managed_command(self.m, 'T', [sys.executable, '-c',
                'import time; time.sleep(10)'], self.root, timeout=.1)
        with self.assertRaisesRegex(ValueError, 'explicit recovery'):
            self.command()
        # A fresh official checkpoint/resume, without replacing the attempt,
        # supplies a new one-use ownership decision.
        self.m.checkpoint('T', self.run['agent_run_id'], 'New explicit pause', 'scope.md')
        self.m.resume('T', self.run['agent_run_id'], 'scope.md')
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual([p['decision_count'] for p in self.active()['owner_resume_claims']], [1, 2])
        self.assertEqual(len(self.m.read()['tasks']['T']['executions']), 1)

    def test_resume_grant_cannot_bypass_later_interrupted_command(self):
        self.resumed_command_interruption(prior_command=True)

    def test_resume_before_first_owner_is_consumed_at_first_claim(self):
        self.resumed_command_interruption(prior_command=False)

    def test_released_generic_worker_does_not_authorize_command_turnover(self):
        with TaskLease(self.root, 'T'):
            claim(self.m, 'T', self.run['agent_run_id'])
        self.assertTrue(json.loads(self.receipt().read_text())['released'])
        with self.assertRaisesRegex(ValueError, 'explicit recovery'):
            self.command()

    def test_nested_commands_do_not_certify_the_worker_lease(self):
        with TaskLease(self.root, 'T'):
            claim(self.m, 'T', self.run['agent_run_id'])
            self.assertEqual(self.command().returncode, 0)
            self.assertEqual(self.command().returncode, 0)
            self.assertFalse(self.active().get('command_owner_completions'))
        with self.assertRaisesRegex(ValueError, 'explicit recovery'):
            self.command()

    def test_completion_requires_matching_token_attempt_and_receipt(self):
        self.command()
        original = copy.deepcopy(self.active()['command_owner_completions'])
        for key in ('token', 'task_id', 'agent_run_id', 'attempt_id', 'receipt_path', 'returncode'):
            with self.subTest(key=key):
                invalid = copy.deepcopy(original)
                invalid[0][key] = 'wrong'
                self.m._mutate('synthetic_mismatched_command_proof',
                    lambda state: state['tasks']['T']['executions'][0].update(command_owner_completions=invalid))
                with self.assertRaisesRegex(ValueError, 'explicit recovery'):
                    self.command()
        self.m._mutate('synthetic_restore_command_proof',
            lambda state: state['tasks']['T']['executions'][0].update(command_owner_completions=original))
        self.assertEqual(self.command().returncode, 0)

    def test_clean_completion_does_not_bypass_uncertain_child(self):
        self.command()
        with patch('harness.process_ownership.inspect_child', return_value={'status': 'UNKNOWN'}):
            with self.assertRaisesRegex(ValueError, 'explicit recovery'):
                self.command()

    def test_spawn_intent_blocks_completed_command_turnover(self):
        self.command()
        path = self.receipt()
        original = path.read_bytes()
        record = json.loads(original); record['spawn_pending'] = ['unresolved']
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'explicit recovery'):
            self.command()
        path.write_bytes(original)
        self.assertEqual(self.command().returncode, 0)

    def test_physical_lease_excludes_overlapping_executor(self):
        self.command()
        with TaskLease(self.root, 'T'):
            script = ('from harness.tasks import Tasks; from harness.execution_policy import managed_command; '
                      'import sys; managed_command(Tasks(sys.argv[1], "run"), "T", '
                      '[sys.executable, "-c", "print(123)"], sys.argv[1])')
            result = subprocess.run([sys.executable, '-B', '-c', script, str(self.root)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('lease held', result.stderr)
            self.assertNotIn('123', result.stdout)


del Fixture
