"""Synthetic worker reports with real Git diffs/commands; not product/model QA."""
from pathlib import Path
import tempfile
import unittest

from harness.test_delegation import build_fixture, mock_worker


class ReportedOpenItemTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manager, self.dev, self.spec = build_fixture(self.root)
        self.unresolved = ['sandbox build NOT_RUN; independent coordinator validation required']
        self.verifications = [{'command': ['worker', 'unavailable', 'build'], 'status': 'NOT_RUN',
                               'evidence': None}]

    def worker(self, *args):
        result = mock_worker(*args)
        result['result']['unresolved'] = list(self.unresolved)
        result['result']['verifications'] = list(self.verifications)
        return result

    def test_complete_open_items_preserved_but_actual_commands_decide(self):
        self.dev.configure(**self.spec)
        result = self.dev.execute('PARENT', self.worker)
        self.assertEqual(result.get('handoff'), 'READY_FOR_VERIFICATION', result)
        self.assertFalse(result['feature_complete'])
        for tid in ('CHILD-KMP', 'CHILD-WEB', 'CHILD-SERVER'):
            task = self.manager.read()['tasks'][tid]
            self.assertEqual(task['state'], 'DONE', task.get('delegation_reason'))
            self.assertEqual(task['reported_unresolved'], self.unresolved)
            self.assertEqual(task['worker_verifications'], self.verifications)
            self.assertTrue(task['change_reference'])
            self.assertTrue(task['reviews'][-1]['results'])
            self.assertTrue(all(r['result'] == 'PASS' for r in task['reviews'][-1]['results']))

    def test_actual_command_failure_blocks_even_complete_report(self):
        self.spec['children'][0]['verification_commands'] = [
            ['rtk', 'proxy', 'python3', '-c', 'raise SystemExit(7)']]
        self.dev.configure(**self.spec)
        result = self.dev.execute('PARENT', self.worker)
        self.assertNotEqual(result.get('handoff'), 'READY_FOR_VERIFICATION', result)
        task = self.manager.read()['tasks']['CHILD-KMP']
        self.assertNotEqual(task['state'], 'DONE')
        self.assertEqual(task['reported_unresolved'], self.unresolved)
        self.assertEqual(task['worker_verifications'], self.verifications)

    def test_partial_report_still_blocks_despite_valid_source_change(self):
        self.dev.configure(**self.spec)
        def partial(*args):
            result = self.worker(*args)
            result['result']['status'] = 'PARTIAL'
            return result
        result = self.dev.execute('PARENT', partial)
        self.assertNotEqual(result.get('handoff'), 'READY_FOR_VERIFICATION', result)
        for tid in ('CHILD-KMP', 'CHILD-WEB', 'CHILD-SERVER'):
            self.assertNotEqual(self.manager.read()['tasks'][tid]['state'], 'DONE')


if __name__ == '__main__':
    unittest.main()
