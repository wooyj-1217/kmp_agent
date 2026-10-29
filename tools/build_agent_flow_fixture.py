"""Synthetic visual states only: no model, product app, platform or server calls."""
from pathlib import Path
import json,sys
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.tasks import Tasks
from harness.logging import Logger

root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
if (root/'.harness/tasks/tasks.yaml').exists():raise SystemExit('Existing fixture preserved; use a new empty directory')
(root/'.harness').mkdir(exist_ok=True);(root/'.harness/project.json').write_text(json.dumps({'project_id':'FLOW-SYNTHETIC','project_path':'..'}));(root/'fixture.md').write_text('# 합성 화면 시험\n실제 모델 호출·제품 요구 충족·플랫폼 검증이 아니다. 상태·관계·시각은 합성 주입한다.\n')
rid=Logger(root).start('HARNESS_BUILD','orchestrator','합성 에이전트 흐름 화면 시험: 실제 모델 호출 없음');m=Tasks(root,rid);cases=[];counter=0

def add(case,suffix,role,title,mode='planned',area=None,parent=None,deps=None):
 global counter
 counter+=1;tid=case+'-'+suffix
 m.register(case,tid,role,title,'합성 상태 연결 시험; 실제 모델·제품 인수 근거 아님',[{'id':'CHECK','description':'합성 상태 투영 확인','required':True}],['fixture.md'],dependencies=deps or [],max_attempts=3,execution_scope='documentation',pipeline_stage={'planning':'planning','design':'design','development':'development','verification':'verification'}[role])
 if mode=='done':
  m.ready(tid);w=m.begin(tid,role,execution_mode='local_check');m.submit(tid,w['agent_run_id'],['fixture.md'],'합성 완료 상태');r=m.begin(tid,'verification',review=True,execution_mode='local_check');m.review(tid,r['agent_run_id'],[{'criterion_id':'CHECK','result':'PASS','evidence':'fixture.md'}],'합성 상태용 자료 확인. 실제 제품 검증 아님.')
 elif mode in {'active','stale','failed'}:
  m.ready(tid);w=m.begin(tid,role,execution_mode='local_check')
  if mode=='failed':m.fail(tid,w['agent_run_id'],'합성 호출 실패 · 시도 상한 도달')
 def decorate(state):
  t=state['tasks'][tid];t['synthetic']=True
  if area:t.update(development_area=area,parent_task_id=parent,delegation_state='FAILED' if mode=='failed' else 'RUNNING' if mode in {'active','stale'} else 'PLANNED')
  if mode in {'active','stale','failed'}:
   work=next(r for r in t['executions'] if r['kind']=='work');work['execution_mode']='independent_process'
   when=(datetime.now(timezone.utc)-timedelta(hours=2 if mode=='stale' else 0)).isoformat();work['started_at']=when
   t['synthetic_runtime']={'independent_model_spawned':True,'pid':'SYNTHETIC-NO-PROCESS','started_at':when,'source':'synthetic_runtime; not role_process evidence'}
   if mode=='failed':
    t['synthetic_runtime'].update(finished_at=when,exit_code=7,process_error='SYNTHETIC invocation failure');t['executions']=[dict(work,agent_run_id=work['agent_run_id']+'-history1'),dict(work,agent_run_id=work['agent_run_id']+'-history2'),work]
  m._event(state,'synthetic_state_injected',t,observed={'synthetic':True,'mode':mode,'area':area})
 m._mutate('synthetic_fixture',decorate,tid);return tid

def config_qa(tid,target,stage,repair=None):
 def op(s):s['tasks'][tid]['qa_config']={'stage':stage,'target_task_id':target,'attempts':[],'repair_task_id':repair}
 m._mutate('synthetic_qa_target',op,tid)

def case(case_id,name,build,decisions=None,historical=False):
 before=set(m.read()['tasks']);build(case_id);members=[t for t in m.read()['tasks'] if t not in before];state=m.read()
 cases.append({'id':case_id,'name':name+' · 합성','goal':name,'project_id':'FLOW-SYNTHETIC','work_type':'HARNESS_BUILD','tasks':{t:{'stage':state['tasks'][t]['pipeline_stage'],'required':True} for t in members},'agent_run_ids':[r['agent_run_id'] for t in members for r in state['tasks'][t]['executions']],'provenance':{'kind':'SYNTHETIC','group_kind':'HISTORICAL_RUN' if historical else 'SYNTHETIC_TEST','basis':'fixture.md'},'decisions':decisions or []})

def design(c):
 d=add(c,'design','design','저장 실패 상태 디자인',mode='done');q=add(c,'qa','verification','실패·복구 동선 독립 검토',mode='active');config_qa(q,d,'design')
case('design-qa','기획·디자인 단계 QA 검토',design)

def parallel(c):
 p=add(c,'coord','development','개발 작업 분배·통합 준비')
 for area,title in [('kmp','공유 저장 정책 구현'),('web','브라우저 오류 복구 구현'),('server','저장 API 구현')]:add(c,area,'development',title,mode='active',area=area,parent=p)
case('parallel','영역별 병렬 개발',parallel)

def waiting(c):
 p=add(c,'contract','planning','저장 API 계약 확정');w=add(c,'web','development','계약 확정 후 화면 API 연결',area='web',deps=[p])
case('waiting','선행 계약 대기',waiting)

def rework(c):
 p=add(c,'coord','development','Web 결함 수정 통합');w=add(c,'web','development','중복 저장 방지 수정',mode='active',area='web',parent=p);q=add(c,'qa','verification','중복 저장 재검증 대기');config_qa(q,p,'retest',p)
 def op(s):
  issue={'id':'SYN-ISSUE-1','feature_id':c,'task_id':p,'qa_task_id':q,'owner':'development','kind':'policy','observed':'중복 저장','expected':'동일 시도 한 건','severity':'MAJOR','evidence':m.artifact('fixture.md'),'synthetic':True,'status':'OPEN','history':[],'assigned_task_id':w};s.setdefault('issues',[]).append(issue)
 m._mutate('synthetic_qa_return',op,p)
case('rework','QA 반환 → 수정 → 재검증',rework)

def partial(c):
 add(c,'server','development','정책 미확정으로 저장소 구현 대기',area='server')
 tid=c+'-server'
 def op(s):s['tasks'][tid].update(state='BLOCKED',blocked_reason='저장 정책 결정 필요')
 m._mutate('synthetic_block',op,tid);add(c,'web','development','독립적인 목록 접근성 수정',mode='active',area='web')
case('partial','일부 차단·무관 작업 진행',partial)
case('decision','사용자 범위 결정 대기',lambda c:add(c,'policy','planning','초안 보존 범위 결정 대기'),[{'requires_human':True,'status':'OPEN','question':'예외 복구 범위를 확정할까요? (합성 질문)','basis':'fixture.md'}])

def platform(c):
 t=add(c,'shared','development','공유 검증 함수 작성',mode='done',area='kmp')
 def op(s):s.setdefault('execution_plans',{})['SYN-TARGETS']={'task_ids':[t],'goal':'공유 검증과 플랫폼 검증 분리','targets':['Mobile Sample','Browser Sample']}
 m._mutate('synthetic_target_scope',op,t)
case('platform','필수 대상 빌드·실행·QA 미검증',platform)

def failed(c):
 t=add(c,'server','development','API 담당 호출 실패와 재시도 상한',mode='failed',area='server');q=add(c,'qa','verification','구현 입력 부족으로 미검증');config_qa(q,t,'implementation')
case('failed','호출 실패·재시도 상한',failed)
case('stale','오래된 활동·상태 확인 필요',lambda c:add(c,'worker','development','오래된 실행 기록 확인',mode='stale',area='web'))
case('history','완료된 과거 작업',lambda c:add(c,'planning','planning','합성 기획 기준 정리',mode='done'),historical=True)
(root/'.harness/dashboard-scopes.json').write_text(json.dumps({'project_name':'합성 흐름 화면 시험 · 실제 모델 실행 없음','scopes':cases},ensure_ascii=False,indent=2))
# Simulate a stale clock only in this newly generated synthetic fixture.
p=root/'.harness/logs/events.jsonl';es=[json.loads(l) for l in p.read_text().splitlines()];stale=next(t for t in m.read()['tasks'].values() if t['task_id']=='stale-worker');aid=stale['executions'][0]['agent_run_id'];old=stale['executions'][0]['started_at']
for e in es:
 e.setdefault('source',{})['synthetic']=True
 if e.get('agent_run_id')==aid:e['timestamp']=old
p.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in es))
print(json.dumps({'root':str(root),'cases':len(cases),'actual_model_calls':0,'data_origin':'SYNTHETIC'},ensure_ascii=False))
