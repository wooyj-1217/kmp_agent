"""Explicit local recovery. No scheduler, approval inference or PASS restoration."""
import copy
import functools
import hashlib
import json
import os
from pathlib import Path
import uuid


def managed_child(function):
    @functools.wraps(function)
    def wrapped(self, parent, spec, *args, **kwargs):
        from harness.process_ownership import TaskLease
        with TaskLease(self.root, spec['task_id']):
            return function(self, parent, spec, *args, **kwargs)
    return wrapped


def _record(root, run):
    ref = run.get('process_owner') or {}
    path = Path(ref.get('receipt_path', '/'))
    if not path.is_absolute() or not path.resolve().is_relative_to(Path(root).resolve()/'.harness'):
        raise ValueError('managed owner receipt unavailable')
    record = json.loads(path.read_text())
    if record.get('token') != ref.get('token') or record.get('task_id') != run['task_id']:
        raise ValueError('owner receipt identity mismatch')
    if run['agent_run_id'] not in record.get('run_ids', [record.get('agent_run_id')]):
        raise ValueError('owner receipt execution mismatch')
    return record


def workspace_basis(manager, task):
    from harness import logging
    files = logging.snapshot(manager.root)
    modes = {p:(manager.root/p).stat().st_mode & 0o777 for p in files}
    # Logging snapshots intentionally omit links. Recovery must also pin their
    # names and raw targets, including dangling and directory links, without
    # following them outside the workspace. Keep the same generated exclusions.
    links = {}
    for path in manager.root.rglob('*'):
        relative = path.relative_to(manager.root)
        if (relative.parts[0] == 'verification'
                or relative.parts[:2] == ('.kmp-agent', 'releases')
                or any(p in ('.git', '.harness', '__pycache__') for p in relative.parts)
                or path.name == '.DS_Store'):
            continue
        if path.is_symlink():
            links[str(relative)] = os.readlink(path)
    result = {'files':files, 'modes':modes, 'symlinks':links}
    if task.get('development_tracking'):
        from harness.development_tracking import capture, baseline
        result['code'] = capture(manager, task)
        result['baseline'] = baseline(task)
    return result


def basis_identity(value):
    value = copy.deepcopy(value)
    if value.get('code'):
        value['code'] = {k:value['code'].get(k) for k in ('state_sha256','scope')}
    return value


def claim(manager, task_id, agent_run_id):
    from harness.process_ownership import current_lease
    lease = current_lease(manager.root, task_id)
    if lease is None:
        raise ValueError('managed process requires an exclusive task lease')
    def op(state):
        task = state['tasks'][task_id]
        run = next(r for r in task['executions'] if r['agent_run_id']==agent_run_id)
        if run.get('ended_at'):
            raise ValueError('cannot claim ended execution')
        previous = run.get('process_owner')
        if previous and previous.get('token') != lease.record()['token']:
            prior = _record(manager.root, run)
            if not (prior.get('released') and manager._valid_artifact(run.get('checkpoint', {}))
                    and run.get('decisions') and manager._valid_artifact(run['decisions'][-1])):
                raise ValueError('unfinished managed execution requires explicit recovery')
        lease.bind(agent_run_id)
        run['process_owner'] = lease.record()
        run.setdefault('recovery_start_basis', workspace_basis(manager, task))
        return copy.deepcopy(run['process_owner'])
    return manager._mutate('claim_managed_owner', op, task_id)


def owned_worker(function):
    @functools.wraps(function)
    def wrapped(manager, task_id, agent_run_id, *args, **kwargs):
        from harness.process_ownership import TaskLease, current_lease
        if current_lease(manager.root, task_id):
            claim(manager, task_id, agent_run_id)
            return function(manager, task_id, agent_run_id, *args, **kwargs)
        with TaskLease(manager.root, task_id):
            claim(manager, task_id, agent_run_id)
            return function(manager, task_id, agent_run_id, *args, **kwargs)
    return wrapped


def owned_command(function):
    @functools.wraps(function)
    def wrapped(manager, task_id, *args, **kwargs):
        from harness.process_ownership import TaskLease, current_lease
        manager.require_dispatch(task_id)
        state=manager.read()
        task=state['tasks'].get(task_id, {})
        active=[r for r in task.get('executions', []) if not r.get('ended_at')]
        if len(active)!=1 or task.get('state') not in {'IN_PROGRESS','IN_REVIEW'}:
            raise ValueError('managed command requires active unblocked execution')
        aid=active[0]['agent_run_id']
        if current_lease(manager.root,task_id):
            claim(manager,task_id,aid)
            return function(manager,task_id,*args,**kwargs)
        with TaskLease(manager.root,task_id):
            claim(manager,task_id,aid)
            return function(manager,task_id,*args,**kwargs)
    return wrapped


def cancel_spawn(manager, task_id, intent):
    from harness.process_ownership import current_lease
    current_lease(manager.root,task_id).cancel_intent(intent)


def spawn_intent(manager, task_id, agent_run_id):
    from harness.process_ownership import current_lease
    claim(manager, task_id, agent_run_id)
    return current_lease(manager.root, task_id).spawn_intent()


def register_process(manager, task_id, child, intent):
    from harness.process_ownership import current_lease
    lease = current_lease(manager.root, task_id)
    try:
        lease.register_child(child, intent)
    except BaseException:
        # Registration uncertainty never leaves the process launched by this
        # caller running silently. Its immediate Popen handle is still owned;
        # historical/PID-only recovery never uses this path.
        if type(child).__module__ == 'subprocess' and getattr(child, 'poll', lambda:None)() is None:
            from harness.execution_policy import stop_owned_group
            stop_owned_group(child, lambda process, timeout:process.communicate(timeout=timeout))
        raise
    if not lease.record().get('guardian'):
        lease.start_guardian()


def progress_gate(manager, task_id, action):
    if action not in {'ready','begin','begin_review','submit','review','resume','dispatch','dispatch_preflight','accept','handoff'}:
        return
    from harness.integration_transaction import unresolved
    if unresolved(manager.root):
        raise ValueError('unresolved integration transaction; explicit recovery required')


def done_reasons(manager, task):
    from harness.verification import current_reasons
    review = (task.get('reviews') or [{}])[-1]
    reasons = current_reasons(manager, task, review)
    if not review:
        reasons.append('completion review missing')
    if task.get('validation_status', {}).get(review.get('agent_run_id'), {}).get('state') == 'RECHECK_REQUIRED':
        reasons.append('recorded validation requires recheck')
    if task.get('development_tracking'):
        from harness.development_tracking import capture, baseline
        from harness.completion import execution_code_matches
        try:
            current = capture(manager, task)
            proof = review.get('development_evidence', {})
            if (current['state_sha256'] != proof.get('code_state', {}).get('state_sha256')
                    and not execution_code_matches(task, review, current)) or baseline(task) != proof.get('baseline'):
                reasons.append('code or baseline changed')
        except (OSError, ValueError, KeyError, TypeError):
            reasons.append('current code scope unknown')
    if task.get('qa_config'):
        from harness.qa import scoped_manifest
        config = task['qa_config']
        if ((config.get('attempts') or [{}])[-1].get('outcome') != 'PASS'
                or scoped_manifest(manager.root, config.get('manifest_scope', {'mode':'UNKNOWN'}), config.get('generated_paths', [])) != config.get('target_manifest')):
            reasons.append('QA observation stale or latest attempt not PASS')
    from harness.integration_transaction import unresolved
    if unresolved(manager.root):
        reasons.append('unresolved integration transaction')
    return sorted(set(reasons))


def inspect_execution(manager, task, run):
    from harness.process_ownership import inspect_owner, inspect_child, inspect_lease
    try:
        slot = inspect_lease(manager.root, task['task_id'])
        if slot.get('held'):
            return {'state':'ACTIVE', 'reason':'kernel task lease held; recovery forbidden'}
        record = _record(manager.root, run)
        owner = inspect_owner(record['owner'])
        if owner['status'] == 'ALIVE':
            return {'state':'ACTIVE', 'reason':'exact owner still alive'}
        if owner['status'] != 'DEAD' or record.get('spawn_pending'):
            return {'state':'MANUAL_INTERVENTION_REQUIRED', 'reason':'owner/spawn identity uncertain'}
        children = [inspect_child(c) for c in record.get('children', [])]
        if any(c['status'] != 'DEAD' for c in children):
            return {'state':'MANUAL_INTERVENTION_REQUIRED', 'reason':'registered child process group unresolved', 'children':children}
        return {'state':'INTERRUPTED', 'reason':'exact owner dead, lease free, registered children stopped', 'token':record['token']}
    except (OSError, ValueError, KeyError, TypeError):
        return {'state':'MANUAL_INTERVENTION_REQUIRED', 'reason':'managed ownership evidence unavailable'}


def _safe_basis(manager, state, task, run):
    if not all(manager._valid_artifact(a) and (manager.root/a['path']).is_file()
               and hashlib.sha256((manager.root/a['path']).read_bytes()).hexdigest()==a['sha256'] for a in task.get('inputs', [])):
        return None, 'input bytes or snapshots changed'
    before = run.get('recovery_start_basis')
    if not before:
        return None, 'start workspace basis unavailable'
    current = workspace_basis(manager, task)
    expected = copy.deepcopy(before)
    if task.get('development_delegation'):
        for child in task['development_delegation']['children']:
            completed = state['tasks'][child['task_id']]
            if completed['state'] == 'DONE' and not done_reasons(manager, completed):
                for name in completed.get('changed_files', []):
                    if name in current['files']:
                        expected['files'][name] = current['files'][name]
                        expected['modes'][name] = current['modes'][name]
                    else:
                        expected['files'].pop(name, None); expected['modes'].pop(name, None)
        # Reconstruct only already-reviewed child changes, never an unreviewed
        # partial integration. HEAD/index/declared baseline remain exact.
        if expected.get('code') and current.get('code'):
            old, new = expected['code'], current['code']
            if any(old.get(k)!=new.get(k) for k in ('head','index','scope')) or expected.get('baseline')!=current.get('baseline'):
                return None, 'coordinator Git/baseline changed'
            expected['code'] = copy.deepcopy(current['code'])
    if basis_identity(expected) != basis_identity(current):
        return None, 'workspace changed outside verified completed results'
    return current, None


def recover_tasks(manager, task_ids=None):
    from harness.process_ownership import exclusive_slot
    from harness.integration_transaction import recover as recover_integration, unresolved
    integrations = recover_integration(manager.root)
    results = []
    initial = manager.read()
    selected = task_ids or [t['task_id'] for t in initial['tasks'].values()
                            if any(r.get('run_id')==manager.run_id for r in t.get('executions', []))]
    for tid in selected:
        try:
            # No lock file age/PID-only inference. Recovery competes for the same
            # kernel slot used by adapters, then checks exact owner in state lock.
            with exclusive_slot(manager.root, tid):
                def op(state):
                    task = state['tasks'][tid]
                    active = [r for r in task['executions'] if not r.get('ended_at')]
                    if not active:
                        return {'task_id':tid, **copy.deepcopy(task.get('recovery', {'state':'RECHECK_REQUIRED','reason':'no interrupted active execution'}))}
                    run = active[0]
                    from harness.process_ownership import inspect_owner, inspect_child
                    try:
                        record = _record(manager.root, run)
                        owner = inspect_owner(record['owner'])
                        if owner['status']=='ALIVE':
                            return {'task_id':tid,'state':'ACTIVE','reason':'exact owner alive'}
                        if owner['status']!='DEAD' or record.get('spawn_pending') or any(inspect_child(c)['status']!='DEAD' for c in record.get('children', [])):
                            return {'task_id':tid,'state':'MANUAL_INTERVENTION_REQUIRED','reason':'ownership or orphan group unresolved'}
                    except (ValueError,OSError,KeyError,TypeError):
                        return {'task_id':tid,'state':'MANUAL_INTERVENTION_REQUIRED','reason':'owner receipt unavailable'}
                    current, reason = _safe_basis(manager, state, task, run)
                    if unresolved(manager.root):
                        current, reason = None, 'integration requires manual intervention'
                    if run['kind']!='work':
                        current, reason = None, 'interrupted review must be independently re-executed'
                    recovery_id = hashlib.sha256((tid+run['agent_run_id']+record['token']).encode()).hexdigest()
                    folder=manager.directory/'recovery'; folder.mkdir(exist_ok=True)
                    checkpoint=folder/(recovery_id+'.json')
                    payload={'version':1,'recovery_id':recovery_id,'task_id':tid,'interrupted_execution':run['agent_run_id'],
                             'current_basis':current,'reason':reason,'observed_at':manager.logger.execution_context(manager.run_id).get('observed_at','UNKNOWN'),
                             'prior_checkpoint':run.get('checkpoint'),'authority':'RECOVERY_CHECKPOINT_ONLY_NO_PASS'}
                    from harness.incremental_sync import atomic_json
                    atomic_json(checkpoint,payload)
                    receipt={'state':'RECOVERABLE' if current else 'RECHECK_REQUIRED','recovery_id':recovery_id,
                             'interrupted_execution':run['agent_run_id'],'reason':reason,
                             'checkpoint':manager.artifact(str(checkpoint.relative_to(manager.root))), 'automatic_execution':False}
                    from harness.logging import now
                    recovered_at=now()
                    run.update(ended_at=recovered_at, outcome='INTERRUPTED', recovery=copy.deepcopy(receipt),
                               end_time_semantics='RECOVERY_OBSERVATION_NOT_EXACT_PROCESS_DEATH')
                    for admission in run.get('runtime_admissions', []):
                        if not admission.get('released_at'):
                            admission.update(released_at=recovered_at, release_reason='CONFIRMED_OWNER_INTERRUPTION')
                    for admission in state.get('runtime_budgets', {}).get(run['run_id'], {}).get('admissions', []):
                        if admission.get('agent_run_id')==run['agent_run_id'] and not admission.get('released_at'):
                            admission.update(released_at=recovered_at, release_reason='CONFIRMED_OWNER_INTERRUPTION')
                    from harness.sequential import wait_end, finish
                    wait_end(manager, state, task, run, 'INTERRUPTED')
                    finish(manager, task, run)
                    task.update(state='BLOCKED',blocked_reason=reason or 'confirmed interruption; explicit safe resume required',recovery=receipt)
                    task.setdefault('recovery_history',[]).append(copy.deepcopy(receipt))
                    manager._event(state,'execution_interruption_recovered',task,run['agent_run_id'],observed=receipt)
                    return {'task_id':tid, **copy.deepcopy(receipt)}
                results.append(manager._mutate('recover_execution',op,tid))
        except (BlockingIOError, RuntimeError) as exc:
            results.append({'task_id':tid,'state':'ACTIVE','reason':str(exc)})
    return {'tasks':results,'integration_recovery':integrations,'automatic_execution':False}


def resume_task(manager, task_id, worker=None):
    from harness.process_ownership import TaskLease
    task = manager.read()['tasks'][task_id]
    if task['state']=='DONE':
        reasons=done_reasons(manager,task)
        return {'task_id':task_id,'cached':True,'state':'RECHECK_REQUIRED' if reasons else 'DONE','reasons':reasons,'official_completion_inferred':False}
    receipt=task.get('recovery') or {}
    if receipt.get('state')!='RECOVERABLE' or receipt.get('resume_dispatched'):
        raise ValueError('explicit recoverable checkpoint required; repeated admission is blocked')
    manager.require_dispatch(task_id, preflight=True)
    if not manager._valid_artifact(receipt['checkpoint']):
        raise ValueError('recovery checkpoint changed')
    saved=json.loads((manager.root/receipt['checkpoint']['snapshot']).read_text())
    if basis_identity(workspace_basis(manager,task))!=basis_identity(saved['current_basis']):
        raise ValueError('recovery basis changed; recheck required')
    with TaskLease(manager.root,task_id):
        def reserve(state):
            live=state['tasks'][task_id]
            if live.get('recovery')!=receipt or any(not r.get('ended_at') for r in live['executions']):
                raise ValueError('recovery admission changed or already active')
            if basis_identity(workspace_basis(manager,live))!=basis_identity(saved['current_basis']):
                raise ValueError('recovery workspace changed during admission')
            if len([r for r in live['executions'] if r['kind']=='work'])>=live['max_attempts']:
                raise ValueError('attempt budget exhausted')
            live['recovery']['resume_dispatched']=str(uuid.uuid4())
            manager._event(state,'recovery_resume_admitted',live,observed=copy.deepcopy(live['recovery']))
        manager._mutate('admit_recovery_resume',reserve,task_id)
        if task.get('development_delegation'):
            from harness.delegation import Development
            return Development(manager.root,manager.run_id).execute(task_id,worker=worker)
        if task.get('qa_config'):
            from harness.qa import QA
            return QA(manager.root,manager.run_id).execute(task_id,worker=worker)
        from harness.roles import Roles
        return Roles(manager.root,manager.run_id).execute(task_id,task['role'],worker=worker)
