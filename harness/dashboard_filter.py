from harness.dashboard_live import time_value
from harness.dashboard_usage import token_parts


def filter_result(result,events,start=None,end=None):
    lo=time_value(start) if start else None;hi=time_value(end) if end else None
    if (start and not lo) or (end and not hi) or (lo and hi and lo>=hi):raise ValueError('invalid period')
    def within(at):
        t=time_value(at)
        return bool(t and (not lo or t>=lo) and (not hi or t<hi)) if lo or hi else True
    def overlap(run):
        a=time_value(run.get('started_at'));b=time_value(run.get('ended_at'))
        return bool(a and (not hi or a<hi) and (not lo or b is None or b>=lo))
    result['period']={'from':start,'to':end,'active':bool(start or end),'state_semantics':'현재 원장 상태 · 기간 내 활동/응답 필터; 과거 상태 재생 아님'}
    if lo or hi:
        result['tasks']=[t for t in result['tasks'] if any(overlap(r) for r in t['runs'])]
        tids={t['id'] for t in result['tasks']}
        for t in result['tasks']:
            t['activity']['events']=[e for e in t['activity']['events'] if within(e.get('at'))]
            t['activity']['last_activity']=max((e['at'] for e in t['activity']['events'] if e.get('at')),default=None)
            if not t['activity']['events'] and t['activity']['kind']=='observed':
                t['activity'].update(kind='unknown',status='선택 기간 내 활동 기록 없음');t['active']=False
        result['usage']['rows']=[r for r in result['usage']['rows'] if within(r.get('occurred_at')) and r.get('task_id') in tids]
        for s in result['stages']:
            members=[t for t in result['tasks'] if t['stage']=={'기획':'planning','디자인':'design','개발':'development','검증':'verification','리포트':'report'}.get(s['name'])]
            s.update(count=len(members),active=any(t['active'] for t in members),note=None)
    usage=result['usage'];rows=usage['rows']
    usage['totals']={k:sum(r[k] for r in rows) for k in ('tokens','normal_input','cached_input','output')}
    usage['totals']['cost_unknown_responses']=sum(r['cost'] is None for r in rows)
    dates=sorted(r['occurred_at'] for r in rows if r.get('occurred_at'))
    usage['scope_info'].update(responses=len(rows),period=[dates[0],dates[-1]] if dates else [],tasks=len(result['tasks']),role_executions=sum(sum(overlap(r) for r in t['runs']) for t in result['tasks']) if lo or hi else sum(len(t['runs']) for t in result['tasks']))
    if lo or hi:result['last_activity']=max((e.get('timestamp') for e in events if e.get('agent_run_id') in {r['id'] for t in result['tasks'] for r in t['runs']} and within(e.get('timestamp')) and e.get('timestamp')),default=None)
    unique={};conflicts=set();invalid=0
    for e in events:
        if e.get('event_type')!='model_usage' or not within(e.get('timestamp')):continue
        o=e.get('observed') or {};key=((e.get('source') or {}).get('session_id'),o.get('response_id'))
        if not all(v and v!='UNKNOWN' for v in key):invalid+=1;continue
        value=(o.get('model'),o.get('usage'),o.get('usage_semantics'))
        if key in unique and unique[key]!=value:conflicts.add(key)
        unique[key]=value
    valid={k:token_parts(v[1],v[2]) for k,v in unique.items() if k not in conflicts}
    invalid+=sum(v is None for v in valid.values());valid={k:v for k,v in valid.items() if v is not None}
    bound={(r['session_id'],r['response_id']) for r in rows}
    selected=set(valid)&bound
    usage['universe']={'scope':'이 저장소에 수집된 로그 · 다른/미확인 프로젝트 포함, 제품 전체 분모 아님','responses':len(valid),'tokens':sum(sum(v) for v in valid.values()),
      'selected_responses':len(selected),'selected_tokens':sum(sum(valid[k]) for k in selected),
      'outside_selected_responses':len(set(valid)-selected),'outside_selected_tokens':sum(sum(valid[k]) for k in set(valid)-selected),
      'conflicting_responses':len(conflicts),'invalid_or_missing':invalid,'collection_omissions':'UNKNOWN',
      'note':'선택 밖은 다른 실행·연결 없음·범위 제외가 섞여 있어 모두 메모 제품 비용이나 귀속 불명으로 단정하지 않음.'}
    return result
