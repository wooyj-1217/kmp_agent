"""Independent, evidence-bound planning / design / development-plan reviews.

The task ledger remains the source of truth. No stage is approved by another stage.
"""
import copy
import json
import uuid
from pathlib import Path
from harness import logging as log

STAGES=('planning','design','development_plan')
ROLES={'planning':'planning','design':'design','development_plan':'development'}
DOMAINS={'planning':('requirements','scope_policy','acceptance'),
         'design':('screens','states','interactions'),
         'development_plan':('modules','task_dependencies','verification_commands')}


def contract_hash(task,config):
    return log.digest(json.dumps({k:task.get(k) for k in ('task_id','feature_id','project_id','work_type','role','execution_scope','criteria')},sort_keys=True,ensure_ascii=False).encode()+json.dumps(config['checks'],sort_keys=True).encode())


def configure(manager,feature_id,stages):
    def op(state):
        if set(stages)!=set(STAGES):raise ValueError('planning, design and development_plan must be separate contracts')
        seen=set()
        for name,c in stages.items():
            t=state['tasks'].get(c.get('task_id'),{})
            required={x['id'] for x in t.get('criteria',[]) if x.get('required')}
            if t.get('feature_id')!=feature_id or t.get('role')!=ROLES[name] or t.get('execution_scope')!='documentation' or t.get('task_id') in seen:
                raise ValueError('stage needs a distinct documentation task of the correct feature and role; input interpretation is not a development plan')
            checks=c.get('checks',{})
            if set(checks)!=set(DOMAINS[name]) or not set(checks.values())<=required or len(set(checks.values()))!=len(checks):
                raise ValueError('each stage domain must map to its own existing required criterion')
            seen.add(t['task_id'])
        if feature_id in state.get('stage_workflows',{}):raise ValueError('workflow already registered; preserve its revision history')
        if len({(state['tasks'][c['task_id']].get('project_id'),state['tasks'][c['task_id']]['work_type']) for c in stages.values()})!=1:raise ValueError('stage project/work type must match')
        value={'stages':{k:{**copy.deepcopy(v),'task_history':[v['task_id']]} for k,v in stages.items()},'configured_at':log.now()}
        state.setdefault('stage_workflows',{})[feature_id]=value
        manager._event(state,'stage_workflow_configured',state['tasks'][stages['planning']['task_id']],observed={'stages':copy.deepcopy(stages)},summary={'scope':'independent task reviews; not implicit user approval'})
        return copy.deepcopy(value)
    return manager._mutate('configure_stage_workflow',op)


def _current(root,a):
    try:
        p=(root/a['path']).resolve();s=(root/a['snapshot']).resolve()
        return p.is_relative_to(root) and s.is_relative_to(root) and p.is_file() and s.is_file() and log.digest(p.read_bytes())==a['sha256'] and log.digest(s.read_bytes())==a['snapshot_sha256']
    except (KeyError,OSError,TypeError):return False


def assess(root,state,feature_id):
    root=Path(root).resolve();flow=state.get('stage_workflows',{}).get(feature_id)
    if not flow:return {'status':'UNKNOWN','stages':[],'reason':'독립 기획·디자인·개발계획 검토 계약 미등록; 승인 추정 금지'}
    output=[];basis={}
    for name in STAGES:
        c=flow['stages'][name];t=state['tasks'][c['task_id']];reviews=t.get('reviews',[]);review=reviews[-1] if reviews else {}
        result={r['criterion_id']:r for r in review.get('results',[])}
        required={r['id'] for r in t['criteria'] if r.get('required')}
        missing=sorted(k for k in required if result.get(k,{}).get('result')!='PASS')
        open_issues=[i for i in state.get('issues',[]) if i.get('status')!='RESOLVED' and i.get('assigned_task_id',i.get('task_id')) in c['task_history']]
        attempts=sum(sum(r.get('kind')=='work' for r in state['tasks'][tid].get('executions',[])) for tid in c['task_history'])
        limit=state['tasks'][c['task_history'][0]]['max_attempts']
        reasons=[];status='PASS'
        if t.get('role')!=ROLES[name] or t.get('execution_scope')!='documentation' or not set(c['checks'].values())<=required:status='UNKNOWN';reasons.append('이 단계의 목적·필수 검토 정의가 등록 계약과 다름')
        elif len(basis)!=STAGES.index(name):status='WAITING_UPSTREAM';reasons.append('선행 단계의 보완·재검토가 먼저 필요')
        elif open_issues:status='REWORK_REQUIRED';reasons.extend(i['observed'] for i in open_issues)
        elif not review:status='NOT_RUN';reasons.append('이 단계 자체의 검토 기록 없음')
        elif missing:status='REWORK_REQUIRED';reasons.append('필수 검토 누락/실패: '+', '.join(missing))
        elif review.get('stage_readiness_contract_sha256')!=contract_hash(t,c):status='RECHECK_REQUIRED';reasons.append('등록된 검토 계약의 당시 버전 연결이 미확인/변경됨; 과거 PASS 비승계')
        elif t.get('state')!='DONE':status='REWORK_REQUIRED';reasons.append('작업 검토/반환 상태가 종료되지 않음')
        elif t.get('validation_status',{}).get(review.get('agent_run_id'),{}).get('state')=='RECHECK_REQUIRED':status='RECHECK_REQUIRED';reasons.append('원본 검증이 재검토 필요')
        elif not t.get('outputs') or not all(_current(root,a) for a in t['outputs']+t.get('inputs',[])) or not all(_current(root,r.get('evidence',{})) for r in review.get('results',[]) if r['criterion_id'] in required):
            status='RECHECK_REQUIRED';reasons.append('입력·산출물·검토 근거의 현재 해시/스냅샷 불일치')
        elif basis and review.get('stage_readiness_basis')!=basis:
            status='RECHECK_REQUIRED';reasons.append('검토 당시 선행 버전 연결이 현재 승인 입력과 다르거나 미확인')
        if status=='PASS':
            basis[name]={'task_id':t['task_id'],'review_id':review['agent_run_id'],'outputs':{a['path']:a['sha256'] for a in t['outputs']}}
        exhausted=status in {'REWORK_REQUIRED','RECHECK_REQUIRED'} and attempts>=limit
        if exhausted:status='BLOCKED_RETRY_LIMIT';reasons.append('재시도 한도 도달; 범위·정책·예산 판단 필요')
        output.append({'stage':name,'task_id':t['task_id'],'status':status,'reasons':reasons,'attempts':attempts,'limit':limit,
            'checks':copy.deepcopy(c['checks']),'task_history':c['task_history'], 'requires_human':exhausted,
            'next':'선행 보완 완료 후 이 단계 재검토' if status=='WAITING_UPSTREAM' else '보완 후 같은 단계 재검토' if status!='PASS' and not exhausted else '한도/범위 판단' if exhausted else '이 단계 검토 근거 유효'})
    return {'status':'PASS' if all(s['status']=='PASS' for s in output) else 'NOT_READY','stages':output,'basis':basis,
            'reason':'단계별 검토는 제품 구현 완료나 사용자 의사결정 승인과 별개'}


def gate(manager,state,task,review_results=None):
    from harness.development_tracking import execution_scope
    flow=state.get('stage_workflows',{}).get(task['feature_id']);code=execution_scope(task)=='code_implementation'
    if not flow:
        return '독립 개발계획 검토 계약 없음; 기획·디자인 통과로 구현 시작 불가' if code and task.get('work_type')=='PRODUCT' else None
    target=next((n for n,c in flow['stages'].items() if c['task_id']==task['task_id']),None)
    if not code and target is None:return None
    origin=state['tasks'][flow['stages']['planning']['task_id']]
    if (task.get('project_id'),task['work_type'])!=(origin.get('project_id'),origin['work_type']):return '단계 승인 범위의 프로젝트·작업 종류와 불일치'
    if target and review_results is None:
        history=flow['stages'][target]['task_history'];attempts=sum(sum(r.get('kind')=='work' for r in state['tasks'][tid].get('executions',[])) for tid in history)
        if attempts>=state['tasks'][history[0]]['max_attempts']:return '단계 전체 재시도 한도 도달; 이전 검토를 덮거나 무한 재시도하지 않음'
    if review_results is not None and any(r['result']!='PASS' for r in review_results):return None
    assessment=assess(manager.root,state,task['feature_id'])
    required=STAGES if code else STAGES[:STAGES.index(target)]
    failed=[s['stage'] for s in assessment['stages'] if s['stage'] in required and s['status']!='PASS']
    if failed:return '선행 단계 보완·재검토 필요: '+', '.join(failed)
    expected={p:h for n in required for p,h in assessment['basis'][n]['outputs'].items()}
    applied={a['path']:a['sha256'] for a in task.get('inputs',[])}
    if any(applied.get(p)!=h for p,h in expected.items()):return '현재 승인된 선행 버전을 입력에 명시적으로 다시 연결해야 함'
    return None


def review_basis(manager,state,task):
    flow=state.get('stage_workflows',{}).get(task['feature_id'])
    if not flow:return None
    name=next((n for n,c in flow['stages'].items() if c['task_id']==task['task_id']),None)
    if name is None:return None
    current=assess(manager.root,state,task['feature_id'])['basis']
    return {n:copy.deepcopy(current[n]) for n in STAGES[:STAGES.index(name)] if n in current}


def bind_inputs(manager,task_id,inputs,reason):
    def op(state):
        task=state['tasks'][task_id]
        if task['feature_id'] not in state.get('stage_workflows',{}) or task['state'] not in {'TODO','READY','BLOCKED'} or any(not r.get('ended_at') for r in task['executions']):
            raise ValueError('stage input binding requires registered workflow and inactive TODO/READY/BLOCKED task')
        if not reason:raise ValueError('input version change needs a reason')
        before=copy.deepcopy(task['inputs']);refs=[manager.artifact(p) for p in inputs];task['inputs']=refs
        task.setdefault('input_rebases',[]).append({'at':log.now(),'reason':reason,'before':before,'after':copy.deepcopy(refs)})
        for r in task['reviews']:task.setdefault('validation_status',{})[r['agent_run_id']]={'state':'RECHECK_REQUIRED','reasons':['explicit input baseline rebound']}
        manager._event(state,'stage_inputs_rebound',task,observed={'before':before,'after':refs},summary={'reason':reason})
    return manager._mutate('bind_stage_inputs',op,task_id)


def return_to_stage(manager,feature_id,stage,reason,evidence,source_task_id=None,source_review_id=None):
    def op(state):
        c=state['stage_workflows'][feature_id]['stages'][stage];old=state['tasks'][c['task_id']]
        active=[r for r in old.get('executions',[]) if not r.get('ended_at')]
        if any(r.get('kind')!='work' or not manager._valid_artifact(r.get('checkpoint',{})) for r in active):
            raise ValueError('active stage requires completed review or a valid work checkpoint before return')
        findings=state.setdefault('issues',[]);issue_id='ISSUE-'+str(uuid.uuid4());proof=manager.artifact(evidence)
        issue={'id':issue_id,'task_id':old['task_id'],'folder':old.get('role_contract',{}).get('folder'),'kind':stage,
            'feature_id':feature_id,'owner':ROLES[stage],'observed':reason,'expected':'stage criteria pass against current inputs','recheck':'responsible stage review with issue-specific evidence','severity':'MAJOR','screen':'stage contract','ui_state':stage,'evidence':proof,'status':'OPEN','returned':True,'created_at':log.now(),'history':[],
            'source_task_id':source_task_id,'source_review_id':source_review_id}
        findings.append(issue)
        attempts=sum(sum(r.get('kind')=='work' for r in state['tasks'][tid].get('executions',[])) for tid in c['task_history'])
        if attempts>=state['tasks'][c['task_history'][0]]['max_attempts']:
            manager._event(state,'stage_rework_limit_reached',old,observed={'stage':stage,'issue_id':issue_id},summary={'reason':reason})
            return {'status':'BLOCKED_RETRY_LIMIT','issue_id':issue_id}
        # A revision preserves the accepted old task and evidence rather than reopening it as if unreviewed.
        tid=old['task_id']+'.R'+str(len(c['task_history']))
        if tid in state['tasks']:raise ValueError('revision task ID collision')
        new={k:copy.deepcopy(old[k]) for k in ('feature_id','role','work_type','project_id','scope','criteria','max_attempts','inputs','execution_scope','visual_required','execution_kind','dependencies') if k in old}
        upstream=assess(manager.root,state,feature_id).get('basis',{})
        refs={a['path']:a for a in new['inputs']}
        for name in STAGES[:STAGES.index(stage)]:
            if name in upstream:
                for a in state['tasks'][upstream[name]['task_id']]['outputs']:refs[a['path']]=copy.deepcopy(a)
        new.update(task_id=tid,title=old['title']+' · 보완',scope=old['scope']+' / 보완: '+reason,state='READY',created_at=log.now(),attempts=0,returns=0,
          executions=[],reviews=[],outputs=[],changes=[],checkpoints=[],return_history=[],returned_issues=[issue_id],validation_status={},inputs=list(refs.values()),
          pipeline_stage='development' if stage=='development_plan' else stage,handoffs=[],blocked_reason=None,design_status={'specification':'NOT_STARTED','mockup':'NOT_PRODUCED','visual_review':'NOT_RUN','visual_evidence':None})
        for name in STAGES[:STAGES.index(stage)]:
            current=state['stage_workflows'][feature_id]['stages'][name]['task_id']
            new['dependencies']=list(dict.fromkeys(new.get('dependencies',[])+[current]))
        for pending in findings:
            if pending.get('status')!='RESOLVED' and pending.get('assigned_task_id',pending.get('task_id')) in c['task_history']:
                pending['history'].append({'event':'stage_rework_routed','target_id':tid});pending['assigned_task_id']=tid
                if pending['id'] not in new['returned_issues']:new['returned_issues'].append(pending['id'])
        state['tasks'][tid]=new;c['task_id']=tid;c['task_history'].append(tid);issue['assigned_task_id']=tid
        for r in old.get('executions',[]):
            if not r.get('ended_at'):
                r.update(ended_at=log.now(),outcome='RETURNED');manager._event(state,'agent_run_finished',old,r['agent_run_id'],observed={'ended_at':r['ended_at'],'outcome':'RETURNED'},summary={'result':reason})
        if old['state']!='DONE':
            previous=old['state'];old.update(state='BLOCKED',blocked_reason='보완 작업으로 반환: '+tid)
            manager._event(state,'task_state_changed',old,observed={'from':previous,'to':'BLOCKED','reason':old['blocked_reason']})
        manager._event(state,'stage_rework_created',new,observed={'stage':stage,'from_task_id':old['task_id'],'issue_id':issue_id},summary={'reason':reason,'result':'보완 후 동일 단계 재검토; 후속 PASS 비승계'})
        return {'status':'REPAIR_READY','task_id':tid,'issue_id':issue_id}
    return manager._mutate('return_to_stage',op)
