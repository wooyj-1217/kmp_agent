"""SYNTHETIC_UNIT_TEST_ONLY: orchestration fixtures, never acceptance/security proof.

Only explicit test setUp calls install this mock. Shared fixture builders and
production code must not activate it, including real-worker trials.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import protected_verification


def synthetic_authority(test_case, root):
    """Mock protected assessments for protected tasks in exactly one fixture root."""
    fixture_root = Path(root).resolve()
    original = protected_verification.assess

    def assess(candidate_root, task):
        if Path(candidate_root).resolve() == fixture_root and protected_verification.requires(task):
            return {'result': 'PASS', 'reason': None, 'checks': [],
                    'issuer': 'SYNTHETIC_UNIT_TEST_ONLY',
                    'scope_note': 'Mock orchestration dependency; not acceptance or security evidence'}
        return original(candidate_root, task)

    mock = patch.object(protected_verification, 'assess', side_effect=assess)
    mock.start()
    test_case.addCleanup(mock.stop)
    return mock


class SyntheticAuthorityTests(unittest.TestCase):
    def test_only_exact_root_and_protected_tasks_receive_synthetic_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_result = {'result': 'BLOCKED', 'reason': 'real assessment sentinel'}
            with patch.object(protected_verification, 'assess', return_value=original_result) as original:
                mock = synthetic_authority(self, root)
                try:
                    protected = {'task_id': 'T', 'execution_scope': 'code_implementation'}
                    self.assertEqual(protected_verification.assess(root, protected)['issuer'], 'SYNTHETIC_UNIT_TEST_ONLY')
                    self.assertEqual(protected_verification.assess(root / 'child', protected), original_result)
                    self.assertEqual(protected_verification.assess(root, {'task_id': 'DOC'}), original_result)
                    self.assertEqual(original.call_count, 2)
                finally:
                    mock.stop()
