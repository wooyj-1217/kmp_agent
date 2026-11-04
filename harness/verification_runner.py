"""Unprivileged observations. These receipts NEVER authorize completion."""
import argparse
import hashlib
import json
import os
import signal
import shutil
from pathlib import Path
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _execution_environment(home=None, tmpdir=None):
    environment = {key: os.environ[key] for key in
        ('PATH', 'JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'SDKROOT', 'DEVELOPER_DIR') if key in os.environ}
    if home is not None:
        environment['HOME'] = str(home)
    if tmpdir is not None:
        environment['TMPDIR'] = str(tmpdir)
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    return environment


def _demote(execution_identity):
    def demote():
        uid, gid = execution_identity
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    return demote if execution_identity is not None else None


def _require_identity(execution_identity):
    if os.geteuid() == 0 and execution_identity is None:
        raise ValueError('root execution requires a separate unprivileged execution_identity')
    if execution_identity is not None and (len(execution_identity) != 2 or
            any(type(value) is not int or value < 0 for value in execution_identity) or execution_identity[0] == 0):
        raise ValueError('execution_identity must specify a non-root uid and gid')


def source_state(root, execution_identity=None, execution_home=None, execution_tmpdir=None):
    _require_identity(execution_identity)
    root = Path(root).resolve()
    def git(*args):
        proc = subprocess.Popen(['rtk', 'proxy', 'git', '-c', 'core.fsmonitor=false',
                                 '-c', 'core.hooksPath=/dev/null', '-c', 'safe.directory=' + str(root),
                                 '-C', str(root), *args],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=_execution_environment(execution_home, execution_tmpdir),
                                preexec_fn=_demote(execution_identity), start_new_session=True)
        try:
            stdout, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.communicate()
            raise
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, proc.args)
        return stdout
    try:
        commit = git('rev-parse', 'HEAD').decode().strip()
        names = git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
        manifest = {}
        for name in names:
            if not name:
                continue
            relative = os.fsdecode(name)
            path = root / relative
            if path.is_symlink():
                manifest[relative] = digest(os.readlink(path).encode())
            elif path.is_file():
                manifest[relative] = digest(path.read_bytes())
            else:
                manifest[relative] = None
        return {'commit': commit, 'clean': not bool(git('status', '--porcelain')),
                'manifest': manifest, 'manifest_sha256': digest(canonical(manifest))}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return {'commit': None, 'clean': False, 'manifest': {}, 'manifest_sha256': None}


def validate_definition(definition):
    if type(definition.get('schema_version')) is not int or definition['schema_version'] != 1 or not isinstance(definition.get('plan_version'), str) or not definition['plan_version'].strip():
        raise ValueError('schema_version 1 and plan_version required')
    seen = set()
    if not isinstance(definition.get('checks'), list) or not definition['checks']:
        raise ValueError('checks required')
    for check in definition['checks']:
        for key in ('id', 'criterion_id', 'expected'):
            if not isinstance(check.get(key), str) or not check[key].strip():
                raise ValueError(key + ' required')
        if check['id'] in seen:
            raise ValueError('duplicate check id')
        seen.add(check['id'])
        if check.get('platform') not in {'common', 'android', 'ios', 'web', 'server'}:
            raise ValueError('unsupported platform')
        if check.get('kind') not in {'build', 'test', 'ui', 'api', 'lint', 'screenshot'}:
            raise ValueError('unsupported kind')
        if not isinstance(check.get('required'), bool):
            raise ValueError('required must be boolean')
        if not isinstance(check.get('command'), list) or not check['command'] or not all(isinstance(x, str) and x for x in check['command']):
            raise ValueError('command argv required')
        if check['command'][:2] != ['rtk', 'proxy'] or len(check['command']) < 3:
            raise ValueError('command must use rtk proxy prefix')
        tests = check.get('expected_tests', [])
        if not isinstance(tests, list) or not all(isinstance(t, str) and t.strip() for t in tests) or len(tests) != len(set(tests)):
            raise ValueError('expected_tests must be distinct nonempty strings')
        if check['kind'] not in {'build', 'lint'} and not check.get('expected_tests'):
            raise ValueError('expected_tests required')
        for key in ('protected_paths', 'validation_inputs'):
            if not isinstance(check.get(key, []), list) or not all(isinstance(p, str) and p.strip() for p in check.get(key, [])):
                raise ValueError(key + ' must be list')
        specs = check.get('results', check.get('result_files', []))
        if not isinstance(specs, list):
            raise ValueError('results must be list')
        seen_paths = set()
        for spec in specs:
            if not isinstance(spec, dict) or not isinstance(spec.get('path'), str) or not spec['path']:
                raise ValueError('result path required')
            path = Path(spec['path'])
            if path.is_absolute() or '..' in path.parts or path.as_posix() != spec['path'] or spec['path'] in seen_paths:
                raise ValueError('result paths must be distinct normalized relative paths')
            seen_paths.add(spec['path'])
            if spec.get('format') not in {'junit', 'playwright'}:
                raise ValueError('unsupported result format')
    return definition


def _results(path, fmt):
    if fmt == 'junit':
        tree = ET.parse(path)
        return [{'id': ((case.get('classname') + '.') if case.get('classname') else '') + case.get('name', ''),
                 'name': case.get('name', ''),
                 'status': 'SKIP' if case.find('skipped') is not None else 'FAIL' if case.find('failure') is not None or case.find('error') is not None else 'PASS'}
                for case in tree.iter('testcase')]
    if fmt == 'playwright':
        data = json.loads(path.read_text())
        rows = []
        def visit(suite, prefix=''):
            for spec in suite.get('specs', []):
                for test in spec.get('tests', []):
                    attempts = test.get('results', [])
                    status = attempts[-1].get('status') if attempts else None
                    rows.append({'id': spec.get('id', prefix + spec.get('title', '')),
                                 'name': spec.get('title', ''),
                                 'status': 'PASS' if status == 'passed' and test.get('expectedStatus', 'passed') == 'passed' else 'SKIP' if status == 'skipped' else 'FAIL'})
            for child in suite.get('suites', []):
                visit(child, prefix + child.get('title', '') + ' ')
        visit(data)
        return rows
    raise ValueError('unsupported result format')


def run_verification(definition, root, checks=None, timeout=300, execution_identity=None,
                     execution_home=None, execution_tmpdir=None):
    _require_identity(execution_identity)
    validate_definition(definition)
    root = Path(root).resolve()
    # Keep observations out of the submitted code manifest, including standalone
    # repositories that have not yet adopted the shared verification ignore rule.
    output_root = root / 'verification' / 'runner'
    if (root / 'verification').is_symlink() or output_root.is_symlink():
        raise ValueError('runner output directories must not be symlinks')
    output_root.mkdir(parents=True, exist_ok=True)
    ignore = output_root / '.gitignore'
    if ignore.is_symlink():
        raise ValueError('runner output ignore must not be a symlink')
    if not ignore.exists():
        ignore.write_text('*\n')
    output_dir = output_root / uuid.uuid4().hex
    output_dir.mkdir()
    if execution_identity is not None:
        for name, supplied in [('home', execution_home), ('tmp', execution_tmpdir)]:
            location = Path(supplied) if supplied else output_dir / name
            location.mkdir(parents=True, exist_ok=True)
            if supplied is None:
                os.chown(location, *execution_identity)
                location.chmod(0o700)
            if name == 'home':
                execution_home = str(location)
            else:
                execution_tmpdir = str(location)
    selected = set(checks) if checks else None
    if selected and selected - {c['id'] for c in definition['checks']}:
        raise ValueError('unknown check')
    receipt = {'schema_version': 1, 'authority': 'UNTRUSTED_OBSERVATION',
               'plan_version': definition['plan_version'], 'definition_sha256': digest(canonical(definition)),
               'source': source_state(root, execution_identity, execution_home, execution_tmpdir), 'checks': []}
    for check in definition['checks']:
        row = {k: check[k] for k in ('id', 'criterion_id', 'platform', 'kind', 'required', 'command', 'expected')}
        row.update(status='NOT_RUN', reason='NOT_SELECTED', scenarios=[], result_files=[], outputs=[])
        receipt['checks'].append(row)
        if selected is not None and check['id'] not in selected:
            continue
        specs = check.get('results', check.get('result_files', []))
        paths = []
        before = {}
        for spec in specs:
            path = (root / spec['path']).resolve()
            if not path.is_relative_to(root):
                raise ValueError('result path escapes root')
            paths.append((path, spec['format']))
            before[str(path)] = (path.stat().st_mtime_ns, digest(path.read_bytes())) if path.is_file() else None
        start = time.time_ns()
        row['started_ns'] = start
        stdout = stderr = b''
        try:
            executable = check['command'][2]
            if ('/' in executable and not (root / executable).exists()) or ('/' not in executable and shutil.which(executable) is None):
                raise FileNotFoundError('verification executable unavailable: ' + executable)
            environment = None
            if execution_identity is not None:
                environment = _execution_environment(execution_home, execution_tmpdir)
            proc = subprocess.Popen(check['command'], cwd=root, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True,
                                    env=environment,
                                    preexec_fn=_demote(execution_identity))
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = proc.communicate()
                raise
            proc.stdout, proc.stderr = stdout, stderr
            row.update(exit_code=proc.returncode, output_sha256=digest(proc.stdout + proc.stderr),
                       stdout=proc.stdout.decode(errors='replace'), stderr=proc.stderr.decode(errors='replace'))
        except FileNotFoundError as exc:
            row.update(reason='RUNNER_UNSUPPORTED', error=str(exc))
            stderr = str(exc).encode()
            continue
        except OSError as exc:
            row.update(reason='EXECUTION_UNAVAILABLE', error=str(exc))
            stderr = str(exc).encode()
            continue
        except subprocess.TimeoutExpired:
            row.update(status='FAIL', reason='TIMEOUT')
            continue
        finally:
            row['finished_ns'] = time.time_ns()
            row['output_sha256'] = digest(stdout + stderr)
            for stream, value in [('stdout', stdout), ('stderr', stderr)]:
                output_path = output_dir / (str(len(receipt['checks'])) + '-' + stream + '.log')
                output_path.write_bytes(value)
                row['outputs'].append({'path': str(output_path.relative_to(root)), 'sha256': digest(value), 'kind': stream})
        if check['kind'] in {'build', 'lint'}:
            row.update(status='FAIL' if proc.returncode else 'OBSERVED_PASS', reason='EXECUTION_FAILED' if proc.returncode else 'EXPECTED_EXIT_ZERO')
            continue
        if not paths:
            row.update(status='FAIL', reason='EXECUTION_FAILED' if proc.returncode else 'RESULT_MISSING')
            continue
        error = None
        for path, fmt in paths:
            if not path.is_file():
                error = 'RESULT_MISSING'
                break
            fingerprint = (path.stat().st_mtime_ns, digest(path.read_bytes()))
            if fingerprint == before[str(path)] or path.stat().st_mtime_ns < start:
                error = 'RESULT_STALE'
                break
            row['result_files'].append({'path': str(path.relative_to(root)), 'sha256': fingerprint[1], 'format': fmt})
            try:
                row['scenarios'].extend(_results(path, fmt))
            except (ValueError, ET.ParseError, KeyError):
                error = 'RESULT_INVALID' if fmt in {'junit', 'playwright'} else 'RUNNER_UNSUPPORTED'
                break
        scenarios = row['scenarios']
        if not error:
            if not scenarios:
                error = 'ZERO_TESTS'
            elif len({s['id'] for s in scenarios}) != len(scenarios):
                error = 'DUPLICATE_SCENARIO_IDS'
            elif all(s['status'] == 'SKIP' for s in scenarios):
                error = 'ALL_TESTS_SKIPPED'
            elif any(s['status'] == 'FAIL' for s in scenarios):
                error = 'SCENARIO_FAILED'
            else:
                for expected in check['expected_tests']:
                    matches = [s for s in scenarios if expected in {s['id'], s['name']}]
                    if not matches:
                        error = 'REQUIRED_SCENARIO_MISSING'
                        break
                    if any(s['status'] != 'PASS' for s in matches):
                        error = 'REQUIRED_SCENARIO_SKIPPED'
                        break
        if proc.returncode:
            row['execution_reason'] = 'EXECUTION_FAILED'
            if error not in {'SCENARIO_FAILED', 'REQUIRED_SCENARIO_SKIPPED', 'ALL_TESTS_SKIPPED'}:
                row['result_reason'] = error
                error = 'EXECUTION_FAILED'
        row.update(status='FAIL' if error else 'OBSERVED_PASS', reason=error or 'EXPECTED_SCENARIOS_PASSED')
    for row in receipt['checks']:
        for scenario in row['scenarios']:
            scenario['result'] = scenario['status']
    receipt['source_after'] = source_state(root, execution_identity, execution_home, execution_tmpdir)
    if receipt['source_after'] != receipt['source']:
        for row in receipt['checks']:
            if row['status'] == 'OBSERVED_PASS':
                row.update(status='FAIL', reason='SOURCE_CHANGED_DURING_EXECUTION')
    for row in receipt['checks']:
        row['result'] = row['status']
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition', required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--check', action='append')
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    result = run_verification(json.loads(Path(args.definition).read_text()), args.root, args.check, args.timeout)
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    return 0 if all(r['status'] == 'OBSERVED_PASS' for r in result['checks'] if r['required']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
