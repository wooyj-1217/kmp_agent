import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness.verification_runner import run_verification, source_state, validate_definition


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["rtk", "proxy", 'git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(["rtk", "proxy", 'git', '-C', str(self.root), 'config', 'user.email', 'test@example.com'], check=True)
        subprocess.run(["rtk", "proxy", 'git', '-C', str(self.root), 'config', 'user.name', 'Test'], check=True)
        (self.root / '.gitignore').write_text('result.xml\nreceipt.json\n')
        subprocess.run(["rtk", "proxy", 'git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(["rtk", "proxy", 'git', '-C', str(self.root), 'commit', '-qm', 'fixture'], check=True)
        self.definition = {'schema_version': 1, 'plan_version': 'approved-1', 'checks': [{
            'id': 'restore-common', 'criterion_id': 'restore', 'platform': 'common', 'kind': 'test',
            'required': True, 'expected': 'unique memo survives reload', 'expected_tests': ['Memo.restore'],
            'command': [], 'results': [{'path': 'result.xml', 'format': 'junit'}]}]}

    def run_xml(self, xml):
        self.definition['checks'][0]['command'] = ["rtk", "proxy", sys.executable, '-c',
            'from pathlib import Path; Path("result.xml").write_text(' + repr(xml) + ')']
        return run_verification(self.definition, self.root)['checks'][0]

    def test_actual_scenario_and_platform_are_recorded_without_authority(self):
        row = self.run_xml('<testsuite><testcase classname="Memo" name="restore"/></testsuite>')
        self.assertEqual(row['status'], 'OBSERVED_PASS')
        self.assertEqual(row['platform'], 'common')
        self.assertEqual(row['scenarios'][0]['id'], 'Memo.restore')
        self.assertTrue(row['result_files'][0]['sha256'])
        self.assertEqual(row['result'], row['status'])
        self.assertEqual(len(row['outputs']), 2)
        self.assertTrue(all((self.root / r['path']).is_file() for r in row['outputs']))

    def test_failed_zero_skipped_and_missing_scenarios(self):
        cases = [('<testsuite/>', 'ZERO_TESTS'),
                 ('<testsuite><testcase classname="Memo" name="restore"><failure/></testcase></testsuite>', 'SCENARIO_FAILED'),
                 ('<testsuite><testcase classname="Memo" name="restore"><skipped/></testcase></testsuite>', 'ALL_TESTS_SKIPPED'),
                 ('<testsuite><testcase name="other"/></testsuite>', 'REQUIRED_SCENARIO_MISSING')]
        for xml, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(self.run_xml(xml)['reason'], reason)

    def test_stale_and_absent_results_cannot_pass(self):
        self.definition['checks'][0]['command'] = ["rtk", "proxy", sys.executable, '-c', 'pass']
        self.assertEqual(run_verification(self.definition, self.root)['checks'][0]['reason'], 'RESULT_MISSING')
        (self.root / 'result.xml').write_text('<testsuite><testcase name="restore"/></testsuite>')
        self.assertEqual(run_verification(self.definition, self.root)['checks'][0]['reason'], 'RESULT_STALE')

    def test_exit_failure_timeout_and_missing_runner(self):
        for command, reason in [(["rtk", "proxy", sys.executable, '-c', 'raise SystemExit(4)'], 'EXECUTION_FAILED'),
                                (["rtk", "proxy", sys.executable, '-c', 'import time; time.sleep(5)'], 'TIMEOUT'),
                                (["rtk", "proxy", '/nonexistent/verification-runner'], 'RUNNER_UNSUPPORTED')]:
            self.definition['checks'][0]['command'] = command
            self.assertEqual(run_verification(self.definition, self.root, timeout=2)['checks'][0]['reason'], reason)

    def test_build_does_not_require_or_invent_scenarios(self):
        check = self.definition['checks'][0]
        check.update(kind='build', command=["rtk", "proxy", sys.executable, '-c', 'pass'])
        check.pop('expected_tests')
        row = run_verification(self.definition, self.root)['checks'][0]
        self.assertEqual(row['status'], 'OBSERVED_PASS')
        self.assertEqual(row['scenarios'], [])

    def test_code_mutation_invalidates_result(self):
        self.definition['checks'][0].update(kind='build', command=["rtk", "proxy", sys.executable, '-c',
            'from pathlib import Path; Path("source.py").write_text("changed")'])
        row = run_verification(self.definition, self.root)['checks'][0]
        self.assertEqual(row['reason'], 'SOURCE_CHANGED_DURING_EXECUTION')

    def test_commit_change_during_execution_invalidates_even_identical_tree(self):
        self.definition['checks'][0].update(kind='build', command=['rtk','proxy','git','commit','--allow-empty','-m','different submitted commit'])
        receipt=run_verification(self.definition,self.root)
        self.assertNotEqual(receipt['source']['commit'],receipt['source_after']['commit'])
        self.assertEqual(receipt['checks'][0]['reason'],'SOURCE_CHANGED_DURING_EXECUTION')

    def test_partial_selection_leaves_required_platform_unrun(self):
        check = self.definition['checks'][0]
        check.update(kind='build', command=["rtk", "proxy", sys.executable, '-c', 'pass'])
        ios = copy.deepcopy(check)
        ios.update(id='restore-ios', platform='ios')
        self.definition['checks'].append(ios)
        rows = run_verification(self.definition, self.root, ['restore-common'])['checks']
        self.assertEqual([r['status'] for r in rows], ['OBSERVED_PASS', 'NOT_RUN'])

    def test_nonzero_exit_retains_failed_scenario(self):
        check = self.definition['checks'][0]
        check['command'] = ['rtk', 'proxy', sys.executable, '-c',
            'from pathlib import Path; Path("result.xml").write_text(\'<testsuite><testcase classname="Memo" name="restore"><failure/></testcase></testsuite>\'); raise SystemExit(1)']
        row = run_verification(self.definition, self.root)['checks'][0]
        self.assertEqual(row['reason'], 'SCENARIO_FAILED')
        self.assertEqual(row['scenarios'][0]['result'], 'FAIL')
        self.assertEqual(row['exit_code'], 1)

    def test_definitions_reject_ambiguous_or_unsafe_execution(self):
        check = self.definition['checks'][0]
        check['command'] = ['rtk', 'proxy', sys.executable, '-c', 'pass']
        alterations = [({'schema_version': True}, None), ({}, {'expected_tests': 'Memo.restore'}),
                       ({}, {'expected_tests': ['same', 'same']}), ({}, {'command': [sys.executable]}),
                       ({}, {'results': [{'path': '../outside.xml', 'format': 'junit'}]}),
                       ({}, {'results': [{'path': './result.xml', 'format': 'junit'}]})]
        for top, row in alterations:
            candidate = copy.deepcopy(self.definition)
            candidate.update(top)
            if row:
                candidate['checks'][0].update(row)
            with self.assertRaises(ValueError):
                validate_definition(candidate)

    def test_duplicate_test_ids_do_not_pass(self):
        row = self.run_xml('<testsuite><testcase classname="Memo" name="restore"/><testcase classname="Memo" name="restore"/></testsuite>')
        self.assertEqual(row['reason'], 'DUPLICATE_SCENARIO_IDS')

    def test_root_requires_identity_and_git_uses_restricted_environment(self):
        with mock.patch('harness.verification_runner.os.geteuid', return_value=0), mock.patch('harness.verification_runner.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                source_state(self.root)
            with self.assertRaises(ValueError):
                run_verification(self.definition, self.root)
            launch.assert_not_called()
            process = launch.return_value
            process.returncode = 0
            process.communicate.side_effect = [(b'commit\n', None), (b'', None), (b'', None)]
            with mock.patch.dict('os.environ', {'PUBLISHER_SECRET': 'never-inherit'}):
                source_state(self.root, execution_identity=(65534, 65534),
                             execution_home='/safe/home', execution_tmpdir='/safe/tmp')
            self.assertEqual(launch.call_count, 3)
            for call in launch.call_args_list:
                argv = call.args[0]
                self.assertIn('core.fsmonitor=false', argv)
                self.assertIn('core.hooksPath=/dev/null', argv)
                self.assertNotIn('PUBLISHER_SECRET', call.kwargs['env'])
                self.assertEqual(call.kwargs['env']['GIT_CONFIG_GLOBAL'], '/dev/null')
                self.assertTrue(call.kwargs['start_new_session'])
                self.assertTrue(callable(call.kwargs['preexec_fn']))
            self.assertEqual(process.communicate.call_args.kwargs['timeout'], 30)

    def test_runner_output_symlinks_are_rejected(self):
        check = self.definition['checks'][0]
        check.update(kind='build', command=['rtk', 'proxy', sys.executable, '-c', 'pass'])
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'verification').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            run_verification(self.definition, self.root)


if __name__ == '__main__':
    unittest.main()
