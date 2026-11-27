"""Explicit command-log continuation; original task/attempt/native authority stays fixed."""
import copy
from pathlib import Path
import uuid

from harness.decisions import _task_basis, digest, native_records


def _scope(root, state, task):
    return {'task': _task_basis(state, Path(root), [task['task_id']]),
            'tracking': copy.deepcopy(task.get('development_tracking')),
            'work_plan': copy.deepcopy(task.get('work_plan')),
            'work_plan_run_id': task.get('work_plan_run_id'),
            'stage_contract': copy.deepcopy(task.get('stage_contract'))}


def _events(root):
    from harness.logging import Logger
    return Logger(root).read()


class CommandRunFinished(ValueError):
    """The selected top-level command log has ended."""


def require_open(root, run_id, *, task=None, records=None):
    records = _events(root) if records is None else records
    if not any(event['run_id'] == run_id and event['event_type'] == 'run_finished'
               for event in records):
        return
    message = 'run already finished'
    if task and task.get('state') == 'IN_PROGRESS':
        works = [run for run in task.get('executions', [])
                 if run.get('kind') == 'work' and not run.get('ended_at')]
        if len(works) == 1:
            work = works[0]
            links = work.get('command_run_continuations', [])
            latest = links[-1]['command_run_id'] if links else work['run_id']
            message += f'; active execution run is {work["run_id"]}'
            if run_id == latest:
                message += ('; use task --operation continue-command-run with the execution run as --run-id '
                            'and the finished run as previous_run_id')
            else:
                message += f'; inspect task state for the latest command run ({latest})'
    raise CommandRunFinished(message)


def _missing_initial_log(records, previous, execution, task_id):
    return previous == execution["run_id"] and not any(
        event.get('run_id') == previous
        and (event.get('event_type') in {'run_started', 'run_finished'}
             or (event.get('event_type', '').startswith('command_')
                 and event.get('task_id') == task_id
                 and event.get('agent_run_id') == execution['agent_run_id']))
        for event in records
    )


def linked(root, state, task, execution, command_run_id, *, historical=False, records=None, include_previous=False):
    """A new log run grants command logging only, never task lifecycle ownership."""
    links = execution.get('command_run_continuations', [])
    if command_run_id == execution['run_id']:
        return historical or include_previous or not links
    if not isinstance(links, list) or not links:
        return False
    candidates = links if historical or include_previous else links[-1:]
    if records is None:
        records = _events(root)
    for link in candidates:
        if (link.get('command_run_id') != command_run_id
                or link.get('execution_run_id') != execution['run_id']
                or link.get('task_id') != task['task_id']
                or link.get('agent_run_id') != execution['agent_run_id']
                or link.get('attempt_id') != execution.get('attempt_id')):
            continue
        proof_index = next((i for i, e in enumerate(records) if e.get('event_id') == link.get('event_id')), None)
        proof = records[proof_index] if proof_index is not None else None
        closed = next((e for e in records if e.get('event_id') == link.get('previous_finished_event_id')), None)
        if (not proof or proof.get('event_type') != 'command_run_continued'
                or proof.get('run_id') != command_run_id
                or proof.get('task_id') != task['task_id']
                or proof.get('agent_run_id') != execution['agent_run_id']
                or proof.get('observed') != {k:v for k,v in link.items() if k != 'event_id'}):
            continue
        previous = link.get('previous_run_id')
        if link.get('previous_log_missing') is True:
            if (link is not links[0] or link.get('previous_finished_event_id') is not None
                    or not _missing_initial_log(records[:proof_index], previous, execution, task['task_id'])):
                continue
        elif (not closed or closed.get('event_type') != 'run_finished'
              or closed.get('run_id') != previous):
            continue
        if not historical:
            bindings = state.get('execution_policy_bindings', {})
            if (bindings.get(execution['run_id']) != link.get('root_binding')
                    or bindings.get(command_run_id) != link.get('root_binding')
                    or digest(_scope(root, state, task)) != link.get('scope_sha256')):
                return False
        return True
    return False


def execution_run(root, state, task_id, agent_run_id, attempt_id, command_run_id):
    task = state.get('tasks', {}).get(task_id)
    matches = [r for r in task.get('executions', []) if r['agent_run_id'] == agent_run_id] if task else []
    if (len(matches) != 1 or matches[0].get('attempt_id') != attempt_id
            or not linked(root, state, task, matches[0], command_run_id)):
        raise ValueError('command run must explicitly link the original execution and attempt')
    return matches[0]['run_id']


def continue_run(manager, task_id, agent_run_id, previous_run_id, reason, evidence):
    if not isinstance(reason, str) or not reason.strip() or not isinstance(previous_run_id, str):
        raise ValueError('explicit predecessor command run and continuation reason required')
    from harness.process_ownership import exclusive_slot, inspect_child
    # No new command context may be created under a concurrent executor.
    with exclusive_slot(manager.root, task_id):
        def operation(state):
            from harness.execution_policy import gate
            from harness.recovery import progress_gate, _record
            progress_gate(manager, task_id, 'dispatch')
            gate(manager, state, task_id, 'dispatch')
            task = state['tasks'][task_id]
            run = manager._active(task, agent_run_id, 'work')
            if task['state'] != 'IN_PROGRESS' or run['run_id'] != manager.run_id:
                raise ValueError('continuation requires the original active unblocked execution run')
            from harness.development_tracking import ensure
            ensure(manager, state, task, 'dispatch', run)
            from harness.stage_readiness import gate as stage_gate
            reason_blocked = stage_gate(manager, state, task)
            if reason_blocked:
                raise ValueError(reason_blocked)
            binding = state.get('execution_policy_bindings', {}).get(manager.run_id)
            if not binding:
                raise ValueError('continuation requires the original immutable native root binding')
            native_records(binding['root_session_path'], binding['root_session_id'])
            if run.get('execution_contract') and any(run['execution_contract'].get(k) != binding[k]
                    for k in ('root_session_path', 'root_session_id')):
                raise ValueError('execution native root binding changed')
            if run.get('process_owner'):
                owner = _record(manager.root, run)
                if (not owner.get('closed') or not owner.get('released') or owner.get('spawn_pending')
                        or any(inspect_child(c)['status'] != 'DEAD' for c in owner.get('children', []))):
                    raise ValueError('unfinished executor requires explicit recovery before continuation')
            ref = manager.artifact(evidence)
            links = run.get('command_run_continuations', [])
            current = links[-1]['command_run_id'] if links else run['run_id']
            events = manager.logger.read()
            if links and not any(e['event_type']=='run_finished' and e['run_id']==current for e in events):
                last = links[-1]
                if (last['previous_run_id'] == previous_run_id and last['reason'] == reason
                        and last['evidence'] == ref and linked(manager.root,state,task,run,current)):
                    return copy.deepcopy(last)
                raise ValueError('an open command continuation already exists; do not duplicate it')
            if previous_run_id != current:
                raise ValueError('explicit predecessor must be the latest command run for this attempt')
            finished = [e for e in events if e['event_type']=='run_finished' and e['run_id']==previous_run_id]
            missing = not links and _missing_initial_log(events, previous_run_id, run, task_id)
            if not missing:
                start = manager.logger.run(previous_run_id, records=events)
                if len(finished) != 1 or start['work_type'] != task['work_type']:
                    raise ValueError('continuation requires one finished predecessor of the same work type')
            command_run = manager.logger.start(task['work_type'],task['role'],reason)
            link = {'version':1,'id':str(uuid.uuid4()),'execution_run_id':run['run_id'],
                    'command_run_id':command_run,'previous_run_id':previous_run_id,
                    'previous_finished_event_id':None if missing else finished[0]['event_id'],
                    'task_id':task_id,'agent_run_id':agent_run_id,'attempt_id':run['attempt_id'],
                    'root_binding':copy.deepcopy(binding),'scope_sha256':digest(_scope(manager.root,state,task)),
                    'reason':reason,'evidence':ref}
            if missing:
                link['previous_log_missing'] = True
            event = manager.logger.append('command_run_continued',command_run,task['work_type'],
                task_id=task_id,agent_run_id=agent_run_id,feature_id=task['feature_id'],observed=link)
            link['event_id'] = event['event_id']
            state['execution_policy_bindings'][command_run] = copy.deepcopy(binding)
            run.setdefault('command_run_continuations', []).append(link)
            return copy.deepcopy(link)
        return manager._mutate('continue_command_run',operation,task_id)
