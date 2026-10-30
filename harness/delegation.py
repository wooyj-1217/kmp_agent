"""Development coordinator: native tasks, isolated model workers, verified integration.

There is one state ledger (Tasks), one execution ID (agent_run_id), and one
response attribution path. Area is an axis, never a replacement role.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from harness import logging
from harness.tasks import Tasks
from harness import development_tracking as tracking

AREAS={'kmp','web','server','android','ios'}

def normalized(value):
    if not isinstance(value,str) or not value or value.startswith('/') or any(x in value.split('/') for x in ('..','.git','.harness','.codex','.agents')) or any(c in value for c in '*?['):
        raise ValueError('ownership must be explicit relative source paths')
    return str(PurePosixPath(value)).rstrip('/')

def inside(path,owner):return path==owner or path.startswith(owner+'/')
def overlap(a,b):return inside(a,b) or inside(b,a)
def valid_done(t):
    review=t.get('reviews',[])[-1] if t.get('reviews') else {}
    return t['state']=='DONE' and bool(review.get('development_evidence')) and t.get('validation_status',{}).get(review.get('agent_run_id'),{}).get('state')=='CURRENT'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else None

def git(root,*args):
    p=subprocess.run(['rtk','proxy','git',*args],cwd=root,capture_output=True)
    if p.returncode:raise ValueError('git operation failed: '+p.stderr.decode(errors='replace')[:300])
    return p.stdout

def manifest(root):
    names=git(root,'ls-files','--cached','--others','--exclude-standard','-z').decode().split(chr(0))
    out={}
    for name in names:
        if not name or any(x in name.split('/') for x in ('.harness','.kmp-agent','.codex','.agents','.git')):continue
        p=root/name
        if p.is_symlink():raise ValueError('symlink source not supported: '+name)
        if p.is_file():out[name]=digest(p)
    return out

class Development:
    def __init__(self,root,run_id):
        self.root=Path(root).resolve();self.tasks=Tasks(self.root,run_id);self.run_id=run_id
        self.integration_lock=threading.Lock()

    def configure(self,parent_task_id,children,architecture,shared_owners,integration_commands,max_parallel=2,executable='codex',timeout=600):
        state=self.tasks.read();parent=state['tasks'][parent_task_id]
        if parent['role']!='development' or tracking.execution_scope(parent)!='code_implementation':raise ValueError('parent must be a configured code-implementation development task')
        if parent['executions'] or parent.get('development_delegation'):raise ValueError('configure before execution; preserve previous plan')
        if type(max_parallel) is not int or not 1<=max_parallel<=8:raise ValueError('max_parallel must be 1..8')
        if type(timeout) is not int or timeout<=0:raise ValueError('positive timeout required')
        if not children or not integration_commands:raise ValueError('children and independent integration commands required')
        for command in integration_commands:self._command(command)
        if not architecture.get('evidence') or not architecture.get('modules'):raise ValueError('actual source/module evidence required; do not infer UI sharing')
        modules={area:[normalized(p) for p in paths] for area,paths in architecture['modules'].items()}
        if set(modules)-AREAS:raise ValueError('unknown source ownership area')
        arch=copy.deepcopy(architecture);arch['evidence']=[self.tasks.artifact(p) for p in architecture['evidence']]
        ids=[x['task_id'] for x in children]
        if len(ids)!=len(set(ids)) or parent_task_id in ids or any(i in state['tasks'] for i in ids):raise ValueError('child IDs must be new and unique')
        owners={normalized(p):tid for p,tid in shared_owners.items()}
        if any(tid not in ids+[parent_task_id] for tid in owners.values()):raise ValueError('shared owner must be parent or selected child')
        specifications=[]
        for spec in children:
            spec=copy.deepcopy(spec);area=spec['area'];paths=[normalized(p) for p in spec['allowed_paths']]
            if area not in AREAS or not paths or area not in modules:raise ValueError('selected area must have actual module paths')
            for p in paths:
                if not any(inside(p,m) for m in modules[area]):raise ValueError('ownership outside declared module for '+area)
                for shared,owner in owners.items():
                    if overlap(p,shared) and owner!=spec['task_id']:raise ValueError('shared file owned by another task: '+shared)
            for previous in specifications:
                if any(overlap(a,b) for a in paths for b in previous['allowed_paths']):raise ValueError('parallel ownership conflict')
            if not spec.get('requirement_ids') or not spec.get('acceptance_ids') or not spec.get('goal') or 'out_of_scope' not in spec:raise ValueError('goal, requirement/acceptance IDs and scope exclusions required')
            if not spec.get('verification_commands'):raise ValueError('area verification commands required')
            for command in spec['verification_commands']:self._command(command)
            if set(spec.get('dependencies',[]))-set(ids):raise ValueError('dependency outside this development plan')
            spec['allowed_paths']=paths;specifications.append(spec)
        for p in manifest(self.root):
            if p in {'settings.gradle.kts','settings.gradle','build.gradle.kts','build.gradle','gradle.properties','gradle/libs.versions.toml','package.json','package-lock.json'} and p not in owners:raise ValueError('explicit common configuration owner required: '+p)
        # Shared Compose UI belongs to the actual shared source set, not native wrappers.
        for path,area in architecture.get('ui_owners',{}).items():
            normalized(path)
            if area not in modules:raise ValueError('UI owner lacks actual source set')
            for spec in specifications:
                if any(overlap(path,p) for p in spec['allowed_paths']) and spec['area']!=area:raise ValueError('UI/source-set ownership mismatch')
        remaining={s['task_id']:set(s.get('dependencies',[])) for s in specifications};done=set();ordered=[]
        while remaining:
            ready=[k for k,v in remaining.items() if v<=done]
            if not ready:raise ValueError('cyclic development dependencies')
            for key in ready:done.add(key);ordered.append(key);remaining.pop(key)
        config={'children':specifications,'architecture':arch,'shared_owners':owners,'integration_commands':integration_commands,'max_parallel':max_parallel,'executable':executable,'timeout':timeout}
        # All constraints are checked before creating any child.
        baselines={k:v['path'] for k,v in parent['development_tracking']['baselines'].items()}
        for tid in ordered:
            spec=next(x for x in specifications if x['task_id']==tid)
            self.tasks.register(parent['feature_id'],tid,'development',spec['title'],spec['goal'],
                [{'id':c,'description':spec['goal'],'required':True} for c in spec['acceptance_ids']],[a['path'] for a in parent['inputs']],max_attempts=spec.get('max_attempts',parent['max_attempts']),dependencies=spec.get('dependencies',[]),work_type=parent['work_type'],execution_scope='code_implementation',pipeline_stage='development')
            self.tasks.configure_development(tid,baselines,spec['allowed_paths'],parent['development_tracking'].get('api_required',False),parent['development_tracking'].get('service_version','UNKNOWN'),parent['development_tracking'].get('change_id'))
        def save(s):
            p=s['tasks'][parent_task_id];p['development_delegation']=config;p['child_task_ids']=ids
            refs={a['path']:a for a in p['inputs']};refs.update({a['path']:a for a in arch['evidence']});p['inputs']=list(refs.values())
            for spec in specifications:
                t=s['tasks'][spec['task_id']];t['inputs']=copy.deepcopy(p['inputs']);t.update(parent_task_id=parent_task_id,coordination_plan_id=parent_task_id,development_area=spec['area'],delegation_state='WAITING',delegation_reason='waiting for explicit predecessor and coordinator dispatch')
                self.tasks._event(s,'development_child_linked',t,observed={'parent_task_id':parent_task_id,'development_area':spec['area'],'dependencies':t['dependencies']})
            self.tasks._event(s,'development_plan_configured',p,observed={'child_task_ids':ids,'max_parallel':max_parallel,'architecture':arch})
            return config
        return self.tasks._mutate('configure_delegation',save,task_id=parent_task_id)

    @staticmethod
    def _command(argv):
        if not isinstance(argv,list) or not argv or not all(isinstance(x,str) and x for x in argv):raise ValueError('verification command must be an argv list')
        if argv[:2]!=['rtk','proxy']:raise ValueError('verification commands must use rtk proxy')

    def update(self,tid,status,reason=None,**fields):
        def op(state):
            t=state['tasks'][tid];t.update(delegation_state=status,delegation_reason=reason,**fields)
            self.tasks._event(state,'development_child_state',t,observed={'state':status,'reason':reason,'parent_task_id':t.get('parent_task_id'),'development_area':t.get('development_area')})
        self.tasks._mutate('delegation_state',op,task_id=tid)

    def workspace(self,tid,aid):
        out=self.tasks.directory/'delegation'/aid;ws=out/'workspace';out.mkdir(parents=True,exist_ok=False)
        git(self.root,'clone','--no-hardlinks','--quiet',str(self.root),str(ws))
        current=manifest(self.root)
        for name in manifest(ws):
            if name not in current:(ws/name).unlink()
        for name in current:
            target=ws/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(self.root/name,target)
        # Dedicated caches; never share a worker Git index or global build outputs.
        with (ws/'.git/info/exclude').open('a') as f:f.write('\n.worker-cache/\n')
        return ws,out,current,git(ws,'rev-parse','HEAD').decode().strip()

    def packet(self,parent,spec,execution,workspace):
        t=self.tasks.read()['tasks'][spec['task_id']]
        from harness.requirement_lineage import compare
        lineage=compare(self.root) if (self.root/'requirement-lineage.json').exists() else {'scope':'SYNTHETIC_OR_LEGACY_UNCERTIFIED','product_requirements_pass':'NOT_ESTABLISHED'}
        from harness.human_progress import for_task, message
        progress=for_task(self.root,parent['task_id'],self.run_id)
        return {'human_progress':progress,'human_progress_message':message(progress),'progress_instructions':'Report the shared native checklist only at major transitions. Retries stay within this task; command return0 is not completion. Explain validation purpose/results in ordinary language. Never invent process activity or product PASS.','requirement_lineage':lineage,'parent_task_id':parent['task_id'],'task_id':t['task_id'],'agent_run_id':execution['agent_run_id'],'development_area':spec['area'],
            'goal':spec['goal'],'requirement_ids':spec['requirement_ids'],'acceptance_ids':spec['acceptance_ids'],
            'baselines':t['development_tracking']['baselines'],'baseline_version':execution['baseline'],'frozen_inputs':execution['inputs'],'code_state':execution['code_state_start'],
            'predecessor_artifacts':{dep:self.tasks.read()['tasks'][dep].get('outputs',[]) for dep in spec.get('dependencies',[])},
            'allowed_paths':spec['allowed_paths'],'shared_owners':parent['development_delegation']['shared_owners'],'dependencies':spec.get('dependencies',[]),
            'scope':spec.get('scope',spec['goal']),'out_of_scope':spec['out_of_scope'],'completion_conditions':spec['acceptance_ids'],
            'verification_commands':[[arg.replace(str(self.root),str(workspace)) for arg in command] for command in spec['verification_commands']],'canonical_verification_commands':spec['verification_commands'],'workspace':str(workspace),
            'instructions':'Distinguish literal user and approved requirements from agent-derived specs. Do not change original values, behavior or scope without explicit approval; return contract_change_required. HARNESS_TRIAL never establishes product PASS. Implement only allowed_paths. Read the frozen baseline documents at their relative paths. Do not alter contracts/shared files owned by others, Git metadata, or commit. Return contract_change_required instead of changing a contract. Do not change tests or verification commands. Write code then return the required structured result. Claims are checked independently. Use rtk proxy for commands; do not install or publish software.'}

    def verify(self,tid,aid,commands,kind='area'):
        records=[];logger=self.tasks.logger;task=self.tasks.read()['tasks'][tid]
        for i,argv in enumerate(commands):
            self._command(argv)
            rc=logger.command(self.run_id,argv,task_id=tid,agent_run_id=aid,command_kind='integration' if kind=='integration' else 'test',attempt_id=aid)
            records.append({'command':argv,'returncode':rc,'status':'PASS' if rc==0 else 'FAIL'})
            if rc:break
        return records

    def report(self,out,name,data):
        if name in {'integration.json','integration-review.json'}:
            from harness.requirement_lineage import compare
            lineage=compare(self.root) if (self.root/'requirement-lineage.json').exists() else {'scope':'SYNTHETIC_OR_LEGACY_UNCERTIFIED','purpose':'legacy or model-free test'}
            data=dict(data,claim_scope=lineage['scope'],purpose=lineage['purpose'],development_integration_result=data.get('result','UNKNOWN'),execution_path_validation='NOT_ESTABLISHED',product_requirements_fulfillment='NOT_ESTABLISHED',scope_note='Development integration only; complete execution-path validation and original product acceptance require separate evidence. No trial PASS inheritance.')
        path=out/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');return str(path.relative_to(self.root))

    def run_child(self,parent,spec,worker):
        from harness.delegation_runtime import run_codex
        if worker is run_codex:
            from harness.requirement_lineage import development_gate
            development_gate(self.tasks, parent['task_id'])
            from harness.execution_plan import require
            require(self.tasks,parent['task_id'])
        tid=spec['task_id'];aid=None
        try:
            def bind_predecessors(state):
                task=state['tasks'][tid];before=copy.deepcopy(task['inputs']);refs={a['path']:a for a in task['inputs']}
                for dep in spec.get('dependencies',[]):
                    for artifact in state['tasks'][dep]['outputs']:refs[artifact['path']]=copy.deepcopy(artifact)
                task['inputs']=list(refs.values())
                if before!=task['inputs']:
                    task.setdefault('input_rebases',[]).append({'reason':'explicit completed predecessor outputs','before':before,'after':copy.deepcopy(task['inputs'])})
                    self.tasks._event(state,'development_predecessor_inputs',task,observed={'dependencies':spec.get('dependencies',[]),'inputs':task['inputs']})
            self.tasks._mutate('delegation_bind_inputs',bind_predecessors,task_id=tid)
            self.tasks.ready(tid);execution=self.tasks.begin(tid,'development',execution_mode='independent_process');aid=execution['agent_run_id']
            self.update(tid,'RUNNING','native worker dispatch reserved')
            ws,out,before,head=self.workspace(tid,aid);packet=self.packet(parent,spec,execution,ws)
            packet_path=self.report(out,'delegation-input.json',packet)
            self.tasks.require_dispatch(tid)
            result=worker(self.tasks,tid,aid,ws,packet,out/'process',parent['development_delegation']['executable'],parent['development_delegation']['timeout'])
            from harness.delegation_runtime import validate_result
            claim=validate_result(result['result']) if result.get('result') else None
            if result.get('returncode')!=0 or not claim:raise ValueError('worker process/report failed: '+str(result.get('error') or result.get('result_error')))
            report_path=self.report(out,'result-envelope.json',result)
            if claim['status']!='COMPLETE':raise ValueError('worker reports partial/failed/blocked implementation')
            # Keep reported open items; coordinator verification and later independent QA
            # decide quality. A NOT_RUN build report is not a missing implementation.
            self.update(tid,'RUNNING','independent implementation verification pending',reported_unresolved=copy.deepcopy(claim['unresolved']),worker_verifications=copy.deepcopy(claim['verifications']))
            if claim['contract_change_required']:
                self.update(tid,'BLOCKED','contract change returned to development coordinator',contract_change_request={'evidence':report_path,'impact':claim['contract_impact']})
                raise ValueError('contract change requires coordinator impact/CR review')
            after=manifest(ws);changed=sorted(k for k in before.keys()|after.keys() if before.get(k)!=after.get(k))
            if not changed:raise ValueError('no actual implementation diff')
            if any(not any(inside(k,p) for p in spec['allowed_paths']) for k in changed):raise ValueError('worker changed files outside ownership')
            if set(changed)!=set(claim['changed_files']):raise ValueError('self report changed_files differs from actual diff')
            if git(ws,'rev-parse','HEAD').decode().strip()!=head or git(ws,'diff','--cached','--name-only').strip():raise ValueError('worker altered Git history/index')
            # Retain an actual portable diff, not just a self-reported reference.
            for name in changed:
                if name not in before:git(ws,'add','-N','--',name)
            (out/'changes.patch').write_bytes(git(ws,'diff','--binary','HEAD','--',*changed))
            with self.integration_lock:
                self.tasks.require_dispatch(tid)
                latest=self.tasks.read()['tasks'][tid]
                if execution['baseline']!=tracking.baseline(latest) or any(self.tasks.artifact(v['path'])['sha256']!=v['sha256'] for v in latest['development_tracking']['baselines'].values()):raise ValueError('baseline changed during worker execution')
                for name in changed:
                    if digest(self.root/name)!=before.get(name):raise ValueError('integration source changed concurrently: '+name)
                for name in changed:
                    target=self.root/name
                    if name in after:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ws/name,target)
                    elif target.exists():target.unlink()
                checks=self.verify(tid,aid,spec['verification_commands'])
                status='PASS' if len(checks)==len(spec['verification_commands']) and all(x['status']=='PASS' for x in checks) else 'FAIL'
                proof={'result':status,'method':'coordinator actual diff plus independent command execution; worker claims not verdicts','tested_outputs':{},'checks':checks,'changed_files':changed,'worker_report':report_path,'patch':str((out/'changes.patch').relative_to(self.root))}
                evidence=self.report(out,'verification.json',proof)
                outputs=[name for name in changed if (self.root/name).is_file()]
                self.tasks.submit(tid,aid,outputs,'coordinator inspected scoped diff and ran registered commands')
                reviewer=self.tasks.begin(tid,'verification',review=True,execution_mode='local_check');rid=reviewer['agent_run_id']
                reviewed=self.tasks.read()['tasks'][tid];proof['code_state_sha256']=reviewed['submission_code_state']['state_sha256'];proof['baseline']=tracking.baseline(reviewed)
                submitted=reviewed['outputs'];proof['tested_outputs']={a['path']:a['sha256'] for a in submitted if a['path']!=evidence}
                # Evidence must not list itself; keep immutable submitted implementation outputs.
                review_evidence=self.report(out,'review-evidence.json',proof)
                criteria=[{'criterion_id':c['id'],'result':status,'evidence':review_evidence} for c in latest['criteria'] if c['required']]
                outcome=self.tasks.review(tid,rid,criteria,'actual commands and scoped changes; automated local review, not independent model review')
                self.update(tid,'VERIFIED' if outcome=='DONE' else 'FAILED',None if outcome=='DONE' else 'area verification failed',changed_files=changed,verification_evidence=[self.tasks.artifact(review_evidence)],change_reference=str((out/'changes.patch').relative_to(self.root)),delegation_input=self.tasks.artifact(packet_path))
                return outcome=='DONE'
        except Exception as exc:
            current=self.tasks.read()['tasks'][tid]
            active=[r for r in current['executions'] if not r.get('ended_at')]
            for r in active:self.tasks.fail(tid,r['agent_run_id'],str(exc))
            status='BLOCKED' if current.get('contract_change_request') else 'FAILED'
            self.update(tid,status,str(exc));return False

    def execute(self,parent_task_id,worker=None):
        from harness.delegation_runtime import run_codex
        from harness.requirement_lineage import development_gate
        # Return historic completion without recertifying or rewriting it.
        previous=self.tasks.read()['tasks'][parent_task_id]
        if previous['state']=='DONE':
            return {'state':'DONE' if valid_done(previous) else 'RECHECK_REQUIRED','cached':True,'parent_task_id':parent_task_id,'claim_scope':'HISTORICAL_ONLY','product_requirements_fulfillment':'NOT_ESTABLISHED','feature_complete':False}
        self.tasks.require_dispatch(parent_task_id, preflight=True)
        # Legacy synthetic tests remain local checks, never product certification.
        if worker is None or (self.root/'requirement-lineage.json').exists():
            development_gate(self.tasks, parent_task_id)
        if worker is None:
            from harness.execution_plan import require
            require(self.tasks,parent_task_id)
        worker=worker or run_codex
        lockpath=self.tasks.directory/('development-'+hashlib.sha256(parent_task_id.encode()).hexdigest()+'.lock')
        with lockpath.open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('development coordinator already running')
            parent=self.tasks.read()['tasks'][parent_task_id];config=parent['development_delegation']
            if parent['state']=='DONE':return {'state':'DONE' if valid_done(parent) else 'RECHECK_REQUIRED','cached':True,'parent_task_id':parent_task_id}
            if any(not r.get('ended_at') for r in parent['executions']):raise ValueError('unfinished coordinator attempt; explicit recovery required, no duplicate dispatch')
            self.tasks.ready(parent_task_id);run=self.tasks.begin(parent_task_id,'development',execution_mode='local_check');aid=run['agent_run_id']
            pending={s['task_id']:s for s in config['children']};failed=set();running={};completed=set()
            try:
                with ThreadPoolExecutor(max_workers=config['max_parallel']) as pool:
                    while pending or running:
                        current=self.tasks.read()['tasks']
                        for tid,spec in list(pending.items()):
                            if current[tid]['state']=='DONE':
                                if valid_done(current[tid]):completed.add(tid)
                                else:failed.add(tid);self.update(tid,'RECHECK_REQUIRED','code/baseline/CR changed; explicit new revision required')
                                pending.pop(tid)
                        for tid,spec in list(pending.items()):
                            deps=set(spec.get('dependencies',[]))
                            if deps&failed:
                                self.update(tid,'BLOCKED','predecessor failed or requires recheck');failed.add(tid);pending.pop(tid);continue
                            if deps<=completed and len(running)<config['max_parallel']:
                                running[pool.submit(self.run_child,parent,spec,worker)]=tid;pending.pop(tid)
                        if not running:
                            if pending:raise ValueError('no runnable child; missing prerequisite')
                            break
                        finished,_=wait(running,return_when=FIRST_COMPLETED)
                        for future in finished:
                            tid=running.pop(future)
                            (completed if future.result() else failed).add(tid)
                if failed:
                    self.tasks.fail(parent_task_id,aid,'child failed/blocked/recheck: '+', '.join(sorted(failed)));return {'state':'BLOCKED','parent_task_id':parent_task_id,'failed':sorted(failed),'completed':sorted(completed)}
                # Area PASS is not feature integration PASS.
                checks=self.verify(parent_task_id,aid,config['integration_commands'],'integration')
                passed=len(checks)==len(config['integration_commands']) and all(c['status']=='PASS' for c in checks)
                out=self.tasks.directory/'delegation'/aid;out.mkdir(parents=True,exist_ok=True)
                evidence=self.report(out,'integration.json',{'result':'PASS' if passed else 'FAIL','method':'separate integration commands after all child reviews','checks':checks,'child_task_ids':sorted(completed)})
                changed=sorted({p for tid in completed for p in self.tasks.read()['tasks'][tid].get('changed_files',[]) if (self.root/p).is_file()})
                self.tasks.submit(parent_task_id,aid,changed,'collected implementation plus separate integration execution')
                review=self.tasks.begin(parent_task_id,'verification',review=True,execution_mode='local_check')
                submitted=self.tasks.read()['tasks'][parent_task_id]
                parent_proof=json.loads((self.root/evidence).read_text());parent_proof.update(code_state_sha256=submitted['submission_code_state']['state_sha256'],baseline=tracking.baseline(submitted))
                review_evidence=self.report(out,'integration-review.json',parent_proof)
                results=[{'criterion_id':c['id'],'result':'PASS' if passed else 'FAIL','evidence':review_evidence} for c in parent['criteria'] if c['required']]
                outcome=self.tasks.review(parent_task_id,review['agent_run_id'],results,'integration command evidence; independent product acceptance remains separate')
                return {'state':outcome,'parent_task_id':parent_task_id,'implementation_review':outcome,'handoff':'READY_FOR_VERIFICATION' if outcome=='DONE' else 'BLOCKED','feature_complete':False,'execution_path_validation':'NOT_ESTABLISHED','product_requirements_fulfillment':'NOT_ESTABLISHED'}
            except BaseException as exc:
                state=self.tasks.read()['tasks'][parent_task_id]
                for r in state['executions']:
                    if not r.get('ended_at'):self.tasks.fail(parent_task_id,r['agent_run_id'],str(exc))
                raise
