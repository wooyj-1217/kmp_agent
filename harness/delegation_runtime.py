"""Native Codex process adapter. Worker reports are claims, never review verdicts."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import threading
import uuid

from harness import logging
from harness.runtime_limits import model_slot


def _drain(child, timeout=5):
    if not hasattr(child, '_usage_chunks'):
        return child.communicate(timeout=timeout)
    child.wait(timeout=timeout)
    for thread in child._usage_threads:
        thread.join(timeout=timeout)
    for pipe in (child.stdin, child.stdout, child.stderr):
        if pipe and not pipe.closed:
            pipe.close()
    return ''.join(child._usage_chunks[0]), ''.join(child._usage_chunks[1])


def _communicate_stream(child, prompt, timeout, stream):
    # Keep the old test-double/process contract; real pipes are drained concurrently.
    if not hasattr(child, 'stdout') or not hasattr(child, 'stdin'):
        return child.communicate(prompt, timeout=timeout)
    child._usage_chunks = [[], []]
    def pump(pipe, index):
        for line in pipe:
            child._usage_chunks[index].append(line)
            if index == 0:
                stream.line(line)
    def feed():
        # Large input must not block the caller before its timeout begins.
        try:
            child.stdin.write(prompt)
        except BrokenPipeError:
            pass  # Same early-exit behavior as subprocess.communicate().
        finally:
            try:
                child.stdin.close()
            except BrokenPipeError:
                pass
    child._usage_threads = [threading.Thread(target=pump, args=(child.stdout, 0), daemon=True),
                            threading.Thread(target=pump, args=(child.stderr, 1), daemon=True),
                            threading.Thread(target=feed, daemon=True)]
    deadline = time.monotonic() + timeout
    for thread in child._usage_threads:
        thread.start()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('native worker', timeout)
        try:
            child.wait(timeout=min(.2, remaining))
            break
        except subprocess.TimeoutExpired:
            stream.tick()
    result = _drain(child)
    stream.tick()
    return result


RESULT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["COMPLETE", "PARTIAL", "FAILED", "BLOCKED"]},
        "summary": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "verifications": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "command": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["PASS", "FAIL", "NOT_RUN"]},
                "evidence": {"type": ["string", "null"]}},
            "required": ["command", "status", "evidence"]}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "contract_change_required": {"type": "boolean"},
        "contract_impact": {"type": "array", "items": {"type": "string"}},
        "change_reference": {"type": ["string", "null"]}},
    "required": ["status", "summary", "changed_files", "verifications", "unresolved",
                 "contract_change_required", "contract_impact", "change_reference"]}


def validate_result(value):
    """Validate the response even when a custom/older runtime ignores schema."""
    if not isinstance(value, dict) or set(value) != set(RESULT_SCHEMA['required']):
        raise ValueError('worker result must match the complete result contract')
    if value['status'] not in RESULT_SCHEMA['properties']['status']['enum']:
        raise ValueError('invalid worker result status')
    if not isinstance(value['summary'], str) or not value['summary'].strip():
        raise ValueError('worker result needs a summary')
    for field in ('changed_files', 'unresolved', 'contract_impact'):
        if not isinstance(value[field], list) or not all(isinstance(x, str) for x in value[field]):
            raise ValueError('invalid worker result ' + field)
    if type(value['contract_change_required']) is not bool:
        raise ValueError('invalid contract_change_required')
    if value['change_reference'] is not None and not isinstance(value['change_reference'], str):
        raise ValueError('invalid change_reference')
    if not isinstance(value['verifications'], list):
        raise ValueError('invalid verifications')
    for check in value['verifications']:
        if (not isinstance(check, dict) or set(check) != {'command', 'status', 'evidence'}
                or check['status'] not in {'PASS', 'FAIL', 'NOT_RUN'}
                or not isinstance(check['command'], list)
                or not all(isinstance(x, str) for x in check['command'])
                or (check['evidence'] is not None and not isinstance(check['evidence'], str))):
            raise ValueError('invalid verification report')
    return value


def run_codex(manager, task_id, agent_run_id, workspace: Path, packet: dict,
              output_dir: Path, executable: str, timeout: int, *,
              result_schema=None, result_validator=None, sandbox='workspace-write', image_paths=None) -> dict:
    """Execute one isolated native worker, retaining evidence on failure/timeout.

    The caller owns dispatch locking, workspace isolation, path enforcement,
    diff inspection and independently executed verification.
    """
    if not isinstance(executable, str) or not executable or timeout <= 0:
        raise ValueError('explicit executable and positive timeout are required')
    if sandbox not in {'workspace-write', 'read-only'}:
        raise ValueError('worker sandbox must be workspace-write or read-only')
    schema = RESULT_SCHEMA if result_schema is None else result_schema
    validator = validate_result if result_validator is None else result_validator
    if not isinstance(schema, dict) or not callable(validator):
        raise ValueError('worker result schema and validator must be explicit valid contracts')
    workspace, output_dir = Path(workspace).resolve(), Path(output_dir).resolve()
    if not workspace.is_dir():
        raise ValueError('workspace must exist')
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    schema_path, result_path = output_dir / 'result-schema.json', output_dir / 'worker-result.json'
    stdout_path, stderr_path = output_dir / 'stdout.jsonl', output_dir / 'stderr.txt'
    if any(p.exists() for p in (result_path, stdout_path, stderr_path)):
        raise ValueError('dispatch output already exists; preserve it and use a new attempt directory')
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2))
    argv = ['rtk', 'proxy', executable, 'exec', '--ignore-user-config', '--sandbox',
            sandbox, '--json', '--output-schema', str(schema_path), '-o',
            str(result_path), '-C', str(workspace), '-']
    image_refs=[]
    for value in image_paths or []:
        image=(workspace/value).resolve()
        if not image.is_relative_to(workspace.resolve()) or not image.is_file():raise ValueError('image must exist inside isolated workspace')
        if image.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('unsupported image extension')
        raw=image.read_bytes()
        if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff') or (raw[:4]==b'RIFF' and raw[8:12]==b'WEBP')):raise ValueError('unsupported image bytes')
        if (image.suffix.lower()=='.png') != raw.startswith(b'\x89PNG\r\n\x1a\n') or (image.suffix.lower() in {'.jpg','.jpeg'}) != raw.startswith(b'\xff\xd8\xff'):raise ValueError('image extension and bytes disagree')
        argv[-1:-1]=['--image',str(image)]
        image_refs.append({'path':str(image.relative_to(workspace)), 'sha256':logging.digest(raw)})
    if image_refs:
        (output_dir/'attached-images.json').write_text(json.dumps(image_refs,indent=2))
    state = manager.read()
    task = state['tasks'][task_id]
    execution = manager._active(task, agent_run_id, 'work')
    packet = {**packet, 'usage_context': execution.get('usage_context')}
    from harness.usage_collection import WorkerStream
    context = dict(feature_id=task['feature_id'], task_id=task_id, agent_run_id=agent_run_id)
    metadata = dict(call_id=str(uuid.uuid4()), command_kind='development',
                    command_name='delegated_codex_worker', cwd=str(workspace),
                    attempt_id=execution.get('attempt_id', agent_run_id),
                    link_status='COLLECTED', adapter='codex_exec',
                    argv_sha256=logging.digest(json.dumps(argv).encode()))
    usage_stream = WorkerStream(manager, task_id, agent_run_id, metadata['call_id'])
    started_at, timer = logging.now(), time.monotonic()
    logger = manager.logger
    from harness.roles import Roles
    adapter = Roles.__new__(Roles)
    adapter.tasks, adapter.root = manager, manager.root
    logger.append('command_started', manager.run_id, task['work_type'], **context,
                  observed={**metadata, 'started_at': started_at})
    child, returncode, error, stdout, stderr = None, 127, None, '', ''
    worker_env=os.environ.copy()
    cache=workspace/'.worker-cache';cache.mkdir(exist_ok=True)
    worker_env.update(GRADLE_USER_HOME=str(cache/'gradle'),KONAN_DATA_DIR=str(cache/'konan'),XDG_CACHE_HOME=str(cache/'xdg'),CARGO_TARGET_DIR=str(cache/'cargo'))
    slot = model_slot(manager, task_id, agent_run_id, timeout)
    slot_acquired = False
    try:
        slot.__enter__()
        slot_acquired = True
        child = subprocess.Popen(argv, cwd=workspace, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True,env=worker_env)
        adapter.process_event(task_id, agent_run_id,
                              {**metadata, 'pid': child.pid, 'spawned': True,
                               'process_state': 'role_process_started',
                               'independent_model_spawned': True, 'started_at': logging.now()})
        prompt = json.dumps(packet, ensure_ascii=False)
        if sandbox == 'read-only':
            prompt += '\nTest/read-only QA: do not modify product files. Report findings and evidence in the required result schema only.'
        stdout, stderr = _communicate_stream(child, prompt, timeout, usage_stream)
        returncode = child.returncode
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        error = type(exc).__name__
        returncode = 124 if isinstance(exc, subprocess.TimeoutExpired) else 130
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = _drain(child, timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                stdout, stderr = _drain(child, timeout=5)
    except (OSError, ValueError) as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        if isinstance(exc, TimeoutError):
            returncode = 124
    finally:
        # Hold the admission through timeout termination and pipe drainage.
        try:
            # A log/adapter failure immediately after Popen must not orphan a
            # model process or release its shared slot while it still runs.
            if child is not None and child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    stdout, stderr = _drain(child, timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    stdout, stderr = _drain(child, timeout=5)
        finally:
            if slot_acquired:
                slot.__exit__(None, None, None)
    ended_at = logging.now()
    for path, content in ((stdout_path, stdout), (stderr_path, stderr)):
        path.write_text(content, encoding='utf-8')
        path.chmod(0o600)
    thread_ids = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'thread.started' and isinstance(event.get('thread_id'), str):
            if event['thread_id'] not in thread_ids:
                thread_ids.append(event['thread_id'])
    result, result_error = None, None
    if returncode == 0:
        try:
            result = validator(json.loads(result_path.read_text()))
        except (OSError, ValueError, TypeError) as exc:
            result_error = str(exc)
    usage_status = 'UNKNOWN'
    usage_error = None
    try:
        # collect_codex expects pure CLI JSONL. RTK diagnostics are never labels.
        stream = '\n'.join(json.dumps(json.loads(line)) for line in stdout.splitlines()
                           if line.strip().startswith('{'))
        usage_status = adapter.collect_codex(task_id, agent_run_id, stream)['usage']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        usage_error = 'usage collection unavailable: ' + str(exc)
    observed = {**metadata, 'pid': child.pid if child else logging.UNKNOWN,
                'ended_at': ended_at, 'elapsed_seconds': time.monotonic() - timer,
                'returncode': returncode, 'stdout_sha256': logging.digest(stdout.encode()),
                'stderr_sha256': logging.digest(stderr.encode()),
                'process_error': error or logging.UNKNOWN,
                'result_error': result_error or logging.UNKNOWN,
                'usage_status': usage_status, 'thread_ids': thread_ids,
                'usage_error': usage_error or logging.UNKNOWN,
                'incremental_usage_error': usage_stream.last_error,
                'result_is_self_report': True}
    logger.append('command_finished', manager.run_id, task['work_type'], **context, observed=observed)
    adapter.process_event(task_id, agent_run_id,
                          {**observed, 'spawned': child is not None, 'exited': True,
                           'process_state': 'role_process_finished', 'exit_code': returncode})
    usage_stream.tick()
    return dict(returncode=returncode, pid=child.pid if child else None,
                started_at=started_at, ended_at=ended_at, result=result,
                stdout_path=str(stdout_path), stderr_path=str(stderr_path),
                thread_ids=thread_ids, usage_status=usage_status,
                error=error, result_error=result_error, usage_error=usage_error)
