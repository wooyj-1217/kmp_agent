"""Failure evidence and terminal cleanup in the existing task ledger/outbox.

Only runs explicitly owned by this invocation are closed. Unrelated active work
and past reports are preserved. Disk/process-loss recovery still needs storage.
"""
import copy
import json
import os
import uuid
from pathlib import Path
from harness import logging as log


def record_failure(manager,task_id,context,error):
    failure_id=str(uuid.uuid4())
    owned=context.get('owned_runs',[])
    record={'failure_id':failure_id,'task_id':task_id,'phase':context.get('phase','UNKNOWN'),
            'outcome':'BLOCKED','failure':type(error).__name__+': '+str(error),
            'recorded_at':log.now(),'owned_runs':owned,'qa_agent_run_id':context.get('agent_run_id'),
            'review_execution':'NOT_ESTABLISHED','execution_status':'UNCONFIRMED','criteria_result':'NOT_RUN'}
    report=None;storage_errors=[]
    # Separate from the failed attempt path: a copy/evidence/report failure must
    # not overwrite its input or hide already preserved worker/command records.
    path=manager.root/'.harness/qa/failures'/failure_id/'report.json'
    try:
        path.parent.mkdir(parents=True,mode=0o700)
        temporary=path.with_suffix('.tmp')
        with temporary.open('w') as out:
            os.fchmod(out.fileno(),0o600)
            out.write(json.dumps(log.redact(record),ensure_ascii=False,indent=2))
            out.flush();os.fsync(out.fileno())
        temporary.replace(path)
        report=manager.artifact(str(path.relative_to(manager.root)))
    except Exception as exc:
        storage_errors.append(type(exc).__name__+': '+str(exc))
    record['report']=report;record['storage_errors']=storage_errors
    def cleanup(state):
        task=state['tasks'].get(task_id)
        if not task:return
        from harness.execution_policy import pending
        if pending(state,task_id):
            record['execution_status']='WAITING_REQUIRED_ANSWER'
            record['recorded_runs']=[r['agent_run_id'] for r in task.get('executions',[]) if r['agent_run_id'] in owned]
            task.setdefault('qa_failures',[]).append(copy.deepcopy(record))
            manager._event(state,'qa_execution_waiting',task,context.get('agent_run_id',log.UNKNOWN),observed=record)
            return
        closed=[]
        for run in task.get('executions',[]):
            if run['agent_run_id'] not in owned:continue
            if not run.get('ended_at'):
                from harness.sequential import finish,wait_end
                try:
                    wait_end(manager,state,task,run,'CANCELLED');finish(manager,task,run)
                except Exception as exc:record['storage_errors'].append('lifecycle cleanup: '+type(exc).__name__+': '+str(exc))
                run.update(ended_at=record['recorded_at'],failure=record['failure'],failure_context={'category':'UNKNOWN','evidence':report,'phase':record['phase']})
                manager._event(state,'agent_run_failed',task,run['agent_run_id'],observed={'reason':record['failure'],'failure_evidence':report,'phase':record['phase']})
                closed.append(run['agent_run_id'])
            if run.get('kind')=='review':
                task.setdefault('validation_status',{})[run['agent_run_id']]={'state':'RECHECK_REQUIRED','reason':record['failure'],'failure_id':failure_id}
        # A rejected concurrent/redundant invocation must not interrupt another
        # owner, nor revoke an already completed execution it did not perform.
        active_foreign=any(not r.get('ended_at') and r['agent_run_id'] not in owned for r in task.get('executions',[]))
        if not active_foreign and (owned or context.get('owns_result') or task['state'] in {'TODO','READY'}):
            previous=task['state'];task.update(state='BLOCKED',blocked_reason=record['failure'])
            manager._event(state,'task_state_changed',task,context.get('agent_run_id',log.UNKNOWN),observed={'from':previous,'to':'BLOCKED','reason':record['failure']})
        created=[r for r in task.get('executions',[]) if r['agent_run_id'] in owned]
        record['recorded_runs']=[r['agent_run_id'] for r in created]
        record['execution_status']='RECORDED_ENDED' if created and all(r.get('ended_at') for r in created) else 'NOT_STARTED' if not created else 'UNCONFIRMED'
        if any(r['agent_run_id']==context.get('agent_run_id') and r.get('kind')=='work' for r in created) and task.get('qa_config'):
            attempts=task['qa_config']['attempts'];attempt=next((a for a in attempts if a['agent_run_id']==context['agent_run_id']),None)
            if attempt:
                attempt.setdefault('prior_outcome',attempt['outcome']);attempt.update(outcome='BLOCKED',failure=copy.deepcopy(record))
            else:attempts.append({'agent_run_id':context['agent_run_id'],'outcome':'BLOCKED','report':report,'finding_ids':[],'repair':'NOT_RUN','failure':copy.deepcopy(record)})
        task.setdefault('qa_failures',[]).append(copy.deepcopy(record))
        manager._event(state,'qa_execution_failed',task,context.get('agent_run_id',log.UNKNOWN),observed={**record,'closed_runs':closed})
    manager._mutate('qa_failure_cleanup',cleanup,task_id)
    return {'outcome':'BLOCKED','agent_run_id':context.get('agent_run_id'),'report':report,'failure':record,'model_executed':'NOT_ESTABLISHED'}
