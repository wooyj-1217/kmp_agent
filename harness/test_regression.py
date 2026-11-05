"""Offline orchestration tests; actual platform tools are exercised elsewhere."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import regression as rg


class RegressionCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source_patch = patch.object(rg.runner, 'source_state', return_value={'commit': 'submitted-commit', 'manifest_sha256': 'source-hash'})
        source_patch.start(); self.addCleanup(source_patch.stop)
        self.definitions = {}
        self.scenarios = []
        for platform in ['android', 'ios', 'web', 'server']:
            group = 'server' if platform == 'server' else 'client'
            check = {'id': 'save-' + platform, 'criterion_id': 'API' if platform == 'server' else 'RESTORE',
                     'platform': platform, 'kind': 'api' if platform == 'server' else 'ui', 'required': True,
                     'command': ['rtk', 'proxy', 'python3', 'scenario.py', '--platform', platform],
                     'expected': 'unique memo is returned exactly', 'expected_tests': ['restore-' + platform],
                     'results': [{'path': 'verification/' + platform + '.xml', 'format': 'junit'}]}
            definition = self.definitions.setdefault(group, {'schema_version': 1, 'plan_version': group + '-approved-v2', 'checks': []})
            definition['checks'].append(check)
            self.scenarios.append({'id': platform + '-restore', 'criterion_id': check['criterion_id'],
                'platform': platform, 'tool': 'http' if platform == 'server' else 'ui-tool', 'scope': 'isolated fixture',
                'definition': group + '.json', 'check_id': check['id'],
                'suites': ['full'] if platform == 'ios' else ['smoke', 'full'], 'required': True, 'owner': 'team'})
        self.catalog = {'schema_version': 1, 'scenarios': self.scenarios}
        self.save()

    def save(self):
        (self.root/'catalog.json').write_text(json.dumps(self.catalog))
        for name, definition in self.definitions.items():
            (self.root/(name + '.json')).write_text(json.dumps(definition))

    def observed(self, definition, root, timeout=300):
        rows = [{**copy.deepcopy(check), 'status': 'OBSERVED_PASS', 'result': 'OBSERVED_PASS',
                 'reason': 'EXPECTED_SCENARIOS_PASSED', 'scenarios': [{'id': check['expected_tests'][0], 'result': 'PASS'}],
                 'result_files': [{'path': 'verification/result.xml', 'sha256': 'result-hash'}], 'outputs': []}
                for check in definition['checks']]
        return {'authority': 'UNTRUSTED_OBSERVATION', 'plan_version': definition['plan_version'],
                'definition_sha256': rg.runner.digest(rg.runner.canonical(definition)),
                'source': {'commit': 'submitted-commit', 'manifest_sha256': 'source-hash'},
                'source_after': {'commit': 'submitted-commit', 'manifest_sha256': 'source-hash'}, 'checks': rows}

    def test_list_is_read_only_and_preserves_approved_group_versions(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result = rg.plan(self.root, 'catalog.json', 'smoke', output='verification/new-run')
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
        self.assertEqual(result['selection']['scenario_ids'], ['android-restore', 'web-restore', 'server-restore'])
        client = result['groups'][0]
        self.assertEqual(client['original_plan_version'], 'client-approved-v2')
        self.assertEqual(client['excluded_check_ids'], ['save-ios'])
        self.assertFalse(result['official']); self.assertFalse(result['full_completion'])

    def test_selected_checks_execute_once_per_definition_and_index_platform_results(self):
        with patch.object(rg.runner, 'run_verification', side_effect=self.observed) as execute:
            summary = rg.run(self.root, 'catalog.json', 'verification/smoke', 'smoke')
        self.assertEqual(execute.call_count, 2)
        self.assertEqual([check['id'] for check in execute.call_args_list[0].args[0]['checks']], ['save-android', 'save-web'])
        self.assertEqual(summary['result'], 'OBSERVED_PASS')
        self.assertNotIn('ios', summary['platforms'])
        self.assertEqual(summary['scenarios'][0]['source']['manifest_sha256'], 'source-hash')
        for group in summary['groups']:
            path = self.root/group['receipt_path']
            self.assertEqual(group['receipt_sha256'], rg.runner.digest(path.read_bytes()))
            self.assertTrue(group['provenance_valid'])
        self.assertTrue((self.root/'verification/smoke/summary.json').is_file())
        self.assertEqual(len(self.definitions['client']['checks']), 3)

    def test_missing_selected_required_row_cannot_pass(self):
        def missing(*args, **kwargs):
            observed = self.observed(*args, **kwargs)
            observed['checks'] = []
            return observed
        with patch.object(rg.runner, 'run_verification', side_effect=missing):
            summary = rg.run(self.root, 'catalog.json', 'verification/missing', 'full', scenarios=['ios-restore'])
        self.assertEqual(summary['result'], 'NOT_RUN')
        self.assertEqual(summary['scenarios'][0]['reason'], 'RUNNER_RESULT_MISSING')

    def test_failure_and_original_reason_are_preserved(self):
        def failed(*args, **kwargs):
            value = self.observed(*args, **kwargs)
            value['checks'][0].update(result='FAIL', status='FAIL', reason='SCENARIO_FAILED')
            return value
        with patch.object(rg.runner, 'run_verification', side_effect=failed):
            summary = rg.run(self.root, 'catalog.json', 'verification/fail', platforms=['server'])
        self.assertEqual(summary['result'], 'FAIL')
        self.assertEqual(summary['scenarios'][0]['reason'], 'SCENARIO_FAILED')

    def test_result_provenance_and_binding_mismatch_fail_closed(self):
        for mutation in ['digest', 'platform', 'duplicate', 'source', 'status']:
            def corrupted(*args, **kwargs):
                value = self.observed(*args, **kwargs)
                if mutation == 'digest': value['definition_sha256'] = 'wrong'
                elif mutation == 'platform': value['checks'][0]['platform'] = 'ios'
                elif mutation == 'duplicate': value['checks'].append(copy.deepcopy(value['checks'][0]))
                elif mutation == 'source': value['source_after']['manifest_sha256'] = 'changed'
                else: value['checks'][0]['status'] = 'FAIL'
                return value
            with self.subTest(mutation=mutation), patch.object(rg.runner, 'run_verification', side_effect=corrupted):
                summary = rg.run(self.root, 'catalog.json', 'verification/' + mutation, platforms=['server'])
            self.assertEqual(summary['result'], 'NOT_RUN')
            self.assertNotEqual(summary['scenarios'][0]['reason'], 'EXPECTED_SCENARIOS_PASSED')

    def test_changed_ignored_definition_invalidates_observation(self):
        def changed(*args, **kwargs):
            value = self.observed(*args, **kwargs)
            (self.root/'server.json').write_text('{}')
            return value
        with patch.object(rg.runner, 'run_verification', side_effect=changed):
            summary = rg.run(self.root, 'catalog.json', 'verification/changed', platforms=['server'])
        self.assertEqual(summary['result'], 'NOT_RUN')
        self.assertEqual(summary['changed_regression_inputs'], ['server.json'])
        self.assertEqual(summary['scenarios'][0]['observation']['result'], 'OBSERVED_PASS')

    def test_selection_rejects_unknown_empty_and_excluded_requests(self):
        for kwargs in [{'suite': 'unknown'}, {'platforms': ['desktop']}, {'scenarios': ['missing']},
                       {'platforms': ['ios']}, {'scenarios': ['ios-restore']},
                       {'platforms': ['server'], 'scenarios': ['android-restore']}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                rg.plan(self.root, 'catalog.json', **kwargs)

    def test_duplicate_ids_bindings_and_same_commands_are_rejected(self):
        duplicate = copy.deepcopy(self.scenarios[0])
        self.scenarios.append(duplicate); self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate scenario'): rg.plan(self.root, 'catalog.json')
        duplicate['id'] = 'different-id'; self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate definition/check'): rg.plan(self.root, 'catalog.json')
        self.scenarios.pop()
        self.definitions['client']['checks'][2]['command'] = self.definitions['client']['checks'][0]['command'][:]
        self.save()
        with self.assertRaisesRegex(ValueError, 'share a command'): rg.plan(self.root, 'catalog.json')

    def test_invalid_binding_definition_and_catalog_paths_are_rejected(self):
        for key, value in [('platform', 'common'), ('criterion_id', 'wrong'), ('check_id', 'unknown'),
                           ('definition', '../escape.json'), ('required', False), ('suites', ['nightly'])]:
            original = copy.deepcopy(self.scenarios[0])
            self.scenarios[0][key] = value; self.save()
            with self.subTest(key=key), self.assertRaises((ValueError, OSError)):
                rg.load_catalog(self.root, 'catalog.json')
            self.scenarios[0] = original
        self.catalog['scenarios'] = self.scenarios
        self.catalog['schema_version'] = True; self.save()
        with self.assertRaises(ValueError): rg.load_catalog(self.root, 'catalog.json')

    def test_outputs_are_verification_only_new_and_never_follow_symlinks(self):
        for output in ['summary.json', '../outside', 'verification']:
            with self.subTest(output=output), self.assertRaises(ValueError):
                rg.plan(self.root, 'catalog.json', output=output)
        with patch.object(rg.runner, 'run_verification', side_effect=self.observed):
            rg.run(self.root, 'catalog.json', 'verification/once', platforms=['server'])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            rg.run(self.root, 'catalog.json', 'verification/once', platforms=['server'])
        (self.root/'verification/link').symlink_to(self.root/'verification/once', target_is_directory=True)
        with self.assertRaises(ValueError): rg.plan(self.root, 'catalog.json', output='verification/link/child')

    def test_cli_lists_without_writes_and_run_requires_new_output(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = rg.main(['list', '--catalog', 'catalog.json', '--root', str(self.root), '--platform', 'server'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())['selection']['scenario_ids'], ['server-restore'])
        self.assertFalse((self.root/'verification').exists())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            rg.main(['run', '--catalog', 'catalog.json', '--root', str(self.root)])
        self.assertEqual(error.exception.code, 2)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(rg.runner, 'run_verification', side_effect=self.observed):
            result = rg.main(['run', '--catalog', 'catalog.json', '--root', str(self.root), '--platform', 'server', '--output', 'verification/cli'])
        self.assertEqual(result, 0)

    def test_runner_exception_is_preserved_without_success(self):
        with patch.object(rg.runner, 'run_verification', side_effect=OSError('tool unavailable')):
            result = rg.run(self.root, 'catalog.json', 'verification/unavailable', platforms=['server'])
        self.assertEqual(result['result'], 'NOT_RUN')
        self.assertEqual(result['scenarios'][0]['reason'], 'RUNNER_ERROR')
        receipt = json.loads((self.root/result['groups'][0]['receipt_path']).read_text())
        self.assertEqual(receipt['error'], 'tool unavailable')

    def test_different_group_source_or_final_source_cannot_form_pass(self):
        def changed_group(definition, root, timeout=300):
            value = self.observed(definition, root, timeout)
            if definition['plan_version'].startswith('server'):
                value['source'].update(commit='later-commit', manifest_sha256='later-source')
                value['source_after'].update(commit='later-commit', manifest_sha256='later-source')
            return value
        with patch.object(rg.runner, 'run_verification', side_effect=changed_group):
            result = rg.run(self.root, 'catalog.json', 'verification/mixed-source')
        self.assertEqual(result['result'], 'NOT_RUN')
        self.assertEqual(result['source_mismatched_groups'], ['server.json'])
        self.assertTrue(all(row['observation']['result'] == 'OBSERVED_PASS' for row in result['scenarios']))
        with patch.object(rg.runner, 'source_state', side_effect=[{'commit': 'submitted-commit', 'manifest_sha256': 'source-hash'},
                                                               {'commit': 'final-change', 'manifest_sha256': 'final-hash'}]), \
             patch.object(rg.runner, 'run_verification', side_effect=self.observed):
            result = rg.run(self.root, 'catalog.json', 'verification/final-source', platforms=['server'])
        self.assertEqual(result['result'], 'NOT_RUN')
        self.assertEqual(result['scenarios'][0]['reason'], 'SOURCE_CHANGED_DURING_REGRESSION')


if __name__ == '__main__':
    unittest.main()
