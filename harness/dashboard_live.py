"""Project-owned task/run joins. Observation is not a process heartbeat."""
from datetime import datetime, timezone

PHASES={'ui':'development','client_integration':'development','server_implementation':'development','integration_verification':'verification'}
AREAS={'kmp':'KMP 공통','web':'Web','server':'Server','android':'Android','ios':'iOS'}
ROLES={'planning':'기획 담당','design':'디자인 담당','development':'개발 담당','verification':'검증 담당','improvement':'개선 담당','orchestrator':'진행 관리'}


def time_value(s):
    try:return datetime.fromisoformat(s.replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError):return None


def recorded_stage(task, run, events):
    # The contract at start time, not a later task edit, labels a historical response.
    frozen=run.get('pipeline_stage') if run.get('pipeline_stage') in {'planning','design','development','verification','report'} else None
    start=time_value(run.get('started_at'));matches=[]
    for e in events:
        when=time_value(e.get('timestamp'))
        if e.get('event_type')=='task_stage_configured' and e.get('task_id')==task.get('task_id') and start and when and when<=start:
            after=(e.get('observed') or {}).get('after') or {}
            if after.get('stage') in PHASES:matches.append((when,after['stage']))
    if matches:
        raw=max(matches)[1]
        if frozen and frozen!=PHASES[raw]:return 'conflict',{'execution.pipeline_stage':frozen,'contract_stage':raw},'동일 축의 시작 단계와 이전 계약 충돌 · 임의 선택 안 함'
        return PHASES[raw],raw,'task_stage_configured.observed.after.stage (실행 시작 이전 계약)'
    if frozen:return frozen,frozen,'execution.pipeline_stage (시작 때 동결된 명시 단계)'
    return None,None,None


def runtime_scopes(tasks,events):
    starts={e['run_id']:e for e in events if e.get('event_type')=='run_started' and e.get('run_id') not in (None,'UNKNOWN')}
    scopes=[]
    for rid,e in starts.items():
        project=e.get('project_id');work=e.get('work_type')
        if project in (None,'UNKNOWN'):continue
        members={};runs=[]
        for tid,t in tasks.items():
            linked=[r for r in t.get('executions',[]) if r.get('run_id')==rid]
            declared=any(x.get('run_id')==rid and x.get('task_id')==tid and x.get('event_type') in {'task_registered','stage_rework_created'} for x in events)
            if not (linked or declared) or t.get('project_id')!=project or t.get('work_type')!=work:continue
            phase,_,_=recorded_stage(t,linked[-1] if linked else {},events)
            members[tid]={'stage':phase,'next_action':None};runs.extend(r['agent_run_id'] for r in linked)
        if not members:continue
        ending=next((x for x in reversed(events) if x.get('event_type')=='run_finished' and x.get('run_id')==rid),None)
        finished=bool(ending)
        scopes.append({'id':'run:'+rid,'name':(e.get('agent_summary') or {}).get('request_summary') or '기록된 실행',
            'goal':(e.get('agent_summary') or {}).get('request_summary'), 'project_id':project,'work_type':work,
            'tasks':members,'agent_run_ids':runs,'recorded_run_id':rid,'artifacts':[],'approved_baselines':[],
            'provenance':{'kind':'RECORDED_RUN','group_kind':'HISTORICAL_RUN' if finished else 'OBSERVED_RUN','not_single_runtime_run':False},
            'outcome':{'status':'ENDED_REPORTED' if finished else 'UNKNOWN','achieved':((ending or {}).get('agent_summary') or {}).get('result'),'summary':'에이전트 종료 보고 · 필수 검토 결과와 별개' if finished else '열린 실행 기록 · 프로세스 생존 미확인'},'decisions':[]})
    bound={aid for s in scopes for aid in s['agent_run_ids']}
    for tid,t in tasks.items():
        if t.get('project_id') in (None,'UNKNOWN') or not t.get('work_type'):continue
        for run in t.get('executions',[]):
            aid=run.get('agent_run_id')
            if not aid or aid in bound:continue
            phase,_,_=recorded_stage(t,run,events)
            scopes.append({'id':'agent:'+aid,'name':t.get('title',tid)+' · 상위 실행 미연결',
              'goal':t.get('scope'),'project_id':t['project_id'],'work_type':t['work_type'],
              'tasks':{tid:{'stage':phase}},'agent_run_ids':[aid],'artifacts':[],'approved_baselines':[],
              'provenance':{'kind':'RECORDED_AGENT_EXECUTION','group_kind':'HISTORICAL_RUN' if run.get('ended_at') else 'OBSERVED_RUN','parent_run_link':'UNKNOWN'},'decisions':[]})
    return scopes


def activity_view(task,scope,events,now=None):
    now=now or datetime.now(timezone.utc)
    allowed=set(scope.get('agent_run_ids',[]))
    runs=[r for r in task.get('executions',[]) if r.get('agent_run_id') in allowed]
    latest=runs[-1] if runs else {}
    work=next((r for r in reversed(runs) if r.get('kind')=='work'),{})
    work_aid=work.get('agent_run_id')
    work_events=[e for e in events if work_aid and e.get('agent_run_id')==work_aid]
    work_terminal=next((e for e in reversed(work_events) if e.get('event_type') in {'agent_run_finished','agent_run_failed'}),{})
    work_ended=work.get('ended_at') or (work_terminal.get('observed') or {}).get('ended_at')
    work_start=time_value(work.get('started_at'));work_end=time_value(work_ended)
    work_observation={'agent_run_id':work_aid,'role':work.get('role'),'started_at':work.get('started_at'),
                      'ended_at':work_ended,'elapsed_seconds':max(0,int(((work_end or now)-work_start).total_seconds())) if work_start else None,
                      'source':'native execution.kind=work in selected scope','process_alive':'UNKNOWN'} if work else None
    aid=latest.get('agent_run_id');rid=latest.get('run_id')
    own=[e for e in events if aid and e.get('agent_run_id')==aid]
    terminal=next((e for e in reversed(own) if e['event_type'] in {'agent_run_finished','agent_run_failed'}),None)
    ended=latest.get('ended_at') or ((terminal.get('observed') or {}).get('ended_at') if terminal else None)
    run_end=next((e for e in reversed(events) if rid and e.get('run_id')==rid and e['event_type']=='run_finished'),None)
    last=max([e.get('timestamp') for e in own if e.get('timestamp')]+([latest['started_at']] if latest.get('started_at') else []),default=None)
    age=(now-time_value(last)).total_seconds() if time_value(last) else None
    historical=scope.get('provenance',{}).get('kind')=='POSTHOC_CONNECTION' or scope.get('provenance',{}).get('group_kind')=='HISTORICAL_RUN' or bool(run_end)
    state=task.get('state')
    if terminal and terminal['event_type']=='agent_run_failed':status='차단';kind='blocked'
    elif state=='BLOCKED':status='차단';kind='blocked'
    elif state=='DONE':status='완료 보고';kind='done'
    elif state=='IN_REVIEW' and latest.get('kind')=='review' and not ended and not historical and age is not None and age<=600:status='검토 진행 기록 관측 · 생존 미확인';kind='observed'
    elif state in {'TODO','READY','IN_REVIEW'}:status='검토 대기' if state=='IN_REVIEW' else '대기';kind='waiting'
    elif ended or run_end:status='실행 종료 · 작업 결과 미확인';kind='unknown'
    elif latest and not historical and age is not None and age<=600:status='진행 기록 관측 · 생존 미확인';kind='observed'
    else:status='최근 활동 미확인 · 열린 기록';kind='unknown'
    delegation=task.get('delegation') or {}
    parent_id=delegation.get('parent_task_id',task.get('parent_task_id'))
    area=delegation.get('development_area',latest.get('development_area',task.get('development_area')))
    delegated_state=delegation.get('delegation_state',task.get('delegation_state'))
    if delegated_state=='FAILED':status='영역 작업 실패';kind='failed'
    elif delegated_state=='BLOCKED':status='영역 작업 차단';kind='blocked'
    elif delegated_state=='RECHECK_REQUIRED':status='영역 작업 재검증 필요';kind='blocked'
    # RUNNING is a coordination label, not proof that an OS process is alive.
    process_start=next((e for e in reversed(work_events) if e.get('event_type')=='role_process_started' or (e.get('event_type')=='role_process' and ((e.get('observed') or {}).get('process_state')=='role_process_started' or ((e.get('observed') or {}).get('spawned') is True and (e.get('observed') or {}).get('process_state')!='role_process_finished')))),{})
    process_end=next((e for e in reversed(work_events) if e.get('event_type')=='role_process_finished' or (e.get('event_type')=='role_process' and (e.get('observed') or {}).get('process_state')=='role_process_finished')),{})
    # An earlier implementation process ending cannot end a newer review.
    if process_end and kind=='observed' and work_aid==aid:
        if (process_end.get('observed') or {}).get('exit_code') not in (None,0,'UNKNOWN'):
            status='전문 에이전트 프로세스 실패';kind='failed'
        else:status='프로세스 종료 · 결과 확인 대기';kind='waiting'
    observation=process_start.get('observed') or {}
    process_evidence={'agent_run_id':work_aid,'pid':observation.get('pid','UNKNOWN'),'adapter':observation.get('adapter','UNKNOWN'),'source':('role_process.observed.process_state' if observation.get('process_state') else 'role_process.observed.spawned' if 'spawned' in observation else process_start.get('event_type','UNKNOWN')),'spawned':observation.get('spawned',True if process_start.get('event_type')=='role_process_started' or observation.get('process_state')=='role_process_started' else 'UNKNOWN'),'independent_model_spawned':observation.get('independent_model_spawned','UNKNOWN'),'started_at':observation.get('started_at') or process_start.get('timestamp'),'finished_at':(process_end.get('observed') or {}).get('ended_at') or process_end.get('timestamp'),'exit_code':(process_end.get('observed') or {}).get('exit_code','UNKNOWN'),'process_alive':'UNKNOWN'}
    start=time_value(latest.get('started_at'));end=time_value(ended) or (time_value((run_end.get('observed') or {}).get('ended_at')) if run_end else None)
    elapsed=max(0,int(((end or now)-start).total_seconds())) if start else None
    phase,raw,basis=recorded_stage(task,latest,events)
    history=[]
    for e in events:
        linked_task=e.get('task_id')==task.get('task_id') and scope.get('recorded_run_id') and e.get('run_id')==scope['recorded_run_id']
        if e.get('agent_run_id') not in {r.get('agent_run_id') for r in runs} and not linked_task:continue
        o=e.get('observed') or {}
        history.append({'type':e['event_type'],'at':e.get('timestamp'),'id':e.get('event_id'),
          'details':{k:o[k] for k in ('from','to','reason','started_at','ended_at','call_id','command_kind','command_name','returncode','elapsed_seconds','stdout_sha256','stderr_sha256','argv_sha256','stage','from_task_id','issue_id','pid','adapter','spawned','process_state','independent_model_spawned','exit_code','parent_task_id','development_area','failure_context') if k in o}})
    return {'parent_task_id':parent_id,'development_area':area,'area_label':AREAS.get(area,area or '영역 미등록'),'delegation_state':delegated_state,'delegation_reason':delegation.get('delegation_reason',task.get('delegation_reason')),'process_evidence':process_evidence,'status':status,'kind':kind,'role':latest.get('role') or task.get('role'),'role_label':ROLES.get(latest.get('role') or task.get('role'),'역할 미확인'),'task_role_label':ROLES.get(task.get('role'),'역할 미확인'),
        'phase':phase,'raw_stage':raw,'stage_basis':basis,'started_at':latest.get('started_at'),'ended_at':ended,'elapsed_seconds':elapsed,'work_observation':work_observation,
        'last_activity':last,'historical':historical,'process_alive':'UNKNOWN','events':history,
        'activity_gap':'10분 넘게 활동이 없으면 진행 중으로 세지 않습니다. 중단 이벤트가 연결되지 않은 기록은 종료를 추정하지 않습니다.'}
