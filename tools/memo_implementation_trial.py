"""Run real model QA/repair against the ordinary isolated memo case."""
import argparse,json,shutil
from pathlib import Path
from harness.qa import QA
from harness.qa_repair import owner_repair
from harness.delegation import Development
from tools.memo_real_trial import manager,NATIVE,NODE

def configure_fix(m):
 if m.read()['tasks'].get('FIX-WEB',{}).get('development_delegation'):return
 refs={'planning':'planning.md','design':'design/design.md','api':'api.md','policy':'policy.md'}
 if 'FIX-WEB' not in m.read()['tasks']:
  m.register('MEMO-TRIAL','FIX-WEB','development','Repair independent QA Web findings','Only Web files; no change to policy, shared/server or settings',[{'id':'AC-FIX','required':True,'description':'Scoped correction independently built then QA retested'}],list(refs.values())+['original-request.md'],max_attempts=2,work_type='HARNESS_BUILD',execution_scope='code_implementation',pipeline_stage='development')
  m.configure_development('FIX-WEB',refs,['web'],api_required=True,service_version='memo-trial-v1')
 Development(m.root,m.run_id).configure('FIX-WEB',[{'task_id':'FIX-WEB-CHILD','area':'web','title':'Address actual implementation QA Web findings','goal':'Read the original request, current code and QA findings in evidence/qa-return.json plus browser/raw evidence. Repair only the actual Web defects returned by independent QA; inspect generated Kotlin module sources if available, never change frozen API policy or other modules. COMPLETE means implemented correction; independently record NOT_RUN if browser/sandbox prevents verification, never claim visual PASS. Coordinator runs syntax/HTTP/browser after you. Preserve all original draft/retry policy. All shell commands use rtk proxy.','requirement_ids':['REQ-01','REQ-03','REQ-04'],'acceptance_ids':['AC-FIX-WEB'],'allowed_paths':['web'],'dependencies':[],'verification_commands':[['rtk','proxy',NODE,'--check','web/app.js']],'out_of_scope':['shared','server','root settings','requirements','design','fake success','Git commits'],'max_attempts':2}],{'evidence':['architecture.md'],'modules':{'web':['web']},'ui_owners':{'web':'web'}},{p:'FIX-WEB' for p in ('build.gradle.kts','settings.gradle.kts','gradle.properties')},[['rtk','proxy',NODE,'--check','web/app.js']],max_parallel=1,executable=NATIVE,timeout=600)

def run(root,stage):
 m=manager(root);q=QA(root,m.run_id)
 if stage=='qa':
  shutil.copy2(root/'.worker-cache/e2e/result.json',root/'evidence/http-before.json')
  configure_fix(m)
  q.configure('QA-IMPLEMENTATION-R2','implementation','IMPLEMENT-R2',['original-request.md'],[
   {'id':'IQ-SHARED-SERVER','required':True,'description':'Independently inspect actual Kotlin shared validation+tests, Ktor routes, exact source and raw evidence/http-before.json. Assess REQ-01/02/04/05. Distinguish real HTTP execution from server:test NO-SOURCE. Do not treat build success as proof of Web behavior. Write evidence under qa-tools.'},
   {'id':'IQ-WEB-FLOW','required':True,'description':'Inspect real Web code and attached actual browser image plus raw evidence/browser-before.json against original request and design. Is the user able to save through Web and see the list using real shared JS? Independently identify actual cause if any from source and execution evidence. Return development findings with precise code_ref and immutable basis; do not modify product files. No actual Web behavior PASS from source or HTTP alone.'}],max_attempts=2,repair_task_id='FIX-WEB',executable=NATIVE,timeout=600,images=['evidence/browser-before.jpg'])
  result=q.execute('QA-IMPLEMENTATION-R2')
  report=json.loads((root/result['report']['path']).read_text());(root/'evidence/qa-return.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
  return result
 if stage=='repair':
  attempts=m.read()['tasks']['QA-IMPLEMENTATION-R2']['qa_config']['attempts'];assert attempts[-1]['outcome']!='PASS','do not manufacture a repair'
  report=json.loads((root/attempts[-1]['report']['path']).read_text());q._workflow_task_id='QA-IMPLEMENTATION-R2'
  return owner_repair(q)(attempts[-1],report['worker_report'],root)
 if stage in {'retest','final-review'}:
  q.configure('QA-IMPLEMENTATION-FINAL' if stage=='final-review' else 'QA-IMPLEMENTATION-R2-RETEST','retest','IMPLEMENT-R2',['original-request.md'],[
   {'id':'IQ-FINAL-CODE','required':True,'description':'Independently inspect final actual shared/Web/Ktor source, evidence/http-after.json and browser-after.json. Check final hashes match actual code, original input contract and all applicable acceptance tests. Prior PASS is not inherited across code changes. Each evidence field must be exactly ONE existing relative file path, never semicolon-separated paths. Put extra references inside your evidence file. You are independently reviewing actual executed evidence, not claiming you personally executed Gradle. Inspect prior qa-tools reports only as historical evidence. Resolve only explicit previous_findings issue IDs you directly verified; describe unexecuted platforms.'},
   {'id':'IQ-FINAL-UI','required':True,'kind':'visual','description':'Review attached actual browser saved-memo capture evidence/browser-after.jpg against approved design and original request. Correlate actual browser-after.json actions and API proof; image alone not E2E. Evidence path must be the actual JPG. Do not claim unexecuted loading/error/360px/mobile states. Inspect whether previous blocking Web findings are truly resolved.'}],max_attempts=1,executable=NATIVE,timeout=600,images=['evidence/browser-after.jpg','evidence/browser-error.jpg'],context_files=['evidence/http-after.json','evidence/browser-after.json','evidence/browser-error.json','evidence/qa-return.json'])
  return q.execute('QA-IMPLEMENTATION-FINAL' if stage=='final-review' else 'QA-IMPLEMENTATION-R2-RETEST')
 raise ValueError(stage)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['qa','repair','retest','final-review']);p.add_argument('--root',required=True);a=p.parse_args();print(json.dumps(run(Path(a.root).resolve(),a.stage),ensure_ascii=False,indent=2))
