"""One project process semaphore and per-run admission budget for all role adapters."""
import fcntl
import time
from contextlib import contextmanager
from harness import logging


def configure(manager,max_parallel=2,max_executions=20):
    if type(max_parallel) is not int or not 1<=max_parallel<=8:raise ValueError('runtime max_parallel must be 1..8')
    if type(max_executions) is not int or not 1<=max_executions<=1000:raise ValueError('runtime max_executions must be 1..1000')
    def op(state):
        if any(not r.get('ended_at') for t in state['tasks'].values() for r in t['executions']):raise ValueError('cannot change runtime limits while tasks are active')
        state['runtime_limits']={'max_parallel':max_parallel,'max_executions':max_executions}
        return state['runtime_limits']
    return manager._mutate('configure_runtime_limits',op)


@contextmanager
def model_slot(manager,task_id,agent_run_id,timeout=300):
    limits=manager.read().get('runtime_limits',{'max_parallel':2,'max_executions':20})
    directory=manager.directory/'process-slots';directory.mkdir(exist_ok=True)
    deadline=time.monotonic()+timeout;handle=None;slot=None
    while handle is None:
        for i in range(limits['max_parallel']):
            candidate=(directory/str(i)).open('a+')
            try:fcntl.flock(candidate,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:candidate.close();continue
            handle=candidate;slot=i;break
        if handle is None:
            if time.monotonic()>=deadline:raise TimeoutError('shared runtime slot wait timed out; no model spawned')
            time.sleep(0.05)
    index=None
    try:
        def admit(state):
            task=state['tasks'][task_id];run=next(r for r in task['executions'] if r['agent_run_id']==agent_run_id)
            if run.get('ended_at') or run.get('run_id')!=manager.run_id:raise ValueError('runtime admission requires active execution in this run')
            budget=state.setdefault('runtime_budgets',{}).setdefault(manager.run_id,{'admissions':[]})
            if len(budget['admissions'])>=limits['max_executions']:raise ValueError('total role-process execution budget exhausted')
            item={'agent_run_id':agent_run_id,'task_id':task_id,'slot':slot,'admitted_at':logging.now(),'released_at':None}
            budget['admissions'].append(item);run.setdefault('runtime_admissions',[]).append(dict(item))
            manager._event(state,'runtime_process_admitted',task,agent_run_id,observed={'slot':slot,'admission_count':len(budget['admissions']),'max_parallel':limits['max_parallel'],'max_executions':limits['max_executions'],'meaning':'process attempt admitted, not proof of model spawn'})
            return len(budget['admissions'])-1
        index=manager._mutate('runtime_admission',admit,task_id=task_id)
        yield {'slot':slot,'max_parallel':limits['max_parallel']}
    finally:
        if index is not None:
            def release(state):
                now=logging.now();state['runtime_budgets'][manager.run_id]['admissions'][index]['released_at']=now
                task=state['tasks'][task_id];run=next(r for r in task['executions'] if r['agent_run_id']==agent_run_id)
                if run.get('runtime_admissions'):run['runtime_admissions'][-1]['released_at']=now
                manager._event(state,'runtime_process_released',task,agent_run_id,observed={'slot':slot,'released_at':now})
            manager._mutate('runtime_release',release,task_id=task_id)
        handle.close()
