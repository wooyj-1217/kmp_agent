"""Regression checks for historical boundaries; all records here are synthetic."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness.usage_context import derive, resolve, recover
from harness.usage_projection import project
from harness.usage_provenance import execution_proof


class HistoricalProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.run = {'agent_run_id': 'a', 'run_id': 'r', 'role': 'development', 'kind': 'work',
                    'started_at': '2026-01-02', 'execution_mode': 'current_agent',
                    'usage_bindings': [{'session_id': 's', 'response_id': 'resp'}]}
        self.task = {'task_id': 'T', 'title': '제품 작업', 'role': 'development', 'project_id': 'p',
                     'executions': [self.run]}
        self.state = {'tasks': {'T': self.task}}
        self.installed = {'version': '0.2.0', 'commit': 'base', 'dirty': False, 'mode': 'installed'}
        self.dev = {**self.installed, 'dirty': True, 'mode': 'development'}
        self.events = [self.start(self.installed)]

    def start(self, identity, work='PRODUCT'):
        return {'event_id': 'start', 'event_type': 'agent_run_started', 'agent_run_id': 'a',
                'task_id': 'T', 'harness': identity, 'work_type': work}

    def test_same_version_is_not_same_capability_and_importer_is_not_executor(self):
        self.events.append({'event_type': 'model_usage', 'agent_run_id': 'a', 'harness': self.dev})
        old = execution_proof(self.task, self.run, self.events)
        self.assertEqual(old['execution_identity'], self.installed)
        self.assertEqual(old['work_domain'], 'product_work')
        self.assertEqual(old['actor'], 'unknown')
        new = execution_proof(self.task, self.run, [self.start(self.dev, 'HARNESS_BUILD')])
        self.assertEqual(new['work_domain'], 'agent_development_test')
        self.assertEqual(new['code_state'], 'unknown')
        self.assertFalse(new['support']['independent_call_observed'])

    def test_mode_role_and_spawn_flag_do_not_prove_independent_execution(self):
        for mode in ['current_agent', 'independent_process']:
            self.run['execution_mode'] = mode
            es = self.events + [{'event_type': 'role_process', 'agent_run_id': 'a',
                                'observed': {'process_state': 'role_process_started', 'independent_model_spawned': True}}]
            self.assertEqual(derive(self.state, self.task, self.run, es)['actor'], 'unknown')

    def test_matching_call_thread_and_bound_usage_prove_actor_without_released_version(self):
        self.run['execution_mode'] = 'independent_process'
        es = [self.start(self.dev, 'HARNESS_BUILD'),
              {'event_id': 'spawn', 'event_type': 'role_process', 'agent_run_id': 'a',
               'observed': {'call_id': 'call', 'process_state': 'role_process_started', 'independent_model_spawned': True}},
              {'event_type': 'role_process', 'agent_run_id': 'a',
               'observed': {'call_id': 'call', 'process_state': 'role_process_finished', 'thread_ids': ['s']}}]
        value = derive(self.state, self.task, self.run, es)
        self.assertEqual(value['actor'], 'independent_agent')
        self.assertEqual(value['provenance']['execution_identity'], self.dev)
        es[-1]['observed']['call_id'] = 'unrelated'
        self.assertEqual(derive(self.state, self.task, self.run, es)['actor'], 'unknown')

    def test_main_requires_explicit_native_context_and_keeps_development_role(self):
        regs = [{'id': 'reg', 'execution_id': 'a', 'task_id': 'T', 'session_id': 's', 'independent': False, 'turn_id': 'turn'}]
        usage = {'event_type': 'model_usage', 'source': {'session_id': 's'},
                 'observed': {'response_id': 'resp', 'turn_id': 'turn'}}
        events = self.events + [usage]
        value = derive(self.state, self.task, self.run, events, regs)
        self.assertEqual(value['actor'], 'main_session')
        self.assertEqual(value['role'], 'development')
        usage['observed']['turn_id'] = 'another-turn'
        self.assertEqual(derive(self.state, self.task, self.run, events, regs)['actor'], 'unknown')
        usage['observed']['turn_id'] = 'turn'
        regs[0]['task_id'] = 'other'
        self.assertEqual(derive(self.state, self.task, self.run, events, regs)['actor'], 'unknown')

    def test_missing_conflicting_or_dirty_source_identity_stays_unknown(self):
        self.assertIsNone(execution_proof(self.task, self.run, [])['execution_identity'])
        self.assertIsNone(execution_proof(self.task, self.run, [self.start(self.installed), self.start(self.dev)])['execution_identity'])
        proof = execution_proof(self.task, self.run, [self.start(self.dev)])
        self.assertEqual(proof['code_state'], 'unknown')
        self.assertNotIn('release_version', proof)

    def test_future_delegation_fields_cannot_retrofit_historical_run(self):
        self.task.update(parent_task_id='P', development_area='web')
        self.run['development_area'] = 'web'
        self.state['tasks']['P'] = {'task_id': 'P', 'development_delegation': {'areas': ['web']},
                                   'executions': [{'agent_run_id': 'parent', 'kind': 'work', 'run_id': 'r'}]}
        for es in [self.events, self.events + [{'event_id': 'future', 'event_type': 'development_child_linked',
                   'task_id': 'T', 'recorded_at': '2026-02-01', 'observed': {'parent_task_id': 'P', 'development_area': 'web'}}]]:
            value = derive(self.state, self.task, self.run, es)
            self.assertEqual(value['purpose'], 'unknown')
            self.assertEqual(value['development_owner'], 'unknown')
            self.assertNotIn('parent_execution_id', value)
        es = self.events + [{'event_id': 'actual', 'event_type': 'development_child_linked', 'task_id': 'T',
                            'recorded_at': '2026-01-01', 'observed': {'parent_task_id': 'P', 'development_area': 'web'}}]
        self.assertEqual(derive(self.state, self.task, self.run, es)['development_owner'], 'web')
        self.assertEqual(derive(self.state, self.task, self.run, es)['actor'], 'unknown')

    def test_future_runtime_changes_do_not_relabel_history_or_change_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / '.harness/tasks').mkdir(parents=True); (root / '.harness/logs').mkdir()
            (root / '.harness/tasks/tasks.yaml').write_text(json.dumps(self.state))
            events = self.events + [{'event_id': 'usage', 'event_type': 'model_usage', 'agent_run_id': 'a', 'task_id': 'T',
                'harness': self.dev, 'source': {'session_id': 's'}, 'observed': {'response_id': 'resp',
                'usage_semantics': 'per_response_increment', 'usage': {'input_tokens': 100, 'cached_input_tokens': 50,
                'output_tokens': 20, 'total_tokens': 120}}}]
            source = root / '.harness/logs/events.jsonl'
            source.write_text(''.join(json.dumps(e)+'\n' for e in events))
            originals = source.read_bytes(); recover(root); before = project(root)
            with patch('harness.version.identity', return_value={'version': 'future', 'commit': 'future'}):
                self.assertEqual(recover(root)['added'], 0)
                self.assertEqual(project(root), before)
            self.assertEqual(before['known_tokens'], 120)
            self.assertEqual(before['rows'][0]['provenance']['execution_identity'], self.installed)
            self.assertEqual(before['rows'][0]['collector_identities'], [self.dev])
            self.assertEqual(source.read_bytes(), originals)

    def test_later_qa_configuration_cannot_reclassify_old_implementation(self):
        self.task['qa_config'] = {'stage': 'retest', 'target_task_id': 'new-target'}
        events = self.events + [{'event_type': 'qa_configured', 'task_id': 'T',
                  'recorded_at': '2026-02-01', 'observed': self.task['qa_config']}]
        self.assertEqual(derive(self.state, self.task, self.run, events)['purpose'], 'unknown')
        events[-1]['recorded_at'] = '2026-01-01'
        self.assertEqual(derive(self.state, self.task, self.run, events)['purpose'], 'qa_retest')

    def test_new_start_freezes_current_typed_configuration_without_retrofitting_old_run(self):
        from harness.usage_context import frozen
        self.task['development_delegation'] = {'areas': ['web']}
        new = frozen(self.state, self.task, self.run)
        self.assertEqual(new['purpose'], 'coordination')
        self.assertEqual(new['development_owner'], 'coordinator')
        self.assertEqual(derive(self.state, self.task, self.run, self.events)['purpose'], 'unknown')
        self.task.pop('development_delegation')
        self.task['qa_config'] = {'stage': 'retest', 'target_task_id': 'target'}
        self.assertEqual(frozen(self.state, self.task, self.run)['purpose'], 'qa_retest')

    def test_repair_cause_uses_defect_ids_not_first_qa_attempt(self):
        self.state['issues'] = [{'id': 'defect', 'qa_task_id': 'QA'}]
        config = {'stage': 'implementation', 'target_task_id': 'target', 'repair_task_id': 'T',
                  'attempts': [{'agent_run_id': 'blocked', 'finding_ids': []},
                               {'agent_run_id': 'found-defect', 'finding_ids': ['defect']}]}
        self.state['tasks']['QA'] = {'task_id': 'QA', 'qa_config': config, 'executions': []}
        events = self.events + [{'event_type': 'qa_configured', 'task_id': 'QA', 'recorded_at': '2026-01-01',
                                 'observed': {'stage': 'implementation', 'target_task_id': 'target'}}]
        value = derive(self.state, self.task, self.run, events)
        self.assertEqual(value['purpose'], 'defect_fix')
        self.assertEqual(value['cause_execution_id'], 'found-defect')
        config['attempts'].append({'agent_run_id': 'ambiguous', 'finding_ids': ['defect']})
        self.assertIsNone(derive(self.state, self.task, self.run, events)['cause_execution_id'])

    def test_unregistered_work_type_is_not_guessed_as_product_or_agent_development(self):
        for work in ['UNKNOWN', 'IMPLEMENT', 'HARNESS_GUESSED']:
            self.assertEqual(execution_proof(self.task, self.run, [self.start(self.dev, work)])['work_domain'], 'unknown')

    def test_new_identity_records_fingerprints_without_inventing_release_version(self):
        from harness.version import identity
        value = identity()
        self.assertIn('harness/usage_context.py', value['source_sha256'])
        self.assertEqual(len(value['source_sha256']['harness/usage_context.py']), 64)
        expected = 'unreleased_worktree' if value['dirty'] is True else 'unconfirmed'
        self.assertEqual(value['release_status'], expected)
        self.assertNotEqual(value['release_status'], 'installed')
        self.assertEqual(value['version'], '0.2.0')


if __name__ == '__main__':
    unittest.main()
