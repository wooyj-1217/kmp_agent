"""Read-only agent/coordination flow. Never equates process, quality and product PASS."""
from datetime import datetime,timezone

ROLES={'planning':'기획','design':'디자인','development':'개발 코디네이터','qa':'QA'}
AREAS={'kmp':'KMP 공통','android':'Android','ios':'iOS','web':'Web','server':'Server'}


def project(root,tasks,events,issues,project_progress,selected_ids,plans,provenance=None):
    from harness.dashboard import task_view
    from harness.dashboard_live import activity_view,time_value
    from harness.execution_plan import exclusion_valid
    from harness.human_progress import verified_task
    now=datetime.now(timezone.utc);groups=[]
    for group in project_progress['groups']:
        gid='|'.join(str(group[k]) for k in ('project_id','work_type','feature_id'))
        ids=[t['task_id'] for t in group['tasks']];raw=[tasks[t] for t in ids]
        scope={'tasks':{tid:{} for tid in ids},'agent_run_ids':[r['agent_run_id'] for t in raw for r in t.get('executions',[])]}
        views={t['task_id']:dict(task_view(root,t,scope,tasks),activity=activity_view(t,scope,events,now)) for t in raw}
        group_events=[e for e in events if e.get('task_id') in ids or e.get('agent_run_id') in scope['agent_run_ids']]
        past={e.get('observed',{}).get('from_task_id') for e in group_events if e.get('event_type')=='stage_rework_created'}
        def category(t):
            if t.get('qa_config') or t.get('role')=='verification' or t.get('pipeline_stage')=='verification':return 'qa'
            if t.get('role') in {'planning','design','development'}:return t.get('role')
            return t.get('pipeline_stage') if t.get('pipeline_stage') in ROLES else None
        def observation(t):
            view=views[t['task_id']];activity=view['activity'];process=activity.get('process_evidence') or {}
            simulated=t.get('synthetic_runtime') if t.get('synthetic') is True else None
            if simulated:process=dict(simulated,agent_run_id=activity.get('work_observation',{}).get('agent_run_id'))
            source=t.get('delegation') or t
            area=source.get('development_area') or t.get('development_area')
            requested=source.get('delegation_state')=='RUNNING' or t['state'] in {'READY','IN_PROGRESS'}
            work=[e for e in t.get('executions',[]) if e.get('kind')=='work']
            live=next((e for e in reversed(work) if not e.get('ended_at')),None)
            independent=process.get('independent_model_spawned') is True
            stale=False
            last=activity.get('last_activity')
            if time_value(last):stale=(now-time_value(last)).total_seconds()>600
            running_process=independent and not process.get('finished_at')
            if t['task_id'] in past:status='보완 이전 기록'
            elif t.get('applicability',{}).get('status')=='EXCLUDED':status='적용 제외' if exclusion_valid(root,t) else '상태 확인 필요 · 제외 승인 재검토'
            elif live and activity['kind']=='observed':
                status='실행 중' if running_process else '검토 중' if independent and process.get('finished_at') else '진행 중 · 메인 세션' if live.get('execution_mode')=='current_agent' else '검토 중' if category(t)=='qa' else '호출 요청 · 실행 미확인'
                if view['verdict'] in {'FAIL','RECHECK_REQUIRED'}:status='보완 중' if independent or live.get('execution_mode')=='current_agent' else '보완 요청 · 실행 미확인'
            elif t['state']=='BLOCKED':status='차단'
            elif view['verdict']=='RECHECK_REQUIRED':status='재검증 필요'
            elif verified_task(view,t):status='완료'
            elif independent and process.get('finished_at') and process.get('exit_code')==0 and live:status='검토 중'
            elif t['state']=='IN_REVIEW':status='검토 중'
            elif source.get('delegation_state')=='FAILED':status='실행 실패'
            elif stale and live:status='상태 확인 필요'
            elif requested:status='호출 요청 · 실행 미확인'
            elif t['state']=='DONE':status='완료 보고 · 미검증'
            else:status='대기' if t['executions'] else '계획됨 · 미실행'
            qa=(t.get('qa_config') or {}).get('attempts',[]);last_attempt=qa[-1] if qa else {}
            proc=next((e.get('observed',{}) for e in reversed(group_events) if e.get('agent_run_id')==(process.get('agent_run_id')) and e.get('event_type')=='role_process' and e.get('observed',{}).get('process_state')=='role_process_finished'),{})
            if simulated:proc=simulated
            contract_error=proc.get('result_error') not in (None,'UNKNOWN','')
            process_error=proc.get('process_error') not in (None,'UNKNOWN','')
            runtime_failed=contract_error or process_error or bool(last_attempt.get('runtime_failure')) or process.get('exit_code') not in (None,0,'UNKNOWN')
            unmet=[tasks[d]['title'] for d in t.get('dependencies',[]) if d in tasks and (d not in views or not verified_task(views[d],tasks[d]))]
            reason=t.get('blocked_reason') or ('선행 작업 대기: '+', '.join(unmet) if unmet and t['state']!='DONE' else None)
            if unmet and not live and status not in {'완료','적용 제외'}:status='대기'
            if t.get('qa_config',{}).get('repair_task_id') and t['state']=='BLOCKED' and not runtime_failed:
                status='대기 · 보완 결과 확인'
            if runtime_failed and not live:status='차단 · 호출/결과 형식 오류'
            return {'task_id':t['task_id'],'name':t['title'],'review_target':tasks.get(t.get('qa_config',{}).get('target_task_id'),{}).get('title'),'review_stage':t.get('qa_config',{}).get('stage'),'status':status,'active':bool(live and activity['kind']=='observed' and (running_process or live.get('execution_mode')=='current_agent')),'independent_process_confirmed':independent and not t.get('synthetic',False),'process_evidence_kind':'SYNTHETIC' if t.get('synthetic') else 'NATIVE','execution_kind':'SYNTHETIC_PROCESS' if independent and t.get('synthetic') else 'INDEPENDENT_MODEL' if independent else 'MAIN_SESSION' if any(e.get('execution_mode')=='current_agent' for e in work) else 'NO_CONFIRMED_MODEL_PROCESS','raw_state':t['state'],'execution_observation':'종료 확인' if process.get('finished_at') or (work and all(e.get('ended_at') for e in work)) else '현재 실행 여부 미확인','verification_status':view['verdict'] if view['verdict'] in {'PASS','FAIL','RECHECK_REQUIRED'} else '미검증' if t.get('criteria') else '기록 없음','assignment':'적용 제외' if status=='적용 제외' else '배정됨','process_alive':'UNKNOWN','quality_outcome':last_attempt.get('outcome',view['verdict']),'runtime_failure':runtime_failed,'last_activity':last,'stale':stale,'reason':reason,'area':area,'attempts':len(work),'attempt_limit':t.get('max_attempts'),'dependencies':[tasks[d]['title'] for d in t.get('dependencies',[]) if d in tasks],'history':t.get('return_history',[]),'role':category(t),'process':process,'checklist':view.get('criteria',[])}
        observations={t['task_id']:observation(t) for t in raw}
        nodes=[]
        def node(key,label,members,kind='role'):
            rows=[observations[t] for t in members if t not in past]
            rows.sort(key=lambda r:(not r['active'],r['status']!='상태 확인 필요',r['status']!='차단',r['status']=='완료'))
            current=rows[0] if rows else None
            active=[r for r in rows if r['active']]
            completed=bool(rows) and all(r['status'] in {'완료','적용 제외'} for r in rows) and any(r['status']=='완료' for r in rows)
            status='완료' if completed else current['status'] if current else '미배정'
            if len(rows)>1 and any(r['status']=='차단' for r in rows) and not all(r['status']=='차단' for r in rows) and not active and current and current['status']=='차단':status='일부 차단 · 다른 작업 별도'
            excluded=bool(rows) and all(r['status']=='적용 제외' for r in rows)
            if excluded:status='적용 제외'
            n={'id':gid+':'+key,'key':key,'label':label,'kind':kind,'status':status,'active':bool(active),'complete':completed and not excluded,'task':(' / '.join((r['review_target']+' · ' if r.get('review_target') else '')+r['name'] for r in active[:2]) if active else (current['review_target']+' · ' if current and current.get('review_target') else '')+current['name'] if current else '배정된 작업 기록 없음'),'task_ids':[r['task_id'] for r in rows],'tasks':rows,'blocked_count':sum(r['status']=='차단' for r in rows),'parallel_count':len(active),'reason':current.get('reason') if current else None}
            nodes.append(n);return n
        role_nodes={}
        for key,label in ROLES.items():
            members=[t['task_id'] for t in raw if category(t)==key and not observations[t['task_id']]['area']]
            role_nodes[key]=node(key,label,members)
        for area in dict.fromkeys(o['area'] for o in observations.values() if o['area']):
            node('area:'+str(area),AREAS.get(area,area),[tid for tid,o in observations.items() if o['area']==area],'development_child')
        observed=[r for r in observations.values() if r['active']]
        main=[r for r in observed if r['execution_kind']=='MAIN_SESSION' and tasks[r['task_id']].get('role')=='orchestrator']
        orchestrator={'id':gid+':orchestrator','key':'orchestrator','label':'오케스트레이터','kind':'coordination','status':'조율 기록 관측' if main else '조율 기록 없음','active':bool(main),'complete':False,'task':main[0]['name'] if main else '조율 기록 없음','task_ids':[],'tasks':main,'execution_kind':'MAIN_SESSION' if main else 'UNCONFIRMED','detail':'활성 메인 세션의 조율 역할입니다. 별도 오케스트레이터 프로세스 실행을 뜻하지 않습니다. 프로세스 생존은 미확인입니다.'}
        nodes.insert(0,orchestrator)
        edges=[]
        for n in nodes[1:]:
            if n['kind']=='role':edges.append({'kind':'coordination','from':'orchestrator','to':n['key'],'active':n['active'],'reason':'조율 관계 · 실행 인계의 증거와 별개'})
        for t in raw:
            for h in t.get('handoffs',[]):
                source=h.get('from_task_id');target=h.get('to_task_id')
                if source in observations and target in observations:
                    a=observations[source]['role'];b=observations[target]['role']
                    edge={'kind':'handoff','from':a,'to':b,'active':observations[target]['active'],'source_task_id':source,'target_task_id':target,'reason':'작업 인계'}
                    if a and b and a!=b and edge not in edges:edges.append(edge)
        returns=[]
        for issue in issues:
            if issue.get('feature_id')!=group['feature_id']:continue
            qa_task=issue.get('qa_task_id') or issue.get('source_task_id')
            owner={'planning':'planning','design':'design','development':'development'}.get(issue.get('owner'))
            if qa_task in observations and observations[qa_task]['role']=='qa' and owner:
                edge={'kind':'qa_return','from':'qa','to':owner,'active':issue.get('status')!='RESOLVED','reason':str(issue.get('observed') or issue.get('qa_finding',{}).get('actual') or '보완 필요')[:60],'issue_id':issue['id'],'target_task_id':issue.get('assigned_task_id') or issue.get('task_id')}
                returns.append(edge)
                if edge['active']:edges.append(edge)
        bound_plans=[p for p in plans.values() if any(t in p['task_ids'] for t in ids)]
        platforms=[]
        for target in dict.fromkeys(t for p in bound_plans for t in p.get('targets',[])):
            checks={k:'미검증' for k in ['build','run','qa']}
            for t in raw:
                for criterion in t.get('criteria',[]):
                    if criterion.get('target')!=target or criterion.get('check_kind') not in checks:continue
                    key=criterion['check_kind'];latest=t['reviews'][-1] if t.get('reviews') else {}
                    actual=next((r.get('result') for r in latest.get('results',[]) if r.get('criterion_id')==criterion['id']),None)
                    checks[key]='PASS' if actual=='PASS' and views[t['task_id']]['verdict']=='PASS' else actual or 'NOT_RUN'
            platforms.append({'target':target,'checks':checks,'missing_checks':[k for k in checks if not any(c.get('target')==target and c.get('check_kind')==k for t in raw for c in t.get('criteria',[]))],'note':'공유 코드 검증이나 에이전트 배정만으로 플랫폼 통과를 추정하지 않음'})
        groups.append({'id':gid,'feature_id':group['feature_id'],'name':group['name'],'work_type':group['work_type'],'nodes':nodes,'edges':edges,'returns':returns,'platforms':platforms,'current':bool(set(ids)&set(selected_ids)),'last_activity':max([r['last_activity'] for r in observations.values() if r.get('last_activity')],default=None),'synthetic':all(t.get('synthetic') is True for t in raw) or (bool(set(ids)&set(selected_ids)) and (provenance or {}).get('kind')=='SYNTHETIC'),'historical':bool(set(ids)&set(selected_ids)) and ((provenance or {}).get('kind')=='POSTHOC_CONNECTION' or (provenance or {}).get('group_kind')=='HISTORICAL_RUN'),'missing_dependencies':[d for t in raw for d in t.get('dependencies',[]) if d not in tasks],'completion':'PROJECT_COMPLETION_NOT_ESTABLISHED'})
    groups.sort(key=lambda g:not g['current'])
    return {'groups':groups,'decisions':project_progress['decisions'],'observed_at':now.isoformat(),'connection':'snapshot_received','note':'프로젝트 전체와 현재 작업 완료는 별개입니다. 기록 관측은 프로세스 생존 보증이 아닙니다.'}
