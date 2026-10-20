"""Durable incremental collection using the existing event converter and identities.

Cursor/index files are disposable acceleration metadata. events.jsonl is authoritative.
No model calls, intervention linking, aggregation or project reconciliation here.
"""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import uuid


def logger_module():
    spec = importlib.util.spec_from_file_location('incremental_logger', Path(__file__).with_name('logging.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def atomic_json(path, value):
    temp = path.with_name(path.name + '.' + str(uuid.uuid4()) + '.tmp')
    try:
        with temp.open('x') as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(value, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


@contextlib.contextmanager
def lock(path, stats, name, timeout=10, trace=None):
    if trace: trace('lock_requested', lock_name=name)
    with path.open('a+') as f:
        os.fchmod(f.fileno(), 0o600)
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout:
                    stats[name + '_lock_wait_seconds'] = time.monotonic() - start
                    owner_path = path.with_name(path.name + '.owner.json')
                    try: owner_hint = json.loads(owner_path.read_text())
                    except (OSError, ValueError): owner_hint = {'state':'UNKNOWN'}
                    if trace: trace('lock_timeout', lock_name=name, wait_seconds=stats[name + '_lock_wait_seconds'], last_owner_hint=owner_hint, owner_hint_is_live_verified=False)
                    raise TimeoutError(name + ' lock acquisition exceeded budget')
                time.sleep(.01)
        stats[name + '_lock_wait_seconds'] = time.monotonic() - start
        stats[name + '_lock_owner_pid'] = os.getpid()
        held = time.monotonic()
        owner_path = path.with_name(path.name + '.owner.json')
        atomic_json(owner_path, dict(pid=os.getpid(),state='HELD',acquired_at=time.time()))
        if trace: trace('lock_acquired', lock_name=name, wait_seconds=stats[name + '_lock_wait_seconds'], owner_pid=os.getpid())
        try: yield f
        finally:
            atomic_json(owner_path, dict(pid=os.getpid(),state='RELEASED',released_at=time.time()))
            stats[name + '_lock_hold_seconds'] = time.monotonic() - held
            fcntl.flock(f, fcntl.LOCK_UN)
            if trace: trace('lock_released',lock_name=name,hold_seconds=stats[name + '_lock_hold_seconds'])


class Collector:
    """Reuse Logger.sync's conversion without its I/O, full-log append or linker."""
    def __init__(self, logger, offset_lines, prefix_lines):
        self.events = []
        self.offset_lines = offset_lines
        self.prefix_lines = prefix_lines
        self.module = logger_module()

    def append(self, event_type, run_id, observed, source, source_key):
        if source['line'] <= self.prefix_lines:
            return None
        source['line'] += self.offset_lines - self.prefix_lines
        self.events.append((event_type, run_id, observed, source, source_key))
        return True

    def write_metadata(self, *args): pass
    def resolve_interventions(self): pass


def write_payload(writer, encoded):
    writer.buffer.write(encoded)
    writer.buffer.flush()
    os.fsync(writer.fileno())


def recover_batch(logger, stats, trace=None):
    """Finish only an exact prefix of our durable intent, without truncating logs."""
    journal = logger.directory / 'collection-batch-intent.json'
    if not journal.exists(): return
    if json.loads(journal.read_text()).get('state') == 'COMMITTED': return
    with lock(logger.path, stats, 'recovery_events', trace=trace) as writer:
        intent = json.loads(journal.read_text())
        if intent.get('state') == 'COMMITTED': return
        writer.seek(0); data = writer.buffer.read()
        start = intent['start']; encoded = intent['encoded'].encode()
        if len(data) >= start+len(encoded):
            if data[start:start+len(encoded)] != encoded:
                raise ValueError('batch journal conflicts with saved events; preserve and inspect')
            atomic_json(journal, dict(state='COMMITTED',end=start+len(encoded)))
            return
        if (len(data) < start or hashlib.sha256(data[:start]).hexdigest() != intent['prefix_sha256']
                or not encoded.startswith(data[start:])):
            raise ValueError('batch journal prefix mismatch; preserve and inspect')
        writer.seek(0,2)
        write_payload(writer, encoded[len(data)-start:])
        stats['recovered_batch_bytes'] = start+len(encoded)-len(data)
        atomic_json(journal, dict(state='COMMITTED',end=start+len(encoded)))


def append_batch(logger, candidates, stats, trace=None):
    """Parse snapshot outside lock; verify unchanged under the same legacy file lock.

    Concurrent legacy writers are compatible. Retry on change; never trust a stale
    sequence/index. An incomplete event-log tail blocks instead of rewriting it.
    """
    module = logger_module()
    recover_batch(logger, stats, trace=trace)
    for attempt in range(10):
        if trace: trace('batch_prepare_started',attempt=attempt)
        start = time.monotonic()
        with logger.path.open('a+b') as reader:
            before = os.fstat(reader.fileno())
            reader.seek(0)
            data = reader.read()
            after = os.fstat(reader.fileno())
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if signature(before) != signature(after): continue
        if data and not data.endswith(b'\n'):
            raise ValueError('incomplete event log tail; preserve and inspect before recovery')
        existing = [json.loads(line) for line in data.splitlines() if line.strip()]
        keys = {e.get('source_key') for e in existing if e.get('source_key')}
        starts = {e['run_id']: e for e in existing if e.get('event_type') == 'run_started'}
        rows = []
        for kind, run, observed, source, key in candidates:
            if key in keys: continue
            keys.add(key)
            context = starts.get(run, {}).get('execution_context', logger.context)
            rows.append(module.redact(dict(schema_version=2, redaction_version=1,
                event_id=str(uuid.uuid4()), sequence=len(existing)+len(rows)+1,
                recorded_at=module.now(), event_type=kind, work_type=module.UNKNOWN,
                run_id=run, feature_id=module.UNKNOWN, task_id=module.UNKNOWN,
                agent_run_id=module.UNKNOWN, harness=logger.harness,
                project_id=context['project_id'], verification_scope=context['verification_scope'],
                execution_context=context, observed=observed, agent_summary={},
                source=source, source_key=key)))
        encoded = b''.join((json.dumps(r, ensure_ascii=False)+'\n').encode() for r in rows)
        stats['batch_prepare_seconds'] = stats.get('batch_prepare_seconds', 0) + time.monotonic()-start
        if trace: trace('batch_prepared',attempt=attempt,candidates=len(candidates),new_events=len(rows),prepare_seconds=time.monotonic()-start)
        with lock(logger.path, stats, 'events', trace=trace) as writer:
            if signature(os.fstat(writer.fileno())) != signature(after): continue
            writer.seek(0, 2)
            # One write buffer; cursor cannot advance until flush + fsync succeed.
            if encoded:
                journal_started=time.monotonic()
                atomic_json(logger.directory / 'collection-batch-intent.json',
                            dict(start=len(data), prefix_sha256=hashlib.sha256(data).hexdigest(),
                                 encoded=encoded.decode()))
                stats['journal_commit_seconds']=time.monotonic()-journal_started
                if trace: trace('batch_intent_durable',new_events=len(rows))
                write_started=time.monotonic()
                write_payload(writer, encoded)
                stats['events_write_fsync_seconds']=time.monotonic()-write_started
                atomic_json(logger.directory / 'collection-batch-intent.json',
                            dict(state='COMMITTED', end=len(data)+len(encoded)))
            stats.update(imported_events=len(rows), duplicate_events=len(candidates)-len(rows), batch_retries=attempt)
            return len(rows)
    raise RuntimeError('event log changed repeatedly; retry collection')


def collect(logger, source, *, mode='hook', trace=None, before_cursor=None, force=False):
    started = time.monotonic()
    stats = dict(mode=mode, status='RUNNING')
    module = logger_module()
    source = Path(source).expanduser().resolve()
    with source.open('rb') as f:
        first = json.loads(f.readline())
    meta = first.get('payload', {}); session = meta.get('session_id', meta.get('id'))
    if first.get('type') != 'session_meta' or not session:
        raise ValueError('session metadata unavailable')
    directory = logger.directory / 'cursors'
    directory.mkdir(mode=0o700, exist_ok=True)
    stem = hashlib.sha256(session.encode()).hexdigest()
    cursor_path = directory / (stem+'.json')
    try:
        with lock(directory/(stem+'.lock'), stats, 'session', trace=trace):
            try:
                cursor = json.loads(cursor_path.read_text()) if cursor_path.exists() else {}
                if not isinstance(cursor,dict) or not isinstance(cursor.get('offset',0),int) or cursor.get('offset',0)<0 or not isinstance(cursor.get('lines',0),int) or cursor.get('lines',0)<0:
                    raise ValueError('invalid cursor fields')
                if cursor:
                    signed = dict(cursor); checksum = signed.pop('cursor_sha256',None)
                    if checksum != hashlib.sha256(json.dumps(signed,sort_keys=True).encode()).hexdigest():
                        raise ValueError('cursor checksum mismatch')
            except (ValueError,TypeError):
                cursor = {}
                stats['cursor_invalid'] = True
            read_started=time.monotonic()
            if trace: trace('source_read_started')
            with source.open('rb') as f:
                stat = os.fstat(f.fileno())
                actual_first = json.loads(f.readline())
                actual_meta = actual_first.get('payload',{})
                if (actual_first.get('type') != 'session_meta'
                        or actual_meta.get('session_id',actual_meta.get('id')) != session):
                    raise ValueError('session source changed during acquisition; retry')
                f.seek(0)
                offset = cursor.get('offset', 0)
                check = time.monotonic()
                # Full byte hash validates even in-place edits. Old JSON is never
                # reparsed; this deliberate linear I/O is measured separately.
                prefix = f.read(min(offset, stat.st_size))
                valid = (not force and cursor.get('session_id') == session
                         and cursor.get('file_identity') == [stat.st_dev, stat.st_ino]
                         and offset <= stat.st_size
                         and prefix.count(b'\n') == cursor.get('lines')
                         and (not prefix or prefix.endswith(b'\n'))
                         and hashlib.sha256(prefix).hexdigest() == cursor.get('prefix_sha256'))
                stats['prefix_check_seconds'] = time.monotonic()-check
                stats['prefix_check_bytes'] = len(prefix)
                if not valid:
                    stats['reset_reason'] = 'forced' if force else ('source_or_cursor_mismatch' if cursor else 'first_collection')
                    cursor = {}; offset = 0; prefix = b''; f.seek(0)
                else: f.seek(offset)
                tail = f.read(stat.st_size-offset)
                current = source.stat()
                if (current.st_dev,current.st_ino) != (stat.st_dev,stat.st_ino) or len(tail) != stat.st_size-offset:
                    raise ValueError('session source replaced or shrank during read; retry')
            stats['source_read_seconds']=time.monotonic()-read_started
            if trace: trace('source_read_finished',read_seconds=stats['source_read_seconds'],read_bytes=len(tail),prefix_check_bytes=stats['prefix_check_bytes'])
            end = tail.rfind(b'\n')+1
            complete = tail[:end]
            stats.update(source_bytes=stat.st_size, read_bytes=len(tail), deferred_bytes=len(tail)-end,
                         cursor_before=offset, complete_records=complete.count(b'\n'))
            parse = time.monotonic()
            if trace: trace('conversion_started')
            synthetic = [dict(type='session_meta', payload=meta),
                         dict(type='turn_context', payload={'model':cursor.get('model',module.UNKNOWN)}),
                         dict(type='event_msg', payload={'type':'task_started','turn_id':cursor.get('turn_id',module.UNKNOWN)})]
            content = b''.join((json.dumps(r)+'\n').encode() for r in synthetic)+complete
            collector = Collector(logger, cursor.get('lines',0), len(synthetic))
            module.Logger.sync(collector, source, content=content)
            turn = cursor.get('turn_id',module.UNKNOWN); model = cursor.get('model',module.UNKNOWN)
            latest_user = cursor.get('latest_user_id'); user_count = cursor.get('user_count',0)
            for line in complete.splitlines():
                row=json.loads(line); payload=row.get('payload',{})
                if row.get('type')=='response_item' and payload.get('type')=='message' and payload.get('role')=='user':
                    latest_user=payload.get('id',module.UNKNOWN); user_count+=1
                if row.get('type')=='turn_context': model=payload.get('model',module.UNKNOWN)
                if row.get('type')=='event_msg' and payload.get('type')=='task_started': turn=payload.get('turn_id',module.UNKNOWN)
            stats['parse_seconds']=time.monotonic()-parse
            if trace: trace('conversion_finished', parse_seconds=stats['parse_seconds'], candidates=len(collector.events), read_bytes=len(tail), deferred_bytes=len(tail)-end)
            count=append_batch(logger,collector.events,stats,trace=trace)
            if trace: trace('events_durable', imported_events=count)
            if before_cursor: before_cursor()
            commit=time.monotonic()
            if trace: trace('cursor_commit_started')
            next_cursor=dict(session_id=session, file_identity=[stat.st_dev,stat.st_ino],
                offset=offset+end, lines=cursor.get('lines',0)+complete.count(b'\n'),
                prefix_sha256=hashlib.sha256(prefix+complete).hexdigest(), turn_id=turn,model=model,
                latest_user_id=latest_user,user_count=user_count)
            next_cursor['cursor_sha256']=hashlib.sha256(json.dumps(next_cursor,sort_keys=True).encode()).hexdigest()
            atomic_json(cursor_path,next_cursor)
            stats.update(cursor_after=offset+end,cursor_commit_seconds=time.monotonic()-commit,status='COMPLETED',
                         latest_collected_message_id=latest_user,collected_user_count=user_count)
            if trace: trace('cursor_committed',cursor_after=offset+end)
        return count
    except BaseException as error:
        stats.update(status='FAILED',error_type=type(error).__name__)
        raise
    finally:
        stats['elapsed_seconds']=time.monotonic()-started
        logger.last_collection=stats
        if trace: trace('collection_finished' if stats['status']=='COMPLETED' else 'collection_failed',**stats)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--mode',choices=['manual','recovery'],default='manual')
    p.add_argument('--full',action='store_true',help='safe replay without deleting events or cursor')
    p.add_argument('source',type=Path)
    args=p.parse_args(); module=logger_module(); logger=module.Logger(args.root)
    invocation=str(uuid.uuid4())
    def trace(phase,**fields):
        record=dict(invocation_id=invocation,phase=phase,recorded_at=module.now(),pid=os.getpid(),**fields)
        with lock(logger.directory/'collection-diagnostics.jsonl',{},'diagnostic') as f:
            f.write(json.dumps(record)+'\n');f.flush();os.fsync(f.fileno())
    trace('collection_started',mode=args.mode)
    collect(logger,args.source,mode=args.mode,force=args.full,trace=trace)
    print(json.dumps(logger.last_collection))

if __name__=='__main__': main()
