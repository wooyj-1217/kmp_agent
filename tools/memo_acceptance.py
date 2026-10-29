#!/usr/bin/env python3
"""Deterministic HTTP acceptance checks, not an independent model QA review.

Only synthetic memos are used. An externally supplied endpoint is modified by
POST, so this tool intentionally accepts loopback trial endpoints only.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def request(base, method, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(base + '/api/memos', data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read().decode('utf-8')
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        return response.status, value


def check_memo(value, body=None):
    assert isinstance(value, dict), 'memo must be a JSON object'
    assert isinstance(value.get('id'), str) and value['id'], 'nonempty string id required'
    assert isinstance(value.get('body'), str), 'string body required'
    assert isinstance(value.get('createdAt'), str), 'string createdAt required'
    dt.datetime.fromisoformat(value['createdAt'].replace('Z', '+00:00'))
    if body is not None:
        assert value['body'] == body, 'body changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18790)
    parser.add_argument('--base-url', help='already running isolated loopback server; no process started')
    parser.add_argument('--expect-empty', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.project.resolve()
    output = args.output or root / '.worker-cache/e2e/result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        prior=output.read_bytes();history=output.parent/'history';history.mkdir(exist_ok=True);(history/(hashlib.sha256(prior).hexdigest()+'.json')).write_bytes(prior)
    base = (args.base_url or f'http://127.0.0.1:{args.port}').rstrip('/')
    url = urllib.parse.urlparse(base)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.port == 8080 or url.path:
        parser.error('only explicit http://127.0.0.1:PORT isolated endpoints, excluding 8080, are permitted')
    cases = []
    process = None
    log = None
    report = {'started_at': now(), 'command': sys.argv, 'base_url': base,
              'method': 'deterministic real HTTP acceptance; not model QA',
              'storage_scope': 'in-memory trial; persistence and idempotency NOT_RUN',
              'cases': cases, 'code_sha256': {}}
    def code_hashes():
        selected=[]
        for folder in ('shared/src','server/src','web'):
            selected.extend(p for p in (root/folder).rglob('*') if p.is_file())
        selected.extend(root/p for p in ('build.gradle.kts','settings.gradle.kts','gradle.properties','shared/build.gradle.kts','server/build.gradle.kts') if (root/p).is_file())
        return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(selected)}
    report['code_sha256']=code_hashes()
    report['inputs_sha256']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('original-request.md','planning.md','design/design.md','api.md','policy.md','architecture.md') if (root/name).is_file()}
    distribution=root/'.worker-cache/build/server/install/server'
    report['distribution_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(distribution.rglob('*')) if p.is_file()}

    def case(name, action):
        item = {'id': name, 'started_at': now()}
        cases.append(item)
        try:
            detail = action()
            item.update(status='PASS', actual=detail)
        except Exception as error:
            item.update(status='FAIL', error=f'{type(error).__name__}: {error}')
            raise
        finally:
            item['finished_at'] = now()
    try:
        if not args.base_url:
            with socket.socket() as sock:
                assert sock.connect_ex(('127.0.0.1', args.port)) != 0, 'port occupied; existing server preserved'
            executable = root / '.worker-cache/build/server/install/server/bin/server'
            assert executable.is_file(), f'missing installDist executable: {executable}'
            env = dict(os.environ, PORT=str(args.port))
            log_path = output.parent / 'server.log'
            log = log_path.open('w')
            process = subprocess.Popen([str(executable)], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            report['server'] = {'pid': process.pid, 'command': [str(executable)],
                                'PORT': str(args.port), 'log': str(log_path)}
            deadline = time.monotonic() + 45
            while True:
                assert process.poll() is None, f'server exited {process.returncode}'
                try:
                    if request(base, 'GET')[0] == 200:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                assert time.monotonic() < deadline, 'server readiness timed out'
                time.sleep(.25)
        initial = []
        def initial_case():
            status, value = request(base, 'GET')
            assert status == 200 and isinstance(value, list), (status, value)
            for memo in value:
                check_memo(memo)
            if args.expect_empty:
                assert not value, 'expected isolated empty in-memory server'
            initial.extend(value)
            return {'http_status': status, 'count': len(value)}
        case('MEMO-GET-INITIAL', initial_case)
        saved = []
        for index, body in enumerate(['first memo', '  메모 🌱\nsecond line  ', '😀' * 200]):
            def save(body=body):
                status, memo = request(base, 'POST', {'body': body})
                assert status == 201, (status, memo)
                check_memo(memo, body)
                assert memo['id'] not in {x['id'] for x in initial + saved}, 'duplicate memo id'
                saved.append(memo)
                return {'http_status': status, 'memo_id': memo['id'], 'codepoints': len(body),
                        'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'createdAt': memo['createdAt']}
            case(f'MEMO-SAVE-{index + 1}', save)
        for index, body in enumerate(['', ' \t\n', 'x' * 201, '😀' * 201]):
            def reject(body=body):
                before_status, before = request(base, 'GET')
                status, value = request(base, 'POST', {'body': body})
                after_status, after = request(base, 'GET')
                assert status == 400, (status, value)
                assert before_status == after_status == 200 and before == after, 'rejected body inserted or changed data'
                return {'http_status': status, 'codepoints': len(body), 'count_unchanged': len(after)}
            case(f'MEMO-REJECT-{index + 1}', reject)
        def refetch():
            status, value = request(base, 'GET')
            assert status == 200 and isinstance(value, list), (status, value)
            assert value == initial + saved, 'refetch differs from saved objects or chronological insertion order'
            timestamps = [dt.datetime.fromisoformat(x['createdAt'].replace('Z', '+00:00')) for x in value]
            assert timestamps == sorted(timestamps), 'not chronological oldest first'
            return {'http_status': status, 'count': len(value), 'saved_ids': [m['id'] for m in saved],
                    'exact_body_preservation': True, 'oldest_first': True}
        case('MEMO-SAVE-REFETCH', refetch)
        assert code_hashes()==report['code_sha256'], 'code changed during E2E'
        report['status'] = 'PASS'
    except Exception as error:
        report.update(status='FAIL', error=f'{type(error).__name__}: {error}')
    finally:
        if process is not None:
            report['server']['exit_before_cleanup'] = process.poll()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            report['server'].update(exit_after_cleanup=process.returncode, cleanup='only tool-owned process')
        if log:
            log.close()
        report['finished_at'] = now()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'cases': len(cases), 'result': str(output)}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
