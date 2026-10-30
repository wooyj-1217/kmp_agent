"""Per-execution evidence. Never treats a collector's version as model origin.

No VERSION-to-capability table and no inspection of today's source for old runs.
"""
import json
from pathlib import Path


def read_jsonl(path):
    import fcntl
    path = Path(path)
    if not path.exists():
        return []
    with path.open() as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        return [json.loads(line) for line in f if line.strip()]


def execution_proof(task, run, events, registrations=()):
    aid = run.get('agent_run_id')
    own = [e for e in events if e.get('agent_run_id') == aid]
    starts = [e for e in own if e.get('event_type') == 'agent_run_started']
    processes = [e for e in own if e.get('event_type') == 'role_process']
    bindings = {b.get('session_id') for b in run.get('usage_bindings', [])}
    native = [r for r in registrations if r.get('execution_id') == aid and r.get('task_id') == task.get('task_id')]
    calls = []
    for event in processes:
        p = event.get('observed', {})
        call = p.get('call_id')
        if p.get('process_state') != 'role_process_started' or not call or p.get('independent_model_spawned') is not True:
            continue
        completed = {s for e in processes if e.get('observed', {}).get('call_id') == call and
                     e.get('observed', {}).get('process_state') == 'role_process_finished'
                     for s in e['observed'].get('thread_ids', [])}
        streaming = {r['session_id'] for r in native if r.get('independent') and r.get('call_id') == call}
        sessions = bindings & (completed | streaming)
        if sessions:
            calls.append({'call_id': call, 'session_ids': sorted(sessions), 'event_id': event.get('event_id')})
    bound = {(b.get('session_id'), b.get('response_id')) for b in run.get('usage_bindings', [])}
    usage_turns = {(e.get('source', {}).get('session_id'), e.get('observed', {}).get('response_id')):
                   e.get('observed', {}).get('turn_id') for e in events if e.get('event_type') == 'model_usage'}
    main = [r for r in native if not r.get('independent') and any(
            session == r.get('session_id') and (response in r['response_ids'] if r.get('response_ids') else
            r.get('turn_id') and usage_turns.get((session, response)) == r['turn_id'])
            for session, response in bound)]
    actor = 'independent_agent' if calls else 'main_session' if main and run.get('execution_mode') == 'current_agent' else 'unknown'
    # Identity on a start event describes that invocation's harness, not its imported token collector.
    identities = [e['harness'] for e in starts if isinstance(e.get('harness'), dict)]
    unique = {json.dumps(i, sort_keys=True) for i in identities}
    identity = identities[0] if len(unique) == 1 else None
    work_types = {e.get('work_type') for e in starts if e.get('work_type')}
    if work_types and work_types <= {'HARNESS_BUILD', 'HARNESS_IMPROVEMENT'}:
        domain = 'agent_development_test'
    elif work_types and work_types == {'PRODUCT'}:
        domain = 'product_work'
    else:
        domain = 'unknown'
    return {'actor': actor, 'calls': calls, 'main_context_ids': sorted(r['id'] for r in main),
            'execution_identity': identity, 'work_domain': domain,
            'code_state': 'fingerprinted' if identity and identity.get('source_sha256') else
                          'clean_commit' if identity and identity.get('commit') not in (None, 'UNKNOWN') and identity.get('dirty') is False else 'unknown',
            'support': {'independent_call_observed': bool(calls), 'main_context_observed': bool(main)},
            'start_event_ids': [e.get('event_id') for e in starts]}


def delegation_proof(task, run, events):
    """Only relations recorded no later than the execution start are recoverable."""
    start = run.get('started_at')
    def before(e):
        at = e.get('recorded_at') or e.get('timestamp')
        return bool(start and at and at <= start)
    linked = [e for e in events if e.get('event_type') == 'development_child_linked' and
              e.get('task_id') == task.get('task_id') and before(e) and
              e.get('observed', {}).get('parent_task_id') == task.get('parent_task_id') and
              e.get('observed', {}).get('development_area') == run.get('development_area')]
    configured = [e for e in events if e.get('event_type') == 'development_plan_configured' and
                  e.get('task_id') == task.get('task_id') and before(e)]
    return {'child': bool(linked), 'coordinator': bool(configured),
            'event_ids': [e.get('event_id') for e in linked + configured]}
