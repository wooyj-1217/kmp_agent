"""Synthetic native evidence only; no private logs, IDs or model calls."""
import concurrent.futures
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from harness import test_completion as completion_fixture
from harness.usage_collection import (append_unique, poll, register, registrations,
                                      revise_registrations, resolve_attribution_limits)
from harness.usage_revision import record_id, unresolved_limits
from harness.usage_context import read_registrations


class RegistrationRevisionTests(unittest.TestCase):
    setUp = completion_fixture.CompletionTests.setUp
    task = completion_fixture.CompletionTests.task
    review = completion_fixture.CompletionTests.review

    def fixture(self):
        self.old = self.task('OLD', configured=False)
        self.new = self.task('NEW', context=False)
        self.source = self.root / 'synthetic-native.jsonl'
        self.usage_value = {'input_tokens': 10, 'cached_input_tokens': 0,
                            'output_tokens': 2, 'total_tokens': 12}
        self.rows = [dict(type='session_meta', payload={'id': 'synthetic-session'}),
                     dict(type='turn_context', payload={'model': 'synthetic'}),
                     dict(type='event_msg', payload={'type': 'task_started', 'turn_id': 'synthetic-turn'}),
                     self.native('old-response'),
                     dict(type='response_item', payload={'type': 'message', 'role': 'user',
                                                        'content': [{'type': 'input_text', 'text': 'Synthetic new request'}]}),
                     self.native('new-response')]
        self.source.write_text(''.join(json.dumps(r) + '\n' for r in self.rows))
        self.old_reg = register(self.manager, 'OLD', self.old['agent_run_id'], 'synthetic-session',
                                turn_id='synthetic-turn', path=self.source)
        self.import_usage('old-response')
        self.manager.bind_usage_batch('OLD', self.old['agent_run_id'],
                                      [{'session_id': 'synthetic-session', 'response_id': 'old-response'}], 'synthetic old attribution')
        self.assertEqual(self.review('OLD'), 'DONE')
        self.new_reg = register(self.manager, 'NEW', self.new['agent_run_id'], 'synthetic-session',
                                turn_id='synthetic-turn', path=self.source)
        self.import_usage('new-response')
        poll(self.manager)
        self.original_tasks = copy.deepcopy(self.manager.read())
        self.raw = (self.root / '.harness/usage/sessions.jsonl').read_bytes()
        self.limits = (self.root / '.harness/usage/attribution-limits.jsonl').read_bytes()
        raw_regs = [json.loads(line) for line in self.raw.splitlines()]
        old, new = raw_regs
        content = self.source.read_bytes()
        self.arguments = dict(supersedes=[old['id'], new['id']], replacements=[
            dict(registration_id=old['id'], side='before', response_ids=['old-response']),
            dict(registration_id=new['id'], side='after', response_ids=['new-response'])],
            evidence=dict(source_path=str(self.source), source_bytes=len(content),
                          source_sha256=hashlib.sha256(content).hexdigest(), boundary_line=5),
            reason='Synthetic native user boundary separates two explicitly declared tasks')

    def native(self, response):
        return dict(type='token_usage_record', payload=dict(thread_id='synthetic-session',
                    turn_id='synthetic-turn', response_id=response, usage=self.usage_value))

    def import_usage(self, response):
        self.logger.append('model_usage', self.run, source={'session_id': 'synthetic-session'},
                           observed={'thread_id': 'synthetic-session', 'turn_id': 'synthetic-turn',
                                     'response_id': response, 'model': 'synthetic',
                                     'usage_semantics': 'per_response_increment', 'usage': self.usage_value})

    def revise(self):
        return revise_registrations(self.manager, **self.arguments)

    def unresolved(self):
        return unresolved_limits(self.root, self.manager.read(), self.logger.read(), registrations(self.root))

    def test_real_narrowing_preserves_history_done_and_exact_bindings(self):
        self.fixture(); revision = self.revise()
        self.assertEqual(poll(self.manager)['new_bindings'], 1)
        self.assertEqual(resolve_attribution_limits(self.manager, revision['id']), 2)
        self.assertEqual(self.unresolved(), set())
        self.assertEqual(read_registrations(self.root), registrations(self.root))
        self.assertEqual(self.manager.read()['tasks']['OLD'], self.original_tasks['tasks']['OLD'])
        self.assertEqual((self.root / '.harness/usage/sessions.jsonl').read_bytes(), self.raw)
        self.assertEqual((self.root / '.harness/usage/attribution-limits.jsonl').read_bytes(), self.limits)
        self.assertEqual(self.review('NEW'), 'DONE')

    def test_unbound_candidate_does_not_resolve(self):
        self.fixture(); revision = self.revise()
        self.assertEqual(resolve_attribution_limits(self.manager, revision['id']), 1)
        self.assertIn(('synthetic-session', 'new-response'), self.unresolved())
        with self.assertRaisesRegex(ValueError, 'missing bound'):
            self.review('NEW')

    def test_other_turn_already_in_prefix_can_be_bound_to_same_execution(self):
        self.fixture()
        continuation = self.native('continuation-response')
        continuation['payload']['turn_id'] = 'continuation-turn'
        self.rows.append(continuation)
        self.source.write_text(''.join(json.dumps(r) + '\n' for r in self.rows))
        content = self.source.read_bytes()
        self.arguments['evidence'].update(source_bytes=len(content),
            source_sha256=hashlib.sha256(content).hexdigest())
        self.logger.append('model_usage', self.run, source={'session_id': 'synthetic-session'},
            observed={'thread_id': 'synthetic-session', 'turn_id': 'continuation-turn',
                      'response_id': 'continuation-response', 'model': 'synthetic',
                      'usage_semantics': 'per_response_increment', 'usage': self.usage_value})
        revision = self.revise()
        register(self.manager, 'NEW', self.new['agent_run_id'], 'synthetic-session',
                 turn_id='continuation-turn', path=self.source)
        poll(self.manager)
        resolve_attribution_limits(self.manager, revision['id'])
        self.assertEqual(len(registrations(self.root)), 3)
        self.assertEqual(self.unresolved(), set())
        current = self.manager.read()['tasks']['NEW']['executions'][0]
        self.assertEqual({b['response_id'] for b in current['usage_bindings']},
                         {'new-response', 'continuation-response'})
        self.assertEqual(self.manager.read()['tasks']['OLD'], self.original_tasks['tasks']['OLD'])
        self.assertEqual(self.review('NEW'), 'DONE')

    def test_retry_is_idempotent(self):
        self.fixture(); revision = self.revise()
        self.assertEqual(self.revise(), revision)
        poll(self.manager)
        resolve_attribution_limits(self.manager, revision['id'])
        self.assertEqual(resolve_attribution_limits(self.manager, revision['id']), 0)
        self.assertEqual(poll(self.manager)['new_bindings'], 0)
        self.assertEqual(len((self.root / '.harness/usage/registration-revisions.jsonl').read_text().splitlines()), 1)

    def test_native_digest_boundary_and_allocation_tampering_rejected(self):
        for kind in ('digest', 'boundary', 'side', 'response', 'owner', 'missing', 'overlap'):
            with self.subTest(kind=kind):
                self.setUp(); self.fixture()
                if kind == 'digest': self.arguments['evidence']['source_sha256'] = '0' * 64
                if kind == 'boundary': self.arguments['evidence']['boundary_line'] = 3
                if kind == 'side': self.arguments['replacements'][0]['side'] = 'after'
                if kind == 'response': self.arguments['replacements'][1]['response_ids'] = ['invented']
                if kind == 'owner': self.arguments['replacements'][1]['registration_id'] = 'invented'
                if kind == 'missing': self.arguments['replacements'][0]['response_ids'] = []
                if kind == 'overlap': self.arguments['replacements'][1]['response_ids'] = ['old-response']
                with self.assertRaises((ValueError, KeyError)):
                    self.revise()
                self.assertFalse((self.root / '.harness/usage/registration-revisions.jsonl').exists())

    def test_forged_resolution_cannot_clear_conflict(self):
        self.fixture()
        limit = json.loads(self.limits.splitlines()[0])
        append_unique(self.root / '.harness/usage/attribution-resolutions.jsonl',
                      dict(limit_id=record_id(limit), revision_id='forged', execution_id=self.old['agent_run_id']))
        self.assertIn(('synthetic-session', 'old-response'), self.unresolved())
        with self.assertRaisesRegex(ValueError, 'verified effective revision'):
            resolve_attribution_limits(self.manager, 'forged')

    def test_native_source_changed_or_imported_value_forged_fails_closed(self):
        self.fixture(); self.revise()
        self.source.write_bytes(self.source.read_bytes().replace(b'Synthetic new request', b'Synthetic BAD request'))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            registrations(self.root)

    def test_conflicting_imported_usage_cannot_support_revision(self):
        self.fixture()
        self.logger.append('model_usage', self.run, source={'session_id': 'synthetic-session'},
                           observed={'response_id': 'new-response', 'turn_id': 'synthetic-turn',
                                     'usage_semantics': 'per_response_increment', 'usage': {'total_tokens': 999}})
        with self.assertRaisesRegex(ValueError, 'differs from native evidence'):
            self.revise()

    def test_copied_native_source_with_identical_contents_is_not_authority(self):
        self.fixture()
        fake = self.root / 'fake-native.jsonl'
        fake.write_bytes(self.source.read_bytes())
        self.arguments['evidence']['source_path'] = str(fake)
        with self.assertRaisesRegex(ValueError, 'registered native source mismatch'):
            self.revise()

    def test_after_boundary_native_responses_cannot_be_silently_excluded(self):
        self.fixture()
        with self.source.open('a') as f: f.write(json.dumps(self.native('another-response')) + '\n')
        self.import_usage('another-response')
        content = self.source.read_bytes()
        self.arguments['evidence'].update(source_bytes=len(content), source_sha256=hashlib.sha256(content).hexdigest())
        with self.assertRaisesRegex(ValueError, 'allocation incomplete'):
            self.revise()

    def test_valid_digest_forged_revision_is_revalidated_on_every_read(self):
        self.fixture()
        value = dict(version=1, **copy.deepcopy(self.arguments))
        value['replacements'][0]['response_ids'] = ['new-response']
        append_unique(self.root / '.harness/usage/registration-revisions.jsonl', value)
        with self.assertRaisesRegex(ValueError, 'existing bindings'):
            registrations(self.root)

    def test_new_broad_conflict_reopens_previously_resolved_limit(self):
        self.fixture(); revision = self.revise(); poll(self.manager)
        resolve_attribution_limits(self.manager, revision['id'])
        other = self.task('OTHER', configured=False)
        register(self.manager, 'OTHER', other['agent_run_id'], 'synthetic-session', turn_id='synthetic-turn', path=self.source)
        poll(self.manager)
        self.assertIn(('synthetic-session', 'new-response'), self.unresolved())
        from harness.usage_projection import project
        with patch('harness.usage_revision.unresolved_limits', wraps=unresolved_limits) as checker:
            project(self.root, task_id='NEW')
        checked_root, checked_state, checked_events, checked_regs = checker.call_args.args
        self.assertIn('OTHER', checked_state['tasks'])
        self.assertTrue(any(r['task_id'] == 'OTHER' for r in checked_regs))
        self.assertIn(('synthetic-session', 'new-response'),
                      unresolved_limits(checked_root, checked_state, checked_events, checked_regs))
        response = next(row for row in project(self.root)['rows'] if row['response_id'] == 'new-response')
        self.assertIn('mapping_error', response['quality'])
        with self.assertRaisesRegex(ValueError, 'unresolved attribution conflict'):
            self.review('NEW')

    def test_future_exact_response_registration_keeps_fixed_revision_valid(self):
        self.fixture(); revision = self.revise(); poll(self.manager)
        with self.source.open('a') as f: f.write(json.dumps(self.native('future-response')) + '\n')
        self.import_usage('future-response')
        register(self.manager, 'NEW', self.new['agent_run_id'], 'synthetic-session',
                 response_ids=['future-response'], path=self.source)
        self.assertEqual(poll(self.manager)['new_bindings'], 1)
        resolve_attribution_limits(self.manager, revision['id'])
        self.assertEqual(self.review('NEW'), 'DONE')

    def test_concurrent_revision_registration_and_poll_do_not_deadlock_or_duplicate(self):
        self.fixture()
        def exact():
            register(self.manager, 'NEW', self.new['agent_run_id'], 'synthetic-session',
                     response_ids=['new-response'], path=self.source)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.revise), pool.submit(exact), pool.submit(poll, self.manager)]
            for future in futures: future.result(timeout=20)
        poll(self.manager)
        bound = self.manager.read()['tasks']['NEW']['executions'][0]['usage_bindings']
        self.assertEqual(bound, [{'session_id': 'synthetic-session', 'response_id': 'new-response'}])

    def test_projection_revalidates_native_registration_once_for_multiple_rows(self):
        self.fixture(); revision = self.revise(); poll(self.manager)
        resolve_attribution_limits(self.manager, revision['id'])
        from harness.usage_projection import project
        from harness.usage_revision import effective_registrations
        with patch('harness.usage_revision.effective_registrations', wraps=effective_registrations) as reader:
            result = project(self.root)
        self.assertEqual(reader.call_count, 1)
        self.assertIsNotNone(reader.call_args.kwargs['state'])
        self.assertIsNotNone(reader.call_args.kwargs['events'])
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['known_tokens'], 24)

    def test_dashboard_labels_share_one_registration_snapshot_for_multiple_rows(self):
        self.fixture(); self.revise(); poll(self.manager)
        from harness.dashboard_usage import apply_recorded_labels
        from harness.usage_revision import effective_registrations
        state = self.manager.read(); events = self.logger.read()
        usage = {'scope_info': {}, 'rows': [
            {'task_id': tid, 'agent_run_id': run['agent_run_id'], 'stage': 'synthetic', 'classification': 'synthetic'}
            for tid, run in [('OLD', self.old), ('NEW', self.new)]]}
        with patch('harness.usage_revision.effective_registrations', wraps=effective_registrations) as reader:
            apply_recorded_labels(usage, state['tasks'], events, self.root, state)
        self.assertEqual(reader.call_count, 1)
        self.assertIs(reader.call_args.kwargs['state'], state)
        self.assertIs(reader.call_args.kwargs['events'], events)
        self.assertTrue(all(row['usage_context']['actor'] == 'main_session' for row in usage['rows']))


if __name__ == '__main__':
    unittest.main()
