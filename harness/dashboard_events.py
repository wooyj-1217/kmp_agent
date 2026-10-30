"""Native invalidations only: no periodic filesystem reads or snapshot computation."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import stat as file_stat
import subprocess
import sys
import threading
import time
import uuid


IGNORED = {'.git', '__pycache__', 'node_modules', 'build', '.gradle', '.idea',
           'artifacts', 'cache', 'caches', 'dashboard-cache', 'derivedData', 'releases',
           'Build', 'DerivedData', 'ios-derived', 'screenshots', 'video', 'videos'}


def included(path):
    return not (set(path.parts) & IGNORED or path.name.endswith(('.lock', '.pyc'))
                or 'cursor' in path.name or path.name.startswith('.dashboard-'))


class NativeEvents:
    """One watcher per server; a revision represents a debounced metadata change."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.condition = threading.Condition()
        self.revision = uuid.uuid4().hex + ':0'
        self.status = 'native'
        self.closed = False
        self._number = 0
        self._handles = {}
        self._metadata = {}
        self._digests = {}
        self._wake, self._writer = socket.socketpair()
        self._backend = None
        self._thread = None
        try:
            if hasattr(select, 'kqueue'):
                self._backend = select.kqueue()
                self._kind = 'kqueue'
            elif sys.platform.startswith('linux'):
                self._libc = ctypes.CDLL(None, use_errno=True)
                self._backend = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
                if self._backend < 0:
                    raise OSError(ctypes.get_errno(), 'inotify_init1')
                self._kind = 'inotify'
            else:
                raise OSError('native filesystem notifications unsupported')
            self._state = self._scan()
            self._thread = threading.Thread(target=self._run, name='dashboard-native-events', daemon=True)
            self._thread.start()
        except (OSError, AttributeError) as error:
            self.status = 'manual: ' + str(error)
            self._dispose()

    def _scan(self):
        state = {}
        # Watch input trees, not product sources, media, immutable releases or build output.
        targets = [self.root / name for name in (
            'docs', '.harness/tasks', '.harness/usage', '.harness/requests',
            '.harness/dashboard', '.kmp-agent', '.harness/logs/events.jsonl',
            '.harness/dashboard-scopes.json', '.harness/integration-status.json',
            'AGENTS.md', 'README.md')]
        code_scopes = []
        def references(value):
            if isinstance(value, dict):
                tracking = value.get("development_tracking")
                if isinstance(tracking, dict):
                    code_scopes.extend(tracking.get("code_paths") or ["."])
                for key, item in value.items():
                    if key in {'path', 'snapshot'} and isinstance(item, str):
                        path = (self.root / item).resolve()
                        if path != self.root and path.is_relative_to(self.root) and not path.is_dir() and included(path.relative_to(self.root)):
                            targets.append(path)
                    elif isinstance(item, (dict, list)):
                        references(item)
            elif isinstance(value, list):
                for item in value:
                    references(item)
        for name in ('.harness/tasks/tasks.yaml', '.harness/dashboard-scopes.json'):
            try:
                references(json.loads((self.root / name).read_text()))
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        # Development evidence depends on source contents, index and HEAD. Only
        # registered scopes are walked; Git object storage is never traversed.
        for scope in code_scopes:
            if isinstance(scope, str):
                target = (self.root / scope).resolve()
                if target.is_relative_to(self.root):
                    targets.append(target)
        # Git can track files under otherwise ignored build/media directories.
        # capture() includes those files, so include exact paths without walking
        # their generated siblings.
        if code_scopes:
            result = subprocess.run(["rtk", "proxy", "git", "ls-files", "-z", "--cached",
                                     "--others", "--exclude-standard", "--", *code_scopes],
                                    cwd=self.root, capture_output=True, text=True)
            if result.returncode == 0:
                for name in result.stdout.split("\0"):
                    target = self.root / name
                    if name and target.resolve().is_relative_to(self.root) and not name.startswith((".harness/", ".kmp-agent/")):
                        targets.append(target)
        git_targets = []
        if code_scopes:
            result = subprocess.run(["rtk", "proxy", "git", "rev-parse", "--git-dir", "--git-common-dir"],
                                    cwd=self.root, capture_output=True, text=True)
            if result.returncode == 0:
                for name in result.stdout.splitlines():
                    git_dir = (self.root / name).resolve()
                    git_targets.extend(git_dir / part for part in
                                       ("HEAD", "index", "packed-refs", "refs", "config", "info/exclude"))
        paths = {self.root}
        for target in targets:
            paths.add(target)
            paths.update(parent for parent in target.parents if parent.is_relative_to(self.root))
            if target.is_dir() and not target.is_symlink():
                for directory, dirs, files in os.walk(target, followlinks=False):
                    base = Path(directory)
                    dirs[:] = [n for n in dirs if included((base / n).relative_to(self.root)) and not (base / n).is_symlink()]
                    paths.update(base / n for n in dirs + files if included((base / n).relative_to(self.root)))
        for target in git_targets:
            paths.add(target)
            # Native events on parents detect atomic replacement and new refs.
            paths.add(target.parent)
            if target.is_dir():
                for directory, dirs, files in os.walk(target, followlinks=False):
                    base = Path(directory)
                    dirs[:] = [n for n in dirs if not (base / n).is_symlink()]
                    paths.update(base / n for n in dirs + files)
        existing = set()
        for path in paths:
            if self.closed:
                return state
            try:
                stat = path.stat(follow_symlinks=False)
                if path.is_symlink():
                    continue
                directory = file_stat.S_ISDIR(stat.st_mode)
                if not directory and not file_stat.S_ISREG(stat.st_mode):
                    continue
                existing.add(path)
                # Directory metadata includes ignored reader-lock creation. Compare files only.
                if not directory:
                    metadata = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                    if self._metadata.get(path) != metadata:
                        with path.open('rb') as source:
                            digest = hashlib.sha256()
                            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                                digest.update(chunk)
                            self._digests[path] = digest.hexdigest()
                        self._metadata[path] = metadata
                    state[str(path)] = (self._digests[path], stat.st_mode & 0o777)
                old = self._handles.get(path)
                if old and old[1] == stat.st_ino:
                    continue
                if old:
                    self._remove(path)
                if self._kind == 'kqueue':
                    fd = os.open(path, getattr(os, 'O_EVTONLY', os.O_RDONLY))
                    flags = select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_ATTRIB | select.KQ_NOTE_EXTEND
                    try:
                        self._backend.control([select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=flags)], 0, 0)
                    except BaseException:
                        os.close(fd)
                        raise
                    self._handles[path] = (fd, stat.st_ino)
                elif directory:
                    wd = self._libc.inotify_add_watch(self._backend, os.fsencode(path), 0x00000FCE)
                    if wd < 0:
                        raise OSError(ctypes.get_errno(), 'inotify_add_watch')
                    self._handles[path] = (wd, stat.st_ino)
            except FileNotFoundError:
                continue
        for path in set(self._metadata) - existing:
            self._metadata.pop(path, None)
            self._digests.pop(path, None)
        for path in set(self._handles) - existing:
            self._remove(path)
        return state

    def _remove(self, path):
        handle, _ = self._handles.pop(path)
        if self._kind == 'kqueue':
            os.close(handle)
        else:
            self._libc.inotify_rm_watch(self._backend, handle)

    def _drain(self):
        if self._kind == 'kqueue':
            self._backend.control(None, max(1, len(self._handles)), 0)
        else:
            try:
                while os.read(self._backend, 65536):
                    pass
            except BlockingIOError:
                pass

    def _run(self):
        try:
            while not self.closed:
                ready, _, _ = select.select([self._backend, self._wake], [], [])
                if self._wake in ready:
                    return
                self._drain()
                # Bounded burst coalescing; timeout is only armed after a native event.
                deadline = time.monotonic() + .12
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([self._backend, self._wake], [], [], max(0, deadline - time.monotonic()))
                    if self._wake in ready:
                        return
                    if self._backend in ready:
                        self._drain()
                state = self._scan()
                if self.closed:
                    return
                if state != self._state:
                    self._state = state
                    with self.condition:
                        self._number += 1
                        self.revision = self.revision.split(':')[0] + ':' + str(self._number)
                        self.condition.notify_all()
        except (OSError, ValueError) as error:
            if not self.closed:
                with self.condition:
                    self.status = 'manual: ' + str(error)
                    self.condition.notify_all()

    def wait(self, revision, timeout=1):
        with self.condition:
            if self.revision == revision and not self.closed and self.status == 'native':
                self.condition.wait(timeout)
            return self.revision

    def _dispose(self):
        for path in list(self._handles):
            self._remove(path)
        if self._backend is not None:
            if isinstance(self._backend, int):
                if self._backend >= 0:
                    os.close(self._backend)
            else:
                self._backend.close()
            self._backend = None

    def close(self):
        if self.closed:
            return
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self._thread:
            self._writer.send(b'x')
            self._thread.join()
        self._dispose()
        self._wake.close()
        self._writer.close()
