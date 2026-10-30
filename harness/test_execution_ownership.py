"""Synthetic ledger admission cases; no device or model is launched."""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

from harness.execution_ownership import gate


class ExecutionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.manager = SimpleNamespace(root=Path('/synthetic/project'))

    def task(self, name, resources=(), code=False, active=False, review=False):
        collection = {'shared_resources': list(resources)}
        task = {'task_id': name, 'role': 'development' if code else 'verification',
                'execution_scope': 'code_implementation' if code else 'documentation',
                'target_repository': str(self.manager.root), 'collection': collection,
                'executions': []}
        if active:
            task['executions'].append({'agent_run_id': name + '-run', 'ended_at': None,
                                       'kind': 'review' if review else 'work',
                                       'execution_scope': task['execution_scope'],
                                       'collection': copy.deepcopy(collection)})
        return task

    def check(self, task, *peers, review=False):
        state = {'tasks': {t['task_id']: t for t in (task,) + peers}}
        before = copy.deepcopy(state)
        try:
            return gate(self.manager, state, task, review)
        finally:
            self.assertEqual(state, before, 'gate must not create a second state store')

    def test_missing_declaration_is_safe_only_without_active_peer(self):
        own = self.task('new'); own.pop('collection')
        self.check(own)
        with self.assertRaisesRegex(ValueError, 'ownership unknown'):
            self.check(own, self.task('active', active=True))

    def test_unknown_peer_or_resource_prevents_parallel_execution(self):
        for value in (None, 'UNKNOWN', ['UNKNOWN'], [''], [1]):
            peer = self.task('active', active=True)
            peer['collection']['shared_resources'] = value
            peer['executions'][0]['collection']['shared_resources'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'ownership unknown'):
                self.check(self.task('new'), peer)

    def test_explicit_empty_or_disjoint_resources_allow_parallel_reviews(self):
        self.check(self.task('new'), self.task('active', active=True), review=True)
        self.check(self.task('new', ['device:ios-B', 'port:9002', 'data:B']),
                   self.task('active', ['device:ios-A', 'port:9001', 'data:A'], active=True), review=True)

    def test_every_shared_resource_is_exclusive(self):
        for resource in ('device:emulator-5554', 'workspace:/tmp/x', 'branch:main', 'port:8102', 'data:/tmp/x'):
            with self.subTest(resource=resource), self.assertRaisesRegex(ValueError, 'ownership conflict'):
                self.check(self.task('new', [resource]), self.task('active', [resource], active=True), review=True)

    def test_same_repository_writers_conflict_even_with_disjoint_claims(self):
        with self.assertRaisesRegex(ValueError, 'same repository workspace writer'):
            self.check(self.task('new', ['workspace:A'], code=True),
                       self.task('active', ['workspace:B'], code=True, active=True))

    def test_distinct_repositories_with_distinct_resources_can_write(self):
        peer = self.task('active', ['workspace:B'], code=True, active=True)
        peer['target_repository'] = '/synthetic/other-project'
        self.check(self.task('new', ['workspace:A'], code=True), peer)

    def test_code_review_is_not_a_writer_but_device_remains_exclusive(self):
        self.check(self.task('new', code=True), self.task('active', code=True, active=True), review=True)
        self.check(self.task('new', code=True), self.task('active', code=True, active=True, review=True))
        with self.assertRaisesRegex(ValueError, 'device:shared'):
            self.check(self.task('new', ['device:shared'], code=True),
                       self.task('active', ['device:shared'], code=True, active=True, review=True), review=True)

    def test_checkpoint_keeps_claim_until_execution_ends(self):
        peer = self.task('active', ['device:shared'], active=True)
        peer['state'] = 'BLOCKED'
        peer['executions'][0]['checkpoint'] = {'snapshot': 'saved'}
        own = self.task('new', ['device:shared'])
        with self.assertRaisesRegex(ValueError, 'ownership conflict'):
            self.check(own, peer)
        peer['executions'][0]['ended_at'] = '2026-10-30T00:00:00Z'
        self.check(own, peer)

    def test_live_declaration_cannot_drop_original_claim(self):
        peer = self.task('active', ['device:original'], active=True)
        peer['collection']['shared_resources'] = ['device:replacement']
        peer['executions'][0]['collection_declarations'] = [{'shared_resources': ['device:intermediate']}]
        for resource in ('device:original', 'device:replacement', 'device:intermediate'):
            with self.subTest(resource=resource), self.assertRaisesRegex(ValueError, 'ownership conflict'):
                self.check(self.task('new', [resource]), peer)

    def test_resume_ignores_own_execution_and_checks_new_peer(self):
        own = self.task('resumed', ['device:own'], active=True)
        self.check(own)
        with self.assertRaisesRegex(ValueError, 'ownership conflict'):
            self.check(own, self.task('peer', ['device:own'], active=True))


if __name__ == '__main__':
    unittest.main()
