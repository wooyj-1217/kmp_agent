"""Independent offline workspace selection and fail-closed orchestration tests."""
import copy
import contextlib
import io
import sys
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import regression
from harness import regression_workspace as workspace


class RegressionWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = {}
        layout = {'harness-project': [('server-api', 'server', True), ('server-negative', 'server', False)],
                  'client-project': [('android-ui', 'android', True), ('ios-ui', 'ios', True), ('web-ui', 'web', True),
                                   ('common-logic', 'common', False), ('android-lint', 'android', False),
                                   ('android-screen', 'android', False), ('web-lint', 'web', False)]}
        for name, entries in layout.items():
            root = self.root/name; root.mkdir()
            catalog = {'schema_version': 1, 'scenarios': []}
            definition = {'schema_version': 1, 'plan_version': name + '-v1', 'checks': []}
            for identity, platform, smoke in entries:
                criterion = 'C-' + identity
                definition['checks'].append({'id': identity, 'criterion_id': criterion, 'platform': platform,
                    'kind': 'api' if platform == 'server' else 'test', 'required': True,
                    'command': ['rtk', 'proxy', 'python3', 'fixture.py', '--case', identity],
                    'expected': 'isolated synthetic contract result', 'expected_tests': [identity],
                    'results': [{'path': 'verification/' + identity + '.xml', 'format': 'junit'}]})
                catalog['scenarios'].append({'id': identity, 'criterion_id': criterion, 'platform': platform,
                    'tool': 'fixture', 'scope': 'API fixture' if platform == 'server' else 'client fixture',
                    'definition': 'definition.json', 'check_id': identity,
                    'suites': ['smoke', 'full'] if smoke else ['full'], 'required': True, 'owner': 'fixture-team'})
            (root/'catalog.json').write_text(json.dumps(catalog))
            (root/'definition.json').write_text(json.dumps(definition))
            (root/'code.txt').write_text('initial source')
            self.projects[name] = {'root': root, 'catalog': catalog, 'definition': definition}
        self.config = {'schema_version': 1, 'required_platforms': ['android', 'ios', 'web', 'server'],
                       'projects': [{'id': name, 'root': name, 'catalog': 'catalog.json'} for name in layout]}
        self.path = self.root/'harness-project/workspace.json'
        self.save()
        location = patch.object(workspace, '__file__', str(self.root/'harness-project/harness/regression_workspace.py'))
        location.start(); self.addCleanup(location.stop)
        source = patch.object(regression.runner, 'source_state', side_effect=self.source_state)
        source.start(); self.addCleanup(source.stop)

    def source_state(self, root):
        return {'commit': 'fixture-commit', 'manifest_sha256': hashlib.sha256((Path(root)/'code.txt').read_bytes()).hexdigest()}

    def save(self):
        self.path.write_text(json.dumps(self.config))
        for item in self.projects.values():
            (item['root']/'catalog.json').write_text(json.dumps(item['catalog']))
            (item['root']/'definition.json').write_text(json.dumps(item['definition']))

    def selected_ids(self, result):
        return [identity for item in result['projects'] for identity in item['plan']['selection']['scenario_ids']]

    def fake_run(self, root, catalog, output, suite='smoke', platforms=None, scenarios=None, timeout=300):
        selection = regression.plan(root, catalog, suite, platforms, scenarios)
        target = Path(root)/output
        target.mkdir(parents=True, exist_ok=False)
        summary = {'authority': regression.AUTHORITY, 'official': False, 'full_completion': False,
                   'selection_result': 'OBSERVED_PASS', 'result': 'OBSERVED_PASS', 'selection': selection['selection'],
                   'source_final': self.source_state(root)}
        (target/'summary.json').write_text(json.dumps(summary))
        return summary

    def test_smoke_covers_four_platforms_and_full_selects_nine_without_execution(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))
        with patch.object(regression, 'run', side_effect=AssertionError('list executed tools')):
            smoke = workspace.plan(self.root, self.path)
            full = workspace.plan(self.root, self.path, suite='full')
        self.assertEqual(len(self.selected_ids(smoke)), 4)
        self.assertEqual(len(self.selected_ids(full)), 9)
        self.assertEqual({platform for item in smoke['projects'] for platform in item['plan']['selection']['platforms']}, {'android', 'ios', 'web', 'server'})
        self.assertFalse(smoke['full_completion'])
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*')))

    def test_platform_and_scenario_filters_skip_unselected_project(self):
        result = workspace.plan(self.root, self.path, platforms=['android'])
        self.assertEqual(self.selected_ids(result), ['android-ui'])
        self.assertEqual(len(result['projects']), 1)
        result = workspace.plan(self.root, self.path, suite='full', scenarios=['server-negative'])
        self.assertEqual(self.selected_ids(result), ['server-negative'])

    def test_unknown_excluded_and_inconsistent_requests_fail_before_execution(self):
        for kwargs in [{'platforms': ['desktop']}, {'scenarios': ['unknown']},
                       {'scenarios': ['server-negative']},
                       {'platforms': ['android'], 'scenarios': ['ios-ui']}, {'suite': 'nightly'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                workspace.plan(self.root, self.path, **kwargs)

    def test_missing_required_platform_is_not_smoke_success(self):
        self.projects['client-project']['catalog']['scenarios'][1]['suites'] = ['full']
        self.save()
        with self.assertRaises(ValueError): workspace.plan(self.root, self.path)
        self.assertEqual(self.selected_ids(workspace.plan(self.root, self.path, platforms=['android'])), ['android-ui'])

    def test_duplicate_project_identity_root_and_cross_project_scenario_fail(self):
        original = copy.deepcopy(self.config)
        for field in ['id', 'root']:
            self.config = copy.deepcopy(original)
            self.config['projects'][1][field] = self.config['projects'][0][field]; self.save()
            with self.subTest(field=field), self.assertRaises(ValueError): workspace.plan(self.root, self.path)
        self.config = original
        self.projects['client-project']['catalog']['scenarios'][0]['id'] = 'server-api'; self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate.*scenario'): workspace.plan(self.root, self.path)

    def test_project_and_catalog_escape_paths_are_rejected(self):
        for key, value in [('root', '../outside'), ('root', str(self.root/'client-project')), ('catalog', '../harness-project/catalog.json')]:
            original = copy.deepcopy(self.config)
            self.config['projects'][1][key] = value; self.save()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): workspace.plan(self.root, self.path)
            self.config = original

    def test_all_success_writes_project_refs_and_workspace_index(self):
        with patch.object(regression, 'run', side_effect=self.fake_run) as execute:
            result = workspace.run(self.root, self.path)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(result['selection_result'], 'OBSERVED_PASS')
        self.assertFalse(result['full_completion'])
        self.assertTrue(Path(result['summary']).is_file())
        self.assertTrue(all(row['result'] == 'OBSERVED_PASS' for row in result['results']))

    def test_one_project_execution_failure_retains_other_project_result(self):
        def execute(root, *args, **kwargs):
            if Path(root).name == 'harness-project': raise OSError('server fixture unavailable')
            return self.fake_run(root, *args, **kwargs)
        with patch.object(regression, 'run', side_effect=execute): result = workspace.run(self.root, self.path)
        self.assertEqual(result['selection_result'], 'FAIL')
        self.assertEqual([row['result'] for row in result['results']], ['FAIL', 'OBSERVED_PASS'])
        self.assertIn('server fixture unavailable', result['results'][0]['error'])

    def test_workspace_configuration_mutation_during_execution_blocks_aggregate(self):
        def changed(*args, **kwargs):
            value = self.fake_run(*args, **kwargs)
            self.path.write_text(self.path.read_text() + '\n')
            return value
        with patch.object(regression, 'run', side_effect=changed): result = workspace.run(self.root, self.path)
        self.assertEqual(result['selection_result'], 'FAIL')
        self.assertFalse(result['workspace_unchanged'])

    def test_other_project_definition_changes_after_workspace_plan_cannot_pass(self):
        def changed(root, *args, **kwargs):
            value = self.fake_run(root, *args, **kwargs)
            if Path(root).name == 'harness-project':
                path = self.projects['client-project']['root']/'definition.json'
                definition = json.loads(path.read_text()); definition['plan_version'] = 'unreviewed-v2'
                path.write_text(json.dumps(definition))
            return value
        with patch.object(regression, 'run', side_effect=changed): result = workspace.run(self.root, self.path)
        self.assertEqual(result['selection_result'], 'FAIL')

    def test_later_project_modifying_completed_project_source_blocks_workspace(self):
        def changed(root, *args, **kwargs):
            value = self.fake_run(root, *args, **kwargs)
            if Path(root).name == 'client-project':
                (self.projects['harness-project']['root']/'code.txt').write_text('changed after server observation')
            return value
        with patch.object(regression, 'run', side_effect=changed): result = workspace.run(self.root, self.path)
        self.assertEqual(result['selection_result'], 'FAIL')

    def test_later_project_changing_completed_project_ignored_definition_blocks_workspace(self):
        def changed(root, *args, **kwargs):
            value = self.fake_run(root, *args, **kwargs)
            if Path(root).name == 'client-project':
                # source_state intentionally hashes only code.txt in this fixture;
                # ignored definition changes must be caught by final plan checks.
                path = self.projects['harness-project']['root']/'definition.json'
                definition = json.loads(path.read_text())
                definition['plan_version'] = 'changed-after-server-completed'
                path.write_text(json.dumps(definition))
            return value
        with patch.object(regression, 'run', side_effect=changed):
            result = workspace.run(self.root, self.path)
        self.assertEqual(result['selection_result'], 'FAIL')
        self.assertFalse(result['plans_consistent'])

    def test_invalid_workspace_schema_and_duplicate_filters_fail_closed(self):
        original = copy.deepcopy(self.config)
        for update in [{'schema_version': True}, {'projects': []}, {'required_platforms': ['android', 'unknown']}]:
            self.config = {**copy.deepcopy(original), **update}; self.save()
            with self.subTest(update=update), self.assertRaises(ValueError): workspace.plan(self.root, self.path)
        self.config = original; self.save()
        with self.assertRaises(ValueError): workspace.plan(self.root, self.path, platforms=['android', 'android'])
        with self.assertRaises(ValueError): workspace.plan(self.root, self.path, scenarios=['android-ui', 'android-ui'])

    def test_deleted_workspace_config_preserves_failed_index(self):
        def deleted(*args, **kwargs):
            value = self.fake_run(*args, **kwargs)
            self.path.unlink(missing_ok=True)
            return value
        with patch.object(regression, 'run', side_effect=deleted): result = workspace.run(self.root, self.path)
        self.assertEqual(result['selection_result'], 'FAIL')
        self.assertFalse(result['workspace_unchanged'])

    def test_cli_requires_explicit_workspace_without_dispatch(self):
        with patch.object(sys, 'argv', ['regression_workspace', 'list']), contextlib.redirect_stderr(io.StringIO()) as errors, patch.object(workspace, 'plan') as plan:
            with self.assertRaises(SystemExit) as exit:
                workspace.main()
        self.assertEqual(exit.exception.code, 2)
        self.assertIn('--workspace', errors.getvalue())
        plan.assert_not_called()

    def test_cli_dispatches_only_the_explicit_workspace(self):
        with patch.object(sys, 'argv', ['regression_workspace', 'list', '--workspace-root', str(self.root), '--workspace', str(self.path)]), patch.object(workspace, 'plan', return_value={'selection_result':'OBSERVED_PASS'}) as plan, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workspace.main(), 0)
        self.assertEqual(plan.call_args.args[:2], (str(self.root), str(self.path)))


if __name__ == '__main__':
    unittest.main()
