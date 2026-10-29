"""Project-wide summary, separate from current-execution CMD Todo projection."""
from collections import defaultdict


def summarize(root,tasks,events,scopes,project_id=None,plans=None):
    from harness.dashboard import task_view
    from harness.dashboard_live import activity_view
    groups=defaultdict(list)
    for t in tasks.values():
        if project_id and t.get('project_id')!=project_id:continue
        groups[(t.get('project_id','UNKNOWN'),t.get('work_type','UNKNOWN'),t.get('feature_id','UNKNOWN'))].append(t)
    work=[]
    superseded={e.get('observed',{}).get('from_task_id') for e in events if e.get('event_type')=='stage_rework_created'}
    for (project,kind,feature),raw in groups.items():
        scope={'tasks':{t['task_id']:{} for t in raw},'agent_run_ids':[r['agent_run_id'] for t in raw for r in t.get('executions',[])]}
        rows=[]
        for t in raw:
            view=task_view(root,t,scope,tasks);activity=activity_view(t,scope,events)
            # Task/QA evidence is not completion of a whole project stage.
            label='재검증 필요' if view['verdict']=='RECHECK_REQUIRED' else '차단' if t['state']=='BLOCKED' or view['verdict']=='FAIL' else '진행 관측' if activity['kind']=='observed' else '검토 통과' if view['verdict']=='PASS' else '완료 보고 · 검증 미확인' if t['state']=='DONE' else '검토 대기' if t['state']=='IN_REVIEW' else '대기'
            from harness.execution_plan import exclusion_valid
            if t.get('applicability',{}).get('status')=='EXCLUDED':label='적용 제외' if exclusion_valid(root,t) else '적용 제외 승인 재확인'
            if t['task_id'] in superseded:label='보완 이전 기록'
            rows.append({'detail':dict(view,activity=activity),'task_id':t['task_id'],'name':t['title'],'role':activity['task_role_label'],'phase':('verification' if t.get('qa_config') else t.get('pipeline_stage') or activity.get('phase') or '미분류'),'status':label,'reason':t.get('blocked_reason'),'qa':t.get('qa_config',{}).get('stage'),'handoffs':[{'target_task_id':h.get('to_task_id'),'target':tasks.get(h.get('to_task_id'),{}).get('title','대상 미확인')} for h in t.get('handoffs',[])],'returns':t.get('return_history',[])})
        phases=[]
        for phase in ['planning','design','development','verification','report','미분류']:
            items=[r for r in rows if r['phase']==phase]
            phases.append({'phase':phase,'tasks':items,'summary':' · '.join(f'{s} {sum(r["status"]==s for r in items)}건' for s in dict.fromkeys(r['status'] for r in items)) or '연결된 작업 없음','completion':'PROJECT_STAGE_COMPLETION_NOT_ESTABLISHED'})
        goals=[p['goal'] for p in (plans or {}).values() if any(t['task_id'] in p['task_ids'] for t in raw)]
        work.append({'name':' / '.join(dict.fromkeys(goals)) if goals else raw[0]['title']+' 관련 작업','project_id':project,'work_type':kind,'feature_id':feature,'phases':phases,'tasks':rows,'completion':'NOT_ESTABLISHED'})
    decisions=[]
    for s in scopes:
        if project_id and s.get('project_id')!=project_id:continue
        for d in s.get('decisions',[]):
            if d.get('requires_human') is True and d.get('status')=='OPEN' and d.get('basis') and d.get('question') and d not in decisions:decisions.append(d)
    for task in tasks.values():
        if project_id and task.get('project_id')!=project_id:continue
        failure=next((r.get('failure_context') for r in reversed(task.get('executions',[])) if r.get('failure_context')),None) if task['state']=='BLOCKED' else None
        if failure and failure.get('requires_human') is True and failure.get('question') and failure.get('evidence'):
            d={'question':failure['question'],'basis':failure['evidence']}
            if d not in decisions:decisions.append(d)
    return {'groups':work,'decisions':decisions,'scope':'프로젝트 전체 · 실행/기능/작업 종류는 구분하여 요약','completion':'NOT_ESTABLISHED','note':'현재 작업 완료는 프로젝트 전체 완료가 아닙니다. 단계별 필수 인수 조건이 없으면 완료를 추정하지 않습니다.'}
