"""Read-only human progress projection shared by UI and agent messages.

Never persists a second status/percentage. Completion is evidence-gated by the
existing dashboard task projection, not inferred from a command or DONE alone.
"""
import argparse
import json
from pathlib import Path

LABELS={'waiting':'대기','active':'진행 중','complete':'완료','blocked':'차단'}


def verified_task(t,raw):
    product_gate=t.get('kind')=='code_implementation' and (raw.get('work_type') not in {'HARNESS_BUILD','HARNESS_IMPROVEMENT'} or any(Path(a.get('path','')).name=='acceptance-contract.json' for a in raw.get('inputs',[])))
    return (t.get('raw_state')=='DONE' and t.get('verdict')=='PASS' and not t.get('blocked') and
            (not product_gate or t.get('compliance')=='PASS') and t.get('compliance') not in {'NON_COMPLIANT','RECHECK_REQUIRED'} and
            bool([c for c in t.get('criteria',[]) if c.get('required')]))

def observed_running(view,raw):
    activity=view.get('activity',{})
    if activity.get('kind')!='observed':return False
    aid=(activity.get('work_observation') or {}).get('agent_run_id')
    work=next((r for r in raw.get('executions',[]) if r.get('agent_run_id')==aid and r.get('kind')=='work'),None)
    if not work or work.get('ended_at'):return False
    if work.get('execution_mode')=='current_agent':return True
    process=activity.get('process_evidence') or {}
    return process.get('independent_model_spawned') is True and not process.get('finished_at')


def project(result, source_tasks, root=None):
    scope=result.get('scope') or {}
    if not result.get('selected'):
        return {'goal':None,'steps':[],'current':[],'completion_conditions':[],'message':'실행을 선택하거나 작업 범위를 등록해야 진행 단계를 확인할 수 있습니다.','decisions':[],'selected':False}
    views={t['id']:t for t in result.get('tasks',[])}
    required_questions=result.get('required_questions',[])
    if isinstance(required_questions,dict):required_questions=list(required_questions.values())
    # Group only explicit native parent links. Never group by title/role guesses.
    rework_parent={e.get('task_id'):e.get('from_task_id') for e in result.get('rework_links',[]) if e.get('from_task_id') in views}
    def parent(tid):
        raw=source_tasks.get(tid,{})
        if tid in rework_parent:return rework_parent[tid]
        qa_target=(raw.get('qa_config') or {}).get('target_task_id')
        if qa_target in views:return qa_target
        # A target may also be its own explicit QA acceptance owner. That
        # association is not a new parent edge; preserve real repair ancestry.
        repair_target=next(((v.get('qa_config') or {}).get('target_task_id') for v in source_tasks.values()
                            if (v.get('qa_config') or {}).get('repair_task_id')==tid
                            and (v.get('qa_config') or {}).get('target_task_id')!=tid),None)
        if repair_target in views:return repair_target
        return raw.get('parent_task_id') or (raw.get('delegation') or {}).get('parent_task_id')
    parent_cycles=set()
    def owner(tid):
        seen=set()
        while parent(tid) in views:
            if tid in seen:
                parent_cycles.update(seen);return min(seen)
            seen.add(tid);tid=parent(tid)
        return tid
    roots=list(dict.fromkeys(owner(tid) for tid in views))
    plan=result.get('execution_plan') or {}
    if plan:roots.sort(key=lambda t:plan['task_ids'].index(t) if t in plan['task_ids'] else len(plan['task_ids'])+list(views).index(t))
    dependencies={tid:set() for tid in roots}
    for tid in views:
        for dep in source_tasks.get(tid,{}).get('dependencies',[]):
            if dep in views and owner(dep)!=owner(tid):dependencies[owner(tid)].add(owner(dep))
    remaining=list(roots);ordered=[];cyclic=bool(parent_cycles)
    while remaining:
        ready=[tid for tid in remaining if dependencies[tid]<=set(ordered)]
        if not ready:cyclic=True;ordered.extend(remaining);break
        # Preserve registration order for independent tasks, not artificial sequence.
        for tid in ready:ordered.append(tid);remaining.remove(tid)
    def verified(t):return verified_task(t,source_tasks.get(t['id'],{}))
    steps=[]
    for index,tid in enumerate(ordered,1):
        t=views[tid];members=[views[x] for x in views if owner(x)==tid]
        # Explicit stage rework supersedes old rejected attempts, not their history.
        superseded={p for p in rework_parent.values()}
        required_members=[m for m in members if m['id'] not in superseded] or members
        effective=required_members[-1] if tid in superseded else t
        raw=source_tasks.get(tid,{})
        problems=[m for m in required_members if m.get('blocked') or m.get('verdict') in {'FAIL','RECHECK_REQUIRED'} or m.get('activity',{}).get('kind') in {'blocked','failed'}]
        running=[m for m in members if observed_running(m,source_tasks.get(m['id'],{}))]
        complete=verified(effective) and all(verified(m) for m in required_members)
        state='complete' if complete else 'active' if running else 'blocked' if problems else 'waiting'
        retries=[{'task_id':m['id'],'task':m['title'],'attempts':len([e for e in source_tasks.get(m['id'],{}).get('executions',[]) if e.get('kind')=='work']),'history':m.get('activity',{}).get('events',[])} for m in members]
        failure=next((e.get('failure_context') for e in reversed(raw.get('executions',[])) if e.get('failure_context')),None) if raw.get('state')=='BLOCKED' else None
        conditions=[c.get('description') or c.get('text') or '기준 설명 미등록' for c in raw.get('criteria',[]) if c.get('required')]
        reason=next((m.get('blocked') or m.get('revalidation_summary') or m.get('activity',{}).get('delegation_reason') or ('관련 입력·검증 근거 재확인 필요' if m.get('verdict')=='RECHECK_REQUIRED' else None) for m in problems),None)
        dependencies_wait=[views[d]['title'] for d in dependencies[tid] if not verified(views[d])]
        if dependencies_wait and state!='complete':
            # Even a recent command cannot establish readiness past failed prerequisites.
            reason=reason or '선행 작업 확인 필요: '+', '.join(dependencies_wait)
            state='blocked' if any(views[d].get('blocked') or views[d].get('verdict') in {'FAIL','RECHECK_REQUIRED'} for d in dependencies[tid]) else 'waiting'
        applicability=t.get('applicability') or {}
        valid_exclusion=t.get('applicability_valid',False)
        if applicability.get('status')=='EXCLUDED':
            state='excluded' if valid_exclusion else 'blocked';reason=applicability['reason'] if valid_exclusion else '적용 제외 승인·현재 기준이 바뀌어 재확인 필요'
        if cyclic:state='blocked';reason='작업의 부모·선행 연결에 순환이 있어 계획 순서를 확인해야 합니다.'
        questions=[q for q in required_questions if q.get('status')=='OPEN' and
                   set(q.get('affected_task_ids',q.get('propagated_task_ids',[]))) & {m['id'] for m in members}]
        gates=[m.get('execution_gate') or source_tasks.get(m['id'],{}).get('execution_gate') or {} for m in members]
        plan_wait=[g for g in gates if g.get('status')=='BLOCKED' and (not running or g.get('finish_status')=='BLOCKED')]
        if state!='complete' and questions:
            state='blocked';reason='사용자 필수 답변 대기: '+'; '.join(q['question'] for q in questions)
        elif state!='complete' and plan_wait:
            state='blocked';reason='착수 조건 대기: '+'; '.join(dict.fromkeys(r for g in plan_wait for r in g.get('reasons',[])))
        label=('적용 제외' if state=='excluded' else LABELS[state])+((' · 재검증' if state=='active' else ' · 재검증 필요') if any(m.get('verdict')=='RECHECK_REQUIRED' for m in members) else '')
        steps.append({'task_id':tid,'phase':(scope.get('tasks',{}).get(tid,{}) or {}).get('stage') or raw.get('pipeline_stage') or '미분류','number':index,'name':t['title'],'state':state,'status':label,
            'conditions':conditions,'result':t.get('result') or ('필수 검토와 현재 근거 확인' if complete else '완료 보고 · 유효한 검증 근거 확인 필요' if t.get('raw_state')=='DONE' else None),
            'doing':'; '.join(m['title']+' · '+m.get('activity',{}).get('role_label','담당 역할 미확인') for m in running) or None,
            'reason':reason,'next':t.get('next') or ('관련 결과·필수 검증 확인' if state=='waiting' else None),
            'children':[{'task_id':m['id'],'name':m['title'],'role':m.get('activity',{}).get('role_label'),'area':m.get('activity',{}).get('area_label'),'kind':m.get('activity',{}).get('kind'),'status':m.get('activity',{}).get('status'),'verdict':m.get('verdict')} for m in members if m['id']!=tid],
            'attempts':retries,'dependencies':[views[d]['title'] for d in sorted(dependencies[tid])],
            'failure':failure,'required_questions':[q['id'] for q in questions],
            'work_plan_registered':bool(raw.get('work_plan')),
            'activity_observation':'최근 실행 기록 관측 · 프로세스 생존 미확인' if running else '현재 수행 중인 작업은 확인되지 않았습니다.'})
    # Keep parallel active steps; no single phase percentage or made-up idle state.
    current=[s['number'] for s in steps if s['state']=='active']
    if not current:current=[s['number'] for s in steps if s['state']=='blocked'][:1] or [s['number'] for s in steps if s['state']=='waiting'][:1]
    decisions=[{'question':d['question'],'basis':d['basis']} for d in scope.get('decisions',[]) if d.get('requires_human') is True and d.get('status')=='OPEN' and d.get('question') and d.get('basis')]
    decisions += [{'question':q['question'],'basis':{'required_question_id':q['id']},
                   'status':q['status'],'options':q.get('options',[]),
                   'human_review_required':q.get('human_review_required',False)}
                  for q in required_questions if q.get('status')=='OPEN']
    for step in steps:
        failure=step.get('failure') or {}
        if failure.get('requires_human') is True and failure.get('question') and failure.get('evidence'):
            decisions.append({'question':failure['question'],'basis':failure['evidence']})
    changes=[]
    for t in result.get('tasks',[]):
        for e in t.get('activity',{}).get('events',[]):
            if e.get('type') in {'stage_rework_created','task_registered','development_child_linked'}:
                changes.append({'type':e['type'],'at':e.get('at'),'task':t['title'],'details':e.get('details',{})})
    return {'selected':True,'project':result.get('project','프로젝트 미등록'),'plan_registered':bool(plan),'plan_history':plan.get('history',[]),'goal':scope.get('goal') or scope.get('name') or '목표 미등록','steps':steps,'current':current,
        'completion_conditions':[{'task':s['name'],'conditions':s['conditions']} for s in steps],
        'decisions':decisions,'required_questions':required_questions,'changes':changes,'cycle_detected':cyclic,
        'historical':scope.get('provenance',{}).get('kind')=='POSTHOC_CONNECTION' or scope.get('provenance',{}).get('group_kind')=='HISTORICAL_RUN',
        'period_limited':bool(result.get('period',{}).get('active')),
        'message':'작업 순서이며 시간 기준 진행률이 아닙니다. 단계 완료는 관련 필수 검토·현재 근거 확인 기준입니다.',
        'details':'원본 명령·실행 ID·검증·재시도 이력은 작업 상세에서 확인합니다.'}


def message(progress, start=False):
    if not progress.get('selected'):return progress['message']
    steps=progress['steps']
    current=[s for s in steps if s['number'] in progress['current']]
    phases={'planning':'기획','design':'디자인','development':'개발','verification':'QA','report':'리포트'}
    location=' / '.join(phases.get(s['phase'],s['phase'])+' > '+s['name'] for s in current) or '현재 실행 > 등록 작업 결과 확인'
    lines=['위치: '+progress.get('project','프로젝트 미등록')+' > '+location,'현재 실행 작업: '+progress['goal'],'']
    for step in steps:
        label=step['name']+' — '+step['status']
        if step['state']=='active':label='**'+label+'**'
        lines.append('- ['+('x' if step['state']=='complete' else ' ')+'] '+label)
        if step['state']=='active' and step.get('doing'):lines.append('  - '+step['doing'])
        elif step.get('reason'):lines.append('  - '+step['reason'])
        elif step['state']=='waiting' and step.get('result'):lines.append('  - '+step['result'])
        children=[c for c in step['children'] if c.get('kind')=='observed']
        for child in step['children']:
            lines.append('  - '+('동시 진행 · ' if len(children)>1 and child in children else '')+(child.get('role') or '담당 미확인')+' · '+child['name']+' — '+(child.get('status') or '상태 미확인'))
        repeated=[a for a in step['attempts'] if a['attempts']>1]
        if repeated:lines.append('  - 같은 단계에서 보완·재시도 '+', '.join(str(a['attempts'])+'회' for a in repeated)+' · 이전 이력 보존')
        failure=step.get('failure') or {}
        if failure:
            category={'PRODUCT_DEFECT':'제품 결함','HARNESS_DEFECT':'하네스 결함','ENVIRONMENT':'시험 환경 문제','UNKNOWN':'원인 분류 미확인'}[failure['category']]
            lines.append('  - '+category+' · '+(failure.get('next_action') or '다음 조치 기록 필요'))
    lines += ['', '사용자 결정: '+('; '.join(d['question'] for d in progress['decisions']) or '근거와 함께 등록된 결정 요청 없음')]
    for question in progress.get('required_questions',[]):
        label='답변 대기' if question['status']=='OPEN' else '답변 확인 완료'
        lines.append('- '+label+': '+question['question'])
        if question['status']=='OPEN' and question.get('options'):lines.append('  선택: '+' / '.join(o['label'] for o in question['options']))
        if question.get('human_review_required'):lines.append('  자유 서술의 의미 확인이 필요하여 계속 대기합니다.')
    if not progress.get('plan_registered'):lines.append('전체 Todo 계획은 미등록입니다. 연결된 기존 작업 체크리스트이며 계획 완전성은 미확인입니다.')
    lines.append('현재 실행 작업의 상태이며 프로젝트 전체 완료 판정과 별개입니다.')
    if start:lines+=['완료 조건: '+'; '.join(s['name']+': '+', '.join(s['conditions']) for s in steps),progress['message']]
    if progress.get('historical'):lines.append('과거 실행 · 현재 수행 상태와 별개입니다.')
    if progress.get('period_limited'):lines.append('선택 기간에 연결된 작업만 표시합니다. 과거 상태를 재생한 결과가 아닙니다.')
    return '\n'.join(lines)


def for_task(root, task_id, run_id):
    from harness.dashboard import snapshot
    data=snapshot(root,'run:'+run_id)
    if data.get('selected') and any(t['id']==task_id for t in data['tasks']):return data['human_progress']
    path=Path(root)/'.harness/tasks/tasks.yaml'
    raw=(json.loads(path.read_text()).get('tasks',{}) if path.exists() else {}).get(task_id)
    if raw is None:return snapshot(root,None)['human_progress']
    run=next((r for r in reversed(raw['executions']) if r.get('kind')=='work'),{})
    return snapshot(root,'agent:'+str(run.get('agent_run_id')))['human_progress']


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--scope');p.add_argument('--start',action='store_true');p.add_argument('--json',action='store_true')
    a=p.parse_args()
    from harness.dashboard import snapshot
    data=snapshot(Path(a.root),a.scope);progress=data['human_progress']
    print(json.dumps(progress,ensure_ascii=False,indent=2) if a.json else message(progress,a.start))

if __name__=='__main__':main()
