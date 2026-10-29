"""Explicit, per-session native response collection while work is running.

No global 'current role', timestamp slicing, text classification or new model call.
Exact main turn/response ownership is declared by the performing agent.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import time
from harness import logging
from harness.usage_context import VERSION, digest


def append_unique(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    value = dict(value); value['id'] = digest(value)
    with path.open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.seek(0)
        if any(json.loads(l).get('id') == value['id'] for l in f if l.strip()):
            return False
        f.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n'); f.flush(); os.fsync(f.fileno())
    return True


def registrations(root):
    from harness.usage_provenance import read_jsonl
    return read_jsonl(Path(root) / '.harness/usage/sessions.jsonl')


def register(manager, task_id, execution_id, session_id, *, path=None, turn_id=None,
             response_ids=None, independent=False, call_id=None, import_scope='session'):
    state = manager.read(); task = state['tasks'][task_id]
    run = next((r for r in task['executions'] if r['agent_run_id'] == execution_id), None)
    if not run:
        raise ValueError('explicit existing execution required')
    if independent and run['execution_mode'] != 'independent_process':
        raise ValueError('independent session requires the existing independent execution mode')
    if not independent and (run['execution_mode'] != 'current_agent' or not (turn_id or response_ids)):
        raise ValueError('main session needs an exact turn or explicit response IDs; no temporal inference')
    if not isinstance(session_id, str) or not session_id or session_id == 'UNKNOWN':
        raise ValueError('native session identity required')
    if response_ids and (not isinstance(response_ids, list) or any(not isinstance(x, str) or not x for x in response_ids)):
        raise ValueError('response IDs must be explicit')
    if import_scope not in {'session', 'registered_turns'} or import_scope == 'registered_turns' and (independent or not turn_id):
        raise ValueError('registered-turn import requires an explicit main native turn')
    value = {'version': VERSION, 'task_id': task_id, 'execution_id': execution_id,
             'run_id': run['run_id'], 'session_id': session_id,
             'source_path': str(Path(path).expanduser().resolve()) if path else None,
             'turn_id': turn_id, 'response_ids': sorted(response_ids or []),
             'independent': independent, 'call_id': call_id, 'context_sha256': digest(run.get('usage_context')),
             'import_scope': import_scope,
             'basis': 'native thread.started for exact worker process' if independent else 'performing agent explicitly declared native turn/response context'}
    append_unique(manager.root / '.harness/usage/sessions.jsonl', value)
    return value


def poll(manager):
    root = manager.root; directory = root / '.harness/usage'; directory.mkdir(parents=True, exist_ok=True)
    from harness.incremental_sync import collect, atomic_json
    status = []; count = 0
    with (directory / 'collection.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous_path = directory / 'collection-state.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        incremental_seen = {(r['session_id'], r['execution_id']) for r in previous.get('sessions', []) if r.get('had_incremental_usage')}
        registered = registrations(root)
        sessions = sorted({r['session_id'] for r in registered})
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        for session in sessions:
            entries = [r for r in registered if r['session_id'] == session]
            paths = {r['source_path'] for r in entries if r.get('source_path')}
            if not paths:
                paths = {str(p) for p in (home / 'sessions').rglob('*' + session + '.jsonl')}
            observed = {'session_id': session, 'mode': 'incremental', 'status': 'source_pending'}
            if len(paths) != 1:
                observed['status'] = 'source_pending' if not paths else 'source_ambiguous'
            else:
                source = Path(next(iter(paths)))
                try:
                    with source.open() as f:
                        meta = json.loads(f.readline())
                    if meta.get('type') != 'session_meta' or meta.get('payload', {}).get('session_id', meta.get('payload', {}).get('id')) != session:
                        raise ValueError('native session identity mismatch')
                    # A shared main session can contain unrelated past requests.
                    # Independent workers own the whole freshly-created session;
                    # main work owns only explicitly registered native turns.
                    turns = None if any(r.get('import_scope', 'session') == 'session' for r in entries) else sorted({r['turn_id'] for r in entries if r.get('turn_id')})
                    if turns == []:
                        # Explicit response-only registrations retain the existing
                        # converter; binding still requires the exact response ID.
                        turns = None
                    collect(manager.logger, source, mode='usage_stream', turn_ids=turns)
                    source_events = [e for e in manager.logger.read() if e['event_type'] == 'model_usage' and e.get('source', {}).get('session_id') == session]
                    # Native bind_usage performs task/validation checks. Repeating
                    # that mutation for every already-bound response makes long
                    # real sessions block fresh response collection.
                    current = manager.read()
                    bound = {(run['agent_run_id'], b.get('session_id'), b.get('response_id'))
                             for task in current['tasks'].values() for run in task.get('executions', [])
                             for b in run.get('usage_bindings', [])}
                    for event in source_events:
                        obs = event['observed']; response = obs.get('response_id')
                        if not response or response == 'UNKNOWN':
                            continue
                        matched = [r for r in entries if (response in r['response_ids'] if r['response_ids'] else
                                   r['independent'] or r['turn_id'] == obs.get('turn_id'))]
                        aids = {r['execution_id'] for r in matched}
                        if len(aids) == 1:
                            entry = matched[0]
                            if (entry['execution_id'], session, response) in bound:
                                continue
                            try:
                                from harness.tasks import Tasks
                                owner = manager if manager.run_id == entry['run_id'] else Tasks(root, entry['run_id'])
                                count += bool(owner.bind_usage(entry['task_id'], entry['execution_id'], session, response, entry['basis'] + '; incremental native collection'))
                            except ValueError:
                                append_unique(directory / 'attribution-limits.jsonl', {'session_id': session, 'response_id': response,
                                              'reason': 'existing_binding_conflict', 'executions': sorted(aids)})
                        elif len(aids) > 1:
                            append_unique(directory / 'attribution-limits.jsonl', {'session_id': session, 'response_id': response,
                                          'reason': 'multiple_explicit_contexts_for_one_response', 'executions': sorted(aids)})
                    observed.update(status='observing', usage_responses=len(source_events))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    observed.update(status='collection_error', error=type(error).__name__ + ': ' + str(error))
            for entry in entries:
                record = {**observed, 'execution_id': entry['execution_id'], 'task_id': entry['task_id']}
                if observed['status'] == 'observing':
                    all_events = manager.logger.read()
                    finished = any(e.get('agent_run_id') == entry['execution_id'] and e.get('event_type') == 'role_process' and
                                   e.get('observed', {}).get('process_state') == 'role_process_finished' for e in all_events)
                    turn_complete = not entry['independent'] and entry.get('turn_id') and any(
                        e.get('source', {}).get('session_id') == session and e.get('event_type') in {'session_task_complete', 'session_turn_aborted'} and
                        e.get('observed', {}).get('turn_id') == entry['turn_id'] for e in all_events)
                    if finished or turn_complete:
                        record.update(mode='after_finish', status='completed')
                run = next(r for r in manager.read()['tasks'][entry['task_id']]['executions'] if r['agent_run_id'] == entry['execution_id'])
                has_bound_usage = any(b.get('session_id') == session for b in run.get('usage_bindings', []))
                record['had_incremental_usage'] = (session, entry['execution_id']) in incremental_seen or bool(
                    record['status'] == 'observing' and has_bound_usage)
                status.append(record)
        atomic_json(directory / 'collection-state.json', {'version': VERSION, 'last_poll_at': logging.now(), 'sessions': status})
    return {'new_bindings': count, 'sessions': status}


class WorkerStream:
    """Receives complete CLI JSONL lines before the worker has exited."""
    def __init__(self, manager, task_id, execution_id, call_id=None):
        self.manager, self.task_id, self.execution_id = manager, task_id, execution_id
        self.call_id = call_id
        self.threads = set(); self.last_error = None

    def line(self, line):
        try:
            event = json.loads(line)
            if event.get('type') == 'thread.started' and event.get('thread_id'):
                session = event['thread_id']
                register(self.manager, self.task_id, self.execution_id, session, independent=True, call_id=self.call_id)
                self.threads.add(session)
        except (ValueError, KeyError, TypeError) as error:
            self.last_error = str(error)

    def tick(self):
        if self.threads:
            try:
                return poll(self.manager)
            except (OSError, ValueError) as error:
                self.last_error = str(error)
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True); parser.add_argument('--run', required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    reg = sub.add_parser('register-main')
    reg.add_argument('--task', required=True); reg.add_argument('--execution', required=True)
    reg.add_argument('--session', required=True); reg.add_argument('--source', required=True)
    reg.add_argument('--turn'); reg.add_argument('--response', action='append', default=[])
    reg.add_argument('--registered-turn-only', action='store_true')
    watch = sub.add_parser('watch'); watch.add_argument('--interval', type=float, default=1)
    sub.add_parser('poll')
    begin = sub.add_parser('begin-main')
    begin.add_argument('--task', required=True); begin.add_argument('--role', required=True)
    begin.add_argument('--context', required=True, type=Path)
    begin.add_argument('--session', required=True); begin.add_argument('--source', required=True)
    begin.add_argument('--turn', required=True)
    begin.add_argument('--registered-turn-only', action='store_true')
    args = parser.parse_args()
    from harness.tasks import Tasks
    manager = Tasks(args.root, args.run)
    if args.action == 'begin-main':
        context = json.loads(args.context.read_text())
        run = manager.begin(args.task, args.role, execution_mode='current_agent', usage_context=context)
        registered = register(manager, args.task, run['agent_run_id'], args.session, path=args.source, turn_id=args.turn,
                              import_scope='registered_turns' if args.registered_turn_only else 'session')
        print(json.dumps({'execution': run, 'native_session_context': registered}, ensure_ascii=False))
    elif args.action == 'register-main':
        print(json.dumps(register(manager, args.task, args.execution, args.session, path=args.source,
                                  turn_id=args.turn, response_ids=args.response,
                                  import_scope='registered_turns' if args.registered_turn_only else 'session'), ensure_ascii=False))
    elif args.action == 'poll':
        print(json.dumps(poll(manager), ensure_ascii=False))
    else:
        if args.interval <= 0:
            raise ValueError('positive interval required')
        while True:
            poll(manager); time.sleep(args.interval)


if __name__ == '__main__':
    main()
