"""Controller-only blind fixture preparation; this script and oracle never enter QA workspace."""
import argparse,json,shutil,subprocess
from pathlib import Path
from harness.logging import Logger
from harness.tasks import Tasks
from harness.qa import QA
from harness.delegation import manifest,digest
from harness.qa_repair import execute_with_owner
from tools.memo_real_trial import NATIVE

def prepare(source,root,kind):
 if root.exists():raise ValueError('new case required')
 root.mkdir(parents=True)
 for name in manifest(source):
  target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,target)
 # Only trial-local infrastructure and immutable requirements; no hidden answer copied.
 (root/'.kmp-agent').mkdir(exist_ok=True);(root/'.kmp-agent/project.json').write_text(json.dumps({'project_id':root.name,'project_path':'..'}))
 oracle={'kind':kind,'source_root':str(source),'source_manifest':manifest(source),'injection':[]}
 if kind=='design':
  p=root/'design/design.md';old=p.read_text();a='| Save error | Retain exact draft and existing records; announce failure. Retry save explicitly starts another attempt; never automatically retry. Editing dismisses stale failure and returns to Save memo. |';b='| Save error | Clear the editor immediately and automatically retry the previous request in the background until successful. |';assert a in old;p.write_text(old.replace(a,b));oracle['injection']=[{'path':'design/design.md','before_sha256':digest(source/'design/design.md'),'after_sha256':digest(p),'replacement':b,'expected_requirement':'REQ-03','answer':'Discarding text and automatic retry contradict immutable policy.'}]
 for args in [('init','-q'),('config','user.name','Isolated Memo Evaluation'),('config','user.email','trial@example.invalid'),('add','.'),('commit','-qm','isolated case inputs')]:subprocess.run(['rtk','proxy','git',*args],cwd=root,check=True,capture_output=True)
 rid=Logger(root).start('HARNESS_BUILD','verification','Independent memo quality review of frozen artifacts')
 m=Tasks(root,rid);m.configure_runtime_limits(max_parallel=2,max_executions=8)
 (root/'.harness/trial.json').write_text(json.dumps({'run_id':rid,'root':str(root)}))
 private=source.parent/'agent-workflows'/(root.name+'-oracle.json');private.parent.mkdir(exist_ok=True);private.write_text(json.dumps(oracle,ensure_ascii=False,indent=2))
 return m

def main():
 p=argparse.ArgumentParser();p.add_argument('kind',choices=['design']);p.add_argument('--source',required=True);p.add_argument('--root',required=True);a=p.parse_args();source=Path(a.source).resolve();root=Path(a.root).resolve();m=prepare(source,root,a.kind)
 m.register('MEMO-QUALITY','ARTIFACT','design','Memo interaction design','Review actual current design artifacts',[{'id':'AC-DESIGN','required':True,'description':'REQ-03 state coverage and consistent behavior'}],['original-request.md','planning.md','api.md','policy.md'],max_attempts=1,work_type='HARNESS_BUILD',execution_scope='documentation',pipeline_stage='design')
 m.ready('ARTIFACT');aid=m.begin('ARTIFACT','design',execution_mode='local_check')['agent_run_id'];m.submit('ARTIFACT',aid,['design/design.md','design/prototype.html','design/capture.png'],'Imported design artifact for independent review; no quality claim',design_status={'specification':'COMPLETE','mockup':'COMPLETE','visual_review':'NOT_RUN'})
 m.register('MEMO-QUALITY','REPAIR','design','Address independent design review findings','Only declared design outputs; immutable original policy',[{'id':'AC-DESIGN','required':True,'description':'Independent QA confirms fixed state specification'}],['original-request.md','planning.md'],max_attempts=2,work_type='HARNESS_BUILD',execution_scope='documentation',pipeline_stage='design')
 q=QA(root,m.run_id);q.configure('QUALITY-REVIEW','design','ARTIFACT',['original-request.md'],[{'id':'DESIGN-CONSISTENCY','required':True,'description':'Independently inspect all design state transitions against immutable request and actual prototype. Check loading/empty/invalid/saving/success/error/retry, body retention, accessibility. Report real contradictions/gaps; do not invent behavior. Inspect provided capture with image tools if possible; distinguish source vs actual visual evidence.'}],max_attempts=2,repair_task_id='REPAIR',executable=NATIVE,timeout=600)
 print(json.dumps(execute_with_owner(q,'QUALITY-REVIEW'),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
