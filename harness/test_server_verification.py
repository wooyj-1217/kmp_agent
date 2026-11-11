"""Required server criterion gate; authority and signatures are synthetic fixtures.

This does not execute an application, provision authority or certify a product.
"""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from harness import protected_verification as pv
from harness import test_protected_verification as fixtures


class ServerVerificationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ProtectedVerificationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.ProtectedVerificationTests.tearDownClass.__func__)
    git = fixtures.ProtectedVerificationTests.git
    sign = fixtures.ProtectedVerificationTests.sign
    status = fixtures.ProtectedVerificationTests.status

    def setUp(self):
        fixtures.ProtectedVerificationTests.setUp(self)
        self.server = {'id':'synthetic-server-check','criterion_id':'SERVER-CONTRACT',
                       'platform':'server','kind':'api','required':True,
                       'command':['rtk','proxy','python3','contract-check.py'],
                       'expected':'Synthetic server criterion must be independently present and passing',
                       'expected_tests':['ServerContract.required_check'],
                       'results':[{'path':'verification/server.xml','format':'junit'}]}
        self.criteria.append({'id': self.server['criterion_id'], 'required': True,
                              'description': self.server['expected']})
        self.definition['checks'].append(copy.deepcopy(self.server))
        (self.root/'verification-plan.json').write_text(json.dumps(self.definition))
        self.git('add', 'verification-plan.json'); self.git('commit', '-m', 'approve separate required server criterion')
        self.contract['approved_commit'] = self.git('rev-parse', 'HEAD').strip()
        self.manager._mutate('fixture approved server criterion',
            lambda state: state['tasks']['T']['criteria'].append(copy.deepcopy(self.criteria[-1])), 'T')

    def complete(self):
        return self.manager.review('T', self.review['agent_run_id'],
            [{'criterion_id': criterion['id'], 'result': 'PASS', 'evidence': 'verification/review.json'}
             for criterion in self.criteria], 'QA summary cannot replace server execution evidence')

    def sign_server(self, mode='pass', observation=None, evidence_root=None):
        def change(payload):
            server = payload['checks'][-1]
            server['scenarios'] = [{'id': 'ServerContract.required_check', 'result': 'PASS'}]
            if observation is not None:
                server.clear(); server.update(copy.deepcopy(observation))
                for ref in server.get('result_files', []) + server.get('outputs', []):
                    source = Path(evidence_root)/ref['path']
                    target = self.root/ref['path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            elif mode == 'missing':
                payload['checks'].pop()
            elif mode == 'fail':
                server.update(result='FAIL', reason='SCENARIO_FAILED', exit_code=1,
                              scenarios=[{'id': 'ServerContract.required_check', 'result': 'FAIL'}])
        return self.sign(change)

    def test_client_pass_cannot_replace_missing_required_server(self):
        self.sign_server('missing')
        with self.assertRaisesRegex(ValueError, 'REQUIRED_CHECKS_INCOMPLETE'):
            self.complete()
        server = next(r for r in self.status()['checks'] if r['platform'] == 'server')
        self.assertNotEqual(server['result'], 'PASS')
        self.assertTrue(all(r['result'] == 'PASS' for r in self.status()['checks'] if r['platform'] != 'server'))

    def test_failed_server_blocks_and_fresh_success_allows_completion(self):
        self.sign_server('fail')
        with self.assertRaisesRegex(ValueError, 'REQUIRED_CHECKS_INCOMPLETE'):
            self.complete()
        self.sign_server()
        self.assertEqual(self.complete(), 'DONE')
        self.assertEqual(self.status()['result'], 'PASS')

    def test_unavailable_authority_is_distinct_from_server_scenario_failure(self):
        self.policy_patch.stop()
        with patch.object(pv, 'POLICY_DIRECTORY', self.root/'not-provisioned'):
            self.assertEqual(self.status()['result'], 'BLOCKED')
            self.assertIn('PROTECTED_AUTHORITY_UNAVAILABLE', self.status()['reason'])
            with self.assertRaisesRegex(ValueError, 'PROTECTED_AUTHORITY_UNAVAILABLE'):
                self.complete()


if __name__ == '__main__':
    unittest.main()
