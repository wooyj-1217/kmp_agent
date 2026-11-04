"""Official completion consumes a separately administered, signed verification job.

The editable task ledger is a cache, never an authority. Deploy this module and
the publisher under an administrator-owned installation, outside candidate code.
No environment variable or candidate file selects the trust root.
"""
import argparse
import base64
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import uuid

POLICY_DIRECTORY = Path('/etc/kmp-agent/verification')


def _runner():
    if os.geteuid() != 0:
        from harness import verification_runner
        return verification_runner
    # Check ownership before executing sibling Python; bypass mutable package
    # search paths and import caches when running as the protected publisher.
    installation = Path(__file__).resolve().parent
    _protected(installation / '__init__.py')
    source = _protected(installation / 'verification_runner.py')
    spec = importlib.util.spec_from_file_location('_protected_verification_runner', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def git(root, *args, identity=None):
    if os.geteuid() == 0 and identity is None:
        raise PermissionError('never inspect candidate Git configuration as root')
    def demote():
        os.setgroups([]); os.setgid(identity[1]); os.setuid(identity[0])
    proc = subprocess.run(['/usr/bin/git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
                           '-c', 'safe.directory=' + str(Path(root).resolve()), *args],
                          cwd=root, capture_output=True, timeout=20,
                          env={'PATH':'/usr/bin:/bin', 'GIT_CONFIG_NOSYSTEM':'1', 'GIT_CONFIG_GLOBAL':'/dev/null'},
                          preexec_fn=demote if identity else None)
    if proc.returncode:
        raise ValueError('verification Git inspection failed: ' + ' '.join(args[:2]))
    return proc.stdout


def _protected(path, owners=(0,)):
    """Reject a trust root replaceable by an implementation/QA OS account."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('protected authority path must be absolute')
    resolved = path.resolve(strict=True)
    for entry in [resolved, *resolved.parents]:
        info = entry.stat()
        if info.st_uid not in owners or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError('verification authority is writable by an untrusted identity')
    return resolved


def load_policy(root):
    root = Path(root).resolve()
    path = POLICY_DIRECTORY / (sha(str(root).encode()) + '.json')
    if not path.exists():
        return None
    data = json.loads(_protected(path).read_text())
    if data.get('schema_version') != 1 or data.get('project_root') != str(root):
        raise ValueError('protected verification policy project/version mismatch')
    if type(data.get('agent_uid')) is not int or type(data.get('publisher_uid')) is not int or data['agent_uid'] == data['publisher_uid']:
        raise ValueError('publisher and implementation/QA must be distinct OS identities')
    if not data.get('issuer') or not data.get('public_key_pem') or not isinstance(data.get('tasks'), dict):
        raise ValueError('protected verification policy is incomplete')
    _protected(data['receipt_directory'])
    _protected(data['execution_root'])
    if Path(data['execution_root']).resolve().is_relative_to(root) or Path(data['receipt_directory']).resolve().is_relative_to(root):
        raise ValueError('protected workspace and receipts must be outside agent checkout')
    return data


def requires(task):
    return bool(task.get('protected_verification_required') or task.get('verification_contract') or
                task.get('execution_scope') == 'code_implementation' or task.get('development_tracking'))


def applies(root, task):
    # Removing task flags or changing its role cannot remove an administrator's
    # task binding. An unreadable authority is a blocker, never an opt-out.
    try:
        policy = load_policy(root)
        return requires(task) or task['task_id'] in (policy or {}).get('tasks', {})
    except (OSError, ValueError, KeyError):
        return True


def validate_ledger(root, state, allow_registration=False):
    tasks = state.get('tasks', {})
    if not isinstance(tasks, dict) or any(not isinstance(task, dict) or task.get('task_id') != key for key, task in tasks.items()):
        raise ValueError('task ledger key/identity mismatch; official completion blocked')
    policy = load_policy(root)
    if policy and not allow_registration and set(policy['tasks']) - set(tasks):
        raise ValueError('protected tasks missing from ledger; official completion blocked')


def _relative(value):
    if not isinstance(value, str) or not value or value == '.' or value.startswith(':') or '\\' in value or '\x00' in value or Path(value).is_absolute() or '..' in Path(value).parts or Path(value).as_posix() != value:
        raise ValueError('verification definition paths must be normalized relative paths')
    return value


def candidate(root, contract, identity=None):
    """The complete submitted Git tree is the invalidation scope; no impact guesses."""
    root = Path(root).resolve()
    def inspect(*args):
        return git(root, *args, identity=identity)
    commit = inspect('rev-parse', 'HEAD').decode().strip()
    status = inspect('status', '--porcelain=v1', '--untracked-files=all').decode()
    if status.strip():
        raise ValueError('submitted commit has uncommitted code or validation input changes')
    approved = contract['approved_commit']
    protected = list(contract.get('protected_paths', []))
    for check in contract['definition']['checks']:
        protected.extend(check.get('protected_paths', []))
        protected.extend(check.get('validation_inputs', []))
    if not protected:
        raise ValueError('approved tests, assertions, baselines and build/CI settings must be protected')
    paths = [_relative(p) for p in protected]
    # Existing approved tests may not change; new test files are allowed. CI and
    # command/exclusion configuration additions are blocked by protected prefixes.
    changes = inspect('diff', '--no-ext-diff', '--no-textconv', '--name-status', '--no-renames', approved, commit, '--', *paths).decode().splitlines()
    changed = [line.split('\t', 1)[1] for line in changes if not line.startswith('A\t')]
    if changed:
        raise ValueError('approved verification inputs changed; owner reapproval required: ' + ', '.join(changed))
    config_paths = ['.github', '.gitlab-ci.yml', 'Jenkinsfile', *contract.get('configuration_paths', [])]
    changed_config = inspect('diff', '--no-ext-diff', '--no-textconv', '--name-only', approved, commit, '--', *[_relative(p) for p in config_paths]).decode().splitlines()
    if changed_config:
        raise ValueError('approved CI/build/exclusion configuration changed; owner reapproval required: ' + ', '.join(changed_config))
    changed_names = inspect('diff', '--no-ext-diff', '--no-textconv', '--name-only', approved, commit).decode().splitlines()
    config_patterns = ('**/build.gradle*', '**/settings.gradle*', 'build.gradle*', 'settings.gradle*',
                       '**/gradle.properties', 'gradle.properties', 'gradle/**', 'gradlew*', '**/package*.json',
                       'package*.json', '**/*config.*', '*config.*', '**/*.xcscheme', '**/project.pbxproj')
    if any(any(fnmatch.fnmatchcase(p, pattern) for pattern in config_patterns) for p in changed_names):
        raise ValueError('approved build/test exclusion configuration changed; owner reapproval required')
    definition = contract['definition']
    _runner().validate_definition(definition)
    plan = contract['plan']
    if sha(inspect('show', commit + ':' + _relative(plan['path']))) != plan['sha256']:
        raise ValueError('approved development plan changed; owner reapproval required')
    definition_path = _relative(contract['definition_path'])
    current = inspect('show', commit + ':' + definition_path)
    if json.loads(current) != definition:
        raise ValueError('approved verification definition/plan changed; owner reapproval required')
    # The owner pins all verification inputs in its policy, not in the ledger.
    for relative, expected in contract.get('validation_inputs', {}).items():
        actual = sha(inspect('show', commit + ':' + _relative(relative)))
        if actual != expected:
            raise ValueError('approved test/assertion/baseline changed: ' + relative)
    return {'commit': commit, 'tree': inspect('rev-parse', 'HEAD^{tree}').decode().strip(),
            'definition_sha256': sha(canonical(definition)), 'plan_version': definition['plan_version'],
            'approved_plan_sha256': plan['sha256'], 'approval_sha256': sha(canonical(contract))}


def _envelope(root, task_id, policy=None):
    # IDs are hashed so a forged ledger cannot choose files outside this directory.
    base = Path(policy['receipt_directory']) if policy and policy.get('receipt_directory') else Path(root) / '.harness/verification-jobs'
    return base / (sha(task_id.encode()) + '.json')


def _history_envelope(root, task_id, job_id, policy=None):
    current = _envelope(root, task_id, policy)
    return current.with_name(current.stem + '-' + sha(job_id.encode()) + '.json')


def _verify_signature(payload, signature, public_key):
    try:
        signature = base64.b64decode(signature, validate=True)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base/'key.pem').write_text(public_key)
            (base/'payload').write_bytes(canonical(payload))
            (base/'signature').write_bytes(signature)
            proc = subprocess.run(['/usr/bin/openssl', 'dgst', '-sha256', '-verify', str(base/'key.pem'),
                                   '-signature', str(base/'signature'), str(base/'payload')], capture_output=True, timeout=10,
                                  env={'PATH':'/usr/bin:/bin'})
        return proc.returncode == 0
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return False


def _blocked(contract, reason, **target):
    checks = []
    for check in ((contract or {}).get('definition') or {}).get('checks', []):
        checks.append({k:check.get(k) for k in ('id','criterion_id','platform','kind','required')})
        checks[-1].update(result='BLOCKED', reason=reason, commit=target.get('commit'))
    return {'result':'BLOCKED', 'reason':reason, 'checks':checks, **target}


def assess(root, task):
    """Read-only official status. Local PASS strings and QA summaries are ignored."""
    contract = None
    try:
        policy = load_policy(root)
        contract = (policy or {}).get('tasks', {}).get(task['task_id'])
        if not contract:
            return {'result': 'BLOCKED' if requires(task) else 'LEGACY_UNCERTIFIED',
                    'reason': 'PROTECTED_AUTHORITY_UNAVAILABLE' if policy is None else 'APPROVED_VERIFICATION_DEFINITION_MISSING', 'checks': []}
        if task.get('criteria') != contract['criteria']:
            raise ValueError('completion criteria differ from protected approval')
        if task.get('completion_contract') != contract.get('completion_contract') or task.get('verification_contract') != contract.get('verification_contract'):
            raise ValueError('completion or verification settings differ from protected approval')
        identity = (policy['execution_uid'], policy['execution_gid']) if os.geteuid() == 0 else None
        current = candidate(root, contract, identity=identity)
        path = _envelope(root, task['task_id'], policy)
        if not path.is_file() or path.stat().st_size > 8_000_000:
            return _blocked(contract, 'PROTECTED_JOB_MISSING', **current)
        envelope = json.loads(path.read_text())
        if not isinstance(envelope, dict) or not isinstance(envelope.get('payload'), dict):
            raise ValueError('invalid protected job envelope')
        payload = envelope.get('payload', {})
        if not _verify_signature(payload, envelope.get('signature', ''), policy['public_key_pem']):
            raise ValueError('protected verification job signature invalid; local PASS is not authority')
        if payload.get('issuer') != policy['issuer'] or payload.get('publisher_uid') != policy['publisher_uid'] or not payload.get('job_id'):
            raise ValueError('verification job provenance mismatch')
        archive = _history_envelope(root, task['task_id'], payload['job_id'], policy)
        if not archive.is_file() or json.loads(archive.read_text()) != envelope:
            raise ValueError('immutable verification job history missing or changed')
        age = time.time() - payload.get('issued_at', 0)
        maximum = policy.get('max_age_seconds', 86400)
        if type(maximum) is not int or maximum <= 0 or age < -60 or age > maximum:
            raise ValueError('protected verification job expired or timestamp invalid')
        if payload.get('project_root') != str(Path(root).resolve()) or payload.get('task_id') != task['task_id']:
            raise ValueError('verification job target mismatch')
        if any(payload.get(k) != v for k, v in current.items()):
            raise ValueError('verification job is stale for submitted commit, tree or approved plan')
        evidence_root = Path(policy.get('execution_root', root)).resolve()
        if payload.get('evidence_root', str(Path(root).resolve())) != str(evidence_root):
            raise ValueError('verification evidence workspace differs from protected job')
        definition = contract['definition']
        required_criteria = {c['id'] for c in contract['criteria'] if c['required']}
        covered = {c['criterion_id'] for c in definition['checks'] if c['required']}
        if not required_criteria.issubset(covered):
            raise ValueError('approved definition omits mandatory completion criteria')
        checks = payload.get('checks', [])
        if not isinstance(checks, list) or any(not isinstance(row, dict) for row in checks):
            raise ValueError('invalid protected job checks')
        ids = [r.get('id') for r in checks]
        if len(ids) != len(set(ids)) or set(ids) - {c['id'] for c in definition['checks']}:
            raise ValueError('verification job has duplicate or unknown checks')
        rows = []
        for check in definition['checks']:
            row = next((r for r in checks if r.get('id') == check['id']), {})
            passed = row.get('result') == 'OBSERVED_PASS' and row.get('command') == check['command']
            passed = passed and all(row.get(k) == check[k] for k in ('criterion_id', 'platform', 'kind', 'expected'))
            if check['kind'] not in {'build', 'lint'}:
                scenarios = row.get('scenarios', [])
                passed = passed and bool(scenarios) and all(any(name in {s.get('id'), s.get('name')} and s.get('result') == 'PASS' for s in scenarios) for name in check['expected_tests'])
                passed = passed and bool(row.get('result_files'))
            passed = passed and row.get('exit_code') == 0 and bool(row.get('outputs'))
            # Frozen raw result files and command output remain live evidence.
            for ref in row.get('result_files', []) + row.get('outputs', []):
                file = (evidence_root / _relative(ref['path'])).resolve()
                passed = passed and file.is_relative_to(evidence_root) and file.is_file() and sha(file.read_bytes()) == ref.get('sha256')
            observed_result = 'FAIL' if row.get('result') == 'FAIL' else 'NOT_RUN' if row.get('result') in {None,'NOT_RUN'} else 'BLOCKED'
            rows.append({'id': check['id'], 'criterion_id': check['criterion_id'], 'platform': check['platform'], 'kind': check['kind'],
                         'required': check['required'], 'result': 'PASS' if passed else observed_result,
                         'reason': None if passed else row.get('reason') or 'REQUIRED_SCENARIO_NOT_VERIFIED',
                         'commit': current['commit'], 'job_id': payload['job_id']})
        passed = bool(rows) and all(r['result'] == 'PASS' for r in rows if r['required'])
        return {'result': 'PASS' if passed else 'BLOCKED', 'reason': None if passed else 'REQUIRED_CHECKS_INCOMPLETE',
                **current, 'issuer': policy['issuer'], 'job_id': payload['job_id'], 'checks': rows,
                'receipt_path':str(archive), 'receipt_sha256':sha(canonical(envelope))}
    except (ValueError, OSError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        return _blocked(contract, str(error))


def gate(manager, task):
    result = assess(manager.root, task)
    if result['result'] not in {'PASS', 'LEGACY_UNCERTIFIED'}:
        raise ValueError('protected verification completion blocked: ' + str(result['reason']))
    return result


def publish(root, task_id, private_key, job_id):
    """Protected job only: execute approved definitions, never sign an agent report.

    Administrator must isolate this service identity and its key from candidate
    commands (VM/container/job boundary); merely using another actor_id is unsafe.
    This entrypoint must run from the administrator-owned trusted installation.
    """
    policy = load_policy(root)
    if not policy or os.geteuid() != 0 or policy['publisher_uid'] != 0 or policy['agent_uid'] == 0:
        raise PermissionError('only protected verification publisher identity may issue results')
    key = _protected(private_key, owners=(0, policy['publisher_uid']))
    if key.stat().st_mode & 0o077:
        raise PermissionError('publisher private key must not be readable by execution identities')
    uid, gid = policy.get('execution_uid'), policy.get('execution_gid')
    if type(uid) is not int or uid <= 0 or uid == policy['agent_uid'] or type(gid) is not int or gid <= 0:
        raise PermissionError('candidate commands require a separate unprivileged execution identity')
    # Trusted publisher code must not be the writable candidate checkout.
    _protected(Path(__file__), owners=(0, policy['publisher_uid']))
    contract = policy['tasks'][task_id]
    workspace = _protected(policy['execution_root'])
    if key.is_relative_to(workspace):
        raise PermissionError('signing key must be outside candidate execution workspace')
    # The administrator materializes an immutable checkout. Only explicitly
    # provisioned build/result directories may be writable by the worker UID.
    writable = [_relative(p) for p in contract.get('execution_writable_paths', [])]
    if any(p == 'verification' or p.startswith('verification/runner') or p.startswith('.git') for p in writable):
        raise PermissionError('worker writable scopes cannot include publisher output or Git control directories')
    for path in workspace.rglob('*'):
        rel = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            raise PermissionError('protected execution workspace refuses symlinks')
        if not any(rel == p or rel.startswith(p + '/') for p in writable):
            _protected(path)
    before = candidate(workspace, contract, identity=(uid, gid))
    observed = _runner().run_verification(contract['definition'], workspace, execution_identity=(uid, gid))
    after = candidate(workspace, contract, identity=(uid, gid))
    if before != after:
        raise ValueError('submitted code or validation inputs changed during protected job')
    payload = {**before, 'project_root': str(Path(root).resolve()), 'task_id': task_id,
               'issuer': policy['issuer'], 'publisher_uid': policy['publisher_uid'], 'job_id': job_id,
               'checks': observed['checks'], 'evidence_root': str(workspace), 'issued_at': time.time()}
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory); (base/'payload').write_bytes(canonical(payload))
        proc = subprocess.run(['/usr/bin/openssl', 'dgst', '-sha256', '-sign', str(key), str(base/'payload')], capture_output=True, timeout=10,
                              env={'PATH':'/usr/bin:/bin'})
        if proc.returncode:
            raise ValueError('protected job signing failed')
    target = _envelope(root, task_id, policy)
    _protected(target.parent)
    if target.is_symlink():
        raise PermissionError('protected receipt cannot be a symlink')
    data = json.dumps({'payload': payload, 'signature': base64.b64encode(proc.stdout).decode()}, ensure_ascii=False, indent=2)
    archive = _history_envelope(root, task_id, job_id, policy)
    with archive.open('x') as stream:
        stream.write(data)
        stream.flush(); os.fsync(stream.fileno())
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x') as stream:
        stream.write(data)
        stream.flush(); os.fsync(stream.fileno())
    temporary.replace(target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'publish'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--private-key', type=Path)
    parser.add_argument('--job-id')
    args = parser.parse_args(argv)
    if args.action == 'publish':
        if not args.private_key or not args.job_id:
            parser.error('publish requires protected private key and job ID')
        print(publish(args.root, args.task_id, args.private_key, args.job_id)); return 0
    # No candidate import: the protected installed evaluator reads the ledger as data.
    try:
        state = json.loads((args.root/'.harness/tasks/tasks.yaml').read_text())
        validate_ledger(args.root, state)
        result = assess(args.root, state['tasks'][args.task_id])
    except (ValueError, OSError, KeyError, TypeError) as error:
        result = {'result':'BLOCKED', 'reason':str(error), 'checks':[]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
