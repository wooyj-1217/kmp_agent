"""Usage metadata, independent of task/QA verdicts. No text-based inference.

Legacy correction records are append-only, content-addressed and evidence checked.
The native tasks/executions/usage_bindings remain the ownership ledger.
"""
import copy
import fcntl
import hashlib
import json
from pathlib import Path

VERSION = 'usage-context-v1'
RECOVERY_VERSION = 'typed-recovery-3'
UNKNOWN = 'unknown'
NA = 'not_applicable'
PURPOSES = {
    'requirements': '요구사항 분석·정책 정의',
    'interaction_design': '디자인·상호작용 설계',
    'technical_design': '개발계획·기술 설계',
    'implementation': '코드 구현',
    'execution_diagnosis': '빌드·실행 오류 조사',
    'qa_review': 'QA 검토·테스트',
    'defect_fix': '결함 수정',
    'qa_retest': '수정 결과 재검증',
    'coordination': '작업 분배·인계·결과 통합',
    'investigation_report': '기록 조사·보고',
    UNKNOWN: '분류 정보 없음',
}
REPETITIONS = {'initial': '최초 수행', 'review_rework': '검토 결과 보완',
               'execution_retry': '실행·출력 오류 재시도', 'retest': '수정 후 재검증',
               UNKNOWN: '반복 관계 기록 없음'}
ACTORS = {'main_session': '메인 세션 직접 수행', 'independent_agent': '독립 서브에이전트 수행',
          UNKNOWN: '확인 불가'}
QUALITY = {NA: '해당 없음', 'missing_classification': '분류 정보 없음',
           'unlinked': '작업·실행 연결 없음', 'missing_usage': '사용량 미수집',
           'mapping_error': '매핑 오류'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def development_owners():
    # Reuse the existing lightweight area labels. Importing the execution runtime
    # here makes direct logging.py CLI entry shadow the stdlib logging module.
    from harness.dashboard_live import AREAS
    return {'coordinator': '개발 코디네이터', **AREAS}


def validate(value, role):
    from harness.tasks import ROLES
    if not isinstance(value, dict) or role not in ROLES:
        raise ValueError('usage context needs an existing role')
    allowed = {'purpose', 'development_owner', 'repetition', 'cause_execution_id',
               'issue_ids', 'change_ids', 'attempt_index', 'parent_execution_id',
               'review_target_task_ids', 'basis', 'source_context_ids'}
    if set(value) - allowed:
        raise ValueError('unknown usage context fields')
    out = copy.deepcopy(value)
    if out.get('purpose', UNKNOWN) not in PURPOSES or out.get('repetition', UNKNOWN) not in REPETITIONS:
        raise ValueError('invalid purpose/repetition; do not infer from titles')
    owner = out.get('development_owner', UNKNOWN if role == 'development' else NA)
    if role != 'development' and owner != NA:
        raise ValueError('development owner is not applicable to this role')
    if role == 'development' and owner not in set(development_owners()) | {UNKNOWN}:
        raise ValueError('development owner must use the existing delegation areas')
    out['development_owner'] = owner
    if 'attempt_index' in out and (type(out['attempt_index']) is not int or out['attempt_index'] < 1):
        raise ValueError('attempt_index must be positive')
    for k in ('issue_ids', 'change_ids', 'review_target_task_ids', 'source_context_ids'):
        if k in out and (not isinstance(out[k], list) or any(not isinstance(x, str) or not x for x in out[k])):
            raise ValueError(k + ' must be explicit IDs')
    for k in ('cause_execution_id', 'parent_execution_id', 'basis'):
        if k in out and (not isinstance(out[k], str) or not out[k].strip()):
            raise ValueError(k + ' must be an explicit nonempty value')
    if out.get('repetition') in {'review_rework', 'execution_retry', 'retest'} and not any(out.get(k) for k in ('cause_execution_id', 'issue_ids', 'review_target_task_ids', 'basis')):
        raise ValueError('repeat relationship needs an explicit cause/target/basis')
    out.setdefault('purpose', UNKNOWN)
    out.setdefault('repetition', UNKNOWN)
    return out


def frozen(state, task, run, explicit=None):
    """Called before agent_run_started, never changes state transitions or gates."""
    configured = task.get('usage_context_configuration', {}) if run.get('role', UNKNOWN) == task['role'] else {}
    value = explicit if explicit is not None else configured
    if not value:
        typed = derive(state, task, run, [], at_start=True)
        value = {k: v for k, v in typed.items() if k in {
            'purpose', 'development_owner', 'repetition', 'cause_execution_id', 'issue_ids',
            'change_ids', 'attempt_index', 'parent_execution_id', 'review_target_task_ids'} and v is not None}
        if value.get('purpose') != UNKNOWN:
            value['basis'] = 'typed task registration / QA / delegation relationship at start'
    value = validate(value, run.get('role', UNKNOWN))
    previous_work = [r for r in task.get('executions', []) if r.get('kind') == 'work']
    if run.get('kind') == 'work':
        value['attempt_index'] = len(previous_work) + 1
        if explicit is None and previous_work and value.get('repetition') == 'initial':
            value['repetition'] = UNKNOWN  # Reusing task configuration is not a retry declaration.
    if 'development_owner' not in (explicit or task.get('usage_context_configuration', {})):
        if run.get('role', UNKNOWN) == 'development':
            if run.get('development_area') in development_owners():
                value['development_owner'] = run['development_area']
            elif task.get('development_delegation'):
                value['development_owner'] = 'coordinator'
    if task.get('parent_task_id') and not value.get('parent_execution_id'):
        parents = [r for r in state['tasks'].get(task['parent_task_id'], {}).get('executions', [])
                   if r.get('run_id') == run.get('run_id') and r.get('kind') == 'work' and not r.get('ended_at')]
        if len(parents) == 1:
            value['parent_execution_id'] = parents[0]['agent_run_id']
    return {'version': VERSION, 'method': 'explicit_start_context', 'role': run.get('role', UNKNOWN),
            **value, 'registered_at': run['started_at']}


def _task_fields(task):
    return {k: task.get(k) for k in ('task_id', 'role', 'parent_task_id', 'development_area',
                                    'role_contract', 'change_id')}


def evidence(state, task, run, events, registrations=()):
    """Hash only relevant values. Later verdicts/log appends do not invalidate metadata."""
    from harness.usage_provenance import execution_proof, delegation_proof
    parent = state['tasks'].get(task.get('parent_task_id'), {})
    # Legacy classification uses configuration recorded before this invocation, not today's task config.
    registered_configs = {}
    if run.get('started_at'):
        for e in sorted(events, key=lambda e: e.get('recorded_at') or e.get('timestamp') or ''):
            at = e.get('recorded_at') or e.get('timestamp')
            if e.get('event_type') == 'qa_configured' and at and at <= run['started_at']:
                registered_configs[e.get('task_id')] = {k: e.get('observed', {}).get(k) for k in ('stage', 'target_task_id', 'repair_task_id')}
    # Older qa_configured events omitted repair_task_id. Retain the explicit native
    # ledger relationship only when its stage/target match the recorded configuration.
    # This recovers a declared repair assignment, never an inferred model call.
    for tid, c in registered_configs.items():
        ledger = state['tasks'].get(tid, {}).get('qa_config', {})
        if all(ledger.get(k) == c.get(k) for k in ('stage', 'target_task_id')):
            c['repair_task_id'] = c.get('repair_task_id') or ledger.get('repair_task_id')
    configs = {tid: c for tid, c in registered_configs.items() if tid == task['task_id'] or
               c.get('repair_task_id') in {task['task_id'], task.get('parent_task_id')} and c.get('repair_task_id')}
    process = [{k: e.get('observed', {}).get(k) for k in ('independent_model_spawned', 'process_state')}
               for e in events if e.get('agent_run_id') == run['agent_run_id'] and e.get('event_type') == 'role_process'
               and e.get('observed', {}).get('process_state') == 'role_process_started']
    return {'execution': {k: run.get(k) for k in ('agent_run_id', 'run_id', 'role', 'kind', 'started_at',
            'execution_mode', 'pipeline_stage', 'development_area', 'parent_task_id', 'usage_context')},
            'task': _task_fields(task), 'parent': _task_fields(parent),
            'delegation': bool(task.get('development_delegation')), 'qa_configs': configs,
            'process_start': process,
            'provenance': execution_proof(task, run, events, registrations),
            'recorded_delegation': delegation_proof(task, run, events),
            'previous_work': [{k: r.get(k) for k in ('agent_run_id', 'ended_at', 'failure_context')}
                              for r in task.get('executions', []) if r.get('kind') == 'work' and
                              r.get('started_at') and run.get('started_at') and r['started_at'] < run['started_at']],
            'related_issues': [{k: i.get(k) for k in ('id', 'qa_task_id', 'assigned_task_id')}
                              for i in state.get('issues', []) if i.get('qa_task_id') in configs or
                              i.get('assigned_task_id') in {task['task_id'], task.get('parent_task_id')} and i.get('assigned_task_id')]}


def derive(state, task, run, events, registrations=(), *, at_start=False):
    """Only typed registration/QA/parent relations. Never names, text or proximity."""
    proof = evidence(state, task, run, events, registrations)
    if at_start:
        # This is the current invocation's explicit typed configuration, frozen
        # before it starts. Historical recovery never uses this branch.
        proof['qa_configs'] = {tid: {k: t['qa_config'].get(k) for k in ('stage', 'target_task_id', 'repair_task_id')}
                               for tid, t in state['tasks'].items() if t.get('qa_config') and
                               (tid == task['task_id'] or t['qa_config'].get('repair_task_id') in
                                {task['task_id'], task.get('parent_task_id')} and t['qa_config'].get('repair_task_id'))}
        proof['recorded_delegation'] = {'coordinator': bool(task.get('development_delegation')),
            'child': bool(task.get('parent_task_id') and state['tasks'].get(task['parent_task_id'], {}).get('development_delegation'))}
    if run.get('usage_context'):
        value = {k: v for k, v in run['usage_context'].items() if k not in ('version', 'method', 'role', 'registered_at')}
        value = validate(value, run.get('role', UNKNOWN))
        method = 'explicit_start_context'
    else:
        from harness.tasks import ROLES
        value = validate({}, run.get('role', UNKNOWN)) if run.get('role') in ROLES else {'purpose': UNKNOWN, 'repetition': UNKNOWN, 'development_owner': UNKNOWN}
        method = 'structured_legacy_recovery'
        configs = proof['qa_configs']
        ownqa = configs.get(task['task_id'], {})
        repair = [k for k, c in configs.items() if c['repair_task_id'] in {task['task_id'], task.get('parent_task_id')} and c['repair_task_id']]
        if run.get('kind') == 'review':
            value['purpose'] = 'qa_retest' if ownqa.get('stage') == 'retest' else 'qa_review'
        elif ownqa:
            value['purpose'] = 'qa_retest' if ownqa['stage'] == 'retest' else 'qa_review'
            if ownqa.get('target_task_id'):
                value['review_target_task_ids'] = [ownqa['target_task_id']]
        elif repair:
            value['purpose'] = 'defect_fix'
        elif task.get('role_contract'):
            value['purpose'] = {'planning': 'requirements', 'design': 'interaction_design',
                                'development': 'technical_design'}.get(run.get('role', UNKNOWN), UNKNOWN)
        elif run.get('role', UNKNOWN) == 'development' and proof['recorded_delegation']['coordinator']:
            value['purpose'] = 'coordination'
        elif run.get('role', UNKNOWN) == 'development' and proof['recorded_delegation']['child']:
            value['purpose'] = 'implementation'
        if run.get('role', UNKNOWN) == 'development':
            value['development_owner'] = run.get('development_area') if proof['recorded_delegation']['child'] and run.get('development_area') in development_owners() else 'coordinator' if proof['recorded_delegation']['coordinator'] else UNKNOWN
        if repair and run.get('kind') == 'work':
            value['repetition'] = 'review_rework'
            value['issue_ids'] = [i['id'] for i in state.get('issues', []) if i.get('qa_task_id') in repair]
            issue_ids = set(value['issue_ids'])
            causes = {attempt['agent_run_id'] for tid in repair
                      for attempt in state['tasks'][tid].get('qa_config', {}).get('attempts', [])
                      if issue_ids & set(attempt.get('finding_ids', []))}
            value['cause_execution_id'] = next(iter(causes)) if len(causes) == 1 else None
        elif proof['previous_work'] and any(e['event_type'] == 'agent_run_failed' and e.get('agent_run_id') == proof['previous_work'][-1]['agent_run_id'] for e in events):
            value.update(repetition='execution_retry', cause_execution_id=proof['previous_work'][-1]['agent_run_id'])
        elif ownqa.get('stage') == 'retest':
            value['repetition'] = 'retest'
        elif not proof['previous_work'] and value['purpose'] != UNKNOWN:
            value['repetition'] = 'initial'
        if run.get('kind') == 'work':
            value['attempt_index'] = len(proof['previous_work']) + 1
        parents = [r for r in state['tasks'].get(task.get('parent_task_id'), {}).get('executions', [])
                   if r.get('kind') == 'work' and r.get('run_id') == run.get('run_id')]
        if len(parents) == 1 and proof['recorded_delegation']['child']:
            value['parent_execution_id'] = parents[0]['agent_run_id']
    actor = proof['provenance']['actor']
    return {**value, 'actor': actor, 'role': run.get('role', UNKNOWN), 'version': VERSION,
            'provenance': {**proof['provenance'], 'delegation_child_observed': proof['recorded_delegation']['child']}, 'method': method, 'method_version': RECOVERY_VERSION, 'evidence_sha256': digest(proof),
            'quality': [k for k, v in (('purpose', value['purpose']), ('development_owner', value['development_owner']), ('repetition', value['repetition']), ('actor', actor)) if v == UNKNOWN]}


def recover(root):
    """Append missing deterministic corrections; never rewrites logs/tasks/old evidence."""
    root = Path(root)
    state = json.loads((root / '.harness/tasks/tasks.yaml').read_text())
    events = read_events(root)
    registrations = read_registrations(root)
    path = root / '.harness/usage/classifications.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with path.open('a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.seek(0)
        known = {json.loads(line)['id'] for line in f if line.strip()}
        for task in state['tasks'].values():
            for run in task.get('executions', []):
                if run.get('usage_context'):
                    continue  # New runs already carry their frozen start context.
                context = derive(state, task, run, events, registrations)
                record = {'version': VERSION, 'project_id': task.get('project_id'),
                          'task_id': task['task_id'], 'execution_id': run['agent_run_id'],
                          'context': context, 'evidence': evidence(state, task, run, events, registrations)}
                record['id'] = digest(record)
                if record['id'] not in known:
                    f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
                    known.add(record['id']); added += 1
        f.flush()
    return {'added': added, 'records': len(known), 'version': VERSION}


def read_events(root):
    from harness.usage_provenance import read_jsonl
    return read_jsonl(Path(root) / '.harness/logs/events.jsonl')


def read_registrations(root):
    from harness.usage_provenance import read_jsonl
    return read_jsonl(Path(root) / '.harness/usage/sessions.jsonl')


def resolve(root, state, task, run, events):
    path = Path(root) / '.harness/usage/classifications.jsonl'
    found = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r['execution_id'] == run['agent_run_id'] and r['task_id'] == task['task_id'] and r['version'] == VERSION:
                    found.append(r)
    current = derive(state, task, run, events, read_registrations(root))
    if found:
        match = [r for r in found if r['context'] == current and r['context']['evidence_sha256'] == current['evidence_sha256'] and
                 digest(r.get('evidence')) == current['evidence_sha256'] and
                 r['id'] == digest({k: v for k, v in r.items() if k != 'id'})]
        if match:
            return {**match[-1]['context'], 'correction_id': match[-1]['id'], 'evidence': match[-1]['evidence']}
        current['quality'] = list(set(current['quality'] + ['mapping_error']))
    return current
