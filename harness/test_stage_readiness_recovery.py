"""Synthetic startup/recovery diagnostics; no historical approvals are invented."""
import copy
import unittest
from unittest.mock import patch

from harness.stage_readiness import STAGES, assess, gate
from harness import test_stage_readiness as fixture


class StageReadinessRecoveryTest(unittest.TestCase):
    setUp = fixture.StageReadinessTest.setUp
    approve = fixture.StageReadinessTest.approve

    def test_missing_workflow_diagnostic_names_native_recovery_operations(self):
        state = self.t.read()
        state.pop('stage_workflows')
        before = copy.deepcopy(state)
        result = assess(self.root, state, 'F')
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['next_actions'][0]['operation'], 'configure-stage-workflow')
        self.assertEqual(result['next_actions'][0]['feature_id'], 'F')
        self.assertEqual(result['next_actions'][0]['required_stages'], list(STAGES))
        reason = gate(self.t, state, state['tasks']['CODE'])
        for operation in ('configure-stage-workflow', 'review', 'bind-stage-inputs'):
            self.assertIn(operation, reason)
        self.assertEqual(state, before)

    def test_existing_markdown_does_not_create_contract_or_approve_stage(self):
        state = self.t.read()
        state.pop('stage_workflows')
        self.t._save(state)
        (self.root/'development_plan.md').write_text('existing unreviewed plan')
        with self.assertRaisesRegex(ValueError, 'configure-stage-workflow'):
            self.t.ready('CODE')
        self.t.configure_stage_workflow('F', self.contract)
        with self.assertRaisesRegex(ValueError, 'planning.*NOT_RUN'):
            self.t.ready('CODE')
        self.assertFalse(self.t.read()['tasks']['development_plan']['reviews'])

    def test_input_diagnostic_points_to_explicit_binding_after_independent_reviews(self):
        for stage in STAGES:
            self.approve(stage)
        state = self.t.read()
        self.assertIn('bind-stage-inputs', gate(self.t, state, state['tasks']['CODE']))
        self.t.bind_stage_inputs('CODE', ['req.md', 'planning.md', 'design.md', 'development_plan.md'],
                                 'current independently reviewed versions')
        state = self.t.read()
        self.assertIsNone(gate(self.t, state, state['tasks']['CODE']))

    def test_resume_rechecks_missing_contract_and_preserves_checkpoint(self):
        self.t.ready('planning')
        work = self.t.begin('planning', 'planning')
        (self.root/'checkpoint.md').write_text('synthetic saved work')
        self.t.checkpoint('planning', work['agent_run_id'], 'pause', 'checkpoint.md')
        state = self.t.read()
        # Model a pre-existing code checkpoint from a ledger without a workflow.
        task = state['tasks']['planning']
        task['execution_scope'] = 'code_implementation'
        state.pop('stage_workflows')
        self.t._save(state)
        before = copy.deepcopy(task)
        with patch('harness.development_tracking.ensure') as ensure:
            with self.assertRaisesRegex(ValueError, 'configure-stage-workflow'):
                self.t.resume('planning', work['agent_run_id'], 'req.md')
        ensure.assert_not_called()
        after = self.t.read()['tasks']['planning']
        for key in ('state', 'executions', 'inputs', 'reviews'):
            self.assertEqual(after[key], before[key])

    def test_normal_document_checkpoint_resumes(self):
        state = self.t.read()
        state['tasks']['planning']['max_attempts'] = 1
        self.t._save(state)
        self.t.ready('planning')
        work = self.t.begin('planning', 'planning')
        (self.root/'checkpoint.md').write_text('synthetic saved plan')
        self.t.checkpoint('planning', work['agent_run_id'], 'pause', 'checkpoint.md')
        self.t.resume('planning', work['agent_run_id'], 'req.md')
        self.assertEqual(self.t.read()['tasks']['planning']['state'], 'IN_PROGRESS')

    def test_resume_blocks_changed_upstream_without_rewriting_active_attempt(self):
        self.approve('planning')
        self.t.bind_stage_inputs('design', ['req.md', 'planning.md'], 'reviewed planning')
        self.t.ready('design')
        work = self.t.begin('design', 'design')
        (self.root/'checkpoint.md').write_text('saved design work')
        self.t.checkpoint('design', work['agent_run_id'], 'pause', 'checkpoint.md')
        before = copy.deepcopy(self.t.read()['tasks']['design']['executions'])
        (self.root/'planning.md').write_text('changed unreviewed upstream')
        with self.assertRaisesRegex(ValueError, 'planning.*RECHECK_REQUIRED'):
            self.t.resume('design', work['agent_run_id'], 'req.md')
        task = self.t.read()['tasks']['design']
        self.assertEqual(task['state'], 'BLOCKED')
        self.assertEqual(task['executions'], before)


if __name__ == '__main__':
    unittest.main()
