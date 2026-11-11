"""Explicit foreground feature controller. Never creates human or issuer authority.

The task ledger remains authoritative. This additive record freezes the execution
contract, records controller attempts, and selects existing executors only.
"""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid

from harness import logging
from harness.process_ownership import TaskLease, inspect_owner
from harness.roles import Roles
from harness.stage_readiness import STAGES, assess
from harness.tasks import Tasks

_foreground_environment = threading.Lock()


@contextmanager
def _lock_budget(root, seconds):
    if type(seconds) is not int or not 15 <= seconds <= 300:
        raise ValueError('lock_wait_timeout must be an integer in 15..300')
    if not _foreground_environment.acquire(blocking=False):
        raise RuntimeError('one foreground controller per Python process required')
    keys = ('KMP_ORCHESTRATION_LOCK_ROOT', 'KMP_ORCHESTRATION_LOCK_WAIT_SECONDS')
    old = {k: os.environ.get(k) for k in keys}
    try:
        os.environ[keys[0]] = str(Path(root).resolve())
        os.environ[keys[1]] = str(seconds)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _foreground_environment.release()


def _read(manager):
    # Selection snapshot only. Every executor/Tasks mutation revalidates through
    # its native gate; avoid refreshing every Git-backed task for each field.
    from harness.integration_transaction import read_barrier
    from harness.sequential import read_state
    with read_barrier(manager.root):
        return read_state(manager.root)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _current(manager, artifact):
    p = manager.root / artifact['path']
    return p.is_file() and logging.digest(p.read_bytes()) == artifact['sha256'] and manager._valid_artifact(artifact)


def _task_contract(task):
    # P/D versions and input hashes are bound only after upstream review. The
    # authorized folder, criteria, scope, retry limits and detailed plan stay fixed.
    return {k: copy.deepcopy(task.get(k)) for k in (
        'role', 'criteria', 'max_attempts', 'visual_required', 'execution_scope',
        'work_type', 'execution_contract', 'verification_contract', 'completion_contract',
        'work_plan')} | {'role_contract': {k: copy.deepcopy(task.get('role_contract', {}).get(k))
                                         for k in ('folder', 'scope', 'change_id', 'design_targets')}
                                     | ({'ui_applicability':copy.deepcopy(task['role_contract']['ui_applicability'])}
                                        if task.get('role_contract', {}).get('ui_applicability') else {})}


def _implementation_contract(task):
    return _task_contract(task) | {k: copy.deepcopy(task.get(k)) for k in (
        'development_tracking', 'development_delegation', 'coordination_plan_id',
        'delegation', 'verification_required', 'protected_verification_required',
        'approved_verification_definition', 'completion_semantics', 'implementation_origin')}


def configure(manager, feature_id, contract_path):
    """Register once; callers pre-register stages, role contracts and policy plans.

    JSON is an execution contract, not natural language decomposition. Replacing
    one requires a new feature/contract; no in-place policy relaxation API exists.
    """
    manager.read()
    artifact = manager.artifact(contract_path)
    value = json.loads((manager.root / artifact['path']).read_text())
    allowed = {'version', 'stages', 'reviewer', 'qa', 'completion', 'approval_question_id', 'work_plans', 'retry_failed_tasks', 'requirements_qa_task_id', 'lock_wait_timeout'}
    if set(value) - allowed or value.get('version') != 1 or value.get('completion') not in {'qa', 'official'}:
        raise ValueError('version 1, explicit qa/official completion and known fields required')
    state = _read(manager)
    if type(value.get('lock_wait_timeout', 300)) is not int or not 15 <= value.get('lock_wait_timeout', 300) <= 300:
        raise ValueError('lock_wait_timeout must be an integer in 15..300')
    if not isinstance(value.get('work_plans', {}), dict) or any(not isinstance(v, dict) for v in value.get('work_plans', {}).values()):
        raise ValueError('work_plans must map explicit task IDs to native detailed plans')
    if not isinstance(value.get('retry_failed_tasks', []), list) or any(not isinstance(t, str) or not t for t in value.get('retry_failed_tasks', [])):
        raise ValueError('retry_failed_tasks must name explicitly authorized task IDs')
    flow = state.get('stage_workflows', {}).get(feature_id)
    if not flow or set(value.get('stages', {})) != set(STAGES):
        raise ValueError('three existing independent stage contracts required')
    reviewer = value.get('reviewer', {})
    if set(reviewer) - {'command', 'timeout'} or type(reviewer.get('timeout', 300)) is not int or not 0 < reviewer.get('timeout', 300) <= 3600:
        raise ValueError('bounded independent reviewer required')
    def argv(command):
        return isinstance(command, list) and bool(command) and all(isinstance(x, str) and x for x in command)
    if 'command' in reviewer and not argv(reviewer['command']):
        raise ValueError('reviewer command must be argv')
    tasks = {}
    for stage in STAGES:
        spec = value['stages'][stage]
        if set(spec) - {'task_id', 'worker', 'timeout'} or spec.get('task_id') != flow['stages'][stage]['task_id']:
            raise ValueError('stage must reference registered task exactly')
        if 'worker' in spec and not argv(spec['worker']):
            raise ValueError('worker must be argv')
        if type(spec.get('timeout', 300)) is not int or not 0 < spec.get('timeout', 300) <= 3600:
            raise ValueError('bounded role timeout required')
        task = state['tasks'][spec['task_id']]
        if not task.get('role_contract') or task['feature_id'] != feature_id:
            raise ValueError('configured native role task required')
        tasks[stage] = _task_contract(task)
    qa = value.get('qa', {})
    value.setdefault('requirements_qa_task_id', str(qa.get('task_id', '')) + '-REQUIREMENTS')
    if not isinstance(value['requirements_qa_task_id'], str) or not value['requirements_qa_task_id']:
        raise ValueError('requirements QA task ID required')
    qa_fields = {'task_id', 'stage', 'original_requests', 'criteria', 'commands', 'max_attempts',
                 'repair_task_id', 'executable', 'timeout', 'images', 'context_files',
                 'generated_paths', 'repair_criteria'}
    if set(qa) - qa_fields or not qa.get('task_id') or not qa.get('criteria') or not qa.get('original_requests') or qa.get('stage') != 'implementation':
        raise ValueError('explicit implementation QA contract required')
    refs = [manager.artifact(p) for p in qa['original_requests'] + qa.get('context_files', []) + qa.get('images', [])]
    commands = [reviewer.get('command', [])] + [value['stages'][s].get('worker', []) for s in STAGES]
    commands += [[qa.get('executable', 'codex')]]
    for command in commands:
        for arg in command:
            candidate = (manager.root / arg).resolve()
            if candidate.is_relative_to(manager.root) and candidate.is_file():
                refs.append(manager.artifact(str(candidate.relative_to(manager.root))))
    for stage in STAGES:
        refs.extend(copy.deepcopy(state['tasks'][value['stages'][stage]['task_id']]['inputs']))
    refs = list({a['path']: a for a in refs}.values())
    product = any(c['work_type'] == 'PRODUCT' for c in tasks.values())
    if product and (not value.get('approval_question_id') or any(not flow['stages'][s].get('human_approval_question_id') for s in STAGES)):
        raise ValueError('PRODUCT requires contract and stage human approval question IDs')
    policy = copy.deepcopy(state.get('execution_policy'))
    binding = copy.deepcopy(state.get('execution_policy_bindings', {}).get(manager.run_id))
    if product and (not policy or 'PRODUCT' not in policy.get('apply_to_work_types', []) or not binding):
        raise ValueError('PRODUCT approval policy missing; automatic dispatch prohibited')
    if product and any(not c['execution_contract'] for c in tasks.values()):
        raise ValueError('PRODUCT tasks must inherit the current execution policy')
    record = {'version': 1, 'feature_id': feature_id, 'run_id': manager.run_id,
              'contract': artifact, 'value': value, 'tasks': tasks,
              'initial_inputs': {s: copy.deepcopy(state['tasks'][value['stages'][s]['task_id']]['inputs']) for s in STAGES},
              'flow': copy.deepcopy(flow), 'source_artifacts': refs,
              'approval_policy': policy, 'execution_policy_binding': binding,
              'attempts': [], 'events': [], 'last_result': None}
    repair = state['tasks'].get(qa.get('repair_task_id'))
    if repair:
        record['authorized_repairs'] = {t: _implementation_contract(state['tasks'][t]) for t in [repair['task_id']] + [c['task_id'] for c in repair.get('development_delegation', {}).get('children', [])]}
    def op(current):
        book = current.setdefault('orchestrations', {})
        if feature_id in book:
            old = book[feature_id]
            if old['contract']['sha256'] != artifact['sha256'] or old['run_id'] != manager.run_id:
                raise ValueError('orchestration already bound; create a reviewed revision')
            return copy.deepcopy(old)
        book[feature_id] = record
        manager._event(current, 'orchestration_registered', current['tasks'][value['stages']['planning']['task_id']], observed={'feature_id': feature_id, 'contract': artifact})
        return copy.deepcopy(record)
    with TaskLease(manager.root, 'orchestration:' + feature_id):
        return manager._mutate('register_orchestration', op)


def _record(manager, feature_id, event, **data):
    def op(state):
        item = state['orchestrations'][feature_id]
        entry = {'at': logging.now(), 'event': event, **copy.deepcopy(data)}
        item['events'].append(entry)
        if event == 'controller_started':
            item['attempts'].append(entry)
        if event == 'controller_stopped':
            item['attempts'][-1]['ended_at'] = entry['at']
            item['last_result'] = data['result']
        anchor = item['value']['stages']['planning']['task_id']
        manager._event(state, 'orchestration_' + event, state['tasks'][anchor], observed=entry)
    manager._mutate('orchestration_event', op)


def _result(code, stage=None, reasons=None, **extra):
    return {'status': code, 'stage': stage, 'reasons': reasons or [],
            'human_approval_inferred': False, 'official_certification_inferred': False, **extra}


def _qa_contract(config):
    # The native QA executor owns observations and authorized repair rebases.
    # Identity, commands, criteria, original inputs and repair authority stay fixed.
    return {k: copy.deepcopy(v) for k, v in config.items()
            if k not in {'attempts', 'retest_bases', 'target_manifest', 'target_baseline'}}


def _question_released(task):
    # Caller first evaluates the native pending gate. Never clear a live
    # question-checkpointed attempt or a different failure reason.
    return task.get('state') == 'BLOCKED' and str(task.get('blocked_reason', '')).startswith('required human answer pending:') and not any(not r.get('ended_at') for r in task.get('executions', []))


def _normal_retry(item, task):
    """A retry grant covers a failed attempt, never invalidated successful code."""
    if task['task_id'] not in item['value'].get('retry_failed_tasks', []):
        return False
    required = {c['id'] for c in task.get('criteria', []) if c.get('required')}
    def was_pass(review):
        rows = {r['criterion_id']: r['result'] for r in review.get('results', [])}
        return review.get('result') == 'PASS' or bool(rows) and all(rows.get(c) == 'PASS' for c in (required or rows))
    if task.get('execution_completion') or any(was_pass(r) for r in task.get('reviews', [])):
        return False
    if task.get('recovery', {}).get('state') in {'RECHECK_REQUIRED', 'MANUAL_INTERVENTION_REQUIRED'} or any(v.get('state') == 'RECHECK_REQUIRED' for v in task.get('validation_status', {}).values()):
        return False
    if any(not r.get('ended_at') for r in task.get('executions', [])):
        return False
    work = [r for r in task.get('executions', []) if r['kind'] == 'work']
    return bool(work and work[-1].get('failure') and work[-1].get('ended_at') and work[-1].get('failure_context', {}).get('requires_human') is not True)


def _decision_resume(manager, task):
    active = [r for r in task.get('executions', []) if not r.get('ended_at')]
    return len(active) == 1 and manager._valid_artifact(active[0].get('checkpoint', {})) and bool(active[0].get('decisions')) and manager._valid_artifact(active[0]['decisions'][-1]) and task['state'] in {'IN_PROGRESS', 'IN_REVIEW'}


def _current_repair(manager, item, original):
    """Fresh repair execution + fresh QA may satisfy QA scope, never old DONE.

    Preserve the original implementation's stale review. A different authorized
    revision must carry its own current execution proof over the same code scope.
    """
    from harness.recovery import done_reasons
    spec = item['value']['qa']
    state = _read(manager)
    qa = state['tasks'].get(spec['task_id'])
    repair = state['tasks'].get(spec.get('repair_task_id'))
    if not qa or not repair or repair['task_id'] == original['task_id'] or qa['state'] != 'DONE' or repair['state'] != 'DONE':
        return False
    config = qa.get('qa_config', {})
    if config.get('target_task_id') != original['task_id'] or config.get('repair_task_id') != repair['task_id'] or not config.get('retest_bases'):
        return False
    if not repair.get('execution_completion') or not qa.get('qa_observation_completion') or done_reasons(manager, repair) or done_reasons(manager, qa):
        return False
    if any(repair.get(k) != original.get(k) for k in ('project_id', 'feature_id', 'work_type')):
        return False
    return set(repair.get('development_tracking', {}).get('code_paths', [])) == set(original.get('development_tracking', {}).get('code_paths', [])) and bool(original.get('development_tracking', {}).get('code_paths'))


def _attach_plan(manager, item, tid):
    plan = item['value'].get('work_plans', {}).get(tid)
    task = _read(manager)['tasks'][tid]
    if plan is not None:
        if task.get('work_plan') is not None and task['work_plan'] != plan:
            raise ValueError('approved detailed task plan differs: ' + tid)
        if task.get('work_plan') is None:
            manager.configure_task_plan(tid, plan, 'explicit frozen orchestration contract')


def _validate(manager, item):
    state = _read(manager)
    if item['run_id'] != manager.run_id:
        return _result('BLOCKED', reasons=['execution session differs; explicit reviewed rebinding required'])
    refs = [item['contract']] + item['source_artifacts']
    if not all(_current(manager, a) for a in refs):
        return _result('RECHECK_REQUIRED', reasons=['execution contract, original input or authority policy changed'])
    frozen = json.loads((manager.root / item['contract']['snapshot']).read_text())
    frozen.setdefault('requirements_qa_task_id', str(frozen.get('qa', {}).get('task_id', '')) + '-REQUIREMENTS')
    if frozen != item['value']:
        return _result('RECHECK_REQUIRED', reasons=['ledger execution arguments differ from approved contract bytes'])
    if state.get('execution_policy') != item['approval_policy'] or state.get('execution_policy_bindings', {}).get(manager.run_id) != item['execution_policy_binding']:
        return _result('RECHECK_REQUIRED', reasons=['execution policy binding changed'])
    for tid, plan in item['value'].get('work_plans', {}).items():
        task = state['tasks'].get(tid)
        if task and task.get('work_plan') is not None and task['work_plan'] != plan:
            return _result('RECHECK_REQUIRED', reasons=['approved detailed task plan changed: ' + tid])
    for event in item['events']:
        for tid, contract in event.get('repair_contracts', {}).items():
            if tid not in state['tasks'] or _implementation_contract(state['tasks'][tid]) != contract:
                return _result('RECHECK_REQUIRED', 'qa', ['approved repair criteria/scope changed: ' + tid])
    for tid, expected in item.get('authorized_repairs', {}).items():
        actual = _implementation_contract(state['tasks'].get(tid, {}))
        before = copy.deepcopy(expected)
        if actual.get('work_plan') == item['value'].get('work_plans', {}).get(tid) and actual.get('work_plan') is not None:
            before['work_plan'] = actual['work_plan']
        if actual != before:
            return _result('RECHECK_REQUIRED', 'qa', ['preauthorized repair contract changed: ' + tid])
    flow = state.get('stage_workflows', {}).get(item['feature_id'], {})
    for stage in STAGES:
        c = flow.get('stages', {}).get(stage, {})
        original = item['flow']['stages'][stage]
        # Existing return_to_stage revisions are accepted only with the same
        # immutable review policy and native history ancestry.
        if {k: v for k, v in c.items() if k not in {'task_id', 'task_history'}} != {k: v for k, v in original.items() if k not in {'task_id', 'task_history'}}:
            return _result('RECHECK_REQUIRED', stage, ['stage review/approval contract changed'])
        history = c.get('task_history', [])
        if history[:len(original['task_history'])] != original['task_history'] or c.get('task_id') not in history:
            return _result('RECHECK_REQUIRED', stage, ['stage history changed'])
        task = state['tasks'].get(c.get('task_id'), {})
        if _task_contract(task) != item['tasks'][stage]:
            return _result('RECHECK_REQUIRED', stage, ['role criteria, scope, retry budget or work plan changed'])
        allowed_inputs = {a['path']: a['sha256'] for a in item['source_artifacts']}
        for earlier in STAGES[:STAGES.index(stage)]:
            previous = state['tasks'][flow['stages'][earlier]['task_id']]
            allowed_inputs.update({a['path']: a['sha256'] for a in previous['outputs']})
            allowed_inputs.update({c['evidence']['path']: c['evidence']['sha256'] for c in previous.get('design_status', {}).get('checks', {}).values() if c.get('evidence') and _current(manager, c['evidence'])})
            for handoff in previous.get('handoffs', []):
                if handoff.get('from_task_id') == previous['task_id'] and handoff.get('to_task_id') == task['task_id']:
                    allowed_inputs.update({a['path']: a['sha256'] for a in handoff.get('supplementary_artifacts', []) if _current(manager, a)})
        if any(allowed_inputs.get(a['path']) != a['sha256'] for a in task['inputs']):
            return _result('RECHECK_REQUIRED', stage, ['stage input outside approved original/upstream scope'])
        actual_inputs = {(a['path'], a['sha256']) for a in task['inputs']}
        if any((a['path'], a['sha256']) not in actual_inputs for a in item['initial_inputs'][stage]):
            return _result('RECHECK_REQUIRED', stage, ['approved original stage input removed'])
    if item['value'].get('approval_question_id'):
        from harness.approvals import human_approval
        tid = item['value']['stages']['planning']['task_id']
        receipt = human_approval(manager.root, state, item['value']['approval_question_id'], tid,
                                 'orchestration', {'feature_id': item['feature_id'], 'contract_sha256': item['contract']['sha256']},
                                 {a['path']: a['sha256'] for a in [item['contract']] + item['source_artifacts']})
        if not receipt:
            return _result('WAITING_FOR_APPROVAL', 'contract', question_id=item['value']['approval_question_id'])
    return None


def _waiting(manager, tid):
    state = _read(manager)
    from harness.execution_policy import pending
    questions = pending(state, tid)
    if questions:
        typed = [state.get('required_questions', {}).get(q, {}).get('decision_contract') for q in questions]
        return _result('WAITING_FOR_APPROVAL' if any(t and t.get('purpose') for t in typed) else 'WAITING_FOR_INPUT', tid, ['required human answer pending'], questions=questions)
    return None


def _review(manager, tid, spec):
    """Run an independent read-only reviewer; never synthesize criterion PASS."""
    from harness.execution_policy import managed_command
    from harness.runtime_limits import model_slot
    with TaskLease(manager.root, tid):
        task = _read(manager)['tasks'][tid]
        existing = [r for r in task['executions'] if not r.get('ended_at') and r['kind'] == 'review']
        review = existing[0] if existing and _decision_resume(manager, task) else manager.begin(tid, 'verification', review=True, execution_mode='independent_process')
        aid = review['agent_run_id']
        directory = manager.directory / 'orchestrator-reviews' / aid
        directory.mkdir(parents=True, exist_ok=True)
        packet = {'kind': 'ROLE_REVIEW', 'task_id': tid, 'project_root': str(manager.root),
                  'criteria': task['criteria'], 'inputs': task['inputs'], 'outputs': task['outputs'],
                  'design_status': task.get('design_status'), 'role_contract': task.get('role_contract'),
                  'instruction': 'Independently inspect each criterion and current outputs. Return JSON {summary,results:[{criterion_id,result:PASS|FAIL|NOT_RUN,evidence:relative_path}],evidence_documents:{safe_name:content},design_checks:optional}. Reference generated evidence as @safe_name; the adapter persists it. Never invent evidence, human approval or official certification. Design checks must follow the existing structure/interaction/visual report contract; unobserved visuals are NOT_RUN. Do not write project source files.'}
        if task.get('role_contract', {}).get('ui_applicability'):
            packet['instruction'] += ' UI is explicitly NOT_APPLICABLE: inspect the source-bound declaration and interface/error contracts; omit design_checks and never report visual PASS.'
        path = directory / 'packet.json'
        path.write_text(json.dumps(packet, ensure_ascii=False, indent=2))
        result_path = directory / 'result.json'
        command = spec.get('command')
        argv = command + [str(path)] if command else ['codex', 'exec', '--ignore-user-config', '--sandbox', 'read-only', '--skip-git-repo-check', '-o', str(result_path), 'Read ' + str(path) + ' and perform its ROLE_REVIEW. Output JSON only.']
        try:
            if task.get('role_contract', {}).get('ui_applicability'):
                manager._mutate('role_process', lambda state: manager._event(state, 'role_process', state['tasks'][tid], aid, observed={'process_state':'role_process_started','independent_model_spawned':command is None,'argv':argv}), tid)
            with model_slot(manager, tid, aid, spec.get('timeout', 300)):
                result = managed_command(manager, tid, argv, manager.root, timeout=spec.get('timeout', 300))
            if task.get('role_contract', {}).get('ui_applicability'):
                manager._mutate('role_process', lambda state: manager._event(state, 'role_process', state['tasks'][tid], aid, observed={'process_state':'role_process_finished','exit_code':result.returncode}), tid)
            (directory / 'stdout.log').write_text(result.stdout)
            (directory / 'stderr.log').write_text(result.stderr)
            if result.returncode:
                raise ValueError('independent review process failed: ' + str(result.returncode))
            response = json.loads(result.stdout if command else result_path.read_text())
            documents = response.get('evidence_documents', {})
            if not isinstance(documents, dict) or any(not isinstance(k, str) or not k or Path(k).name != k or not isinstance(v, str) or not v.strip() for k, v in documents.items()):
                raise ValueError('review evidence documents require safe names and nonempty text')
            mapping = {}
            for name, content in documents.items():
                evidence = directory / ('evidence-' + name)
                evidence.write_text(content)
                mapping['@' + name] = str(evidence.relative_to(manager.root))
            for criterion in response['results']:
                if criterion.get('evidence') in mapping:
                    criterion['evidence'] = mapping[criterion['evidence']]
            (directory / 'response.json').write_text(json.dumps(response, ensure_ascii=False, indent=2))
            return manager.review(tid, aid, response['results'], response['summary'], design_checks=response.get('design_checks'))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            manager.fail(tid, aid, 'orchestrator review failed: ' + str(error))
            raise


def _recover(manager, tid, resume, worker=None):
    from harness.recovery import recover_tasks, resume_task, inspect_execution
    task = _read(manager)['tasks'][tid]
    active = [r for r in task.get('executions', []) if not r.get('ended_at')]
    receipt = task.get('recovery', {})
    if _decision_resume(manager, task):
        return None  # existing claim() checks the released owner receipt again
    if len(active) == 1 and active[0].get('required_question_wait') and task['state'] == 'BLOCKED':
        if not resume:
            return _result('WAITING_FOR_INPUT', tid, ['answered checkpoint requires explicit resume'])
        state = _read(manager)
        ids = active[0].get('required_question_waits', [active[0]['required_question_wait']])
        from harness.decisions import validate_answer
        for qid in ids:
            question = state.get('required_questions', {}).get(qid)
            if not question or not validate_answer(state, qid, manager.root):
                return _result('WAITING_FOR_INPUT', tid, ['checkpoint answer missing or invalid'])
        path = manager.directory / ('orchestration-decision-' + str(uuid.uuid4()) + '.json')
        path.write_text(json.dumps({'source': 'VALIDATED_NATIVE_ANSWERS', 'questions': [state['required_questions'][q] for q in ids]}, ensure_ascii=False, indent=2))
        manager.resume(tid, active[0]['agent_run_id'], str(path.relative_to(manager.root)))
        return _result('CONTINUE', tid)
    if len(active) == 1 and task['state'] == 'BLOCKED' and manager._valid_artifact(active[0].get('checkpoint', {})):
        checkpoint = active[0]['checkpoint']
        data = json.loads((manager.root / checkpoint['snapshot']).read_text())
        if isinstance(data, dict) and data.get('questions'):
            # Roles.accept(waiting) is an intentional input checkpoint, not a
            # dead process. Keep its existing resume/decision-file contract;
            # never manufacture an answer or HUMAN_APPROVAL from this request.
            return _result('WAITING_FOR_INPUT', tid, ['role requested input; supply decision through existing Tasks.resume then explicitly resume controller'],
                           questions=data['questions'], agent_run_id=active[0]['agent_run_id'], checkpoint=checkpoint,
                           resume_api='Tasks.resume(task_id, agent_run_id, decision_file)')
    if active:
        ownership = inspect_execution(manager, task, active[0])
        if ownership['state'] != 'INTERRUPTED':
            return _result('BLOCKED', tid, [ownership['reason']], recovery=ownership)
        if not resume:
            return _result('RECOVERABLE', tid, ['confirmed interrupted execution requires explicit recovery'], recovery=ownership)
        related = [c['task_id'] for c in task.get('development_delegation', {}).get('children', [])]
        recover_tasks(manager, related + [tid])
        children = _read(manager)['tasks']
        if any(children[c].get('recovery', {}).get('state') in {'RECOVERABLE', 'RECHECK_REQUIRED', 'MANUAL_INTERVENTION_REQUIRED'} and children[c]['state'] != 'DONE' for c in related):
            return _result('BLOCKED', tid, ['child checkpoint requires explicit existing child recovery/admission before parent resume'])
        task = _read(manager)['tasks'][tid]
        receipt = task.get('recovery', {})
        if any(not r.get('ended_at') for r in task['executions']):
            return _result('BLOCKED', tid, ['execution still active or ownership uncertain'])
    if receipt.get('state') in {'RECHECK_REQUIRED', 'MANUAL_INTERVENTION_REQUIRED'}:
        return _result(receipt['state'] if receipt['state'] == 'RECHECK_REQUIRED' else 'BLOCKED', tid, ['existing recovery requires recheck/manual intervention'])
    if receipt.get('state') == 'RECOVERABLE' and not receipt.get('resumed_execution'):
        if not resume:
            return _result('RECOVERABLE', tid, ['explicit resume required'])
        resume_task(manager, tid, worker=worker)
        return _result('CONTINUE', tid)
    return None


def _stage_action(manager, item, stage, resume):
    flow = _read(manager)['stage_workflows'][item['feature_id']]
    tid = flow['stages'][stage]['task_id']
    task = _read(manager)['tasks'][tid]
    spec = item['value']['stages'][stage]
    waiting = _waiting(manager, tid)
    if waiting:
        return waiting
    recovered = _recover(manager, tid, resume, spec.get('worker'))
    if recovered:
        return recovered
    assessment = next(s for s in assess(manager.root, _read(manager), item['feature_id'])['stages'] if s['stage'] == stage)
    if assessment['status'] == 'PASS':
        return None
    if assessment['status'] == 'HUMAN_APPROVAL_REQUIRED':
        return _result('WAITING_FOR_APPROVAL', stage, assessment['reasons'], question_id=flow['stages'][stage].get('human_approval_question_id'))
    if assessment['status'] in {'RECHECK_REQUIRED', 'BLOCKED_RETRY_LIMIT', 'UNKNOWN'} or task['state'] == 'DONE':
        return _result('RECHECK_REQUIRED' if assessment['status'] != 'BLOCKED_RETRY_LIMIT' else 'BLOCKED', stage, assessment['reasons'])
    if task['state'] == 'IN_REVIEW':
        _record(manager, item['feature_id'], 'action', stage=stage, action='role_review', task_id=tid)
        _review(manager, tid, item['value']['reviewer'])
        return _result('CONTINUE', stage)
    if task['state'] not in {'TODO', 'READY', 'BLOCKED'} and not _decision_resume(manager, task):
        return _result('BLOCKED', stage, ['unsupported stage state ' + task['state']])
    released = _question_released(task)
    if task['state'] == 'BLOCKED' and not released and not _normal_retry(item, task):
        return _result('BLOCKED', stage, [task.get('blocked_reason') or 'explicit repair/recovery required'])
    if task['state'] == 'TODO' or released:
        upstream = [_read(manager)['tasks'][flow['stages'][s]['task_id']] for s in STAGES[:STAGES.index(stage)]]
        paths = list(dict.fromkeys([a['path'] for a in task['inputs']] + [a['path'] for t in upstream for a in t['outputs']]))
        for previous in upstream:
            paths.extend(c['evidence']['path'] for c in previous.get('design_status', {}).get('checks', {}).values() if c.get('evidence'))
        paths = list(dict.fromkeys(paths))
        versions = {t['role']: t.get('delivery', {}).get('version') for t in upstream}
        Roles(manager.root, manager.run_id).rebase(tid, paths, planning_version=versions.get('planning'), design_version=versions.get('design'))
        manager.bind_stage_inputs(tid, paths, 'orchestrator binds current reviewed upstream outputs')
        for parent in upstream[-1:] if task['state'] == 'TODO' else []:
            if parent['task_id'] in task.get('dependencies', []):
                manager.handoff(parent['task_id'], tid)
    _record(manager, item['feature_id'], 'action', stage=stage, action='role_execute', task_id=tid)
    Roles(manager.root, manager.run_id).execute(tid, task['role'], worker=spec.get('worker'), timeout=spec.get('timeout', 300))
    return _result('CONTINUE', stage)


def _next(manager, item, resume):
    manager.read()  # one authoritative refresh per controller action
    item = _read(manager)["orchestrations"][item["feature_id"]]
    invalid = _validate(manager, item)
    if invalid:
        return invalid
    for stage in STAGES:
        result = _stage_action(manager, item, stage, resume)
        if result:
            return result
    from harness.implementation_bridge import prepare, execute
    from harness.recovery import done_reasons
    plan_tid = _read(manager)['stage_workflows'][item['feature_id']]['stages']['development_plan']['task_id']
    tid = prepare(manager, plan_tid)
    waiting = _waiting(manager, tid)
    if waiting:
        return waiting
    recovered = _recover(manager, tid, resume)
    if recovered:
        return recovered
    task = _read(manager)['tasks'][tid]
    for planned in [tid] + [c['task_id'] for c in task.get('development_delegation', {}).get('children', [])]:
        _attach_plan(manager, item, planned)
    children = [c['task_id'] for c in task.get('development_delegation', {}).get('children', [])]
    expected = {t: _implementation_contract(_read(manager)['tasks'][t]) for t in [tid] + children}
    connected = [e for e in _read(manager)['orchestrations'][item['feature_id']]['events'] if e['event'] == 'implementation_connected']
    if not connected:
        _record(manager, item['feature_id'], 'implementation_connected', tasks=expected)
    elif connected[-1]['tasks'] != expected:
        return _result('RECHECK_REQUIRED', 'implementation', ['approved implementation criteria, scope, baseline or verification command changed'])
    # Native Development already requires a current independent comparison with
    # original requirements. Reuse its lineage gate instead of bypassing it.
    from harness.requirement_lineage import configure_qa, require_review
    qreq = item['value']['requirements_qa_task_id']
    if qreq not in _read(manager)['tasks']:
        configure_qa(manager.root, manager.run_id, qreq, tid)
        _attach_plan(manager, item, qreq)
        configured = _read(manager)['tasks'][qreq]
        _record(manager, item['feature_id'], 'requirements_qa_configured', task_id=qreq, config=_qa_contract(configured['qa_config']), task_contract=_task_contract(configured))
        return _result('CONTINUE', 'requirements_qa')
    reqtask = _read(manager)['tasks'][qreq]
    reqrecords = [e for e in _read(manager)['orchestrations'][item['feature_id']]['events'] if e['event'] == 'requirements_qa_configured']
    if not reqrecords or _qa_contract(reqtask.get('qa_config', {})) != reqrecords[-1]['config'] or _task_contract(reqtask) != reqrecords[-1]['task_contract']:
        return _result('RECHECK_REQUIRED', 'requirements_qa', ['requirements QA scope changed or belongs to another contract'])
    wait = _waiting(manager, qreq) or _recover(manager, qreq, resume)
    if wait:
        return wait
    if reqtask['state'] != 'DONE':
        if reqtask['state'] == 'BLOCKED' and not _question_released(reqtask):
            return _result('BLOCKED', 'requirements_qa', [reqtask.get('blocked_reason') or 'requirements review failed'])
        _record(manager, item['feature_id'], 'action', stage='requirements_qa', action='qa_execute', task_id=qreq)
        Roles(manager.root, manager.run_id).execute(qreq, 'verification')
        return _result('CONTINUE', 'requirements_qa')
    require_review(manager, _read(manager)['tasks'][tid])
    repaired = bool(task.get('execution_completion')) and _current_repair(manager, item, task)
    if task['state'] != 'DONE' and not repaired:
        if task['state'] == 'BLOCKED' and not _question_released(task) and not _normal_retry(item, task):
            return _result('BLOCKED', 'implementation', [task.get('blocked_reason') or 'explicit repair required'])
        _record(manager, item['feature_id'], 'action', stage='implementation', action='implementation_bridge', task_id=tid)
        execute(manager, plan_tid)
        return _result('CONTINUE', 'implementation')
    reasons = done_reasons(manager, task)
    if reasons and not repaired:
        return _result('RECHECK_REQUIRED', 'implementation', reasons)
    from harness.qa import QA
    qa_spec = copy.deepcopy(item['value']['qa'])
    qid = qa_spec.pop('task_id')
    current = _read(manager)['tasks'].get(qid)
    if not current:
        QA(manager.root, manager.run_id).configure(qid, target_task_id=tid, **qa_spec)
        _attach_plan(manager, item, qid)
        if qa_spec.get('repair_task_id'):
            _attach_plan(manager, item, qa_spec['repair_task_id'])
        configured = _read(manager)['tasks'][qid]
        repairs = {}
        if qa_spec.get('repair_task_id'):
            repair = _read(manager)['tasks'][qa_spec['repair_task_id']]
            for rid in [repair['task_id']] + [c['task_id'] for c in repair.get('development_delegation', {}).get('children', [])]:
                _attach_plan(manager, item, rid)
                repairs[rid] = _implementation_contract(_read(manager)['tasks'][rid])
        _record(manager, item['feature_id'], 'qa_configured', task_id=qid, config=configured['qa_config'], task_contract=_task_contract(configured), repair_contracts=repairs)
        return _result('CONTINUE', 'qa')
    prior = [e for e in _read(manager)['orchestrations'][item['feature_id']]['events'] if e['event'] == 'qa_configured']
    if not prior or current.get('qa_config', {}).get('target_task_id') != tid or _qa_contract(current.get('qa_config', {})) != _qa_contract(prior[-1]['config']) or _task_contract(current) != prior[-1].get('task_contract'):
        return _result('RECHECK_REQUIRED', 'qa', ['QA contract not configured by this orchestration or changed'])
    config = current['qa_config']
    if not config.get('attempts') and any(config.get(k) != prior[-1]['config'].get(k) for k in ('target_manifest', 'target_baseline', 'retest_bases')):
        return _result('RECHECK_REQUIRED', 'qa', ['QA target changed before an observed execution'])
    waiting = _waiting(manager, qid)
    if waiting:
        return waiting
    recovered = _recover(manager, qid, resume)
    if recovered:
        return recovered
    if current['state'] != 'DONE':
        if current['state'] == 'BLOCKED' and not _question_released(current):
            return _result('BLOCKED', 'qa', [current.get('blocked_reason') or 'QA failed; approved repair required'])
        _record(manager, item['feature_id'], 'action', stage='qa', action='qa_execute', task_id=qid)
        Roles(manager.root, manager.run_id).execute(qid, 'verification')
        return _result('CONTINUE', 'qa')
    reasons = done_reasons(manager, current)
    if reasons:
        return _result('RECHECK_REQUIRED', 'qa', reasons)
    if not current.get('qa_observation_completion'):
        return _result('BLOCKED', 'qa', ['independent QA observation receipt missing'])
    if item['value']['completion'] == 'qa':
        return _result('COMPLETED', 'qa', completion_scope='QA_OBSERVATION_ONLY', official_certification=False)
    from harness.protected_verification import assess as certification
    proof = certification(manager.root, _read(manager)['tasks'][tid])
    if proof.get('result') != 'PASS' or proof.get('approval_type') != 'OFFICIAL_CERTIFICATION':
        return _result('BLOCKED', 'official', ['current protected issuer evidence required'], certification=proof)
    # Existing official Tasks.review gates remain authoritative. Do not mint
    # evidence, change purpose, or treat ROLE_REVIEW/QA/legacy DONE as authority.
    if not _read(manager)['tasks'][tid].get('reviews', [])[-1].get('protected_verification'):
        _record(manager, item['feature_id'], 'action', stage='official', action='official_review', task_id=tid)
        _review(manager, tid, item['value']['reviewer'])
        return _result('CONTINUE', 'official')
    return _result('COMPLETED', 'official', completion_scope='OFFICIAL_CERTIFICATION', official_certification=True, certification=proof)


def status(manager, feature_id):
    manager.read()
    item = _read(manager).get('orchestrations', {}).get(feature_id)
    if not item:
        return _result('BLOCKED', reasons=['orchestration contract not registered'])
    invalid = _validate(manager, item)
    if invalid:
        return invalid
    last = copy.deepcopy(item.get('last_result'))
    if last and last['status'] == 'COMPLETED':
        # Status is an observation, never an unchecked historical PASS cache.
        readiness = assess(manager.root, _read(manager), feature_id)
        if not all(s['status'] == 'PASS' for s in readiness['stages']):
            return _result('RECHECK_REQUIRED', reasons=['completed stage readiness changed'])
        from harness.recovery import done_reasons
        state = _read(manager)
        qid = item['value']['qa']['task_id']
        qa = state['tasks'].get(qid)
        target_id = qa.get('qa_config', {}).get('target_task_id') if qa else None
        if not qa or qa['state'] != 'DONE' or not target_id or done_reasons(manager, qa) or (done_reasons(manager, state['tasks'][target_id]) and not _current_repair(manager, item, state['tasks'][target_id])):
            return _result('RECHECK_REQUIRED', reasons=['completed code/QA evidence no longer current'])
        if item['value']['completion'] == 'official':
            from harness.protected_verification import assess as certification
            if certification(manager.root, state['tasks'][target_id]).get('result') != 'PASS':
                return _result('RECHECK_REQUIRED', reasons=['official certification no longer current'])
    return last or _result('CONTINUE')


def _run(manager, feature_id, *, resume=False, max_actions=40):
    """Foreground loop, bounded actions, explicit resume after interruptions only."""
    if type(max_actions) is not int or not 1 <= max_actions <= 200:
        raise ValueError('max_actions must be 1..200')
    item = _read(manager).get('orchestrations', {}).get(feature_id)
    if not item:
        return _result('BLOCKED', reasons=['orchestration contract not registered'])
    try:
        with TaskLease(manager.root, 'orchestration:' + feature_id) as lease:
            prior = item['attempts'][-1] if item['attempts'] else None
            if prior and not prior.get('ended_at'):
                live = inspect_owner(prior.get('owner'))
                if live['status'] != 'DEAD':
                    return _result('BLOCKED', reasons=['previous controller ownership unknown/live'])
                if not resume:
                    return _result('RECOVERABLE', reasons=['previous controller interrupted; explicit resume required'])
            lease.bind(str(uuid.uuid4()))
            _record(manager, feature_id, 'controller_started', owner=lease.record()['owner'], controller_id=lease.record()['token'])
            result = _result('CONTINUE')
            try:
                for _ in range(max_actions):
                    result = _next(manager, _read(manager)['orchestrations'][feature_id], resume)
                    if result['status'] != 'CONTINUE':
                        break
                else:
                    result = _result('BLOCKED', reasons=['action budget exhausted; inspect transition history'])
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
                result = _result('BLOCKED', reasons=[type(error).__name__ + ': ' + str(error)])
            _record(manager, feature_id, 'controller_stopped', result=result)
            return result
    except (BlockingIOError, RuntimeError) as error:
        return _result('BLOCKED', reasons=['feature ownership unavailable: ' + str(error)])


def run(manager, feature_id, *, resume=False, max_actions=40):
    from harness.sequential import read_state
    # Reading the budget is not authorization. _run still validates exact
    # frozen contract bytes and every native gate before progressing.
    item = read_state(manager.root).get('orchestrations', {}).get(feature_id)
    if not item:
        return _result('BLOCKED', reasons=['orchestration contract not registered'])
    try:
        with _lock_budget(manager.root, item['value'].get('lock_wait_timeout', 300)):
            return _run(manager, feature_id, resume=resume, max_actions=max_actions)
    except (RuntimeError, ValueError) as error:
        return _result('BLOCKED', reasons=[str(error)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--feature-id', required=True)
    parser.add_argument('operation', choices=['configure', 'run', 'resume', 'status'])
    parser.add_argument('--contract')
    args = parser.parse_args(argv)
    manager = Tasks(args.root, args.run_id)
    if args.operation == 'configure':
        if not args.contract:
            parser.error('--contract required')
        value = configure(manager, args.feature_id, args.contract)
    elif args.operation == 'status':
        value = status(manager, args.feature_id)
    else:
        value = run(manager, args.feature_id, resume=args.operation == 'resume')
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value.get('status') in {'CONTINUE', 'COMPLETED'} or args.operation == 'configure' else 2


if __name__ == '__main__':
    raise SystemExit(main())
