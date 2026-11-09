"""Exact-prefix event append recovery. Call only while holding events file LOCK_EX.

Unknown tails are never truncated. Journals provide crash recovery, not protection
against a same-account writer changing both journal and event log.
"""
import hashlib
import json
import os
import uuid


def atomic_json(path, value):
    temp = path.with_name(path.name + '.' + str(uuid.uuid4()) + '.tmp')
    try:
        with temp.open('x') as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(value, f)
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def write_payload(handle, encoded):
    handle.seek(0, 2)
    target = getattr(handle, 'buffer', handle)
    view = memoryview(encoded)
    while view:
        written = target.write(view)
        if not written:
            raise OSError('event append made no progress')
        view = view[written:]
    target.flush(); os.fsync(handle.fileno())
    os.fchmod(handle.fileno(), 0o600)


def recover_locked(path, handle):
    recovered = 0
    for name in ('collection-batch-intent.json', 'events-append-intent.json'):
        journal = path.parent / name
        if not journal.exists(): continue
        intent = json.loads(journal.read_text())
        if intent.get('state') == 'COMMITTED': continue
        handle.seek(0)
        raw = getattr(handle, 'buffer', handle).read()
        if isinstance(raw, str): raw = raw.encode()
        start = intent['start']; encoded = intent['encoded'].encode()
        if (type(start) is not int or start < 0 or len(raw) < start
                or hashlib.sha256(raw[:start]).hexdigest() != intent['prefix_sha256']):
            raise ValueError('event intent prefix mismatch; preserve and inspect')
        tail = raw[start:]
        if len(tail) >= len(encoded):
            if tail[:len(encoded)] != encoded:
                raise ValueError('event intent conflicts with saved events; preserve and inspect')
        elif encoded.startswith(tail):
            write_payload(handle, encoded[len(tail):])
            recovered += len(encoded)-len(tail)
        else:
            raise ValueError('event intent tail mismatch; preserve and inspect')
        atomic_json(journal, dict(state='COMMITTED', end=start+len(encoded)))
    handle.seek(0)
    data = getattr(handle, 'buffer', handle).read()
    if isinstance(data, str): data = data.encode()
    if data and not data.endswith(b'\n'):
        raise ValueError('incomplete event log tail without matching intent; preserve and inspect')
    return recovered


def append_locked(path, handle, encoded, writer=None, intent_durable=None):
    recover_locked(path, handle)
    handle.seek(0)
    data = getattr(handle, 'buffer', handle).read()
    if isinstance(data, str): data = data.encode()
    journal = path.parent / 'events-append-intent.json'
    atomic_json(journal, dict(start=len(data), prefix_sha256=hashlib.sha256(data).hexdigest(), encoded=encoded.decode()))
    if intent_durable: intent_durable()
    (writer or write_payload)(handle, encoded)
    atomic_json(journal, dict(state='COMMITTED', end=len(data)+len(encoded)))
