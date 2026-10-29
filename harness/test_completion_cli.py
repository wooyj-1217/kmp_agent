"""Selected-entry routing against synthetic native usage; no external model calls."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from harness import cli, test_usage_context as fixtures


class CompletionCliTests(unittest.TestCase):
    setUp = fixtures.UsageContextTests.setUp
    begin = fixtures.UsageContextTests.begin
    native = fixtures.UsageContextTests.native

    def invoke(self, action, **options):
        argv = ['agent.py', '--target', str(self.root), action, '--run-id', self.rid]
        for key, value in options.items():
            argv += ['--' + key.replace('_', '-'), str(value)]
        output = io.StringIO()
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output), \
             patch.object(cli.bootstrap, 'read', return_value={'mode': 'development'}), \
             patch.object(cli.bootstrap, 'reference', return_value=cli.ROOT), \
             patch.object(cli.bootstrap, 'validate'), patch('harness.logging.resolve_session', return_value=None):
            code = cli.main()
        return code, json.loads(output.getvalue())

    def test_usage_register_collects_only_explicit_turn_and_poll_is_idempotent(self):
        work = self.begin('MAIN')
        source = self.native('main', [('selected', 'current', 100), ('old', 'unrelated', 200)])
        data = self.root / 'registration.json'
        data.write_text(json.dumps({'session_id': 'main', 'path': str(source), 'turn_id': 'current'}))
        code, result = self.invoke('usage-register', task_id='MAIN', agent_run_id=work['agent_run_id'], data=data)
        self.assertEqual(code, 0)
        self.assertEqual(result['registration']['import_scope'], 'registered_turns')
        self.assertEqual(result['collection']['new_bindings'], 1)
        usage = [e for e in self.logger.read() if e['event_type'] == 'model_usage']
        self.assertEqual([e['observed']['response_id'] for e in usage], ['selected'])
        code, result = self.invoke('usage-poll')
        self.assertEqual((code, result['new_bindings']), (0, 0))

    def test_configure_completion_routes_through_selected_entry(self):
        self.manager.register('F', 'T', 'planning', 'synthetic', 'documents',
                              [{'id': 'AC', 'required': True}], ['input.md'], execution_scope='documentation')
        data = self.root / 'completion.json'
        data.write_text(json.dumps({'task_id': 'T', 'context_paths': ['input.md']}))
        code, result = self.invoke('task', operation='configure-completion', data=data)
        self.assertEqual(code, 0)
        self.assertTrue(result['usage_required'])
        self.assertTrue(result['context_required'])

    def test_missing_native_identity_and_unknown_fields_are_rejected(self):
        work = self.begin('MAIN')
        data = self.root / 'bad.json'
        for body in ({'session_id': 'main', 'invented': True}, []):
            data.write_text(json.dumps(body))
            code, result = self.invoke('usage-register', task_id='MAIN', agent_run_id=work['agent_run_id'], data=data)
            self.assertEqual((code, result['result']), (1, 'FAIL'))
        self.assertFalse((self.root / '.harness/usage/sessions.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
