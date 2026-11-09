"""Durable, conservative multi-file integration; never restores unknown edits.

Snapshots are hash-checked and read-only, not an OS security authority. Recovery
is explicit. A committed transaction records integration only, never task DONE.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import threading
import time
import uuid

TERMINAL = {'COMMITTED', 'ROLLED_BACK', 'ABANDONED'}
_local = threading.local()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _base(root):
    root = Path(root).resolve()
    base = root/'.harness/integration-transactions'
    if any(p.is_symlink() for p in [root/'.harness', base]):
        raise ValueError('integration journal path must not be symlink')
    return base


def _fsync_dir(path):
    fd = os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _mkdir(path):
    missing=[]; current=Path(path)
    while not current.exists(): missing.append(current); current=current.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True); _fsync_dir(directory.parent)


def _write(path,data,mode=0o600):
    path = Path(path)
    temporary = path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(data); handle.flush(); os.fchmod(handle.fileno(),mode); os.fsync(handle.fileno())
        os.replace(temporary,path); _fsync_dir(path.parent)
    finally:
        if temporary.exists(): temporary.unlink()


def _journal(folder,record):
    _write(folder/'journal.json',(json.dumps(record,sort_keys=True,indent=2)+'\n').encode())


@contextmanager
def _locked(root,blocking=True,timeout=None,kind='writer'):
    base = _base(root); key=str(base)
    held=getattr(_local,'held',None)
    if held is None: held={}; _local.held=held
    if key in held:
        if kind=='recover':
            yield None
            return
        if kind=='read' and held[key]=='read':
            yield base
            return
        raise RuntimeError('integration operation cannot nest inside active '+held[key]+' lock')
    _mkdir(base)
    with (base/'lock').open('a+b') as handle:
        if timeout is None:
            try: fcntl.flock(handle,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                yield None
                return
        else:
            deadline=time.monotonic()+timeout
            while True:
                try:
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic()>=deadline:
                        raise TimeoutError('integration read barrier timed out; no task progress permitted')
                    time.sleep(.01)
        held[key]=kind
        try: yield base
        finally:
            held.pop(key,None)
            fcntl.flock(handle,fcntl.LOCK_UN)


@contextmanager
def read_barrier(root,timeout=None):
    """Hold a consistent integration view through ledger refresh/gate/save.

    This waits for the physical writer, never rolls it back, and fails closed on
    timeout. Same-thread nested readers share the lock. Tasks must not run under
    an active apply writer; that inversion is rejected rather than deadlocking.
    """
    if timeout is None:
        timeout = 15.0
        # Foreground orchestration may wait longer for a legitimate, expensive
        # ledger refresh. This changes no lock, owner, baseline or authority gate.
        # Exact-root scoping is inherited by native child processes/threads.
        if os.environ.get('KMP_ORCHESTRATION_LOCK_ROOT') == str(Path(root).resolve()):
            try:
                budget = int(os.environ.get('KMP_ORCHESTRATION_LOCK_WAIT_SECONDS', ''))
                if 15 <= budget <= 300:
                    timeout = budget
            except ValueError:
                pass
    if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<0:
        raise ValueError('nonnegative integration barrier timeout required')
    with _locked(root,timeout=timeout,kind='read'):
        yield


def _path(root,name, *, baseline=False):
    path = Path(name)
    forbidden = {'..', '.git'} if baseline else {'..', '.git', '.harness', '.kmp-agent'}
    if (not isinstance(name,str) or not name or path.is_absolute() or
            any(p in forbidden for p in path.parts) or path.as_posix()!=name):
        raise ValueError('integration path must be normalized product-relative path')
    target = root/path
    for current in [target,*target.parents]:
        if current == root: break
        if current.is_symlink(): raise ValueError('integration source contains symlink: '+name)
    if not target.resolve().is_relative_to(root): raise ValueError('integration path escapes project')
    return target


def _fingerprint(path):
    if path.is_symlink(): raise ValueError('integration refuses symlink')
    if not path.exists(): return None
    if not path.is_file(): raise ValueError('integration target must be regular file')
    return {'sha256':_sha(path.read_bytes()),'mode':stat.S_IMODE(path.stat().st_mode)}


def _git_pin(root):
    def git(*args):
        result = subprocess.run(['rtk','proxy','git',*args],cwd=root,capture_output=True,timeout=20)
        if result.returncode: raise ValueError('integration Git pin unavailable')
        return result.stdout
    head = git('rev-parse','HEAD').decode().strip()
    index = Path(git('rev-parse','--git-path','index').decode().strip())
    if not index.is_absolute(): index = root/index
    return {'head':head,'index_sha256':_sha(index.read_bytes()) if index.exists() else None}


def _check_baseline(root,value):
    if isinstance(value,dict):
        if 'path' in value and 'sha256' in value:
            # Baselines are read-only evidence, not integration write targets.
            # Native design/review receipts live under .harness. Keep the same
            # containment/symlink checks and preserve the stricter write policy.
            target = _path(root,value['path'],baseline=True)
            if not target.is_file() or _sha(target.read_bytes())!=value['sha256']:
                raise ValueError('integration baseline changed: '+value['path'])
        for item in value.values(): _check_baseline(root,item)
    elif isinstance(value,list):
        for item in value: _check_baseline(root,item)


def _read(folder):
    path = folder/'journal.json'
    if folder.is_symlink() or path.is_symlink(): raise ValueError('integration journal contains symlink')
    if not path.exists(): return {'state':'STAGING','transaction_id':folder.name}
    record = json.loads(path.read_text())
    if (record.get('schema_version')!=1 or not isinstance(record.get('files'),list)
            or record.get('state') not in TERMINAL|{'PREPARED','APPLYING','ROLLING_BACK','MANUAL'}
            or not isinstance(record.get('transaction_id'),str)):
        raise ValueError('invalid integration journal')
    if record['state']!='ABANDONED':
        pin=record.get('git_pin')
        if not isinstance(pin,dict) or set(pin)!={'head','index_sha256'} or not isinstance(pin.get('head'),str):
            raise ValueError('invalid integration Git pin')
        if not record['files']: raise ValueError('empty integration source map')
    names=[]
    for row in record['files']:
        if not isinstance(row,dict) or not isinstance(row.get('path'),str): raise ValueError('invalid integration file row')
        names.append(row['path'])
        for side in ['before','after']:
            if side not in row: raise ValueError('missing integration before/after pin')
            value=row[side]
            if value is not None and (not isinstance(value,dict) or set(value)!={'sha256','mode'}
                    or not isinstance(value.get('sha256'),str) or len(value['sha256'])!=64
                    or any(c not in '0123456789abcdef' for c in value['sha256'])
                    or type(value.get('mode')) is not int or not 0<=value['mode']<=0o7777
                    or not isinstance(row.get(side+'_snapshot'),str)):
                raise ValueError('invalid integration file fingerprint')
    if len(names)!=len(set(names)): raise ValueError('duplicate integration path')
    return record


def unresolved(root):
    """Read-only fail-closed gate input; no implicit recovery or status mutation."""
    result = []
    base = _base(root)
    if not base.exists(): return result
    for folder in sorted(base.glob('txn-*')):
        try: record = _read(folder)
        except (ValueError,OSError,TypeError): record = {'state':'MANUAL','reason':'unreadable integration journal'}
        if record.get('state') not in TERMINAL:
            result.append({'transaction_id':record.get('transaction_id',folder.name),
                'state':record.get('state'),'reason':record.get('reason'), 'journal':str(folder/'journal.json')})
    return result


def _snapshot(folder,row,side):
    expected = row[side]
    if expected is None: return None
    relative = row[side+'_snapshot']
    path = folder/relative
    if (Path(relative).name!=relative or path.is_symlink() or not path.is_file()
            or _sha(path.read_bytes())!=expected['sha256']):
        raise ValueError('integration snapshot missing or changed')
    return path.read_bytes()


def _install(target,data,fingerprint):
    if fingerprint is None:
        if target.exists(): target.unlink(); _fsync_dir(target.parent)
    else:
        _mkdir(target.parent)
        _write(target,data,fingerprint['mode'])


def _rollback(root,folder,record):
    try:
        if _git_pin(root)!=record['git_pin']: raise ValueError('Git HEAD/index changed')
        _check_baseline(root,record.get('baseline'))
        # Validate the ENTIRE recovery set before the first overwrite. This
        # prevents a known user edit in a later file causing partial rollback.
        prepared = []
        for row in record['files']:
            target = _path(root,row['path']); current = _fingerprint(target)
            if current not in (row['before'],row['after']):
                raise ValueError('source differs from expected before/after: '+row['path'])
            old = _snapshot(folder,row,'before'); _snapshot(folder,row,'after')
            prepared.append((target,old,row,current))
        record.update(state='ROLLING_BACK'); _journal(folder,record)
        for target,old,row,observed in reversed(prepared):
            # Recheck immediately before writing; never overwrite a new edit.
            if _fingerprint(target)!=observed: raise ValueError('source changed during rollback: '+row['path'])
            _install(target,old,row['before'])
        record.update(state='ROLLED_BACK',reason='explicit recovery restored expected integration bytes')
    except (ValueError,OSError,KeyError,TypeError) as error:
        record.update(state='MANUAL',reason=str(error))
    _journal(folder,record)
    return record


def recover(root):
    """Explicit idempotent recovery. MANUAL requires caller/user reconciliation."""
    root = Path(root).resolve(); results=[]
    with _locked(root,blocking=False,kind='recover') as base:
        if base is None: return [{'state':'ACTIVE','reason':'integration lock held; no recovery mutation performed'}]
        for folder in sorted(base.glob('txn-*')):
            try:
                record = _read(folder)
                if record['state']=='STAGING':
                    record.update(schema_version=1,files=[],state='ABANDONED',reason='no durable preparation; apply never started')
                    _journal(folder,record)
                elif record['state'] not in TERMINAL:
                    record = _rollback(root,folder,record)
                results.append({'transaction_id':record.get('transaction_id',folder.name),
                    'state':record['state'],'reason':record.get('reason')})
            except (ValueError,OSError,KeyError,TypeError) as error:
                results.append({'transaction_id':folder.name,'state':'MANUAL','reason':str(error)})
    return results


def apply(root,changes,expected_source,transaction_id,baseline=None,fault_hook=None):
    """changes maps product paths to workspace paths (None means deletion).

    expected_source is the worker's starting content hash for each changed path.
    fault_hook is an explicit test fault boundary, never loaded from settings.
    """
    root = Path(root).resolve()
    if not changes or set(changes)!=set(expected_source): raise ValueError('exact integration source map required')
    with _locked(root) as base:
        if unresolved(root): raise ValueError('unresolved integration transaction; explicit recovery required')
        folder = base/('txn-'+_sha(str(transaction_id).encode()))
        if folder.exists():
            previous = _read(folder)
            if (previous['state']=='COMMITTED' and previous.get('baseline')==baseline
                    and previous.get('git_pin')==_git_pin(root)
                    and {row['path'] for row in previous['files']}==set(changes)
                    and {row['path']:(row['before'] or {}).get('sha256') for row in previous['files']}==expected_source
                    and all(_fingerprint(_path(root,row['path']))==row['after']
                        and (_fingerprint(Path(changes[row['path']])) if changes[row['path']] is not None else None)==row['after']
                        for row in previous['files'])):
                for row in previous['files']: _snapshot(folder,row,'before'); _snapshot(folder,row,'after')
                return dict(previous,cached=True)
            raise ValueError('integration transaction identity already used')
        folder.mkdir(); _fsync_dir(base)
        record = {'schema_version':1,'transaction_id':str(transaction_id),'state':'PREPARED',
            'git_pin':_git_pin(root),'baseline':baseline,'files':[]}
        try:
            _check_baseline(root,baseline)
            for number,name in enumerate(sorted(changes)):
                target = _path(root,name); before = _fingerprint(target)
                if (before or {}).get('sha256')!=expected_source[name]: raise ValueError('integration source changed: '+name)
                source = Path(changes[name]) if changes[name] is not None else None
                after = _fingerprint(source) if source is not None else None
                if source is not None and after is None: raise ValueError('integration workspace source missing')
                row = {'path':name,'before':before,'after':after}
                for side,path in [('before',target),('after',source)]:
                    if row[side] is not None:
                        name_snapshot = str(number)+'-'+side+'.bin'
                        data = path.read_bytes()
                        if _sha(data)!=row[side]['sha256']: raise ValueError('source changed during staging')
                        _write(folder/name_snapshot,data,0o400); row[side+'_snapshot']=name_snapshot
                record['files'].append(row)
            _journal(folder,record)
            if fault_hook: fault_hook('prepared',None)
            if _git_pin(root)!=record['git_pin']: raise ValueError('Git HEAD/index changed during staging')
            _check_baseline(root,baseline)
            if any(_fingerprint(_path(root,row['path']))!=row['before'] for row in record['files']):
                raise ValueError('integration source changed during staging')
            record['state']='APPLYING'; _journal(folder,record)
            for row in record['files']:
                target = _path(root,row['path'])
                if _fingerprint(target)!=row['before']: raise ValueError('source changed during integration: '+row['path'])
                _install(target,_snapshot(folder,row,'after'),row['after'])
                if fault_hook: fault_hook('applied',row['path'])
            record['state']='COMMITTED'; _journal(folder,record)
            return record
        except Exception:
            # Only a durable APPLYING journal authorizes any source restoration.
            if (folder/'journal.json').exists(): _rollback(root,folder,record)
            else:
                record.update(state='ABANDONED',reason='staging failed before any source write')
                _journal(folder,record)
            raise
