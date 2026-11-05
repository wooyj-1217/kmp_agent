"""Aborting a review retains its original error without issuing acceptance."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.tasks import Tasks


class ReviewFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('input.md', 'output.md', 'evidence.md'):
            (self.root / name).write_text('synthetic document fixture')
        self.tasks = Tasks(self.root, 'review-failure-fixture')
        self.tasks.register('F', 'T', 'planning', 'Fixture', 'Review abort',
                            [{'id': 'AC', 'required': True, 'text': 'fixture'}],
                            ['input.md'], execution_scope='documentation')
        self.tasks.ready('T')
        self.work = self.tasks.begin('T', 'planning')

    def begin_review(self):
        self.tasks.submit('T', self.work['agent_run_id'], ['output.md'], 'fixture')
        return self.tasks.begin('T', 'verification', review=True)

    def task(self):
        return self.tasks.read()['tasks']['T']

    def test_rejected_official_review_can_abort_with_original_cause(self):
        review = self.begin_review()
        cause = 'protected verification completion blocked: PROTECTED_AUTHORITY_UNAVAILABLE'
        with patch('harness.protected_verification.gate', side_effect=ValueError(cause)):
            with self.assertRaisesRegex(ValueError, 'PROTECTED_AUTHORITY_UNAVAILABLE'):
                self.tasks.review('T', review['agent_run_id'],
                                  [{'criterion_id': 'AC', 'result': 'PASS', 'evidence': 'evidence.md'}], 'local observation')
        self.tasks.fail('T', review['agent_run_id'], cause)
        task = self.task()
        self.assertEqual(task['state'], 'BLOCKED')
        self.assertEqual(task['blocked_reason'], cause)
        self.assertEqual(task['reviews'], [])
        self.assertTrue(task['executions'][-1]['ended_at'])
        event = [e for e in self.tasks.logger.read() if e['event_type'] == 'agent_run_failed'][-1]
        self.assertEqual(event['observed']['kind'], 'review')
        self.assertEqual(event['observed']['reason'], cause)

    def test_blocked_active_review_can_abort(self):
        review = self.begin_review()
        self.tasks._mutate('fixture blocked review', lambda state: state['tasks']['T'].update(state='BLOCKED'), 'T')
        self.tasks.fail('T', review['agent_run_id'], 'review infrastructure failed')
        self.assertTrue(self.task()['executions'][-1]['ended_at'])

    def test_unknown_completed_and_duplicate_failure_ids_are_rejected(self):
        review = self.begin_review()
        for aid in ('missing-id', self.work['agent_run_id']):
            with self.assertRaisesRegex(ValueError, 'execution is not active'):
                self.tasks.fail('T', aid, 'invalid abort')
        self.assertIsNone(self.task()['executions'][-1]['ended_at'])
        self.tasks.fail('T', review['agent_run_id'], 'real abort')
        with self.assertRaisesRegex(ValueError, 'execution is not active'):
            self.tasks.fail('T', review['agent_run_id'], 'duplicate abort')

    def test_work_failure_keeps_existing_behavior(self):
        self.tasks.fail('T', self.work['agent_run_id'], 'worker stopped')
        task = self.task()
        self.assertEqual(task['state'], 'BLOCKED')
        self.assertEqual(task['executions'][0]['failure'], 'worker stopped')
        self.assertTrue(task['executions'][0]['ended_at'])


if __name__ == '__main__':
    unittest.main()
