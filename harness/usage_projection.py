"""One measured token total; independent task/role/owner/purpose/repeat views.

Unlinked/classification-missing facts remain in the project known subtotal.
Ambiguous token values are quarantined, not replaced by zero or guessed.
"""
import json
from collections import defaultdict
from pathlib import Path
from harness.dashboard_usage import token_parts, native_identity_conflict
from harness.dashboard_live import ROLES
from harness.usage_context import (UNKNOWN, NA, PURPOSES, REPETITIONS, ACTORS,
                                   development_owners, resolve, read_events, read_registrations)


def total(rows):
    return sum(r['tokens'] for r in rows) if rows else None


def groups(rows, field, labels):
    out = defaultdict(list)
    for row in rows:
        out[row.get(field) or UNKNOWN].append(row)
    return [{'code': code, 'label': labels.get(code, code), 'tokens': total(rs),
             'responses': len(rs), 'normal_input': sum(r['normal_input'] for r in rs),
             'cached_input': sum(r['cached_input'] for r in rs),
             'output': sum(r['output'] for r in rs)} for code, rs in sorted(out.items())]


def project(root, task_id=None, execution_id=None, mode='tasks', include_children=False, project_id=None):
    root = Path(root)
    p = root / '.harness/tasks/tasks.yaml'
    state = json.loads(p.read_text()) if p.exists() else {'tasks': {}}
    tasks = state['tasks']; events = read_events(root)
    from harness.usage_targets import registered_targets, partition
    if project_id is not None and project_id not in registered_targets(root)[1]:
        raise ValueError('unknown or unconfirmed work target')
    runs = {}; owners = defaultdict(set); facts = defaultdict(list)
    finished = {e.get('run_id') for e in events if e['event_type'] == 'run_finished'}
    ended = {e.get('agent_run_id') for e in events if e['event_type'] in {'agent_run_finished', 'agent_run_failed'}}
    snapshot_count = 0
    limits_path = root / '.harness/usage/attribution-limits.jsonl'
    limits = {(r['session_id'], r['response_id']) for r in
              (json.loads(l) for l in limits_path.read_text().splitlines() if l.strip())} if limits_path.exists() else set()
    for tid, task in tasks.items():
        for run in task.get('executions', []):
            runs[run['agent_run_id']] = (task, run)
            for binding in run.get('usage_bindings', []):
                owners[(binding.get('session_id'), binding.get('response_id'))].add(run['agent_run_id'])
    for e in events:
        if e['event_type'] == 'model_usage':
            key = (e.get('source', {}).get('session_id'), e.get('observed', {}).get('response_id'))
            facts[key].append(e)
        elif e['event_type'] == 'usage_snapshot':
            snapshot_count += 1
    registered = read_registrations(root)
    contexts = {aid: resolve(root, state, task, run, events) for aid, (task, run) in runs.items()}
    rows = []; quarantine = []
    for key, source_events in facts.items():
        invalid_identity = [e for e in source_events if native_identity_conflict(e)]
        if invalid_identity:
            quarantine.append({'session_id':key[0], 'response_id':key[1], 'reason':'native_identity_conflict',
                               'event_ids':[e.get('event_id') for e in invalid_identity], 'tokens':None})
            source_events = [e for e in source_events if not native_identity_conflict(e)]
            if not source_events:
                continue
        candidates = {(json.dumps(e['observed'].get('usage'), sort_keys=True),
                       e['observed'].get('usage_semantics'), e['observed'].get('model')) for e in source_events}
        missing_identity = any(v in (None, '', 'UNKNOWN') for v in key)
        if missing_identity or len(candidates) != 1:
            quarantine.append({'session_id': key[0], 'response_id': key[1], 'reason': 'missing_identity' if missing_identity else 'conflicting_token_values',
                               'event_ids': [e.get('event_id') for e in source_events], 'tokens': None})
            continue
        e = source_events[0]; obs = e['observed']; parts = token_parts(obs.get('usage'), obs.get('usage_semantics'))
        if parts is None:
            quarantine.append({'session_id': key[0], 'response_id': key[1], 'reason': 'invalid_or_uncollected_token_fields',
                               'event_ids': [x.get('event_id') for x in source_events], 'tokens': None})
            continue
        targets = set(owners[key])
        targets.update(x.get('agent_run_id') for x in source_events if x.get('agent_run_id') in runs)
        aid = next(iter(targets)) if len(targets) == 1 else None
        task, run = runs.get(aid, ({}, {}))
        declared_tasks = {x.get('task_id') for x in source_events if x.get('task_id') not in (None, '', 'UNKNOWN')}
        mapping_error = key in limits or len(targets) > 1 or (bool(task) and bool(declared_tasks - {task['task_id']}))
        if mapping_error:
            task, run, aid = {}, {}, None
        ctx = contexts.get(aid, {})
        quality = list(ctx.get('quality', []))
        if mapping_error:
            quality.append('mapping_error')
        elif not task:
            quality.append('unlinked')
        registered_new = any(reg.get('session_id') == key[0] and
            (key[1] in reg.get('response_ids', []) or reg.get('turn_id') and obs.get('turn_id') == reg['turn_id'])
            for reg in registered)
        generation = 'new_context' if run.get('usage_context') or registered_new else 'historical' if aid else 'origin_unknown'
        rows.append({'project_id': task.get('project_id') or e.get('project_id') or 'UNKNOWN',
                     'task_id': task.get('task_id'), 'task_name': task.get('title', '작업·실행 연결 없음'),
                     'execution_id': aid, 'parent_task_id': run.get('parent_task_id') or task.get('parent_task_id'),
                     'parent_execution_id': ctx.get('parent_execution_id'),
                     'role': ctx.get('role', UNKNOWN), 'development_owner': ctx.get('development_owner', UNKNOWN),
                     'actor': ctx.get('actor', UNKNOWN), 'purpose': ctx.get('purpose', UNKNOWN),
                     'repetition': ctx.get('repetition', UNKNOWN), 'attempt_index': ctx.get('attempt_index'),
                     'cause_execution_id': ctx.get('cause_execution_id'), 'issue_ids': ctx.get('issue_ids', []),
                     'change_ids': ctx.get('change_ids', []), 'quality': quality,
                     'session_id': key[0], 'response_id': key[1], 'model': obs.get('model'),
                     'occurred_at': obs.get('occurred_at') or e.get('timestamp') or e.get('recorded_at'),
                     'collected_at': max(x.get('recorded_at') or x.get('timestamp') or '' for x in source_events),
                     'tokens': sum(parts), 'normal_input': parts[0], 'cached_input': parts[1], 'output': parts[2],
                     'reasoning_output': obs['usage'].get('reasoning_output_tokens'),
                     'original_usage': obs['usage'], 'semantics': obs.get('usage_semantics'),
                     'source_event_ids': [x.get('event_id') for x in source_events],
                     'collector_identities': [x.get('harness') for x in source_events],
                     'provenance': ctx.get('provenance', {}),
                     'classification': ctx, 'record_generation': generation})
    target_scope = partition(rows, tasks, project_id)
    if project_id is not None:
        tasks = {tid: t for tid, t in tasks.items() if t.get('project_id') == project_id}
        if task_id is not None and task_id not in tasks:
            raise ValueError('task outside selected work target')
        if execution_id is not None and (execution_id not in runs or runs[execution_id][0]['task_id'] not in tasks):
            raise ValueError('execution outside selected work target')
        rows = [r for r in rows if r['target_project_id'] == project_id]
    recorded_parents = {t['task_id']: t.get('parent_task_id') for aid, (t, r) in runs.items()
                        if t['task_id'] in tasks and
                        (r.get('usage_context', {}).get('parent_execution_id') or
                            contexts[aid].get('provenance', {}).get('delegation_child_observed'))}
    for row in rows:
        row['parent_task_id'] = recorded_parents.get(row['task_id'])
    collection_path = root / '.harness/usage/collection-state.json'
    collection = json.loads(collection_path.read_text()) if collection_path.exists() else {}
    latest_process = {}
    for event in events:
        process_state = event.get('observed', {}).get('process_state')
        if event['event_type'] == 'role_process' and process_state in {'role_process_started', 'role_process_finished'}:
            latest_process[event.get('agent_run_id')] = process_state
    collected_states = defaultdict(list)
    for entry in collection.get('sessions', []):
        collected_states[entry.get('execution_id')].append(entry.get('status'))
    closed_native = {aid for aid, statuses in collected_states.items() if statuses and
                     len(statuses) >= sum(r['execution_id'] == aid for r in registered) and
                     all(s == 'completed' for s in statuses)}
    active_ids = {aid for aid, (t, r) in runs.items() if t['task_id'] in tasks and not r.get('ended_at') and aid not in ended and
                  aid not in closed_native and latest_process.get(aid) != 'role_process_finished' and
                  r.get('run_id') not in finished and t.get('state') not in {'DONE', 'BLOCKED'}}
    selected_tasks = {task_id} if task_id else set(tasks)
    if task_id and include_children:
        while True:
            more = {tid for tid, task in tasks.items() if recorded_parents.get(tid) in selected_tasks}
            if more <= selected_tasks:
                break
            selected_tasks |= more
    selected = [r for r in rows if (not task_id or r['task_id'] in selected_tasks) and
                (not execution_id or r['execution_id'] == execution_id) and
                (mode != 'current' or r['execution_id'] in active_ids)]
    if mode == 'current' and not task_id and not execution_id:
        # No historical run silently substitutes for a current run.
        selected = [r for r in rows if r['execution_id'] in active_ids]
    role_labels = {**ROLES, 'verification': 'QA', 'orchestrator': '오케스트레이터', UNKNOWN: '역할 분류 없음'}
    owner_labels = {**development_owners(), NA: '해당 없음', UNKNOWN: '개발 담당 기록 없음'}
    by_time = defaultdict(list)
    for row in selected:
        by_time[str(row['occurred_at'])[:13]].append(row)
    time_bars = [{'hour': hour, 'tokens': total(rs), 'roles': groups(rs, 'role', role_labels),
                  'development': groups([r for r in rs if r['role'] == 'development'], 'development_owner', owner_labels)}
                 for hour, rs in sorted(by_time.items())]
    task_list = []
    for tid, task in tasks.items():
        direct = [r for r in rows if r['task_id'] == tid]
        descendants = {tid}
        while True:
            more = {k for k, t in tasks.items() if recorded_parents.get(k) in descendants}
            if more <= descendants:
                break
            descendants |= more
        tree = [r for r in rows if r['task_id'] in descendants]
        task_list.append({'project_id': task.get('project_id'), 'task_id': tid, 'title': task['title'],
                          'role': task['role'], 'direct_tokens': total(direct), 'including_children_tokens': total(tree),
                          'responses': len(direct), 'execution_ids': [r['agent_run_id'] for r in task['executions']],
                          'collection_state': 'observed' if direct else 'missing_usage'})
    collector_executions = {x.get('execution_id') for x in collection.get('sessions', []) if x.get('mode') == 'incremental' and x.get('status') == 'observing'}
    selected_execution_ids = {aid for aid in runs if runs[aid][0]['task_id'] in tasks and (not task_id or runs[aid][0]['task_id'] in selected_tasks) and
                              (not execution_id or aid == execution_id) and (mode != 'current' or aid in active_ids)}
    # Binding and collection-state are separate atomic writes. A freshly bound
    # response can be visible before the first poll status is published.
    blocked_sessions = {s.get('session_id') for s in collection.get('sessions', [])
                        if s.get('status') in {'collection_error', 'source_ambiguous'}}
    observed_registered = {reg['execution_id'] for reg in registered
                           if reg.get('session_id') not in blocked_sessions and any(
                               row['execution_id'] == reg['execution_id'] and row['session_id'] == reg['session_id']
                               for row in rows)}
    live = bool(selected_execution_ids & active_ids & (collector_executions | observed_registered))
    historical_incremental = mode != 'current' and any(s.get('execution_id') in selected_execution_ids and
        s.get('had_incremental_usage') for s in collection.get('sessions', []))
    pending = not live and any(r['execution_id'] in selected_execution_ids & active_ids for r in registered)

    unlinked = [r for r in rows if not r['task_id']]
    return {'version': 'usage-context-v1', 'mode': mode, 'task_id': task_id, 'execution_id': execution_id,
            'target_scope': target_scope,
            'known_tokens': total(selected), 'project_known_tokens': total(rows),
            'project_responses': len(rows), 'selected_responses': len(selected),
            'unlinked_tokens': total(unlinked), 'unlinked_responses': len(unlinked),
            'unclassified_role_tokens': total([r for r in selected if r['role'] == UNKNOWN]),
            'unclassified_purpose_tokens': total([r for r in selected if r['purpose'] == UNKNOWN]),
            'usage_complete': False, 'unquantified_records': quarantine,
            'snapshots_not_added': snapshot_count, 'deduplicated_events': sum(len(v)-1 for v in facts.values()),
            'active_executions': [{'execution_id': aid, 'task_id': runs[aid][0]['task_id'], 'role': runs[aid][1]['role']} for aid in sorted(active_ids)],
            'collection_mode': 'incremental' if live or historical_incremental else 'pending' if pending else 'after_finish',
            'collection_label': '실행 중 반영' if live else '응답별 수집 기록' if historical_incremental else '수집 연결 확인 중' if pending else '종료 후 반영',
            'last_usage_at': max((r['occurred_at'] or '' for r in selected), default=None),
            'last_collected_at': max((r['collected_at'] for r in selected), default=None),
            'last_polled_at': collection.get('last_poll_at'),
            'roles': groups(selected, 'role', role_labels),
            'configured_development_owners': sorted({c['development_owner'] for aid, c in contexts.items() if runs[aid][0]['task_id'] in tasks and c['role']=='development' and c['development_owner'] not in {NA, UNKNOWN}}),
            'development': groups([r for r in selected if r['role'] == 'development'], 'development_owner', owner_labels),
            'purposes': groups(selected, 'purpose', PURPOSES), 'repetitions': groups(selected, 'repetition', REPETITIONS),
            'actors': groups(selected, 'actor', ACTORS), 'time_bars': time_bars,
            'tasks': task_list, 'rows': selected,
            'quality': {'historical_missing_classification': sum(bool(r['quality']) and r['record_generation'] == 'historical' for r in rows),
                        'new_missing_classification': sum(bool(r['quality']) and r['record_generation'] == 'new_context' for r in rows),
                        'mapping_errors': sum('mapping_error' in r['quality'] for r in rows),
                        'legacy_unclassified_tokens': sum(r['tokens'] for r in rows if r['quality'] and r['record_generation'] == 'historical'),
                        'new_unclassified_tokens': sum(r['tokens'] for r in rows if r['quality'] and r['record_generation'] == 'new_context'),
                        'unlinked_origin_unknown_tokens': sum(r['tokens'] for r in rows if r['record_generation'] == 'origin_unknown'),
                        'missing_usage_executions': sum(not any(r['execution_id'] == aid for r in rows)
                                                        for aid in runs if runs[aid][0]['task_id'] in tasks)},
            'taxonomy': {'roles': role_labels, 'development': owner_labels, 'purposes': PURPOSES,
                         'repetitions': REPETITIONS, 'actors': ACTORS}}
