"""Whole execution Todo registration using native Tasks, IDs and evidence.
Only plan order/authority is stored here; no parallel status or progress ledger.
"""
import copy
import json
from pathlib import Path


PROCEDURES={'INVESTIGATE':'evidence_review','IMPLEMENT':'delivery_with_qa','VERIFY':'evidence_validation','CORRECT':'repair_and_recheck','REPORT':'source_based_report','HARNESS_IMPROVEMENT':'local_change_validation'}


def register(manager, request_type, procedure, goal, steps, scope_source, target_binding=None, reason='initial whole execution plan'):
    if request_type not in PROCEDURES or procedure!=PROCEDURES[request_type]:
        raise ValueError('select the documented request-type procedure; custom sequences are expressed by scoped steps')
    if not request_type or not procedure or not goal or not reason or not steps:
        raise ValueError('explicit request type, procedure, goal and whole steps required')
    basis=manager.artifact(scope_source)
    targets=[]
    if target_binding:
        from harness.requirement_lineage import compare
        lineage=compare(manager.root)
        if lineage['authority_issues']:raise ValueError('target scope approval is unconfirmed')
        req=next((r for r in lineage['requirements'] if r['id']==target_binding['requirement_id']),None)
        targets=req['expected'].get(target_binding['property']) if req else None
        if not isinstance(targets,list) or not targets or any(not isinstance(t,str) or not t for t in targets) or len(set(targets))!=len(targets):
            raise ValueError('targets must come from explicit authoritative requirement binding')
    def operation(state):
        if manager.run_id in state.get('execution_plans',{}):raise ValueError('plan already registered; revise with reason/evidence')
        if len({s.get('work_type','HARNESS_BUILD') for s in steps})!=1:raise ValueError('execution Todo cannot combine product and harness work')
        tids=[]
        for spec in steps:
            spec=copy.deepcopy(spec);template=spec.pop('target_criterion',None)
            if template:
                if not targets:raise ValueError('no approved target binding; never infer platforms')
                templates=template if isinstance(template,list) else [template]
                spec['criteria']=spec.get('criteria',[])+[dict(item,id=item['id'].format(target_index=i,target=t),description=item['description'].format(target_index=i,target=t),target=t) for i,t in enumerate(targets,1) for item in templates]
            manager._register_state(state,**spec);tids.append(spec['task_id'])
        plan={'request_type':request_type,'procedure':procedure,'goal':goal,'task_ids':tids,'scope_source':basis,'targets':targets,'target_binding':target_binding,'history':[{'reason':reason,'evidence':basis,'task_ids':tids[:]}]}
        state.setdefault('execution_plans',{})[manager.run_id]=plan
        manager._event(state,'execution_plan_registered',state['tasks'][tids[0]],observed=plan)
        return copy.deepcopy(plan)
    return manager._mutate('register_execution_plan',operation)


def attach_existing(manager, task_ids, request_type, procedure, goal, scope_source, reason):
    """Explicit migration: does not pretend an old plan was registered at start."""
    basis=manager.artifact(scope_source)
    def op(state):
        if manager.run_id in state.get('execution_plans',{}):raise ValueError('already registered')
        if not task_ids or len(set(task_ids))!=len(task_ids) or any(t not in state['tasks'] for t in task_ids):raise ValueError('explicit existing task references required')
        if len({(state['tasks'][tid]['project_id'],state['tasks'][tid]['work_type']) for tid in task_ids})!=1:raise ValueError('cannot combine project/work types')
        plan={'request_type':request_type,'procedure':procedure,'goal':goal,'task_ids':task_ids[:],'scope_source':basis,'targets':[],'history':[{'reason':reason,'evidence':basis,'posthoc':True,'task_ids':task_ids[:]}]}
        state.setdefault('execution_plans',{})[manager.run_id]=plan;manager._event(state,'execution_plan_connected',state['tasks'][task_ids[0]],observed=plan)
        return copy.deepcopy(plan)
    return manager._mutate('connect_execution_plan',op)


def revise(manager, added_steps, reason, evidence):
    if not reason:raise ValueError('plan change reason required')
    proof=manager.artifact(evidence)
    def op(state):
        plan=state['execution_plans'][manager.run_id]
        for spec in added_steps:
            manager._register_state(state,**spec);plan['task_ids'].append(spec['task_id'])
        plan['history'].append({'reason':reason,'evidence':proof,'task_ids':plan['task_ids'][:]})
        manager._event(state,'execution_plan_revised',state['tasks'][plan['task_ids'][0]],observed={'reason':reason,'evidence':proof,'task_ids':plan['task_ids'][:]})
        return copy.deepcopy(plan)
    return manager._mutate('revise_execution_plan',op)


def exclude(manager, task_id, reason, source_id, anchor):
    from harness.requirement_lineage import load,file_ref,NAME
    c=load(manager.root);source=next((s for s in c['sources'] if s['id']==source_id),{})
    if not reason or not anchor or source.get('kind')!='USER_ORIGINAL':raise ValueError('exclusion needs reason and original approval source/anchor; agent approval forbidden')
    proof=manager.artifact(source['path']);contract=file_ref(manager.root,NAME)
    def op(state):
        task=state['tasks'][task_id]
        if any(not e.get('ended_at') for e in task['executions']):raise ValueError('cannot exclude an active task')
        record={'status':'EXCLUDED','reason':reason,'authority':proof,'contract':contract,'source_id':source_id,'anchor':anchor,'criteria_ids':[c['id'] for c in task['criteria']]}
        task.setdefault('applicability_history',[]).append(copy.deepcopy(record));task['applicability']=record
        manager._event(state,'task_applicability_changed',task,observed=record)
        return record
    return manager._mutate('exclude_task',op,task_id)


def exclusion_valid(root,task):
    record=task.get('applicability',{})
    if record.get('status')!='EXCLUDED':return False
    try:
        from harness.requirement_lineage import load,file_ref,NAME
        c=load(root);s=next(s for s in c['sources'] if s['id']==record['source_id'])
        return s['kind']=='USER_ORIGINAL' and record['authority']['sha256']==s['sha256'] and record['contract']==file_ref(root,NAME) and record['criteria_ids']==[c['id'] for c in task['criteria']] and bool(record['reason'] and record['anchor'])
    except (ValueError,KeyError,OSError,StopIteration):return False


def main():
    import argparse
    from harness.tasks import Tasks
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--run-id',required=True);p.add_argument('--input',required=True);p.add_argument('action',choices=['register','revise','exclude'])
    a=p.parse_args();m=Tasks(a.root,a.run_id);args=json.loads(Path(a.input).read_text());result={'register':register,'revise':revise,'exclude':exclude}[a.action](m,**args);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()


def reopen(manager,task_id,reason,evidence):
    """Return the same Todo for authorized supplementation; preserve all attempts."""
    if not reason:raise ValueError('recheck reason required')
    proof=manager.artifact(evidence)
    def op(state):
        t=state['tasks'][task_id]
        if any(not r.get('ended_at') and (r.get('kind')!='work' or r.get('execution_mode')=='independent_process') for r in t['executions']):
            raise ValueError('finish/cancel independent process or active review before reopening')
        from harness.logging import now
        for r in t['executions']:
            if not r.get('ended_at'):
                r.update(ended_at=now(),outcome='RETURNED_FOR_SUPPLEMENT')
                manager._event(state,'agent_run_finished',t,r['agent_run_id'],observed={'ended_at':r['ended_at'],'outcome':'RETURNED_FOR_SUPPLEMENT'},summary={'reason':reason})
        old=t['state'];t.update(state='BLOCKED',blocked_reason=reason)
        t.setdefault('return_history',[]).append({'reason':reason,'evidence':proof,'previous_state':old})
        manager._event(state,'task_returned_for_supplement',t,observed={'from':old,'to':'BLOCKED','reason':reason,'evidence':proof})
    manager._mutate('reopen_execution_todo',op,task_id)


def require(manager,task_id):
    state=manager.read();plan=state.get('execution_plans',{}).get(manager.run_id)
    allowed=set((plan or {}).get('task_ids',[]));changed=True
    revisions={e.get('task_id'):e.get('observed',{}).get('from_task_id') for e in manager.logger.read() if e.get('event_type')=='stage_rework_created' and e.get('run_id')==manager.run_id}
    while changed:
        changed=False
        for tid,t in state['tasks'].items():
            parent=t.get('parent_task_id') or (t.get('delegation') or {}).get('parent_task_id') or revisions.get(tid) or t.get('qa_config',{}).get('target_task_id')
            repair=next((q.get('qa_config',{}).get('target_task_id') for q in state['tasks'].values() if q.get('qa_config',{}).get('repair_task_id')==tid),None)
            if tid not in allowed and (parent in allowed or repair in allowed):allowed.add(tid);changed=True
    if plan and task_id in allowed and state['tasks'][task_id].get('applicability',{}).get('status')!='EXCLUDED':return plan
    reason='전체 실행 Todo 미등록 또는 해당 작업 연결·적용 범위 미확인. 시작 전에 요청 유형·전체 단계·검증 조건을 등록해야 합니다.'
    def blocked(current):
        t=current['tasks'][task_id]
        if not any(not r.get('ended_at') for r in t['executions']):t.update(state='BLOCKED',blocked_reason=reason)
        manager._event(current,'execution_plan_required',t,observed={'reason':reason,'next_action':'register whole native execution plan; never invent a single-step plan'})
    manager._mutate('require_execution_plan',blocked,task_id)
    raise ValueError(reason)
