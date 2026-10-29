"""Synthetic review cases only. No product data copied or old runs reassigned."""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def write_fixture(root):
    root = Path(root); (root / '.harness/tasks').mkdir(parents=True, exist_ok=True)
    (root / '.harness/logs').mkdir(parents=True, exist_ok=True)
    (root / 'docs').mkdir(exist_ok=True)
    (root / 'docs/requirements.md').write_text('# 합성 프로젝트 승인 기준\nCompose Android/iOS · Ktor 서버 · 웹 UI 미정\nmodel/domain 공통, 서버와 클라이언트의 전용 domain/data/presentation 경계\n')
    (root / 'docs/prototype.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><style>body{font:18px system-ui;background:#f5f7fb;padding:24px}article{background:white;border:1px solid #ddd;padding:20px;border-radius:10px}textarea{width:95%;height:100px}</style><h1>합성 메모 시안</h1><article><a>목록으로</a><h2>메모 작성</h2><textarea placeholder="내용을 입력하세요"></textarea><p>0 / 500</p><button disabled>저장</button><p>미저장 상태에서 이동 시 확인이 필요합니다.</p></article></html>')
    def ref(path, **extra):
        return {'path': path, 'sha256': hashlib.sha256((root / path).read_bytes()).hexdigest(), **extra}
    tasks={}; scopes=[]; events=[]
    scenarios=[('normal','정상 진행'),('parallel','여러 단계 동시 진행'),('recheck','수정·재검증'),('decision','사람 결정 대기'),('blocked','BLOCKED 종료')]
    for case, name in scenarios:
        tid=case+'-work'; rid=case+'-attempt'; reviewid=case+'-review'
        t={'task_id':tid,'project_id':'SYNTHETIC','feature_id':'DASHBOARD-REVIEW','work_type':'PRODUCT','title':'저장 상태 화면 구현','role':'development','scope':'승인 시안의 빈 입력·저장 중·불확실 저장 복구 상태 구현','state':'IN_PROGRESS','execution_scope':'code_implementation','criteria':[{'id':'STATE-1','required':True,'description':'승인 상태와 실제 화면 비교'}], 'inputs':[ref('docs/requirements.md')], 'outputs':[], 'dependencies':[], 'executions':[{'agent_run_id':rid,'role':'development','started_at':'2026-10-27T00:00:00Z','ended_at':None}], 'reviews':[]}
        s={'id':case,'name':name+' · 합성 예시','project_id':'SYNTHETIC','work_type':'PRODUCT','goal':'세 플랫폼에서 동일한 저장 경험을 구현합니다.','scope':'합성 데이터로 조회 경계와 상태 표현만 확인','agreement_summary':'목표: Compose Android/iOS·Ktor. 웹 UI는 결정 전입니다. 현재 대체 구현은 승인 목표가 아닙니다.','tasks':{tid:{'stage':'development','required':True,'next_action':'상태별 화면을 승인 시안과 비교'}}, 'agent_run_ids':[rid], 'stage_requirements':{'development':{'task_ids':[tid],'basis':'합성 승인 기준 STATE-1'}}, 'approved_baselines':[ref('docs/requirements.md',label='개발에 적용한 승인 기준',task_ids=[tid])], 'artifacts':[ref('docs/requirements.md',label='요구사항',kind='요구사항',approval='적용 승인본 · 합성'),ref('docs/prototype.html',label='저장 화면 프로토타입',kind='디자인',approval='최신 작성본 · 검토 전')], 'decisions':[]}
        if case=='parallel':
            t2=copy.deepcopy(t); t2.update(task_id='parallel-design',title='저장 중 상태 디자인 검토',role='design');t2['executions']=[{'agent_run_id':'parallel-design-run','role':'design','started_at':'2026-10-27T00:01:00Z','ended_at':None}];tasks[t2['task_id']]=t2
            s['tasks'][t2['task_id']]={'stage':'design','required':True};s['agent_run_ids'].append('parallel-design-run')
        if case=='recheck':
            t['state']='DONE';t['executions'][0]['ended_at']='2026-10-27T00:03:00Z';t['executions'].append({'agent_run_id':reviewid,'role':'verification','started_at':'2026-10-27T00:02:00Z','ended_at':'2026-10-27T00:03:00Z'})
            t['reviews']=[{'agent_run_id':reviewid,'results':[{'criterion_id':'STATE-1','result':'PASS'}]}];t['validation_status']={reviewid:{'state':'RECHECK_REQUIRED','reasons':['승인 시안 변경: 저장 중 버튼과 이탈 확인 상태를 다시 비교해야 합니다']}};s['agent_run_ids'].append(reviewid)
        if case in ('decision','blocked'):
            t['state']='BLOCKED';t['executions'][0]['ended_at']='2026-10-27T00:03:00Z';t['blocked_reason']='웹 UI 범위가 결정되지 않아 화면 공유 구현을 시작할 수 없습니다'
        if case=='decision':
            s['decisions']=[{'status':'OPEN','requires_human':True,'question':'웹에도 공통 UI를 적용할까요?','impact':'웹 화면 구현 및 공유 모듈 경계','basis':'합성 기준의 웹 UI 미정 항목'}]
        if case=='blocked':
            s['outcome']={'status':'BLOCKED','summary':'동작 데모는 확보했지만 승인 목표의 필수 조건을 충족하지 못했습니다.','achieved':'목록·저장 기능의 제한된 동작 확인','unmet':'합의 스택 준수·상태별 시각 비교','next':'승인 목표의 구현 계획과 미검증 기준을 연결'}
        tasks[tid]=t; scopes.append(s)
        for n in range(2):
            events.append({'event_type':'model_usage','timestamp':f'2026-10-27T0{n}:00:00Z','agent_run_id':rid,'task_id':tid,'harness':{'version':'0.2.0 (합성 관측)'},'source':{'session_id':'fixture'},'observed':{'usage_semantics':'per_response_increment','response_id':case+str(n),'model':'synthetic-model','usage':{'input_tokens':1000,'cached_input_tokens':400,'output_tokens':200}}})
    tasks['unrelated']={'task_id':'unrelated','project_id':'OTHER','work_type':'HARNESS_BUILD','title':'연결 시험 · 제품 구현 아님','state':'DONE','execution_scope':'input_interpretation_only'}
    (root / '.harness/tasks/tasks.yaml').write_text(json.dumps({'tasks':tasks},ensure_ascii=False))
    (root / '.harness/dashboard-scopes.json').write_text(json.dumps({'project_name':'메모 저장 경험 · 합성 검토용','scopes':scopes},ensure_ascii=False,indent=2))
    (root / '.harness/logs/events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args();write_fixture(args.root)
