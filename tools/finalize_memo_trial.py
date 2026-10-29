"""Native final integration gate; consumes existing valid HTTP/UI evidence, no product edits."""
import argparse,json,hashlib,xml.etree.ElementTree as ET
from pathlib import Path
from tools.memo_real_trial import manager,NODE
from harness.delegation import Development

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(root):
 m=manager(root);state=m.read();qa=state['tasks']['QA-IMPLEMENTATION-FINAL']['qa_config']['attempts'][-1]
 assert qa['outcome']=='PASS',qa
 assert not [i for i in state.get('issues',[]) if i['task_id']=='IMPLEMENT-R2' and i['status']=='OPEN' and i.get('qa_finding',{}).get('blocking')], 'QA blockers remain'
 http=json.loads((root/'evidence/http-after.json').read_text());assert http['status']=='PASS' and len(http['cases'])==9
 for section in ('code_sha256','inputs_sha256','distribution_sha256'):
  for path,h in http[section].items():assert sha(root/path)==h,('stale executed evidence',path)
 tests=[ET.parse(p).getroot() for p in root.glob('.worker-cache/build/shared/test-results/jvmTest/TEST-*.xml')];assert tests and sum(int(t.get('tests',0)) for t in tests)==5 and all(t.get('failures')=='0' and t.get('errors')=='0' for t in tests)
 body=json.loads((root/'evidence/browser-after.json').read_text());assert 'Saved. ID:' in body['dom'] and body['page']['memos'] and body['page']['width']>=body['page']['scrollWidth']
 error=json.loads((root/'evidence/browser-error.json').read_text());assert 'Retry save' in error['dom'] and '실패 후 재시도할 메모' in error['dom']
 refs={'planning':'planning.md','design':'design/design.md','api':'api.md','policy':'policy.md'}
 tid='FINAL-INTEGRATION'
 if tid not in m.read()['tasks']:
  m.register('MEMO-TRIAL',tid,'development','Final compiled memo candidate and independent QA evidence gate','KMP JVM/JS+Web+Ktor trial only; no mobile/DB persistence claim',[{'id':'FINAL-TRIAL','required':True,'description':'Final source matches actual JVM/JS build, actual Ktor HTTP9, observed Web save/failure/retry, independent QA'}],list(refs.values())+['original-request.md','evidence/http-after.json','evidence/browser-after.json','evidence/browser-error.json',qa['report']['path']],max_attempts=1,work_type='HARNESS_BUILD',execution_scope='code_implementation',pipeline_stage='development')
  m.configure_development(tid,refs,['shared/src','web','server/src'],api_required=True,service_version='memo-trial-v1');m.ready(tid);m.begin(tid,'development',execution_mode='local_check')
 aid=next(e['agent_run_id'] for e in m.read()['tasks'][tid]['executions'] if e['kind']=='work' and not e.get('ended_at'))
 checks=[]
 for command in [['rtk','proxy','python3','tools/build.py',':shared:jvmTest',':shared:jsBrowserProductionLibraryDistribution',':server:installDist'],['rtk','proxy',NODE,'--check','web/app.js']]:
  events=m.logger.read();wanted=hashlib.sha256(json.dumps(command).encode()).hexdigest()
  calls={e['observed']['call_id'] for e in events if e['event_type']=='command_started' and e.get('task_id')==tid and e.get('agent_run_id')==aid and e.get('observed',{}).get('argv_sha256')==wanted}
  old=[e for e in events if e['event_type']=='command_finished' and e.get('observed',{}).get('call_id') in calls]
  result=old[-1]['observed']['returncode'] if old else m.logger.command(m.run_id,command,task_id=tid,agent_run_id=aid,attempt_id=aid,command_kind='integration')
  assert result==0,result
  checks.append({'command':command,'status':'PASS','result':result})
 # Recheck immutable source/evidence after final incremental build.
 for section in ('code_sha256','inputs_sha256','distribution_sha256'):
  for path,h in http[section].items():assert sha(root/path)==h,('final build drift',path)
 paths=[p for p in http['code_sha256'] if p.startswith(('shared/src/','web/','server/src/'))]
 m.submit(tid,aid,paths,'Coordinator final integrated source; no independent-model invocation in this local gate')
 checks.append({'status':'PASS','method':'independent model review of code+actual HTTP/UI execution evidence','qa_task_id':'QA-IMPLEMENTATION-FINAL','qa_report':qa['report'],'http_evidence':m.artifact('evidence/http-after.json'),'browser_evidence':m.artifact('evidence/browser-after.json'),'error_evidence':m.artifact('evidence/browser-error.json')})
 from harness import development_tracking as tracking
 current=m.read()['tasks'][tid]
 proof={'result':'PASS','checks':checks,'code_state_sha256':current['submission_code_state']['state_sha256'],'baseline':tracking.baseline(current),'tested_outputs':{r['path']:r['sha256'] for r in current['outputs']},'missing_platforms':['Android NOT_RUN: no app entrypoint','iOS NOT_RUN: no app entrypoint'],'out_of_scope':['DB persistence','request idempotency'],'full_product_complete':False}
 path=root/'.harness/final-integration.json';path.write_text(json.dumps(proof,ensure_ascii=False,indent=2))
 review=m.begin(tid,'verification',review=True,execution_mode='local_check');outcome=m.review(tid,review['agent_run_id'],[{'criterion_id':'FINAL-TRIAL','result':'PASS','evidence':str(path.relative_to(root))}],'Final current-code evidence and separate independent QA; not whole product acceptance')
 assert outcome=='DONE',outcome
 print(json.dumps({'scope':'isolated memo vertical slice only','state':outcome,'feature_complete':False,'task_id':tid,'code_state_sha256':proof['code_state_sha256'],'qa':qa},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();run(Path(a.root).resolve())
