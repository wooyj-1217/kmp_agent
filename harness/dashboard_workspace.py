"""Read-only request/task view. No session/title/time proximity attribution."""
import json
import hashlib
from pathlib import Path
from harness.usage_projection import project, total, groups
from harness.usage_context import read_events
from harness.dashboard import task_view


def stamp(e):
    return e.get('observed', {}).get('occurred_at') or e.get('recorded_at') or ''


def requests(events, worker_sessions=()):
    result = {}
    # These are model call inputs, not human requests.
    worker_sessions = set(worker_sessions)
    for e in events:
        if e.get('event_type') != 'session_message' or e.get('observed', {}).get('role') != 'user':
            continue
        obs = e['observed']; source = e.get('source', {})
        if source.get('session_id') in worker_sessions:
            continue
        parts = obs.get('content', [])
        # Transport-injected instructions are retained in logs, not presented as requests.
        text = '\n'.join(p.get('text', '') for p in parts if p.get('text') and
                         not p['text'].startswith(('# AGENTS.md instructions', '<environment_context>')))
        if not text.strip():
            continue
        rid = e['event_id']
        result[rid] = {'id': rid, 'summary': text.strip().splitlines()[0][:120],
                       'text': text, 'at': stamp(e), 'message_id': obs.get('message_id'),
                       'session_id': source.get('session_id'), 'task_ids': [], 'links': [],
                       'attachments': [p for p in parts if p.get('type') not in {'input_text', 'text'}]}
    for e in events:
        if e.get('event_type') != 'human_intervention':
            continue
        declared = e.get('agent_summary', {}); obs = e.get('observed', {})
        source_id = obs.get('source_event_id') or declared.get('source_event_id')
        if source_id not in result:
            continue
        r = result[source_id]
        if e.get('task_id') not in (None, '', 'UNKNOWN'):
            r['task_ids'].append(e['task_id'])
            r['links'].append({'task_id': e['task_id'], 'execution_id': e.get('agent_run_id'),
                               'classification': declared.get('classification'),
                               'basis': declared.get('basis'), 'evidence': declared.get('evidence'),
                               'event_id': e['event_id']})
    for r in result.values():
        r['task_ids'] = sorted(set(r['task_ids']))
    return sorted(result.values(), key=lambda r: r['at'], reverse=True)


def usage_slice(data, task_ids=None, execution_id=None, start=None, end=None):
    """Filter already canonical facts. Each response stays counted once."""
    rows = [r for r in data['rows'] if (task_ids is None or r['task_id'] in task_ids)
            and (not execution_id or r['execution_id'] == execution_id)
            and (not start or (r['occurred_at'] or '')[:10] >= start)
            and (not end or (r['occurred_at'] or '')[:10] <= end)]
    out = dict(data); out['rows'] = rows; out['known_tokens'] = total(rows)
    out['selected_responses'] = len(rows)
    for field, key in [('role', 'roles'), ('development_owner', 'development'),
                       ('purpose', 'purposes'), ('repetition', 'repetitions'), ('actor', 'actors')]:
        subset = [r for r in rows if r['role'] == 'development'] if key == 'development' else rows
        out[key] = groups(subset, field, data['taxonomy'][key])
    out['unlinked_tokens'] = total([r for r in rows if not r['task_id']])
    out['unclassified_role_tokens'] = total([r for r in rows if r['role'] == 'unknown'])
    out['last_collected_at'] = max((r['collected_at'] for r in rows), default=None)
    out['last_usage_at'] = max((r['occurred_at'] or '' for r in rows), default=None)
    out['tasks'] = [{**t, 'direct_tokens': total([r for r in rows if r['task_id'] == t['task_id']])}
                    for t in data['tasks'] if task_ids is None or t['task_id'] in task_ids]
    buckets = {}
    for r in rows:
        buckets.setdefault((r['occurred_at'] or '')[:13], []).append(r)
    out['time_bars'] = [{'hour': k, 'tokens': total(v)} for k, v in sorted(buckets.items())]
    return out


def workspace(root, project_id=None):
    root = Path(root); events = read_events(root)
    p = root / '.harness/tasks/tasks.yaml'
    state = json.loads(p.read_text()) if p.exists() else {'tasks': {}}
    tasks = state['tasks']; usage = project(root, project_id=project_id)
    scope = {'tasks': {tid: {} for tid in tasks},
             'agent_run_ids': [r['agent_run_id'] for t in tasks.values() for r in t.get('executions', [])]}
    views = {tid: task_view(root, t, scope, tasks) for tid, t in tasks.items()}
    assignments = [{'child_task_id': e['task_id'], 'parent_task_id': e['observed']['parent_task_id'],
                    'development_owner': e['observed'].get('development_area'), 'event_id': e['event_id'], 'at': stamp(e)}
                   for e in events if e.get('event_type') == 'development_child_linked' and
                   e.get('task_id') in tasks and e.get('observed', {}).get('parent_task_id') in tasks]
    reqs = requests(events, {r['session_id'] for r in usage['rows'] if r['actor'] == 'independent_agent'})
    # Explicit new-work links may reference an already imported user message in
    # another local collection root. Check the exact source event, not its age.
    context_path = root / '.harness/requests/context.jsonl'
    link_errors = []
    for line in context_path.read_text().splitlines() if context_path.exists() else []:
        try:
            link = json.loads(line)
            source = next(e for e in (json.loads(l) for l in Path(link['source_log']).read_text().splitlines()) if e.get('event_id') == link['source_event_id'])
            digest = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if digest != link['source_event_sha256'] or not link.get('basis'):
                raise ValueError('source evidence differs')
            imported = requests([source])
            if not imported or any(tid not in tasks for tid in link['task_ids']):
                raise ValueError('source/task missing')
            existing = next((r for r in reqs if r['id'] == source['event_id']), None)
            if existing is None:
                existing = imported[0]; reqs.append(existing)
            existing['task_ids'] = sorted(set(existing['task_ids'] + link['task_ids']))
            if link.get('display_summary'):
                existing['summary'] = link['display_summary']
            existing['links'].append({'basis': link['basis'], 'method': 'explicit_context_reference',
                                      'source_event_sha256': digest, 'registered_at': link['registered_at']})
        except (OSError, ValueError, KeyError, StopIteration):
            link_errors.append('요청 연결 근거를 확인할 수 없습니다.')
    if project_id is not None:
        tasks = {tid: t for tid, t in tasks.items() if t.get('project_id') == project_id}
        assignments = [a for a in assignments if a['child_task_id'] in tasks and a['parent_task_id'] in tasks]
        reqs = [r for r in reqs if any(tid in tasks for tid in r['task_ids'])]
    active_ids = {r['task_id'] for r in usage['active_executions']}
    for req in reqs:
        req['direct_task_ids'] = [tid for tid in req['task_ids'] if tid in tasks]
        ids = set(req['direct_task_ids'])
        while True:
            more = {r['task_id'] for r in usage['rows'] if r.get('parent_task_id') in ids}
            more |= {a['child_task_id'] for a in assignments if a['parent_task_id'] in ids}
            if more <= ids:
                break
            ids |= more
        req['task_ids'] = sorted(ids)
        req['active'] = bool(active_ids.intersection(req['task_ids']))
        req['status'] = ('진행 중' if req['active'] else
                         '연결된 작업 완료' if req['task_ids'] and all(tasks[t]['state'] == 'DONE' for t in req['task_ids']) else
                         '문제 확인 필요' if any(tasks[t]['state'] == 'BLOCKED' for t in req['task_ids']) else
                         '작업 기록 있음' if req['task_ids'] else '작업 연결 없음')
        req['tokens'] = total([r for r in usage['rows'] if r['task_id'] in req['task_ids']])
    important = {'qa_attempt_finished': 'QA 검토 결과', 'issue_returned': '보완 요청',
                 'issue_resolved': '문제 해결 확인', 'task_reviewed': '검토 결과 등록',
                 'task_state_changed': '작업 완료', 'task_handoff': '작업 인계',
                 'agent_run_started': '작업 시작', 'agent_run_failed': '실행 실패'}
    activity = []
    run_kinds = {r['agent_run_id']: r.get('kind') for t in tasks.values() for r in t.get('executions', [])}
    done_reviews = {e.get('agent_run_id') for e in events if e.get('event_type') == 'task_state_changed' and e.get('observed', {}).get('to') == 'DONE'}
    for e in events:
        typ = e.get('event_type'); tid = e.get('task_id')
        if typ not in important or tid not in tasks:
            continue
        if typ == 'agent_run_started' and run_kinds.get(e.get('agent_run_id')) == 'review':
            continue
        if typ == 'task_reviewed' and e.get('agent_run_id') in done_reviews:
            continue
        if typ == 'task_state_changed' and e.get('observed', {}).get('to') != 'DONE':
            continue
        suffix = {'PASS': '검토 통과', 'REWORK': '오류 발견·보완 요청', 'FAIL': '검토 실패', 'NOT_RUN': '검증 미완료', 'BLOCKED': '검토 차단'}.get(e.get('observed', {}).get('outcome'), important[typ])
        activity.append({'at': stamp(e), 'task_id': tid, 'type': typ,
                         'text': tasks[tid]['title'] + ' · ' + suffix,
                         'detail': {k: v for k, v in e.get('observed', {}).items() if k in {'outcome', 'from', 'to', 'state', 'issue_id', 'result'}}, 'event_id': e.get('event_id')})
    task_rows = []
    display_path = root / '.harness/dashboard/display.json'
    display = json.loads(display_path.read_text()) if display_path.exists() else {}
    for tid, t in tasks.items():
        view = views[tid]
        results = {c['criterion_id']: c['result'] for c in (t.get('reviews') or [{}])[-1].get('results', [])}
        view['criteria'] = [{**c, 'result': 'RECHECK_REQUIRED' if view['verdict']=='RECHECK_REQUIRED' and results.get(c['id'])=='PASS' else results.get(c['id'], 'NOT_RUN')} for c in t.get('criteria', [])]
        label = display.get('tasks', {}).get(tid, {})
        title = label.get('title') if label.get('original_title') == t.get('title') else None
        task_rows.append({**t, 'original_title': t.get('title'), 'title': title or t.get('title'), 'view': view,
                          'request_ids': [r['id'] for r in reqs if tid in r['task_ids']]})
        for criterion in view['criteria']:
            if criterion['id'] in display.get('checks', {}):
                criterion['original_description'] = criterion.get('description')
                criterion['description'] = display['checks'][criterion['id']]
    labels = {t['task_id']: t['title'] for t in task_rows}
    for item in activity:
        item['text'] = labels[item['task_id']] + item['text'][len(tasks[item['task_id']]['title']):]
    collection_path = root / '.harness/usage/collection-state.json'
    collection = json.loads(collection_path.read_text()) if collection_path.exists() else {}
    observing = {r.get('execution_id') for r in collection.get('sessions', []) if r.get('status') == 'observing'}
    incremental = sorted({r.get('execution_id') for r in collection.get('sessions', []) if r.get('had_incremental_usage') or r.get('mode') == 'incremental'})
    observed_tasks = sorted({r['task_id'] for r in usage['active_executions'] if r['execution_id'] in observing})
    origin_path = root / '.harness/dashboard/origin.json'
    origin = json.loads(origin_path.read_text()).get('origin') if origin_path.exists() else 'ACTUAL_RECORDED_RUN'
    return {'requests': reqs, 'tasks': task_rows,
            'issues': [i for i in state.get('issues', []) if project_id is None or
                       any(i.get(k) in tasks for k in ('task_id', 'repair_task_id', 'qa_task_id'))],
            'activity': sorted(activity, key=lambda r: r['at'], reverse=True),
            'usage': usage, 'active_task_ids': sorted(active_ids),
            'observed_active_task_ids': observed_tasks,
            'incremental_usage_execution_ids': incremental,
            'assigned_children': assignments,
            'active_request_ids': [r['id'] for r in reqs if r['active']],
            'unlinked_active_task_ids': sorted(active_ids - {t for r in reqs for t in r['task_ids']}),
            'request_link_errors': link_errors,
            'history_mode': 'confirmed_records_only', 'origin': origin}


def compact(value):
    """Heavy immutable evidence is fetched on demand, not on every heartbeat."""
    hidden = {'collection', 'source_sha256', 'collector_identities', 'classification',
              'target_manifest', 'target_baseline', 'code_manifest', 'files', 'runs',
              'input_bundle', 'input_comparison', 'historical_reviews'}
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k not in hidden}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value
