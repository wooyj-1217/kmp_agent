"""Derived read-only cross-case audit. Native ledgers and executed artifacts stay canonical."""
import argparse,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
from tools.verify_agent_trials import load,processes,usage_proof
from harness.qa import QA
from tools.memo_real_trial import manager,NATIVE

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(base):
 result={'observed_at':datetime.now(timezone.utc).isoformat(),'scope':'isolated real memo trial and separate controlled evaluations; not demo v1 completion','cases':{},'not_run':['Android/iOS apps: no entry points in this fixture, not a claimed environment failure','360px layout: actual viewport measured400','keyboard traversal/full accessibility regression','DB/restart persistence and idempotency outside memory-only trial'],'provenance':'original-request.md and public user-request.md are synthetic derived trial specifications, not private user text. Historical private-user audits are not reproduced by this public fixture. Earlier runs are not retroactively relabeled.'}
 for name,kind in [('memo-real-20261027','ordinary development; naturally discovered Web defect'),('memo-review-a2-20261027','separate controlled design evaluation'),('memo-review-b-20261027','separate controlled API evaluation')]:
  root=base/name;state,events=load(root);rid=json.loads((root/'.harness/trial.json').read_text())['run_id'];proc=processes(events)
  assert all(p['exit_code']==0 and p['independent_model_spawned'] for p in proc)
  qa={k:{'attempts':[{'outcome':a['outcome'],'agent_run_id':a['agent_run_id'],'report':a['report'],'resolved_issue_ids':a.get('resolved_issue_ids',[])} for a in t['qa_config']['attempts']],'stage':t['qa_config']['stage']} for k,t in state['tasks'].items() if t.get('qa_config')}
  owners={k:{'area':t.get('development_area'),'parent_task_id':t.get('parent_task_id'),'state':t['state'],'actual_integrated_files':[r['path'] for r in t.get('outputs',[])],'reported_unresolved':t.get('reported_unresolved',[]),'change_reference':t.get('change_reference')} for k,t in state['tasks'].items() if t.get('development_area')}
  case={'root':str(root),'kind':kind,'run_id':rid,'actual_model_processes':proc,'qa':qa,'owners':owners,'issues':[{'id':i['id'],'task_id':i['task_id'],'status':i['status'],'kind':i.get('qa_finding',{}).get('kind'),'owner':i.get('owner'),'resolution':i.get('resolution')} for i in state.get('issues',[])],'usage':usage_proof(root,rid)}
  for task,t in state['tasks'].items():
   if t.get('development_area'):
    for changed in [r['path'] for r in t.get('outputs',[])]:assert any(changed==p or changed.startswith(p+'/') for p in t['development_tracking']['code_paths']),(task,changed)
  if name!='memo-real-20261027':
   oracle=base/'agent-workflows'/(name+'-oracle.json');assert oracle.exists();case['controller_oracle']={'path':str(oracle),'sha256':sha(oracle),'included_in_qa_workspace':False}
   for folder in (root/'.harness/qa').glob('*/*/workspace'):
    assert not list(folder.rglob('*oracle.json'))
    assert not (folder/'tools/memo_blind_trial.py').exists() and not (folder/'tools/memo_server_review.py').exists()
   initial_task='QUALITY-REVIEW' if name=='memo-review-a2-20261027' else 'SERVER-QA'
   first=state['tasks'][initial_task]['qa_config']['attempts'][0]['agent_run_id']
   trace=(root/'.harness/qa'/initial_task/first/'runtime/stdout.jsonl').read_text()
   case['initial_qa_tooltrace_oracle_reference']=any(value in trace for value in (str(oracle),'memo_blind_trial.py','memo_server_review.py'))
   assert not case['initial_qa_tooltrace_oracle_reference'],'potential blind input disclosure in actual tool trace'
   case['blinding_checked']='Controller script/oracle absent from isolated QA workspace; no planted location or answer in QA config. Original expected behavior remains available.'
  else:
   http=json.loads((root/'evidence/http-after.json').read_text());assert http['status']=='PASS' and len(http['cases'])==9
   for section in ('code_sha256','inputs_sha256','distribution_sha256'):
    assert all(sha(root/path)==value for path,value in http[section].items()),section
   assert state['tasks']['QA-IMPLEMENTATION-FINAL']['qa_config']['attempts'][-1]['outcome']=='PASS'
   case['final_http']={'path':'evidence/http-after.json','sha256':sha(root/'evidence/http-after.json'),'cases':len(http['cases']),'code_sha256':http['code_sha256'],'inputs_sha256':http['inputs_sha256']}
   case['final_integration']=state['tasks'].get('FINAL-INTEGRATION',{}).get('state','UNKNOWN')
  result['cases'][name]=case
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--goal-review',action='store_true');a=p.parse_args();base=Path(a.base).resolve();result=audit(base);out=base/'agent-workflows/memo-real-proof.json';out.parent.mkdir(exist_ok=True)
 if out.exists():
  prior=out.read_bytes();history=out.parent/'history';history.mkdir(exist_ok=True);(history/(hashlib.sha256(prior).hexdigest()+'.json')).write_bytes(prior)
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(out)
 if a.goal_review:
  root=base/'memo-real-20261027';(root/'evidence/case-audit.json').write_text(out.read_text());m=manager(root);q=QA(root,m.run_id)
  q.configure('QA-USER-GOAL','retest','IMPLEMENT-R2',['user-request.md'],[{'id':'USER-GOAL','required':True,'description':'Independently compare the public synthetic trial specification to actual current implementation and native cross-case execution evidence. Read evidence/input-provenance.md: both public request files are derived trial specifications, NOT private user text or approved product policy. Historical private-user audits are not reproduced by this public fixture. Earlier agents used that trial specification. Inspect frozen case-audit.json, raw HTTP/browser evidence and current code yourself. Distinguish actual model execution, deterministic tests, real build/HTTP and UI observation. Confirm ordinary vs controlled cases and retained NOT_RUN/format errors, ownership scope, and current-code linkage. Do not claim Android/iOS/DB persistence/360px success. If this limited experiment does not cover the user goal, report the actual remaining gap; do not invent PASS. Evidence field must be exactly one existing relative file path, no semicolon lists.'}],max_attempts=1,executable=NATIVE,timeout=600,context_files=['evidence/input-provenance.md','original-request.md','evidence/case-audit.json','evidence/http-after.json','evidence/browser-after.json','evidence/browser-error.json'])
  print(json.dumps(q.execute('QA-USER-GOAL'),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
