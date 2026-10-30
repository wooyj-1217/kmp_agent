"""Opt-in completion evidence. Does not spawn models or infer usage ownership."""
import copy
import hashlib
import json
from pathlib import Path


def _file(manager, relative):
    if not isinstance(relative, str) or not relative:
        raise ValueError('completion context path must name a repository file')
    path = (manager.root / relative).resolve()
    if not path.is_relative_to(manager.root) or not path.is_file():
        raise ValueError('completion evidence must be an existing repository file')
    return path


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract(manager, context_paths, usage_required=True, context_required=True, exception_reason=None):
    if type(usage_required) is not bool or type(context_required) is not bool:
        raise ValueError('completion required flags must be booleans')
    if exception_reason is not None and not _reason(exception_reason):
        raise ValueError('completion exception_reason must contain an explicit reason')
    if (not usage_required or not context_required) and not _reason(exception_reason):
        raise ValueError('completion exception_reason required for each disabled requirement')
    if not isinstance(context_paths, list) or len(context_paths) > 64:
        raise ValueError('completion context_paths must be a bounded list of files')
    paths = [str(_file(manager, p).relative_to(manager.root)) for p in context_paths]
    if len(set(paths)) != len(paths) or context_required and not paths:
        raise ValueError('completion requires distinct context paths; required context cannot be empty')
    return {'context_paths': paths, 'usage_required': usage_required,
            'context_required': context_required, 'exception_reason': exception_reason}


def inherited_contract(manager, work_type):
    """Read only at new-task registration. Existing tasks retain frozen contracts."""
    relative = '.harness/completion-policy.json'
    candidate = manager.root / relative
    if not candidate.exists() and not candidate.is_symlink():
        return None
    path = _file(manager, relative)
    if path.stat().st_size > 64_000:
        raise ValueError('completion policy exceeds bounded configuration size')
    try:
        payload = path.read_bytes()
        if len(payload) > 64_000:
            raise ValueError('completion policy exceeds bounded configuration size')
        policy = json.loads(payload)
    except (OSError, ValueError) as error:
        raise ValueError('invalid completion policy JSON') from error
    required = {'version', 'apply_to_work_types', 'context_paths', 'usage_required', 'context_required'}
    if not isinstance(policy, dict) or not required.issubset(policy) or set(policy) - (required | {'exception_reason'}):
        raise ValueError('completion policy has missing or unknown fields')
    from harness.logging import KINDS
    types = policy['apply_to_work_types']
    if type(policy['version']) is not int or policy['version'] != 1:
        raise ValueError('unsupported completion policy version')
    if not isinstance(types, list) or not types or any(not isinstance(t, str) or t not in KINDS for t in types) or len(set(types)) != len(types):
        raise ValueError('completion policy requires distinct supported work types')
    config = _contract(manager, policy['context_paths'], policy['usage_required'],
                       policy['context_required'], policy.get('exception_reason'))
    if work_type not in types:
        return None
    artifact = manager.artifact(relative)
    if artifact['sha256'] != hashlib.sha256(payload).hexdigest():
        raise ValueError('completion policy changed during registration; retry with stable policy')
    config.update(configuration_source='project_policy', policy=artifact)
    return config


def configure(manager, task_id, context_paths, usage_required=True, context_required=True, exception_reason=None):
    def operation(state):
        task = state['tasks'][task_id]
        if task['state'] not in {'TODO', 'READY'} or any(not r.get('ended_at') for r in task['executions']):
            raise ValueError('completion configuration requires inactive TODO/READY')
        previous = copy.deepcopy(task.get('completion_contract'))
        if previous and not _reason(exception_reason):
            raise ValueError('completion contract override requires explicit exception_reason')
        config = _contract(manager, context_paths, usage_required, context_required, exception_reason)
        if previous:
            config['configuration_source'] = 'explicit_override'
            if previous.get('policy'):
                config['policy'] = copy.deepcopy(previous['policy'])
        task['completion_contract'] = config
        task.pop('context_maintenance', None)
        observed = copy.deepcopy(config)
        if previous:
            observed.update(previous_contract=previous, override_reason=exception_reason)
        manager._event(state, 'completion_configured', task, observed=observed)
        return copy.deepcopy(config)
    return manager._mutate('configure_completion', operation, task_id)


def _reason(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip() != 'UNKNOWN'


def _work(task, execution_id):
    run = next((r for r in task['executions'] if r['agent_run_id'] == execution_id and r['kind'] == 'work'), None)
    if run is None:
        raise ValueError('context maintenance requires explicit work execution identity')
    return run


def _context(manager, task, execution_id, data, approved=False):
    config = task['completion_contract']
    if data.get('task_id') != task['task_id'] or data.get('work_execution_id') != execution_id:
        raise ValueError('context maintenance task/work execution mismatch')
    entries = data.get('context_paths')
    if not isinstance(entries, list) or len(entries) != len(config['context_paths']) or any(not isinstance(x, dict) for x in entries):
        raise ValueError('context maintenance requires exact configured context_paths hashes')
    paths = [e.get('path') for e in entries]
    if any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths) or set(paths) != set(config['context_paths']):
        raise ValueError('context maintenance context_paths mismatch')
    for entry in entries:
        if _hash(_file(manager, entry['path'])) != entry.get('sha256'):
            raise ValueError('context maintenance stale context hash: ' + entry['path'])
    maintainer = data.get('maintainer', {})
    if not isinstance(maintainer, dict) or maintainer.get('result') not in {'UPDATED', 'NO_CHANGE'} or not _reason(maintainer.get('reason')):
        raise ValueError('context maintenance needs UPDATED/NO_CHANGE with reason')
    if maintainer.get('independence') != 'agent_declared':
        raise ValueError('maintainer independence must be agent_declared; model execution is not proven by a string')
    if approved:
        review = data.get('main_review', {})
        if not isinstance(review, dict) or review.get('accepted') is not True or not _reason(review.get('reason')):
            raise ValueError('context maintenance needs separate main accepted review with reason; proposals are not approval')


def record(manager, task_id, work_execution_id, report_path):
    def operation(state):
        task = state['tasks'][task_id]
        if not task.get('completion_contract'):
            raise ValueError('configure_completion before context maintenance')
        work = _work(task, work_execution_id)
        latest = [r for r in task['executions'] if r['kind'] == 'work'][-1]
        if task['state'] not in {'IN_PROGRESS', 'IN_REVIEW'} or latest['agent_run_id'] != work['agent_run_id']:
            raise ValueError('context maintenance requires current latest work in IN_PROGRESS/IN_REVIEW; completed evidence is immutable')
        path = _file(manager, report_path)
        if str(path.relative_to(manager.root)) in task['completion_contract']['context_paths']:
            raise ValueError('maintenance receipt cannot recursively be a configured context path')
        if path.stat().st_size > 1_000_000:
            raise ValueError('context maintenance report exceeds bounded evidence size')
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise ValueError('invalid context maintenance JSON') from error
        if not isinstance(data, dict):
            raise ValueError('context maintenance report must be an object')
        _context(manager, task, work_execution_id, data)
        receipt = {'work_execution_id': work_execution_id, 'report': manager.artifact(report_path),
                   'independence': 'agent_declared'}
        task.setdefault('context_maintenance', {})[work_execution_id] = receipt
        manager._event(state, 'context_maintenance_recorded', task, work_execution_id, observed=copy.deepcopy(receipt))
        return copy.deepcopy(receipt)
    return manager._mutate('record_context_maintenance', operation, task_id)


def _matches(registration, event):
    obs = event.get('observed', {})
    if registration.get('session_id') != event.get('source', {}).get('session_id'):
        return False
    if registration.get('response_ids'):
        return obs.get('response_id') in registration['response_ids']
    return bool(registration.get('independent') or registration.get('turn_id') and registration['turn_id'] == obs.get('turn_id'))


def _usage(manager, state, task, run):
    from harness.usage_collection import registrations
    from harness.dashboard_usage import token_parts, native_identity_conflict
    events = [e for e in manager.logger.read() if e.get('event_type') == 'model_usage']
    regs = registrations(manager.root, state=state, events=events)
    from harness.usage_revision import unresolved_limits
    limits = unresolved_limits(manager.root, state, events, regs)
    own = [r for r in regs if r.get('task_id') == task['task_id'] and r.get('execution_id') == run['agent_run_id'] and r.get('run_id') == run['run_id']]
    if not own:
        raise ValueError('completion usage UNKNOWN: missing exact session/turn registration')
    if any(not _reason(r.get('session_id')) or not (r.get('independent') or _reason(r.get('turn_id')) or r.get('response_ids')) for r in own):
        raise ValueError('completion usage UNKNOWN: registration lacks exact session/turn identity')
    if any(r.get('independent') and run.get('execution_mode') != 'independent_process' for r in own):
        raise ValueError('completion usage UNKNOWN: independent session/execution mode mismatch')
    keys = {(b.get('session_id'), b.get('response_id')) for b in run.get('usage_bindings', [])}
    if not keys:
        raise ValueError('completion usage UNKNOWN: missing bound model_usage')
    for registration in own:
        expected = {(registration['session_id'], response) for response in registration.get('response_ids', [])}
        if not expected.issubset(keys):
            raise ValueError('completion usage UNKNOWN: explicit registered response still pending or unbound')
        if not any(_matches(registration, event) for event in events):
            raise ValueError('completion usage UNKNOWN: registered session/turn still pending')
    relevant = [e for e in events if any(_matches(r, e) for r in own)]
    relevant_keys = {(e.get('source', {}).get('session_id'), e.get('observed', {}).get('response_id')) for e in relevant}
    if keys != relevant_keys:
        raise ValueError('completion usage UNKNOWN: missing or mismatched exact response binding')
    for key in keys:
        if key in limits:
            raise ValueError('completion usage UNKNOWN: response has unresolved attribution conflict')
        if any(x in (None, '', 'UNKNOWN') for x in key):
            raise ValueError('completion usage UNKNOWN: missing native response identity')
        facts = [e for e in events if (e.get('source', {}).get('session_id'), e.get('observed', {}).get('response_id')) == key]
        if any(native_identity_conflict(e) for e in facts):
            raise ValueError('completion usage UNKNOWN: source session/native thread identity conflict')
        values = {(json.dumps(e['observed'].get('usage'), sort_keys=True), e['observed'].get('usage_semantics'), e['observed'].get('model'), e['observed'].get('turn_id')) for e in facts}
        if len(values) != 1 or any(token_parts(e['observed'].get('usage'), e['observed'].get('usage_semantics')) is None for e in facts):
            raise ValueError('completion usage UNKNOWN: conflicting or invalid original model_usage')
        owners = {r['agent_run_id'] for t in state['tasks'].values() for r in t['executions']
                  if any((b.get('session_id'), b.get('response_id')) == key for b in r.get('usage_bindings', []))}
        owners.update(e.get('agent_run_id') for e in facts if e.get('agent_run_id') not in (None, '', 'UNKNOWN'))
        owners.update(r.get('execution_id') for r in regs if any(_matches(r, e) for e in facts))
        declared_tasks = {e.get('task_id') for e in facts if e.get('task_id') not in (None, '', 'UNKNOWN')}
        registration_conflict = any((r.get('task_id'), r.get('execution_id'), r.get('run_id')) !=
                                    (task['task_id'], run['agent_run_id'], run['run_id'])
                                    for r in regs if any(_matches(r, e) for e in facts))
        if owners != {run['agent_run_id']} or declared_tasks - {task['task_id']} or registration_conflict:
            raise ValueError('completion usage UNKNOWN: ambiguous or conflicting execution binding')


def gate(manager, state, task):
    config = task.get('completion_contract')
    if not config:
        return
    runs = [r for r in task['executions'] if r['kind'] == 'work']
    if not runs or not runs[-1].get('ended_at'):
        raise ValueError('completion requires ended work execution')
    run = runs[-1]
    if config['usage_required']:
        _usage(manager, state, task, run)
    if config['context_required']:
        receipt = task.get('context_maintenance', {}).get(run['agent_run_id'])
        if not receipt or not manager._valid_artifact(receipt.get('report')):
            raise ValueError('completion context UNKNOWN: missing valid maintenance receipt')
        path = _file(manager, receipt['report']['snapshot'])
        data = json.loads(path.read_text())
        _context(manager, task, run['agent_run_id'], data, approved=True)
