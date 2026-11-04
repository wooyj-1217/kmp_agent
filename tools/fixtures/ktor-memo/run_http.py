"""Actual loopback Ktor process verification; no demo/mobile or restart claim."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent
SCENARIO = 'create_then_get'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(base, method, path, data=None):
    req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'}, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=3)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read().decode()
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = None
        return {'method': method, 'path': path, 'status': response.status, 'body': body,
                'json': parsed}


def main():
    evidence = ROOT / 'verification/ktor-memo'
    run = evidence / uuid.uuid4().hex
    run.mkdir(parents=True)
    record = {'schema_version': 1, 'scope': 'isolated Ktor API fixture; demo keeps local storage',
              'scenario': 'KtorMemo.' + SCENARIO, 'started_at': time.time(), 'requests': [],
              'commit': subprocess.check_output(['rtk', 'proxy', 'git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
              'validation_inputs': {name: sha(ROOT/name) for name in subprocess.check_output(
                  ['rtk', 'proxy', 'git', 'ls-files', str(FIXTURE.relative_to(ROOT))], cwd=ROOT).decode().splitlines()},
              'result': 'FAIL', 'reason': 'BUILD_FAILED'}
    build = ['rtk', 'proxy', str(FIXTURE/'gradlew'), '--no-daemon', '-p', str(FIXTURE),
             '--project-cache-dir', str(evidence/'gradle-cache'), 'installDist', '--console=plain']
    record['build_command'] = build
    process = None
    testcase = ET.Element('testcase', classname='KtorMemo', name=SCENARIO)
    try:
        with (run/'build.log').open('wb') as log:
            completed = subprocess.run(build, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        record['build_exit_code'] = completed.returncode
        if completed.returncode:
            raise RuntimeError('Ktor build failed; see build.log')
        launcher = evidence/'build/install/ktor-memo-verification/bin/ktor-memo-verification'
        record['build_sha256'] = {str(p.relative_to(ROOT)): sha(p) for p in sorted((evidence/'build/install').rglob('*')) if p.is_file()}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = os.environ.copy(); env['PORT'] = str(port)
        record['server_command'] = ['rtk', 'proxy', str(launcher)]
        record['reason'] = 'SERVER_START_FAILED'
        with (run/'server.log').open('wb') as log:
            process = subprocess.Popen(record['server_command'], cwd=ROOT, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            record['server_pid'] = process.pid
            base = 'http://127.0.0.1:' + str(port)
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Ktor process exited before readiness')
                try:
                    health = request(base, 'GET', '/health')
                    if health['status'] == 200:
                        break
                except (OSError, ValueError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Ktor readiness deadline exceeded')
                time.sleep(.1)
            record['ready_at'] = time.time()
            unique = uuid.uuid4().hex
            memo = {'title': 'unique-title-' + unique, 'body': '고유 본문 ' + unique + '\nrestore exact text'}
            record['input'] = memo
            record['reason'] = 'POST_SCENARIO_FAILED'
            posted = request(base, 'POST', '/api/memos', memo)
            record['requests'].append(posted)
            assert posted['status'] == 201, 'POST must return 201'
            created = posted['json']
            assert isinstance(created.get('id'), str) and created['id'], 'POST must generate id'
            assert created['title'] == memo['title'] and created['body'] == memo['body'], 'POST exact title/body'
            record['reason'] = 'GET_SCENARIO_FAILED'
            loaded = request(base, 'GET', '/api/memos/' + created['id'])
            record['requests'].append(loaded)
            assert loaded['status'] == 200, 'separate GET must return 200'
            assert loaded['json'] == created, 'separate GET must preserve generated id and unique title/body'
            record.update(result='PASS', reason='POST_201_GET_200_EXACT_MEMO')
    except Exception as error:
        record['error'] = str(error)
        if record['reason'] in {'BUILD_FAILED', 'SERVER_START_FAILED'}:
            ET.SubElement(testcase, 'skipped', message=record['reason'])
        else:
            ET.SubElement(testcase, 'failure', message=record['reason']).text = str(error)
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            record['server_exit_code_after_shutdown'] = process.returncode
        record['finished_at'] = time.time()
        record['logs'] = {str(p.relative_to(ROOT)): sha(p) for p in run.glob('*.log')}
        (run/'http.json').write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
        (evidence/'latest.json').write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
        suite = ET.Element('testsuite', name='KtorMemo', tests='1', failures='1' if testcase.find('failure') is not None else '0')
        suite.append(testcase)
        ET.ElementTree(suite).write(evidence/'results.xml', encoding='utf-8', xml_declaration=True)
    print(json.dumps({'result': record['result'], 'reason': record['reason'], 'evidence': str(run.relative_to(ROOT))}))
    return 0 if record['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
