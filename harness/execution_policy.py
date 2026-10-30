"""Opt-in execution contracts and a read-only managed-worker gate.

This controls harness-managed actions, not arbitrary shell commands or OS tools.
The durable activation lives in the native task ledger, never in an env lookup.
"""
import copy
import json
import os
import signal
import subprocess
import time
from pathlib import Path

KINDS = {'HARNESS_BUILD', 'HARNESS_IMPROVEMENT', 'PRODUCT'}
START = {'ready', 'begin', 'begin_review', 'resume', 'dispatch', 'dispatch_preflight'}
ADVANCE = START | {'submit', 'review', 'handoff', 'accept'}


def configure(manager, root_session_path, root_session_id, apply_to_work_types=None,
              grandfather_active_ids=None):
    from harness.decisions import native_records
    path = Path(root_session_path).resolve(strict=True)
    native_records(path, root_session_id)
    kinds = list(apply_to_work_types or sorted(KINDS))
    if not kinds or set(kinds) - KINDS:
        raise ValueError('unsupported execution-policy work type')
    requested = set(grandfather_active_ids or [])
    def op(state):
        if state.get('execution_policy'):
            raise ValueError('execution policy is already frozen; weakening/replacement is forbidden')
        active = {r['agent_run_id']: t['task_id'] for t in state['tasks'].values()
                  for r in t['executions'] if not r.get('ended_at')}
        if requested - active.keys():
            raise ValueError('grandfather IDs must be currently active executions')
        from harness.logging import now
        policy = {'version': 1, 'run_id': manager.run_id, 'apply_to_work_types': kinds, 'activated_at': now(),
                  'root_session_path': str(path), 'root_session_id': root_session_id,
                  'grandfathered_active_attempts': {k: active[k] for k in sorted(requested)}}
        state['execution_policy'] = policy
        state['execution_policy_bindings'] = {manager.run_id: {
            'root_session_path': str(path), 'root_session_id': root_session_id}}
        for task in state['tasks'].values():
            if task['state'] != 'DONE' and task['work_type'] in kinds:
                task['execution_contract'] = copy.deepcopy(policy)
        anchor = next((t for t in state['tasks'].values() if t['work_type'] in kinds and t['state'] != 'DONE'), None)
        if anchor:
            manager._event(state, 'execution_policy_activated', anchor, observed=copy.deepcopy(policy))
        return copy.deepcopy(policy)
    return manager._mutate('configure_execution_policy', op)


def bind_session(manager, root_session_path, root_session_id):
    from harness.decisions import native_records
    path = Path(root_session_path).resolve(strict=True)
    native_records(path, root_session_id)
    value = {'root_session_path': str(path), 'root_session_id': root_session_id}
    def op(state):
        if not state.get('execution_policy'):
            raise ValueError('configure the immutable project execution policy first')
        bindings = state.setdefault('execution_policy_bindings', {})
        old = bindings.get(manager.run_id)
        if old and old != value:
            raise ValueError('existing run root binding is immutable')
        bindings[manager.run_id] = value
        anchor = next((t for t in state['tasks'].values() if t['state'] != 'DONE'), None)
        if anchor and not old:
            manager._event(state, 'execution_session_bound', anchor, observed=copy.deepcopy(value))
        return copy.deepcopy(value)
    return manager._mutate('bind_execution_session', op)


def inherit(state, task, run_id=None):
    policy = state.get('execution_policy')
    if policy and task['work_type'] in policy['apply_to_work_types']:
        if 'execution_contract' not in task:
            contract = copy.deepcopy(policy)
            if run_id:
                contract['run_id'] = run_id
                contract.update(state.get('execution_policy_bindings', {}).get(run_id, {}))
            task['execution_contract'] = contract
    return task.get('execution_contract')


def configure_plan(manager, task_id, work_plan, reason):
    if not isinstance(work_plan, dict):
        raise ValueError('work_plan object required')
    plan = copy.deepcopy(work_plan)
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    def fields(item):
        return all(isinstance(item.get(k), list) and item[k] and all(text(v) for v in item[k])
                   for k in ('completion_criteria', 'inputs', 'outputs', 'verification'))
    if not text(reason) or plan.get('version') != 1 or not fields(plan):
        raise ValueError('version, reason, completion criteria, inputs, outputs and verification required')
    steps = plan.get('steps')
    if not isinstance(steps, list) or not steps or any(not isinstance(s, dict) or not text(s.get('id')) or not text(s.get('action')) or not fields(s) for s in steps):
        raise ValueError('each concrete step needs id/action/completion criteria/inputs/outputs/verification')
    if len({s['id'] for s in steps}) != len(steps):
        raise ValueError('duplicate step ID')
    def op(state):
        task = state['tasks'][task_id]
        if plan.get('owner') != task['role']:
            raise ValueError('owner must equal Task.role')
        member = membership(state, manager.run_id, task_id)
        if not member or plan.get('whole_plan_task_id') != member:
            raise ValueError('task must be a member of the whole execution plan')
        if task.get('work_plan') == plan and task.get('work_plan_run_id') == manager.run_id:
            return copy.deepcopy(plan)
        task.setdefault('work_plan_history', []).append({'plan': copy.deepcopy(plan), 'reason': reason, 'run_id': manager.run_id})
        task['work_plan'] = plan
        task['work_plan_run_id'] = manager.run_id
        manager._event(state, 'task_work_plan_configured', task, observed={'work_plan': plan, 'reason': reason})
        return copy.deepcopy(plan)
    return manager._mutate('configure_task_plan', op, task_id)


def membership(state, run_id, task_id):
    """Resolve explicit native delegation/QA links to a whole-plan member."""
    members = set(state.get('execution_plans', {}).get(run_id, {}).get('task_ids', []))
    seen = set()
    current = task_id
    while current in state['tasks'] and current not in seen:
        if current in members:
            return current
        seen.add(current)
        task = state['tasks'][current]
        parent = task.get('parent_task_id') or task.get('delegation', {}).get('parent_task_id') or task.get('qa_config', {}).get('target_task_id')
        if not parent:
            parent = next((tid for tid, t in state['tasks'].items() if t.get('qa_config', {}).get('repair_task_id') == current), None)
        ancestor = state['tasks'].get(parent, {})
        if ancestor.get('project_id') != task.get('project_id') or ancestor.get('work_type') != task.get('work_type'):
            return None
        current = parent
    return None


def dependency_closure(state, initial):
    affected = set(initial)
    while True:
        before = len(affected)
        affected.update(tid for tid, t in state['tasks'].items()
                        if set(t.get('dependencies', [])) & affected or t.get('parent_task_id') in affected
                        or t.get('delegation', {}).get('parent_task_id') in affected
                        or t.get('qa_config', {}).get('target_task_id') in affected)
        affected.update(t['qa_config']['repair_task_id'] for tid, t in state['tasks'].items()
                        if tid in affected and t.get('qa_config', {}).get('repair_task_id') in state['tasks'])
        if len(affected) == before:
            return affected


def pending(state, task_id):
    result = []
    for qid, q in state.get('required_questions', {}).items():
        if q['status'] != 'OPEN':
            continue
        affected = dependency_closure(state, q['propagated_task_ids'])
        if task_id in affected:
            result.append(qid)
    return result


def gate(manager, state, task_id, action):
    if action not in ADVANCE:
        return
    if task_id not in state['tasks']:
        raise ValueError('managed execution requires an existing task')
    task = state['tasks'][task_id]
    if task['state'] == 'DONE':
        if action == 'handoff':
            return  # Completed source history may be handed to a separately gated target.
        raise ValueError('completed task history does not permit a new managed execution: task already completed')
    questions = pending(state, task_id)
    if questions:
        raise ValueError('required human answer pending: ' + ', '.join(questions))
    contract = inherit(state, task, manager.run_id)
    if not contract or task['state'] == 'DONE':
        return
    if manager.run_id not in state.get('execution_policy_bindings', {}):
        raise ValueError('bind the current run to its fixed native root session before managed execution')
    # Existing active attempt alone may finish/resume; a fresh dispatch is never exempt.
    old = contract['grandfathered_active_attempts']
    legacy = any(not r.get('ended_at') and old.get(r['agent_run_id']) == task_id
                 for r in task['executions'])
    if legacy and action in {'resume', 'submit', 'review', 'accept'}:
        return
    if not membership(state, manager.run_id, task_id):
        raise ValueError('whole execution plan membership required before ' + action)
    if not task.get('work_plan') or task.get('work_plan_run_id') != manager.run_id:
        raise ValueError('assigned detailed work plan required before ' + action)
    if action == 'dispatch':
        active = [r for r in task['executions'] if not r.get('ended_at')]
        if len(active) != 1 or active[0].get('run_id') != manager.run_id or task['state'] != ('IN_REVIEW' if active[0].get('kind') == 'review' else 'IN_PROGRESS'):
            raise ValueError('managed dispatch requires one active unblocked execution in the current run')
        if any(state['tasks'][d]['state'] != 'DONE' for d in task.get('dependencies', [])):
            raise ValueError('unfinished dependency prevents managed dispatch')
        if not all(manager._valid_artifact(a) for a in task.get('inputs', [])):
            raise ValueError('invalid input snapshot prevents managed dispatch')


class WorkerGate:
    """Stat-cache the same native ledger; never Tasks.read()/rewrite on each tick."""
    def __init__(self, manager, task_id):
        self.manager, self.task_id = manager, task_id
        self.signature, self.state = None, None

    def check(self):
        stat = self.manager.path.stat()
        signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        if signature != self.signature:
            self.state = json.loads(self.manager.path.read_text())
            self.signature = signature
        if pending(self.state, self.task_id):
            raise ValueError('required human answer pending; managed worker interrupted')


def status(state, task, run_id=None):
    qids = pending(state, task['task_id']) if task['state'] != 'DONE' else []
    contract = task.get('execution_contract') or state.get('execution_policy', {})
    active = bool(contract and task['work_type'] in contract['apply_to_work_types'])
    run_id = run_id or next((r.get('run_id') for r in reversed(task['executions']) if r.get('run_id')), contract.get('run_id'))
    member = membership(state, run_id, task['task_id']) if active else None
    task_plan = bool(task.get('work_plan') and task.get('work_plan_run_id') == run_id)
    legacy = any(not r.get('ended_at') and contract.get('grandfathered_active_attempts', {}).get(r['agent_run_id']) == task['task_id'] for r in task['executions'])
    reasons = ['required human answer pending'] if qids else []
    if task['state'] == 'DONE':reasons.append('completed task history does not permit a new managed execution')
    if active and task['state'] != 'DONE':
        if run_id not in state.get('execution_policy_bindings', {}):reasons.append('current run native root session binding required')
        if not member: reasons.append('whole execution plan membership required')
        if not task_plan: reasons.append('assigned detailed work plan required')
    finish_reasons = ['required human answer pending'] if qids else []
    if not legacy and task['state'] != 'DONE': finish_reasons = reasons[:]
    return {'status': 'HISTORICAL' if task['state'] == 'DONE' else 'BLOCKED' if reasons else 'ALLOWED' if active else 'NOT_CONFIGURED',
            'start_status': 'BLOCKED' if reasons else 'ALLOWED' if active else 'NOT_CONFIGURED',
            'finish_status': 'HISTORICAL' if task['state'] == 'DONE' else 'BLOCKED' if finish_reasons else 'ALLOWED' if active else 'NOT_CONFIGURED',
            'question_ids': qids, 'reasons': reasons, 'finish_reasons': finish_reasons,
            'plan_registered': bool(member), 'task_plan_registered': task_plan,
            'contract_active': active, 'legacy_active_attempt': legacy,
            'historical_done': task['state'] == 'DONE', 'contract_version': contract.get('version')}


def stop_owned_group(child, drain, timeout=2):
    """Stop only a freshly owned session/PG, including pipe-detaching descendants."""
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    result = None
    try:
        result = drain(child, timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return result if result is not None else drain(child, timeout=timeout)


def managed_command(manager, task_id, argv, cwd, timeout=None, text=True):
    """Poll and terminate only this owned process; no arbitrary historical PIDs."""
    manager.require_dispatch(task_id)
    watch = WorkerGate(manager, task_id)
    child = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text,
                             start_new_session=True)
    deadline = time.monotonic() + timeout if timeout is not None else None
    try:
        while True:
            watch.check()
            remaining = deadline - time.monotonic() if deadline is not None else .2
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                stdout, stderr = child.communicate(timeout=min(.2, remaining))
                watch.check()
                return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        stop_owned_group(child, lambda owned, timeout: owned.communicate(timeout=timeout))
        raise
