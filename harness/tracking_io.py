"""Bounded inspection I/O and opt-in raw diagnostics; no task status store."""
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import json
import os
from pathlib import Path
import subprocess
import threading
import time

GIT_TIMEOUT_SECONDS = 5.0
CAPTURE_TIMEOUT_SECONDS = 15.0
LOCK_TIMEOUT_SECONDS = 10.0
_deadline = ContextVar('tracking_deadline', default=None)


def trace(root, event, **fields):
    if os.environ.get('KMP_AGENT_DIAGNOSTICS') != '1': return
    path=Path(root)/'.harness/logs/inspection-diagnostics.jsonl'
    path.parent.mkdir(parents=True,exist_ok=True)
    payload={'event':event,'monotonic':time.monotonic(),'pid':os.getpid(),'thread':threading.get_ident(),**fields}
    fd=os.open(path,os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
    try:os.write(fd,(json.dumps(payload,sort_keys=True)+'\n').encode())
    finally:os.close(fd)


@contextmanager
def capture_budget(root, task_id):
    started=time.monotonic();previous=_deadline.get()
    token=_deadline.set(min(previous,started+CAPTURE_TIMEOUT_SECONDS) if previous else started+CAPTURE_TIMEOUT_SECONDS)
    trace(root,'capture_started',task_id=task_id)
    try:yield
    finally:
        trace(root,'capture_finished',task_id=task_id,elapsed_seconds=time.monotonic()-started)
        _deadline.reset(token)


def run_git(root, *args, input=None):
    remaining=GIT_TIMEOUT_SECONDS
    if _deadline.get() is not None:remaining=min(remaining,_deadline.get()-time.monotonic())
    if remaining<=0:raise ValueError('capture inspection deadline exceeded; validation not established')
    argv=['rtk','proxy','git',*args];started=time.monotonic()
    trace(root,'git_started',operation=args[0] if args else '',timeout_seconds=remaining)
    child=subprocess.Popen(argv,cwd=root,stdin=subprocess.PIPE if input is not None else None,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    error=None
    try:
        stdout,stderr=child.communicate(input=input,timeout=remaining)
        return subprocess.CompletedProcess(argv,child.returncode,stdout,stderr)
    except BaseException as exc:
        error=type(exc).__name__
        from harness.execution_policy import stop_owned_group
        stop_owned_group(child,lambda owned,timeout:owned.communicate(timeout=timeout),timeout=1)
        if isinstance(exc,subprocess.TimeoutExpired):raise ValueError('Git inspection timed out; validation not established') from exc
        raise
    finally:trace(root,'git_finished',operation=args[0] if args else '',pid=child.pid,returncode=child.returncode,error=error,elapsed_seconds=time.monotonic()-started)


@contextmanager
def state_lock(root, path, action):
    start=time.monotonic();trace(root,'state_lock_wait',action=action)
    with Path(path).open('a+') as handle:
        while True:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()-start>=LOCK_TIMEOUT_SECONDS:
                    trace(root,'state_lock_timeout',action=action,wait_seconds=time.monotonic()-start)
                    raise TimeoutError('task state lock timed out; no stale status or mutation returned')
                time.sleep(.01)
        acquired=time.monotonic();trace(root,'state_lock_acquired',action=action,wait_seconds=acquired-start)
        try:yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)
            trace(root,'state_lock_released',action=action,held_seconds=time.monotonic()-acquired)
