"""Gate reproduction with actual runner observations and synthetic authority only.

Never calls the protected publisher. Disposable signing keys and mocked policy
exercise Tasks.review; they cannot issue administrator-authorized product PASS.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch

from harness import protected_verification as pv
from harness.logging import Logger
from harness.tasks import Tasks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--approved-commit', required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--expect', choices=['PASS', 'BLOCKED'], required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    fixture = Path(__file__).resolve().parent
    definition = json.loads((fixture/'verification.json').read_text())
    observation = json.loads(args.receipt.read_text())
    check = definition['checks'][0]
    criteria = [{'id': check['criterion_id'], 'required': True, 'description': check['expected']}]
    relative = lambda path: str(path.relative_to(root))
    protected = [name for name in subprocess.check_output(
        ['rtk', 'proxy', 'git', 'ls-files', str(fixture.relative_to(root))], cwd=root).decode().splitlines()
        if not name.endswith('/Main.kt')]
    contract = {'approved_commit': args.approved_commit, 'definition_path': relative(fixture/'verification.json'),
                'definition': definition, 'criteria': criteria,
                'plan': {'path': relative(fixture/'README.md'), 'sha256': pv.sha((fixture/'README.md').read_bytes())},
                'protected_paths': protected,
                'configuration_paths': [relative(fixture/'build.gradle.kts'), relative(fixture/'settings.gradle.kts')],
                'validation_inputs': {path: pv.sha((root/path).read_bytes()) for path in protected}}
    report = {'authority': 'SYNTHETIC_POLICY_DISPOSABLE_KEY_ONLY', 'operational_certification': False,
              'task_id': args.task_id, 'observation_receipt': str(args.receipt),
              'original_observed_commit': observation['source']['commit']}
    with tempfile.TemporaryDirectory(prefix='ktor-gate-test-key-') as directory:
        key = Path(directory)/'private.pem'
        subprocess.run(['rtk', 'proxy', 'openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(key)], check=True, capture_output=True)
        public = subprocess.check_output(['rtk', 'proxy', 'openssl', 'pkey', '-in', str(key), '-pubout']).decode()
        policy = {'schema_version': 1, 'project_root': str(root), 'agent_uid': __import__('os').getuid(),
                  'publisher_uid': 0, 'issuer': 'SYNTHETIC-KTOR-GATE-TEST', 'public_key_pem': public,
                  'tasks': {args.task_id: contract}}
        with patch.object(pv, 'load_policy', return_value=policy):
            run_id = Logger(root).start('HARNESS_BUILD', 'orchestrator', 'synthetic authority with actual Ktor observation')
            manager = Tasks(root, run_id)
            manager.register('KTOR-FIXTURE', args.task_id, 'planning', 'Ktor actual HTTP gate proof',
                             'API fixture only; synthetic authority', criteria, [relative(fixture/'README.md')], execution_scope='documentation')
            manager._mutate('fixture protected contract', lambda state: state['tasks'][args.task_id].update(protected_verification_required=True), args.task_id)
            manager.ready(args.task_id)
            work = manager.begin(args.task_id, 'planning')
            manager.submit(args.task_id, work['agent_run_id'], [relative(fixture/'README.md')], 'actual Ktor observation submitted')
            review = manager.begin(args.task_id, 'verification', review=True)
            current = pv.candidate(root, contract)
            report['fixture_evaluation_commit'] = current['commit']
            assert current['commit'] == observation['source']['commit'], 'runner commit must match submitted candidate'
            assert observation['source']['manifest_sha256'] == observation['source_after']['manifest_sha256'], 'runner source changed'
            payload = {**current, 'project_root': str(root), 'task_id': args.task_id, 'issuer': policy['issuer'],
                       'publisher_uid': 0, 'job_id': 'synthetic-' + args.task_id, 'checks': observation['checks'], 'issued_at': time.time()}
            signed = subprocess.run(['rtk', 'proxy', 'openssl', 'dgst', '-sha256', '-sign', str(key)],
                                    input=pv.canonical(payload), capture_output=True, check=True).stdout
            envelope = {'payload': payload, 'signature': base64.b64encode(signed).decode()}
            destination = pv._envelope(root, args.task_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(envelope))
            pv._history_envelope(root, args.task_id, payload['job_id']).write_text(json.dumps(envelope))
            try:
                manager.review(args.task_id, review['agent_run_id'],
                               [{'criterion_id': check['criterion_id'], 'result': 'PASS', 'evidence': str(args.receipt.relative_to(root))}],
                               'actual observation; fixture authority')
                report['completion'] = 'PASS'
            except ValueError as error:
                report.update(completion='BLOCKED', error=str(error))
            report['gate'] = manager.verification_status(args.task_id)
    output = root/'verification/ktor-memo'/('completion-' + args.task_id + '.json')
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    assert report['completion'] == args.expect


if __name__ == '__main__':
    main()
