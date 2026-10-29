"""Read-only usage projections. No inferred run membership or synthetic token counts."""
import hashlib
import json
import zipfile
from functools import lru_cache

LABELS = {'기획':'기획', '디자인':'디자인', '구현':'개발', '검증':'검증', '수정':'수정·재작업', '보고서':'리포트', '공통':'공통'}


def native_identity_conflict(event):
    """Quarantine a proven thread mismatch, never infer missing historical IDs.

    Older child imports could stamp the parent's session ID on the event.
    Both native IDs must be present before rejecting that recorded identity;
    missing metadata continues through the existing UNKNOWN policy.
    """
    session = (event.get('source') or {}).get('session_id')
    thread = (event.get('observed') or {}).get('thread_id')
    def known(value):
        return isinstance(value, str) and bool(value.strip()) and value != 'UNKNOWN'
    return known(session) and known(thread) and session != thread


def token_parts(u, semantics='per_response_increment'):
    if semantics != 'per_response_increment' or not isinstance(u, dict):
        return None
    if not all(type(u.get(k)) is int and u[k] >= 0 for k in ('input_tokens','cached_input_tokens','output_tokens')):
        return None
    if u['cached_input_tokens'] > u['input_tokens'] or u.get('cache_write_input_tokens', 0) != 0:
        return None
    if 'reasoning_output_tokens' in u and (type(u['reasoning_output_tokens']) is not int or not 0 <= u['reasoning_output_tokens'] <= u['output_tokens']):
        return None
    if 'total_tokens' in u and u['total_tokens'] != u['input_tokens'] + u['output_tokens']:
        return None
    return [u['input_tokens']-u['cached_input_tokens'], u['cached_input_tokens'], u['output_tokens']]


@lru_cache(maxsize=4)
def _read_archive(path, expected, size, mtime):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('analysis archive changed')
    with zipfile.ZipFile(path) as z:
        prefix = z.namelist()[0].split('/')[0]+'/'
        def read(name):
            info=z.getinfo(prefix+name)
            if info.file_size>15_000_000: raise ValueError('oversized analysis')
            return z.read(info).decode()
        rows=[json.loads(l) for l in read('analysis/usage-by-response.jsonl').splitlines()]
        summary=json.loads(read('analysis/summary.json'))
        original=json.loads(read('summary.json'))
        pricing=json.loads(read('analysis/pricing.json'))
        excluded=json.loads(read('analysis/scope-exclusions.json'))
    keys=[(r['session_id'],r['response_id']) for r in rows]
    if len(set(keys))!=len(keys):raise ValueError('duplicate analysis identities')
    if any(token_parts(r['raw_usage']) is None for r in rows):raise ValueError('invalid analysis tokens')
    if sum(sum(token_parts(r['raw_usage'])) for r in rows)!=summary['total_observed_scoped']['total_tokens']:
        raise ValueError('analysis totals disagree')
    return rows, summary, original, pricing, excluded


def enrich_usage(root, usage, scope):
    """Match exact response identity AND token values. Broad analysis never joins scope totals."""
    usage['scope_info']={'project_id':scope.get('project_id'), 'tasks':len(scope.get('tasks',{})), 'role_executions':len(scope.get('agent_run_ids',[])),
                         'attribution':'원본에 기록된 명시적 연결', 'source':'.harness/logs/events.jsonl + tasks.yaml usage_bindings', 'collection_completeness':'UNKNOWN'}
    for r in usage['rows']:
        r.update(stage='귀속 불명', classification='분류 근거 없음', classification_reason=[], rework='재작업 귀속 불명', rework_basis='UNKNOWN')
    ref=scope.get('usage_analysis') or {}
    usage['analysis_state']='NOT_REGISTERED'
    if ref:
        try:
            p=(root/ref['path']).resolve()
            if not p.is_relative_to(root) or p.suffix!='.zip':raise ValueError('private/outside analysis')
            raw, summary, original, pricing, excluded=_read_archive(p,ref['sha256'],p.stat().st_size,p.stat().st_mtime_ns)
            indexed={(r['session_id'],r['response_id']):r for r in raw}
            matched=[]
            for r in usage['rows']:
                a=indexed.get((r['session_id'],r['response_id']))
                if not a or a.get('model')!=r.get('model') or token_parts(a['raw_usage']) != [r['normal_input'],r['cached_input'],r['output']]:continue
                matched.append(a)
                r.update(stage=LABELS.get(a.get('stage'),'귀속 불명'), classification='사후 분류', classification_reason=a.get('stage_reason',[]),
                         classification_source=ref['path']+' / analysis/usage-by-response.jsonl', rework_basis=a.get('rework_link_strength','UNKNOWN'))
                if a.get('rework_episodes'):
                    r['rework']='재작업 연결 있음'
                elif a.get('rework_link_strength') not in (None,'UNKNOWN'):
                    r['rework']='재작업 아님 · 기록 근거 있음'
            dates=sorted(r['occurred_at'] for r in raw if r.get('occurred_at'))
            matched_tokens=sum(sum(token_parts(r['raw_usage'])) for r in matched)
            usage['analysis_state']='VERIFIED_ARCHIVE'
            usage['comparison']={'source':ref, 'period':[dates[0],dates[-1]], 'generated_at':summary['generated_at'],
                'project_scope':'메모 제품과 초기 기획·디자인 선행 이력; 혼합 요청 전체 턴 제외',
                'tasks':original['tasks'], 'role_executions':original['executions'], 'requests':summary['requests'],
                'responses':len(raw), 'tokens':summary['total_observed_scoped']['total_tokens'],
                'linked_responses':len(matched), 'linked_tokens':matched_tokens,
                'posthoc_context_responses':len(raw)-len(matched), 'posthoc_context_tokens':summary['total_observed_scoped']['total_tokens']-matched_tokens,
                'mixed_excluded_responses':len(excluded['mixed_request_usage_excluded']),
                'excluded_old_requests':excluded['previous_30_requests']['excluded_count'],
                'unknown_task_responses':sum(not r.get('task_ids') or r.get('task_ids')==['UNKNOWN'] for r in raw),
                'multiple_task_context_responses':sum(len(r.get('task_ids',[]))>1 for r in raw),
                'whole_product_usage':'UNKNOWN', 'pricing_reference':pricing,
                'note':'선택 범위와 광역 분석은 직접 비교할 수 없습니다. 추가분은 응답 문맥의 사후 분류이며 선택 실행의 작업 비용에 합산하지 않습니다.'}
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
            usage['analysis_state']='UNKNOWN_CHANGED_OR_INVALID'
    rows=usage['rows']
    dates=sorted(r['occurred_at'] for r in rows if r.get('occurred_at'))
    usage['scope_info'].update(responses=len(rows),period=[dates[0],dates[-1]] if dates else [],
                               attribution='원장에 기록된 응답–작업 연결 · 단계는 별도 사후 분류')
    usage['totals']={k:sum(r[k] for r in rows) for k in ('tokens','normal_input','cached_input','output')}
    if not rows and usage.get('identity_conflicts'):
        usage['totals']={k:None for k in ('tokens','normal_input','cached_input','output')}
    usage['totals']['cost_unknown_responses']=sum(r['cost'] is None for r in rows)
    # Price reference is a dated comparison scenario, NOT an observed actual billing route.
    pricing=(usage.get('comparison') or {}).get('pricing_reference')
    if pricing:
        for r in rows:
            rates=pricing.get('scenarios',{}).get('standard_short_base')
            if r['model']==pricing.get('model') and rates:
                r['scenario_cost']=sum(r[k]*rates[rate] for k,rate in [('normal_input','normal_input'),('cached_input','cached_input'),('output','output')])/1e6
            else:r['scenario_cost']=None
    else:
        for r in rows:r['scenario_cost']=None
    usage['coverage']='선택 실행에 명시적으로 연결된 응답만 집계. 전체 v1 분모·수집 누락량은 미확인; 전체 대비 비중·수집률을 산출하지 않습니다.'
    return usage


def apply_recorded_labels(usage,tasks,events,root=None,state=None):
    from harness.dashboard_live import recorded_stage,ROLES
    names={'planning':'기획','design':'디자인','development':'개발','verification':'검증','report':'리포트','conflict':'라벨 충돌'}
    for r in usage['rows']:
        r['response_stage']=r['stage']
        r['posthoc_classification']=r['classification']
        task=tasks.get(r.get('task_id'),{})
        run=next((x for x in task.get('executions',[]) if x.get('agent_run_id')==r.get('agent_run_id')), {})
        stage,raw,basis=recorded_stage(task,run,events)
        r.update(stage=names.get(stage,'귀속 불명'),role=ROLES.get(run.get('role'),'귀속 불명'),
                 raw_role=run.get('role'),raw_stage=raw,stage_basis=basis,
                 development_area=('해당 없음' if run.get('role')!='development' else {'kmp':'KMP 공통','web':'Web','server':'Server','android':'Android','ios':'iOS'}.get(run.get('development_area'),'전문 영역 라벨 미수집')),parent_task_id=run.get('parent_task_id'),
                 classification='명시 연결 · 시작 당시 작업 단계' if stage else '작업 단계 근거 없음')
        if root is not None and run:
            from harness.usage_context import resolve,PURPOSES,REPETITIONS,ACTORS,development_owners
            ctx=resolve(root,state or {'tasks':tasks},task,run,events)
            r.update(purpose=PURPOSES[ctx['purpose']],purpose_code=ctx['purpose'],
                     repetition=REPETITIONS[ctx['repetition']],actor=ACTORS[ctx['actor']],
                     development_owner=({'not_applicable':'해당 없음','unknown':'개발 담당 기록 없음',**development_owners()}).get(ctx['development_owner']),
                     usage_context=ctx)
    usage['scope_info']['attribution']='원장 명시 연결 · 단계=시작 당시 작업 계약, 역할=해당 실행; 응답 활동 사후 분류는 별도 축'
    return usage
