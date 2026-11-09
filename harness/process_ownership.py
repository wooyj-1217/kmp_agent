"""Local process identity and exclusive execution leases.

Kernel flock, not JSON existence/mtime, establishes slot ownership. Identity
checks fail closed on unsupported hosts, PID reuse or missing evidence. Native
PID checks precede signals; macOS has no pidfd-style atomic check-and-signal,
so this is not an OS security boundary against hostile same-user processes.
"""
import contextlib
import copy
import ctypes
import errno
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

_local = threading.local()


def current_lease(root, task_id):
    return getattr(_local, 'leases', {}).get((str(Path(root).resolve()), task_id))


def managed_task(function):
    @functools.wraps(function)
    def wrapped(self, task_id, *args, **kwargs):
        if current_lease(self.root, task_id):
            return function(self, task_id, *args, **kwargs)
        with TaskLease(self.root, task_id):
            return function(self, task_id, *args, **kwargs)
    return wrapped


def _boot_id():
    if sys.platform.startswith('linux'):
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if sys.platform == 'darwin':
        value = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.boottime'], capture_output=True, text=True, timeout=3, check=True).stdout
        parts = re.search(r'sec\s*=\s*(\d+),\s*usec\s*=\s*(\d+)', value)
        if not parts:
            raise ValueError('unrecognized boot identity')
        return ':'.join(parts.groups())
    raise ValueError('unsupported process identity host')


@functools.lru_cache(maxsize=1)
def _host_boot():
    # A process cannot survive a host reboot; caching avoids a sysctl process
    # on every guardian poll. Missing boot access still uses precise birth ID.
    try:
        return _boot_id()
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'UNKNOWN'


class _BsdInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in
        ('flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'rfu')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'pjobc', 'e_tdev', 'e_tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64), ('start_usec', ctypes.c_uint64)]


def owner_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    result = {'pid': pid, 'host': platform.node(), 'status': 'UNKNOWN'}
    if type(pid) is not int or pid <= 0:
        return result
    result['boot_id'] = _host_boot()
    try:
        if sys.platform.startswith('linux'):
            text = Path('/proc', str(pid), 'stat').read_text()
            fields = text[text.rfind(')') + 2:].split()
            result.update(start_id=fields[19], pgid=int(fields[2]), ppid=int(fields[1]),
                          status='DEAD' if fields[0] in ('Z', 'X') else 'ALIVE')
        elif sys.platform == 'darwin':
            lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
            info = _BsdInfo()
            ctypes.set_errno(0)
            size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if size != ctypes.sizeof(info):
                if ctypes.get_errno() in (errno.ESRCH, errno.ENOENT):
                    result['status'] = 'DEAD'
                    return result
                os.kill(pid, 0)
                return result
            result.update(start_id=f'{info.start_sec}:{info.start_usec}', pgid=info.pgid, ppid=info.ppid,
                          status='DEAD' if info.status == 5 else 'ALIVE')
        if result['status'] == 'ALIVE':
            result['identity_assurance'] = 'HOST_BOOT_PROCESS_BIRTH' if result['boot_id'] != 'UNKNOWN' else 'HOST_PROCESS_BIRTH'
        return result
    except (FileNotFoundError, ProcessLookupError):
        result['status'] = 'DEAD'
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    return result


def inspect_owner(expected):
    """A reused PID is UNKNOWN, never a death certificate or kill target."""
    if not isinstance(expected, dict) or expected.get('status') != 'ALIVE':
        return {'status': 'UNKNOWN', 'reason': 'missing original live identity'}
    current = owner_identity(expected.get('pid'))
    if not expected.get('host') or current.get('host') != expected['host']:
        return {'status': 'UNKNOWN', 'reason': 'host identity mismatch', 'current': current}
    old_boot, new_boot = expected.get('boot_id', 'UNKNOWN'), current.get('boot_id', 'UNKNOWN')
    if old_boot != 'UNKNOWN' and new_boot != 'UNKNOWN' and old_boot != new_boot:
        return {'status': 'UNKNOWN', 'reason': 'boot identity mismatch', 'current': current}
    if current['status'] == 'DEAD':
        return {'status': 'DEAD', 'reason': 'original process exited', 'current': current}
    if current['status'] != 'ALIVE' or current.get('start_id') != expected.get('start_id'):
        return {'status': 'UNKNOWN', 'reason': 'PID reused or identity unavailable', 'current': current}
    if current.get('pgid') != expected.get('pgid'):
        return {'status': 'UNKNOWN', 'reason': 'process group changed', 'current': current}
    return {'status': 'ALIVE', 'reason': 'exact identity live', 'current': current}


def _directory(root, task_id):
    root = Path(root).resolve()
    folder = root / '.harness' / 'process-ownership' / hashlib.sha256(task_id.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to(root):
        raise ValueError('lease directory escapes project')
    return folder


def _read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextlib.contextmanager
def exclusive_slot(root, task_id):
    """Nonblocking physical slot; recovery and dispatch must share this lock.

    Lock files must never be unlinked, including during cleanup.
    """
    folder = _directory(root, task_id)
    fd = os.open(folder / 'lease.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    os.set_inheritable(fd, False)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('lease lock must be a regular file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('task execution lease held; recovery/duplicate execution refused') from error
        yield folder
    finally:
        os.close(fd)


def inspect_lease(root, task_id):
    folder = _directory(root, task_id)
    record = _read(folder / 'owner.json')
    held = False
    try:
        with exclusive_slot(root, task_id):
            pass
    except RuntimeError:
        held = True
    if record is None:
        return {'status': 'UNKNOWN' if held else 'ABSENT', 'held': held, 'record': None,
                'reason': 'no readable ownership receipt'}
    result = inspect_owner(record.get('owner'))
    status = result['status']
    if held and status != 'ALIVE':
        status = 'UNKNOWN'
    if not held and status == 'ALIVE':
        status = 'UNKNOWN'  # A live PID without its lease is not recoverable proof.
    return {'status': status, 'held': held, 'record': record, 'reason': result['reason']}


def read_owner(root, task_id):
    """Read again while holding exclusive_slot during a recovery transaction."""
    return _read(_directory(root, task_id) / 'owner.json')


def _group_members(pgid):
    if sys.platform.startswith('linux'):
        pids = [int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()]
    elif sys.platform == 'darwin':
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        # PROC_PGRP_ONLY=2. Extra room tolerates new members; omitted members
        # are not signaled blindly and remain an explicit cleanup limitation.
        ctypes.set_errno(0)
        size = lib.proc_listpids(2, pgid, None, 0)
        if size <= 0:
            if ctypes.get_errno():
                raise ValueError('process group inspection unavailable')
            return []
        items = (ctypes.c_int * (size // ctypes.sizeof(ctypes.c_int) + 128))()
        count = lib.proc_listpids(2, pgid, items, ctypes.sizeof(items))
        if count < 0:
            raise ValueError('cannot enumerate child process group')
        pids = list(items)[:count // ctypes.sizeof(ctypes.c_int)]
    else:
        raise ValueError('unsupported process group inspection')
    return [i for i in (owner_identity(p) for p in pids if p > 0)
            if i['status'] == 'ALIVE' and i.get('pgid') == pgid]


def inspect_child(child):
    try:
        identity = child['identity']
        if child.get('completion') == 'REAPED_NO_GROUP_MEMBERS':
            if type(child.get('returncode')) is not int or owner_identity(identity['pid'])['status'] != 'DEAD' or _group_members(identity['pgid']):
                return {'status': 'UNKNOWN', 'reason': 'reaped child PID/group no longer demonstrably empty'}
            return {'status': 'DEAD', 'reason': 'Popen reaped child and dedicated group empty'}
        state = inspect_owner(identity)
        if state['status'] == 'DEAD' and _group_members(identity['pgid']):
            return {'status': 'UNKNOWN', 'reason': 'leader exited but unregistered group members remain'}
        return state
    except (ValueError, OSError, KeyError, TypeError):
        return {'status': 'UNKNOWN', 'reason': 'child process group identity unavailable'}


def safe_stop_child(child, token, agent_run_id=None, grace=0.5):
    if not isinstance(child, dict) or child.get('token') != token or child.get('agent_run_id') != agent_run_id:
        return {'status': 'UNKNOWN', 'reason': 'child ownership binding mismatch'}
    leader = child.get('identity')
    state = inspect_child(child)
    if state['status'] != 'ALIVE':
        return state  # Never kill a reused PID or an unidentifiable orphan group.
    if leader.get('pgid') != leader.get('pid') or leader['pgid'] == os.getpgrp():
        return {'status': 'UNKNOWN', 'reason': 'dedicated child process group required'}
    try:
        members = _group_members(leader['pgid'])
        if not any(i['pid'] == leader['pid'] and i.get('start_id') == leader.get('start_id') for i in members):
            return {'status': 'UNKNOWN', 'reason': 'group leader identity changed'}
        # Signal only individually verified members; never broad killpg after
        # a leader disappears. Escaped/new descendants are not assumed owned.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for identity in members:
                if inspect_owner(identity)['status'] == 'ALIVE':
                    os.kill(identity['pid'], sig)
            if sig == signal.SIGTERM:
                time.sleep(max(0, min(grace, 5)))
        until = time.monotonic() + 1
        statuses = [inspect_owner(i)['status'] for i in members]
        while any(s == 'ALIVE' for s in statuses) and time.monotonic() < until:
            time.sleep(.02)
            statuses = [inspect_owner(i)['status'] for i in members]
        return {'status': 'DEAD' if all(s == 'DEAD' for s in statuses) and not _group_members(leader['pgid']) else 'UNKNOWN',
                'reason': 'registered exact process group members stopped', 'members': members}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {'status': 'UNKNOWN', 'reason': str(error)}


class TaskLease:
    def __init__(self, root, task_id, agent_run_id=None):
        self.root = Path(root).resolve(); self.task_id = task_id
        self.agent_run_id = agent_run_id; self._record = None; self._slot = None

    def __enter__(self):
        self._slot = exclusive_slot(self.root, self.task_id)
        folder = self._slot.__enter__()
        try:
            previous = _read(folder / 'owner.json')
            if previous is None and (folder / 'owner.json').exists():
                raise RuntimeError('unreadable previous ownership receipt requires manual recovery')
            if previous and not previous.get('released'):
                state = inspect_owner(previous.get('owner'))
                if state['status'] != 'DEAD':
                    raise RuntimeError('previous owner is live/unknown; explicit recovery required')
                if previous.get('spawn_pending'):
                    raise RuntimeError('unregistered spawn intent requires manual recovery')
                for child in previous.get('children', []):
                    if inspect_child(child)['status'] != 'DEAD':
                        raise RuntimeError('previous registered children unresolved; recovery required')
            identity = owner_identity()
            if identity['status'] != 'ALIVE':
                raise RuntimeError('cannot establish exact local process identity')
            token = str(uuid.uuid4())
            self.path = folder / ('attempt-' + token + '.json')
            self.current_path = folder / 'owner.json'
            self._record = {'version': 1, 'task_id': self.task_id, 'agent_run_id': self.agent_run_id,
                'run_ids': [self.agent_run_id] if self.agent_run_id else [],
                'token': token, 'owner': identity, 'children': [], 'released': False,
                'spawn_pending': [],
                'receipt_path': str(self.path)}
            self._save()
            if not hasattr(_local, 'leases'):
                _local.leases = {}
            _local.leases[(str(self.root), self.task_id)] = self
            return self
        except BaseException:
            self._slot.__exit__(*sys.exc_info()); self._slot = None
            raise

    def _save(self):
        _write(self.path, self._record); _write(self.current_path, self._record)

    def record(self):
        return copy.deepcopy(self._record)

    def spawn_intent(self):
        token = str(uuid.uuid4())
        self._record['spawn_pending'].append(token); self._save()
        return token

    def cancel_intent(self, intent):
        """Caller may use only after Popen raised before returning a child."""
        if intent not in self._record['spawn_pending']:
            raise ValueError('unknown pending spawn intent')
        self._record['spawn_pending'].remove(intent)
        self._record.setdefault('cancelled_intents', []).append(intent)
        self._save()

    def bind(self, agent_run_id):
        if self._record['agent_run_id'] == agent_run_id:
            return self.record()
        if self._record['spawn_pending'] or any(inspect_child(c)['status'] != 'DEAD' for c in self._record['children']):
            raise ValueError('previous agent run still owns unresolved children/spawn intent')
        self.agent_run_id = agent_run_id; self._record['agent_run_id'] = agent_run_id; self._save()
        if agent_run_id not in self._record['run_ids']:
            self._record['run_ids'].append(agent_run_id)
            self._save()
        return self.record()

    def register_child(self, process, intent=None):
        identity = owner_identity(process.pid)
        child = {'token': self._record['token'], 'agent_run_id': self.agent_run_id, 'identity': identity}
        if identity['status'] != 'ALIVE' or identity.get('pgid') != process.pid or identity.get('ppid') != os.getpid() or process.pid == os.getpgrp():
            # A genuinely returned Popen can certify its own already-reaped
            # child; a fake PID/mock or residual group cannot clear an intent.
            actual_popen = any(c.__module__ == 'subprocess' and c.__name__ == 'Popen' for c in type(process).__mro__)
            code = process.poll() if actual_popen else None
            observed = owner_identity(process.pid)
            if type(code) is not int or observed['status'] != 'DEAD' or _group_members(process.pid):
                raise ValueError('live owned child or reaped empty dedicated group required')
            child.update(completion='REAPED_NO_GROUP_MEMBERS', returncode=code,
                         identity={**observed, 'pgid': process.pid})
        if intent is None and len(self._record['spawn_pending']) == 1:
            intent = self._record['spawn_pending'][0]
        if intent is not None:
            if intent not in self._record['spawn_pending']:
                raise ValueError('unknown spawn intent')
            self._record['spawn_pending'].remove(intent)
            child['spawn_intent'] = intent
        self._record['children'].append(child); self._save()
        return child

    def start_guardian(self):
        if self._record.get('guardian'):
            raise ValueError('guardian already started')
        env = dict(os.environ)
        source = str(Path(__file__).resolve().parent.parent)
        env['PYTHONPATH'] = source + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        child = subprocess.Popen([sys.executable, '-B', '-m', 'harness.process_ownership', '--watch', str(self.path), self._record['token']],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=True, env=env)
        self._record['guardian'] = owner_identity(child.pid); self._save()
        self._guardian = child
        return child

    def __exit__(self, *exc):
        try:
            results = [safe_stop_child(c, self._record['token'], c.get('agent_run_id')) for c in self._record['children']]
            self._record['cleanup'] = results
            self._record['released'] = not self._record['spawn_pending'] and all(r['status'] == 'DEAD' for r in results)
            self._record['closed'] = True
            self._save()
            guardian = getattr(self, '_guardian', None)
            if guardian is not None:
                try:
                    guardian.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass  # Unknown watcher state is not permission for broad kill.
        finally:
            getattr(_local, 'leases', {}).pop((str(self.root), self.task_id), None)
            self._slot.__exit__(*exc); self._slot = None


def _watch(path, token):
    path = Path(path)
    while True:
        record = _read(path)
        if not record or record.get('token') != token or record.get('released') or record.get('closed'):
            return
        state = inspect_owner(record.get('owner'))
        if state['status'] == 'UNKNOWN':
            return  # Never guess that a reused/remote PID is dead.
        if state['status'] == 'DEAD':
            result = [safe_stop_child(c, token, c.get('agent_run_id')) for c in record.get('children', [])]
            _write(path.with_name(path.name + '.cleanup.json'), {'token': token, 'owner_state': state, 'children': result})
            return
        time.sleep(0.1)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--watch':
        _watch(sys.argv[2], sys.argv[3])
