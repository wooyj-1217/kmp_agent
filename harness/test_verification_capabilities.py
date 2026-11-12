"""Synthetic capability contracts, never a claim of live browser verification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import verification_capabilities as capabilities
from harness.logging import digest


class Manager:
    def __init__(self, root, state):
        self.root, self.run_id, self.state = root, 'RUN', state

    def _valid_artifact(self, ref):
        return True

    def artifact(self, path):
        data = (self.root / path).read_bytes()
        return {'path': path, 'snapshot': path, 'sha256': digest(data), 'snapshot_sha256': digest(data)}

    def _mutate(self, action, operation, task_id):
        return operation(self.state)

    def _event(self, *args, **kwargs):
        pass


class VerificationCapabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.argv = ['test-runner', '--suite', 'ui']
        self.target = {'task_id': 'DEV', 'work_type': 'PRODUCT', 'state': 'DONE',
                       'development_tracking': {'code_paths': ['src']},
                       'executions': [{'kind': 'work', 'ended_at': 'finished', 'actor_id': 'implementer'}]}
        self.task = {'task_id': 'QA', 'work_type': 'PRODUCT', 'state': 'IN_PROGRESS', 'role': 'verification',
                     'inputs': [], 'dependencies': [], 'execution_contract': {'grandfathered_active_attempts': {}},
                     'work_plan': {'version': 1}, 'work_plan_run_id': 'RUN',
                     'executions': [{'kind': 'work', 'role': 'verification', 'ended_at': None,
                                     'run_id': 'RUN', 'actor_id': 'independent-reviewer', 'agent_run_id': 'QA-WORK'}],
                     'qa_config': {'target_task_id': 'DEV', 'commands': [self.argv],
                                   'manifest_scope': {'mode': 'target_paths', 'paths': ['src']},
                                   'target_manifest': {'source': 'frozen'}, 'generated_paths': []}}
        self.state = {'tasks': {'DEV': self.target, 'QA': self.task},
                      'execution_policy': {'version': 1, 'apply_to_work_types': ['PRODUCT']},
                      'execution_plans': {'RUN': {'task_ids': ['DEV']}},
                      'execution_policy_bindings': {'RUN': {'root_session_id': 'SESSION'}}}
        self.manager = Manager(self.root, self.state)
        for name, replacement in (
            ('Tasks', lambda *args: self.manager),
            ('context', lambda *args: {}),
        ):
            mocked = patch.object(capabilities, name, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch('harness.qa.scoped_manifest', return_value={'source': 'frozen'})
        self.manifest = mocked.start()
        self.addCleanup(mocked.stop)
        mocked = patch.object(capabilities.development_constraints, 'load',
                              return_value={'policy': {'target_commands': {'web': [self.argv]}}})
        self.authority = mocked.start()
        self.addCleanup(mocked.stop)
        mocked = patch.object(capabilities.development_tracking, 'capture', return_value={'state_sha256': 'target-code'})
        self.capture = mocked.start()
        self.addCleanup(mocked.stop)

    def command(self, argv=None, **kwargs):
        return capabilities.authorize_command(self.root, self.state, 'SESSION', 'QA', self.argv if argv is None else argv, **kwargs)

    def test_guard_wrapper_and_internal_command_use_verification_contract(self):
        import shlex
        from harness import product_guard
        (self.root/'.kmp-agent').mkdir()
        (self.root/'.kmp-agent/installation.json').write_text('{}')
        ledger=self.root/'.harness/tasks/tasks.yaml'
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps(self.state))
        command='python3 .kmp-agent/agent.py command --run-id RUN --task-id QA --argv-json '+shlex.quote(json.dumps(self.argv))
        with patch.object(product_guard,'active',side_effect=AssertionError('implementation gate must not run')):
            result=product_guard.evaluate(self.root,dict(hook_event_name='PreToolUse',cwd=str(self.root),session_id='SESSION',tool_name='functions.exec_command',tool_input={'cmd':command}))
            self.assertEqual({},result)
            product_guard.authorize_command(self.root,self.state,'QA',self.argv,run_id='RUN')
        self.assertEqual('DONE',self.target['state'])

    def test_independent_qa_runs_against_completed_implementation(self):
        manager, task = self.command()
        self.assertIs(task, self.task)
        self.assertEqual('DONE', self.target['state'])
        self.assertEqual('IN_PROGRESS', self.task['state'])

    def test_target_actor_and_native_session_are_required(self):
        self.task['executions'][0]['actor_id'] = 'implementer'
        with self.assertRaisesRegex(ValueError, 'separately identified'):
            self.command()
        self.task['executions'][0]['actor_id'] = 'reviewer'
        with self.assertRaisesRegex(ValueError, 'different native session'):
            capabilities.authorize_command(self.root, self.state, 'OTHER', 'QA', self.argv)
        with self.assertRaisesRegex(ValueError, 'run differs'):
            self.command(run_id='OTHER')

    def test_changed_target_or_command_cannot_reuse_qa_authority(self):
        with self.assertRaisesRegex(ValueError, 'frozen approved'):
            self.command(['test-runner', '--delete-product'])
        self.manifest.return_value = {'source': 'changed'}
        with self.assertRaisesRegex(ValueError, 'target changed'):
            self.command()
        self.manifest.return_value = {'source': 'frozen'}
        self.authority.return_value = {'policy': {'target_commands': {'web': []}}}
        with self.assertRaisesRegex(ValueError, 'authoritative'):
            self.command()

    def test_completed_or_wrong_role_qa_cannot_run(self):
        self.task['state'] = 'DONE'
        with self.assertRaisesRegex(ValueError, 'active verification role'):
            self.command()
        self.task['state'] = 'IN_PROGRESS'
        self.task['executions'][0]['role'] = 'development'
        with self.assertRaisesRegex(ValueError, 'active verification role'):
            self.command()

    def test_native_review_does_not_require_active_implementation(self):
        del self.task['qa_config']
        self.task['state'] = 'IN_REVIEW'
        self.task['development_tracking'] = {'code_paths': ['src']}
        self.task['executions'].insert(0, {'kind': 'work', 'ended_at': 'finished', 'actor_id': 'implementer'})
        self.task['executions'][-1]['kind'] = 'review'
        self.state['execution_plans']['RUN']['task_ids'] = ['QA']
        with patch.object(capabilities.development_tracking, 'ensure') as ensure:
            self.command()
            ensure.assert_called_once()

    def test_native_certification_begin_changes_done_to_review_state(self):
        from harness.logging import Logger
        from harness.tasks import Tasks
        self.authority.return_value = None
        logger = Logger(self.root)
        run_id = logger.start('HARNESS_IMPROVEMENT', 'orchestrator', 'synthetic certification review')
        manager = Tasks(self.root, run_id)
        (self.root / 'input.md').write_text('synthetic input')
        (self.root / 'output.md').write_text('synthetic output')
        (self.root / 'review.md').write_text('synthetic review evidence')
        manager.register('FEATURE', 'CERT', 'planning', 'certification', 'synthetic documents',
                         [{'id': 'AC', 'required': True}], ['input.md'], execution_scope='documentation')
        manager.ready('CERT')
        work = manager.begin('CERT', 'planning', actor_id='implementer')
        manager.submit('CERT', work['agent_run_id'], ['output.md'], 'synthetic implementation')
        review = manager.begin('CERT', 'verification', review=True, actor_id='first-reviewer')
        manager.review('CERT', review['agent_run_id'], [{'criterion_id': 'AC', 'result': 'PASS', 'evidence': 'review.md'}], 'synthetic review')
        self.assertEqual('DONE', manager.read()['tasks']['CERT']['state'])
        manager._mutate('synthetic_current_review', lambda state: state['tasks']['CERT'].setdefault('validation_status', {}).update(
            {review['agent_run_id']: {'state': 'CURRENT'}}), 'CERT')
        # Scope semantics are covered by completion's own tests; this isolates
        # the native lifecycle transition that the capability gate consumes.
        with patch('harness.completion.execution_review', return_value=True):
            fresh = manager.begin('CERT', 'verification', review=True, actor_id='certification-reviewer')
        self.assertEqual('IN_REVIEW', manager.read()['tasks']['CERT']['state'])
        self.assertEqual('review', fresh['kind'])

    def fixture(self):
        return {'version': 1, 'target_task_id': 'DEV', 'tools': [
            {'tool_name': 'mcp__synthetic_ui__screenshot', 'target': {'tab_id': 'test-tab'},
             'input': {'tab_id': 'test-tab', 'path': 'verification/screen.png'}}]}

    def freeze_ui(self):
        self.task.pop('qa_config', None)
        self.task['state'] = 'TODO'
        self.task['executions'] = []
        self.task['verification_contract'] = {'procedure': 'synthetic'}
        self.state['execution_plans']['RUN']['task_ids'].append('QA')
        path = self.root / 'ui-capabilities.json'
        path.write_text(json.dumps(self.fixture()))
        capabilities.configure(self.manager, 'QA', path.name)
        self.task['state'] = 'IN_PROGRESS'
        self.task['executions'] = [{'kind': 'work', 'role': 'verification', 'ended_at': None,
                                    'run_id': 'RUN', 'actor_id': 'reviewer', 'agent_run_id': 'QA-UI'}]

    def test_only_exact_frozen_ui_target_and_input_are_allowed(self):
        self.freeze_ui()
        fixture = self.fixture()['tools'][0]
        capabilities.authorize_tool(self.root, self.state, 'SESSION', fixture['tool_name'], fixture['input'])
        for args in ({**fixture['input'], 'tab_id': 'unrelated-tab'},
                     {**fixture['input'], 'extra': True}, {'tab_id': 'test-tab'}):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'exact frozen'):
                capabilities.authorize_tool(self.root, self.state, 'SESSION', fixture['tool_name'], args)
        self.capture.return_value = {'state_sha256': 'changed-code'}
        with self.assertRaisesRegex(ValueError, 'target code changed'):
            capabilities.authorize_tool(self.root, self.state, 'SESSION', fixture['tool_name'], fixture['input'])

    def test_guard_routes_structured_ui_fixture_without_implementation_authority(self):
        from harness import product_guard
        self.freeze_ui()
        (self.root/'.kmp-agent').mkdir()
        (self.root/'.kmp-agent/installation.json').write_text('{}')
        ledger=self.root/'.harness/tasks/tasks.yaml'
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps(self.state))
        fixture=self.fixture()['tools'][0]
        payload=dict(hook_event_name='PreToolUse',cwd=str(self.root),session_id='SESSION',tool_name=fixture['tool_name'],tool_input=fixture['input'])
        self.assertEqual({},product_guard.evaluate(self.root,payload))
        payload['tool_input']={**fixture['input'],'tab_id':'another-tab'}
        self.assertEqual('deny',product_guard.evaluate(self.root,payload)['hookSpecificOutput']['permissionDecision'])

    def test_ui_output_symlink_cannot_write_product_source(self):
        self.freeze_ui()
        (self.root/'src').mkdir()
        (self.root/'verification').symlink_to(self.root/'src',target_is_directory=True)
        fixture=self.fixture()['tools'][0]
        with self.assertRaisesRegex(ValueError,'symlinks'):
            capabilities.authorize_tool(self.root,self.state,'SESSION',fixture['tool_name'],fixture['input'])

    def test_ui_contract_freezes_once_and_source_changes_revoke_it(self):
        self.freeze_ui()
        with self.assertRaisesRegex(ValueError, 'frozen once'):
            capabilities.configure(self.manager, 'QA', 'ui-capabilities.json')
        (self.root / 'ui-capabilities.json').write_text(json.dumps(self.fixture()) + '\n')
        fixture = self.fixture()['tools'][0]
        with self.assertRaisesRegex(ValueError, 'snapshot is missing or changed'):
            capabilities.authorize_tool(self.root, self.state, 'SESSION', fixture['tool_name'], fixture['input'])

    def test_ui_json_types_and_session_are_exact(self):
        fixture = self.fixture()
        fixture['tools'][0]['input']['emit'] = True
        self.fixture = lambda: fixture
        self.freeze_ui()
        tool = fixture['tools'][0]
        capabilities.authorize_tool(self.root, self.state, 'SESSION', tool['tool_name'], tool['input'])
        with self.assertRaisesRegex(ValueError, 'exact frozen'):
            capabilities.authorize_tool(self.root, self.state, 'SESSION', tool['tool_name'], {**tool['input'], 'emit': 1})
        with self.assertRaisesRegex(ValueError, 'exact frozen'):
            capabilities.authorize_tool(self.root, self.state, 'OTHER', tool['tool_name'], tool['input'])

    def test_pending_required_answer_still_blocks_verification(self):
        self.state['required_questions'] = {'QUESTION': {'status': 'OPEN', 'affected_task_ids': ['DEV']}}
        with self.assertRaisesRegex(ValueError, 'required human answer pending'):
            self.command()

    def test_ui_scripts_and_unpinned_inputs_are_rejected_before_freezing(self):
        for mutate in (
            lambda f: f['tools'][0].update(tool_name='mcp__cua_repl__js'),
            lambda f: f['tools'][0].update(tool_name='mcp__filesystem__write_file'),
            lambda f: f['tools'][0]['input'].update(path='src/App.kt'),
            lambda f: f['tools'][0]['input'].update(path='verification/../src/App.kt'),
            lambda f: f['tools'][0]['input'].update(code='await arbitrary()'),
            lambda f: f['tools'][0]['input'].update(nested={'command': 'rm product'}),
            lambda f: f['tools'][0]['target'].clear(),
            lambda f: f['tools'][0]['input'].update(tab_id='wrong-tab'),
        ):
            fixture = copy.deepcopy(self.fixture())
            mutate(fixture)
            with self.assertRaises(ValueError):
                capabilities.validate(fixture)


if __name__ == '__main__':
    unittest.main()
