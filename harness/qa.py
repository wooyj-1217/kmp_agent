"""Evidence-bound QA using native verification tasks, snapshots, issues and reviews.

QA never repairs product files. An explicit repair callback is a separate owner action.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from harness.tasks import Tasks

STAGES={'requirements','planning','design','implementation','retest'}
KINDS={'specification_violation','baseline_gap','baseline_contradiction','usability','improvement'}
RESULTS={'PASS','FAIL','BLOCKED','NOT_RUN'}
FINDING_FIELDS={'kind','severity','owner_role','requirement_ids','design_ids','contract_ids','expected','actual','repro','evidence','blocking','reason_code','code_ref','baseline_ref'}
RESULT_SCHEMA={'type':'object','additionalProperties':False,'properties':{
 'criteria':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{'criterion_id':{'type':'string'},'result':{'type':'string','enum':sorted(RESULTS)},'observation':{'type':'string'},'evidence':{'type':['string','null']}},'required':['criterion_id','result','observation','evidence']}},
 'findings':{'type':'array','items':{'type':'object','additionalProperties':False,'properties':{k:({'type':'boolean'} if k=='blocking' else {'type':'array','items':{'type':'string'}} if k in {'requirement_ids','design_ids','contract_ids','repro'} else {'type':'string'}) for k in FINDING_FIELDS},'required':sorted(FINDING_FIELDS)}},
 'reviewed_issue_ids':{'type':'array','items':{'type':'string'}},
 'recommendation':{'type':'string','enum':['PASS','REWORK','BLOCKED','NOT_RUN']},'summary':{'type':'string'}},'required':['criteria','findings','recommendation','summary','reviewed_issue_ids']}


# The model schema and local validator share the same controlled vocabulary.
RESULT_SCHEMA['properties']['criteria']['items']['required'].append('platform_results')
RESULT_SCHEMA['properties']['criteria']['items']['properties']['platform_results']={'type':'array','items':{'type':'object','additionalProperties':False,'properties':{k:({'type':'array','items':{'type':'string'}} if k=='evidence' else {'type':'string'}) for k in ('platform','result','environment','command_or_steps','expected','observed','doctor','drive','cleanup','evidence')},'required':['platform','result','environment','command_or_steps','expected','observed','doctor','drive','cleanup','evidence']}}
_platform_properties=RESULT_SCHEMA['properties']['criteria']['items']['properties']['platform_results']['items']['properties']
_platform_properties['platform']['enum']=['android','ios','web','server']
for _status in ('result','doctor','drive','cleanup'):
    _platform_properties[_status]['enum']=sorted(RESULTS)
    _platform_properties[_status]['description']='Exact status token only. Put explanations in observation or evidence files.'

RESULT_SCHEMA['properties']['criteria']['items']['properties']['evidence']['description']='Exactly ONE existing relative file path in the review workspace. Not a sentence, URL, line reference or semicolon-separated paths. Write a qa-tools evidence file that cites any additional sources.'
RESULT_SCHEMA['properties']['findings']['items']['properties']['evidence']['description']='Exactly ONE existing relative file path in the review workspace. Put observations and line references inside that file, not in this field.'
_finding_properties=RESULT_SCHEMA['properties']['findings']['items']['properties']
_finding_properties['kind']={'type':'string','enum':sorted(KINDS)}
_finding_properties['severity']={'type':'string','enum':['BLOCKER','MAJOR','MINOR']}
_finding_properties['owner_role']={'type':'string','enum':['planning','design','development','verification','improvement','orchestrator']}


def validate_result(value):
    if not isinstance(value,dict) or not (set(RESULT_SCHEMA['required'])-{'reviewed_issue_ids'}).issubset(value) or set(value)-set(RESULT_SCHEMA['properties']):raise ValueError('invalid QA result contract')
    if not isinstance(value.get('reviewed_issue_ids',[]),list) or not all(isinstance(x,str) for x in value.get('reviewed_issue_ids',[])):raise ValueError('invalid reviewed issue IDs')
    if value['recommendation'] not in {'PASS','REWORK','BLOCKED','NOT_RUN'} or not isinstance(value['summary'],str):raise ValueError('invalid QA recommendation')
    if not isinstance(value['criteria'],list) or not isinstance(value['findings'],list):raise ValueError('QA lists required')
    for row in value['criteria']:
        if set(row)-{'platform_results'}!={'criterion_id','result','observation','evidence'} or not isinstance(row['criterion_id'],str) or not row['criterion_id'] or row['result'] not in RESULTS or not isinstance(row['observation'],str) or (row['evidence'] is not None and not isinstance(row['evidence'],str)):raise ValueError('invalid QA criterion')
        if 'platform_results' in row:
            platforms=row['platform_results']
            if not isinstance(platforms,list):raise ValueError('QA platform_results must be a list')
            seen=set()
            for item in platforms:
                if not isinstance(item,dict) or set(item)!=set(_platform_properties):raise ValueError('QA platform result must match complete contract')
                if item['platform'] not in _platform_properties['platform']['enum'] or item['platform'] in seen:raise ValueError('invalid or duplicate QA platform')
                seen.add(item['platform'])
                if any(item[k] not in RESULTS for k in ('result','doctor','drive','cleanup')):raise ValueError('QA platform status must be an exact token; explanations belong in evidence')
                if not all(isinstance(item[k],str) and item[k].strip() for k in ('environment','command_or_steps','expected','observed')):raise ValueError('QA platform observations must be concrete')
                if not isinstance(item['evidence'],list) or any(not isinstance(x,str) or not x.strip() for x in item['evidence']) or item['result']=='PASS' and not item['evidence']:raise ValueError('QA platform evidence must be explicit paths')
    for f in value['findings']:
        if set(f)!=FINDING_FIELDS or f['kind'] not in KINDS or f['severity'] not in {'BLOCKER','MAJOR','MINOR'} or type(f['blocking']) is not bool:raise ValueError('invalid QA finding')
        if f['owner_role'] not in {'planning','design','development','verification','improvement','orchestrator'}:raise ValueError('invalid finding owner')
        if not all(isinstance(f[k],list) and all(isinstance(x,str) for x in f[k]) for k in ('requirement_ids','design_ids','contract_ids','repro')):raise ValueError('invalid finding IDs/repro')
        if not all(isinstance(f[k],str) and f[k].strip() for k in ('expected','actual','evidence','reason_code','code_ref','baseline_ref')):raise ValueError('finding needs exact expectation, observation and evidence')
    return value


def manifest(root,generated_paths=()):
    """Content manifest, excluding private harness state/Git and QA-only scratch."""
    root=Path(root);out={}
    for p in root.rglob('*'):
        rel=p.relative_to(root)
        if set(rel.parts)&{'.git','.harness','.kmp-agent','.codex','.agents','.worker-cache','__pycache__','qa-tools'}:continue
        if p.is_symlink():out[str(rel)]='SYMLINK:'+os.readlink(p)
        elif p.is_file() and not any(rel.as_posix()==base or rel.as_posix().startswith(base+'/') for base in generated_paths):out[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def target_scope(target,original_requests):
    """Explicit task paths only; no filename/text inference or whole-feature guess."""
    tracking=target.get('development_tracking') or {}
    if tracking.get('scope_policy')=='full_repository':
        return {'mode':'full_repository','paths':[],'basis':'explicit development_tracking.scope_policy'}
    target_refs=target.get('inputs',[])+target.get('outputs',[])
    code_paths=tracking.get('code_paths') or []
    if not code_paths and not target_refs:
        return {'mode':'UNKNOWN','paths':[],'basis':'no target code scope or artifact references; conservative whole repository fallback'}
    paths=list(code_paths)
    def refs(value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str):paths.append(value['path'])
            for child in value.values():refs(child)
        elif isinstance(value,list):
            for child in value:refs(child)
    refs(target_refs);refs(original_requests);refs(tracking.get('baselines',{}))
    clean=[]
    for value in paths:
        path=Path(value)
        if path.is_absolute() or '..' in path.parts:raise ValueError('QA target paths must stay inside project')
        rel=path.as_posix().rstrip('/')
        if rel=='.':return {'mode':'full_repository','paths':[],'basis':'explicit root code path'}
        if rel and rel not in clean:clean.append(rel)
    return {'mode':'target_paths','paths':clean,'basis':'declared code_paths, target inputs/outputs, baseline refs and original requests'}


def scoped_manifest(root,scope,generated_paths=()):
    content=manifest(root,generated_paths)
    if scope.get('mode')!='target_paths':return content
    paths=scope['paths']
    return {p:sha for p,sha in content.items() if any(p==base or p.startswith(base+'/') for base in paths)}


def finding_return_stage(finding,workflow,target_task_id):
    """Only explicit stage ownership may invalidate a development-plan review."""
    if not finding.get('blocking') or finding.get('kind')=='improvement':return None
    owner=finding.get('owner_role')
    if owner in {'planning','design'}:return owner
    plan=((workflow or {}).get('stages',{}).get('development_plan') or {})
    if owner=='development' and finding.get('kind') in {'baseline_gap','baseline_contradiction'} and target_task_id in [plan.get('task_id')]+plan.get('task_history',[]):return 'development_plan'
    return None


class QA:
    def __init__(self,root,run_id):
        self.root=Path(root).resolve();self.tasks=Tasks(self.root,run_id)

    def configure(self,task_id,stage,target_task_id,original_requests,criteria,commands=None,max_attempts=2,repair_task_id=None,executable='codex',timeout=600,images=None,context_files=None,generated_paths=None,repair_criteria=None):
        if stage not in STAGES or not original_requests or max_attempts<1:raise ValueError('QA requires stage, original requests and positive retry limit')
        state=self.tasks.read();target=state['tasks'][target_task_id]
        lineage_path=self.root/'requirement-lineage.json'
        if lineage_path.exists():
            from harness.requirement_lineage import load, NAME
            lineage=load(self.root)
            authoritative={s['path'] for s in lineage['sources'] if s['kind']!='AGENT_DERIVED'}
            if set(original_requests)-authoritative:
                raise ValueError('agent-derived document cannot be original or approved QA authority')
            context_files=list(dict.fromkeys((context_files or [])+[NAME]+[s['path'] for s in lineage['sources']]))
        refs=[self.tasks.artifact(p) for p in original_requests]
        image_refs=[self.tasks.artifact(p) for p in (images or [])]
        context_refs=[self.tasks.artifact(p) for p in (context_files or [])]
        inputs=list(dict.fromkeys([r['path'] for r in refs+target['inputs']+target['outputs']+image_refs+context_refs]))
        if not criteria or any(not c.get('id') or not c.get('description') or type(c.get('required')) is not bool for c in criteria):raise ValueError('explicit QA criteria required')
        commands=commands or []
        if any(not isinstance(c,list) or not c or not all(isinstance(x,str) for x in c) for c in commands):raise ValueError('commands must be argv lists')
        from harness.qa_policy import generated_paths as check_generated,repair_criteria as check_links
        protected=[r['path'] for r in refs+target['inputs']+target['outputs']+image_refs+context_refs]
        protected+=target.get('development_tracking',{}).get('code_paths',[])
        generated=check_generated(self.root,[] if generated_paths is None else generated_paths,protected)
        links=check_links({} if repair_criteria is None else repair_criteria,state['tasks'].get(repair_task_id),criteria)
        self.tasks.register(target['feature_id'],task_id,'verification','QA '+stage+': '+target['title'],'Independent QA; product files read-only',criteria,inputs,max_attempts=max_attempts,work_type=target['work_type'],execution_scope='documentation',pipeline_stage='verification')
        scope=target_scope(target,refs+image_refs+context_refs)
        if stage=='requirements':
            if not lineage_path.exists():raise ValueError('requirements QA requires typed lineage')
            scope={'mode':'target_paths','paths':list(dict.fromkeys(['requirement-lineage.json']+[s['path'] for s in lineage['sources']])),'basis':'source and derivation scope; implementation changes do not invalidate source alignment'}
        config={'generated_paths':generated,'repair_criteria':copy.deepcopy(links),'repair_criteria_definitions':{c['id']:copy.deepcopy(c) for c in state['tasks'].get(repair_task_id,{}).get('criteria',[]) if c['id'] in links},'context_artifacts':context_refs,'images':image_refs,'manifest_scope':scope,'stage':stage,'executable':executable,'timeout':timeout,'target_task_id':target_task_id,'original_requests':refs,'commands':commands,'repair_task_id':repair_task_id,'target_manifest':scoped_manifest(self.root,scope,generated),'target_baseline':copy.deepcopy(target.get('development_tracking',{}).get('baselines',target.get('inputs',[]))),'attempts':[]}
        def op(s):
            t=s['tasks'][task_id];t['qa_config']=config
            self.tasks._event(s,'qa_configured',t,observed={'stage':stage,'target_task_id':target_task_id,'original_requests':refs})
        self.tasks._mutate('configure_qa',op,task_id)
        return config

    def accept_owner(self, task_id):
        """Re-use an explicit current QA attempt; never rerun or copy whole PASS."""
        from harness.qa_repair import _owner_review
        state=self.tasks.read();task=state['tasks'][task_id];config=task['qa_config']
        owner=state['tasks'][config['repair_task_id']]
        if owner['state']!='IN_REVIEW' or not config['attempts']:raise ValueError('submitted owner and explicit QA attempt required')
        context={'phase':'owner_result_processing','owned_runs':[]}
        try:return _owner_review(self,task_id,config['attempts'][-1],owner,context)
        except BaseException as error:
            if context['owned_runs']:
                from harness.qa_failure import record_failure
                record_failure(self.tasks,owner['task_id'],context,error)
            raise

    def _generated(self,config,task):
        from harness.qa_policy import generated_paths as check_generated
        target=self.tasks.read()['tasks'][config['target_task_id']]
        protected=[r['path'] for r in config['original_requests']+task['inputs']+target['inputs']+target['outputs']]
        protected+=target.get('development_tracking',{}).get('code_paths',[])
        return check_generated(self.root,config.get('generated_paths',[]),protected)

    def _save(self,task_id,attempt):
        def op(s):
            task=s['tasks'][task_id];task['qa_config']['attempts'].append(copy.deepcopy(attempt))
            self.tasks._event(s,'qa_attempt_finished',task,attempt['agent_run_id'],observed=attempt)
        self.tasks._mutate('qa_attempt',op,task_id)

    def _resolve_reviewed_issues(self,qa_task_id,target_task_id,result,qa_run_id,review_run_id,evidence,code_manifest):
        proof=self.tasks.artifact(evidence)
        def op(s):
            qa=s['tasks'][qa_task_id]
            review=next((r for r in qa['reviews'] if r['agent_run_id']==review_run_id),None)
            if qa['state']!='DONE' or not review or not all(r['result']=='PASS' for r in review['results'] if r['criterion_id'] in {c['id'] for c in qa['criteria'] if c['required']}) or scoped_manifest(self.root,qa['qa_config'].get('manifest_scope',{'mode':'UNKNOWN'}),qa['qa_config'].get('generated_paths',[]))!=code_manifest:raise ValueError('issue closure requires current actual QA PASS')
            if any(f['blocking'] and f['kind']!='improvement' for f in result['findings']):raise ValueError('blocking findings cannot close issues')
            closed=[]
            for issue_id in dict.fromkeys(result['reviewed_issue_ids']):
                issue=next((i for i in s.get('issues',[]) if i['id']==issue_id and i.get('task_id')==target_task_id),None)
                if not issue or issue.get('status')!='OPEN':continue
                # Only issues from this explicit QA target workflow are eligible.
                if not issue.get('qa_finding') or s['tasks'].get(issue.get('qa_task_id'),{}).get('qa_config',{}).get('target_task_id')!=target_task_id:continue
                resolution={'qa_task_id':qa_task_id,'qa_agent_run_id':qa_run_id,'review_run_id':review_run_id,'evidence':proof,'code_manifest':copy.deepcopy(code_manifest),'method':'explicit model reviewed IDs plus actual native QA evidence/command gate'}
                issue['status']='RESOLVED';issue.setdefault('history',[]).append({'event':'qa_verified_resolution',**resolution});issue['resolution']=resolution;closed.append(issue_id)
                self.tasks._event(s,'issue_resolved',s['tasks'][target_task_id],qa_run_id,observed={'issue_id':issue_id,'resolution':resolution})
            return closed
        return self.tasks._mutate('qa_verified_issue_resolution',op,qa_task_id)

    def execute(self,task_id,worker=None,repair=None,executable=None,timeout=None):
        self.tasks.require_dispatch(task_id, preflight=True)
        context={'phase':'preflight','owned_runs':[]}
        try:
            return self._execute(task_id,worker,repair,executable,timeout,context)
        except BaseException as error:
            from harness.qa_failure import record_failure
            try:failure=record_failure(self.tasks,task_id,context,error)
            except Exception as cleanup_error:
                if callable(getattr(error,'add_note',None)):
                    error.add_note('QA cleanup could not be persisted: '+type(cleanup_error).__name__+': '+str(cleanup_error))
                raise error from cleanup_error
            if not context['owned_runs'] or not isinstance(error,Exception):raise
            return failure

    def _execute(self,task_id,worker,repair,executable,timeout,context):
        task=self.tasks.read()['tasks'][task_id];config=task.get('qa_config')
        executable=executable or (config or {}).get('executable','codex');timeout=timeout or (config or {}).get('timeout',600)
        if task['role']!='verification' or not config:raise ValueError('QA must be configured on verification task')
        if any(r.get('ended_at') is None for r in task['executions']):raise ValueError('QA already has an active execution')
        if any(str(v).startswith('SYMLINK:') for v in manifest(self.root).values()):raise ValueError('QA isolation refuses product symlinks')
        if task['state']=='DONE':raise ValueError('QA already completed; configure a new retest task')
        if scoped_manifest(self.root,config.get('manifest_scope',{'mode':'UNKNOWN'}),config.get('generated_paths',[]))!=config['target_manifest']:raise ValueError('target changed since QA configuration; configure a new retest task')
        generated=self._generated(config,task)
        from harness.delegation_runtime import validate_images
        validate_images(self.root,[r['path'] for r in config.get('images',[])])
        for ref in config['original_requests']+task['inputs']:
            if not self.tasks._valid_artifact(ref):raise ValueError('missing or changed frozen QA input')
        if worker is None:
            from harness.execution_plan import require
            try:require(self.tasks,task_id)
            except ValueError as error:
                from harness.qa_failure import record_failure
                return record_failure(self.tasks,task_id,context,error)
        lineage_comparison=None
        if (self.root/'requirement-lineage.json').exists():
            from harness.requirement_lineage import compare, require_review
            lineage_comparison=compare(self.root)
            if config['stage'] in {'implementation','retest'}:
                require_review(self.tasks,self.tasks.read()['tasks'][config['target_task_id']])
        remaining=task['max_attempts']-len([r for r in task['executions'] if r['kind']=='work'])
        if remaining<=0:raise ValueError('QA retry limit reached')
        last=None
        for _ in range(remaining):
            task=self.tasks.read()['tasks'][task_id]
            context['phase']='preflight'
            generated=self._generated(config,task)
            context['phase']='begin';context['owned_runs']=[];context.pop('agent_run_id',None)
            if task['state']!='READY':self.tasks.ready(task_id)
            reserved_id=str(uuid.uuid4());context.update(agent_run_id=reserved_id,owned_runs=[reserved_id])
            run=self.tasks.begin(task_id,'verification',actor_id='qa-producer:'+reserved_id,agent_run_id=reserved_id,execution_mode='independent_process' if worker is None else 'local_check')
            aid=run['agent_run_id'];context.update(agent_run_id=aid,owned_runs=[aid],phase='prepare_workspace');base=self.root/'.harness'/'qa'/task_id/aid;workspace=base/'workspace';base.mkdir(parents=True)
            source_before=scoped_manifest(self.root,config.get('manifest_scope',{'mode':'UNKNOWN'}),config.get('generated_paths',[]))
            shutil.copytree(self.root,workspace,ignore=shutil.ignore_patterns('.git','.harness','.kmp-agent','.codex','.agents','__pycache__','.worker-cache'))
            before=manifest(workspace,generated)
            before_all=manifest(workspace) if generated else before
            current_state=self.tasks.read();current_target=current_state['tasks'][config['target_task_id']]
            previous_issues=[copy.deepcopy(i) for i in current_state.get('issues',[]) if i.get('task_id')==config['target_task_id']]
            packet={'previous_findings':previous_issues,'previous_qa_attempts':copy.deepcopy(config.get('attempts',[])),'current_target':{'task_id':current_target['task_id'],'inputs':current_target['inputs'],'outputs':current_target['outputs'],'state':current_target['state'],'development_tracking':current_target.get('development_tracking',{})},'qa_stage':config['stage'],'qa_task_id':task_id,'target_task_id':config['target_task_id'],'criteria':task['criteria'],'original_requests':config['original_requests'],'inputs':task['inputs'],'baseline':config['target_baseline'],'code_manifest':before,'source_manifest_scope':config.get('manifest_scope',{'mode':'UNKNOWN'}),'source_target_manifest':source_before,'authorized_generated_paths':generated,'commands':config['commands'],'instructions':'Inspect original requests and frozen inputs. Do not modify product files. Write evidence only under qa-tools/. Findings must distinguish baseline errors, implementation violations, usability, suggestions. No approval from self-report alone. Return the exact supplied QA result schema.','result_schema':RESULT_SCHEMA}
            from harness.human_progress import for_task, message
            progress=for_task(self.root,task_id,self.tasks.run_id)
            packet['human_progress']=progress
            packet['human_progress_message']=message(progress)
            packet['progress_instructions']='Use the same native checklist at major transitions. Keep repair/retest within its task; identify product/harness/environment failures only with evidence; report unexecuted checks honestly.'
            if task.get('verification_contract'):
                packet['verification_contract']=copy.deepcopy(task['verification_contract'])
                packet['instructions']+=' Return platform_results for every criterion platform in verification_contract: exact environment, command_or_steps, expected, observed, doctor/drive/cleanup verdicts, and relative observation evidence paths. Build/API success never substitutes for a required UI journey. Missing tools/devices/auth must remain NOT_RUN/BLOCKED, never weaken expectations.'
            packet['requirement_lineage']=lineage_comparison or {'semantic_review':'NOT_ESTABLISHED','legacy_inputs':'authority not certified'}
            if lineage_comparison:
                packet['instructions']+=' Independently read the literal user source and approved requirements, not just the derived inventory. Detect missing original items, changed values/behavior and exclusions. Agent-authored documents are never user authority. Verify exact approval evidence. Return baseline_gap/baseline_contradiction to planning; do not invent policy. A HARNESS_TRIAL PASS is execution-path evidence only, never product compliance.'
            context['phase']='materialize_inputs'
            bundle=workspace/'qa-tools'/'frozen-inputs';bundle.mkdir(parents=True,exist_ok=True)
            packet['frozen_input_materializations']=[]
            for ref in config['original_requests']+task['inputs']:
                source=(self.root/ref['snapshot']).resolve()
                if not self.tasks._valid_artifact(ref) or not source.is_relative_to(self.root) or not source.is_file():raise ValueError('missing or changed frozen QA input')
                dest=bundle/(ref['sha256']+'.txt');shutil.copyfile(source,dest)
                packet['frozen_input_materializations'].append({'source_path':ref['path'],'source_sha256':ref['sha256'],'snapshot_path':str(dest.relative_to(workspace)),'snapshot_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
            context['phase']='worker'
            error=None;result=None;runtime=None
            try:
                self.tasks.require_dispatch(task_id)
                if worker is None:
                    from harness.delegation_runtime import run_codex
                    runtime=run_codex(self.tasks,task_id,aid,workspace,packet,base/'runtime',executable,timeout,result_schema=RESULT_SCHEMA,result_validator=validate_result,sandbox='workspace-write',image_paths=[r['path'] for r in config.get('images',[])])
                    if runtime['returncode']!=0:raise ValueError('QA runtime failed: '+str(runtime['returncode']))
                    result=validate_result(runtime['result'])
                else:result=validate_result(worker(workspace,packet))
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
            context['phase']='verify_workspace'
            frozen_tampered=any(not (workspace/r['snapshot_path']).is_file() or hashlib.sha256((workspace/r['snapshot_path']).read_bytes()).hexdigest()!=r['snapshot_sha256'] for r in packet['frozen_input_materializations'])
            modified=manifest(workspace,generated)!=before or frozen_tampered
            self._generated(config,self.tasks.read()['tasks'][task_id])
            source_changed=scoped_manifest(self.root,config.get('manifest_scope',{'mode':'UNKNOWN'}),config.get('generated_paths',[]))!=source_before
            context['phase']='commands'
            commands=[]
            if result is not None and not modified and not source_changed:
                for index,argv in enumerate(config['commands']):
                    started=time.monotonic()
                    try:
                        from harness.execution_policy import managed_command
                        proc=managed_command(self.tasks,task_id,argv,workspace,timeout)
                        status='PASS' if proc.returncode==0 else 'FAIL';code=proc.returncode;output=proc.stdout+'\n'+proc.stderr
                    except (OSError,subprocess.TimeoutExpired) as exc:status='NOT_RUN';code=None;output=str(exc)
                    path=base/('command-'+str(index)+'.txt');path.write_text(output)
                    self.tasks.logger.append('qa_command_finished',run_id=self.tasks.run_id,task_id=task_id,agent_run_id=aid,work_type=task['work_type'],feature_id=task['feature_id'],observed={'command':argv,'exit_code':code,'status':status,'evidence':str(path.relative_to(self.root))})
                    commands.append({'command':argv,'status':status,'exit_code':code,'elapsed_seconds':time.monotonic()-started,'evidence':self.tasks.artifact(str(path.relative_to(self.root)))})
            modified=modified or manifest(workspace,generated)!=before
            context['phase']='result_processing'
            problems=[]
            if error:problems.append(error)
            if modified:problems.append('QA changed product files in isolated workspace')
            if source_changed or scoped_manifest(self.root,config.get('manifest_scope',{'mode':'UNKNOWN'}),config.get('generated_paths',[]))!=source_before:problems.append('target code/baseline changed during QA')
            checked={};evidence_refs={}
            if result:
                rows=result['criteria'];expected={c['id'] for c in task['criteria']}
                if {r['criterion_id'] for r in rows}!=expected or len(rows)!=len(expected):problems.append('QA must cover each criterion exactly once')
                for r in rows:
                    if r['result']=='PASS':
                        rel=r.get('evidence');path=(workspace/str(rel)).resolve()
                        if not rel or not path.is_relative_to(workspace) or not path.is_file():problems.append('PASS lacks actual evidence: '+r['criterion_id'])
                        else:
                            dest=base/'evidence'/hashlib.sha256(r['criterion_id'].encode()).hexdigest();dest.parent.mkdir(exist_ok=True);shutil.copyfile(path,dest)
                            evidence_refs[r['criterion_id']]=self.tasks.artifact(str(dest.relative_to(self.root)))
                    checked[r['criterion_id']]=r['result']
                for index,finding in enumerate(result['findings']):
                    path=(workspace/finding['evidence']).resolve()
                    if not path.is_relative_to(workspace) or not path.is_file():problems.append('finding evidence missing: '+str(index))
                    else:
                        dest=base/'evidence'/('finding-'+str(index));dest.parent.mkdir(exist_ok=True);shutil.copyfile(path,dest)
                        evidence_refs['finding-'+str(index)]=self.tasks.artifact(str(dest.relative_to(self.root)))

                for c in task['criteria']:
                    if c.get('required') and (c.get('visual_required') or c.get('kind')=='visual'):
                        row=next((r for r in rows if r['criterion_id']==c['id']),{})
                        capture=workspace/str(row.get('evidence',''))
                        image=capture.read_bytes() if capture.is_file() and capture.resolve().is_relative_to(workspace) else b''
                        if not (image.startswith(b'\x89PNG\r\n\x1a\n') or image.startswith(b'\xff\xd8\xff') or (image[:4]==b'RIFF' and image[8:12]==b'WEBP')):problems.append('visual criterion lacks actual image capture: '+c['id'])
                if any(f['blocking'] and f['kind']!='improvement' for f in result['findings']):problems.append('unresolved blocking QA findings')
                if any(f['blocking'] and f['kind'] in {'baseline_gap','baseline_contradiction'} for f in result['findings']):problems.append('baseline owner decision required; do not invent expected policy')
                optional_improvements_only=bool(result['findings']) and all(f['kind']=='improvement' for f in result['findings']) and all(checked.get(c['id'])=='PASS' for c in task['criteria'] if c['required'])
                if result['recommendation']!='PASS' and not optional_improvements_only:problems.append('QA recommends '+result['recommendation'])
            if lineage_comparison and not lineage_comparison['structurally_ready']:
                problems.append('baseline owner decision required; unapproved requirement changes')
            required_pass=bool(result) and all(checked.get(c['id'])=='PASS' for c in task['criteria'] if c['required'])
            passed=required_pass and not problems and all(c['status']=='PASS' for c in commands)
            outcome='PASS' if passed else 'BLOCKED' if error or modified or source_changed or any('baseline owner decision' in x for x in problems) else 'REWORK' if result and (result['findings'] or any(v=='FAIL' for v in checked.values())) else 'NOT_RUN'
            report={'result':outcome,'worker_report_is_self_report':True,'review_method':'native local evidence and independently executed commands; not an independent model review','target_task_id':config['target_task_id'],'target_manifest':source_before,'criteria':checked,'evidence_refs':evidence_refs,'worker_report':result,'commands':commands,'problems':problems,'runtime':runtime}
            report['review_execution']='INDEPENDENT_PROCESS' if worker is None and (runtime or {}).get('pid') else 'SYNTHETIC_OR_LOCAL_WORKER' if worker is not None else 'NOT_RUN'
            report['review_method']='independent model review plus local evidence gate; not whole-product acceptance' if report['review_execution']=='INDEPENDENT_PROCESS' else 'synthetic/local worker and local evidence gate; not independent model review'
            report['requirement_lineage']=lineage_comparison
            report['claim_scope']=lineage_comparison['scope'] if lineage_comparison else 'LEGACY_UNCERTIFIED'
            report['execution_path_validation']='NOT_ESTABLISHED'
            report['product_requirements_fulfillment']='NOT_ESTABLISHED'
            report['scope_note']='QA task PASS alone does not establish execution-path or whole-product PASS; trial evidence never transfers to product acceptance.'
            report['failure']={'phase':'worker','cause':error} if error else None
            report['target_scope']=copy.deepcopy(config['manifest_scope'])
            report['criterion_definitions']=copy.deepcopy(task['criteria'])
            report['repair_criteria']=copy.deepcopy(config.get('repair_criteria',{}))
            report['repair_criteria_definitions']=copy.deepcopy(config.get('repair_criteria_definitions',{}))
            report['generated_paths']=generated
            after_all=manifest(workspace) if generated else {}
            report['generated_changes']=[{'path':p,'before':before_all.get(p),'after':after_all.get(p)} for p in sorted(before_all.keys()|after_all.keys()) if generated and before_all.get(p)!=after_all.get(p) and any(p==g or p.startswith(g+'/') for g in generated)]
            context['phase']='publish_report'
            report_path=base/'report.json';report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            md=base/'report.md';md.write_text('# QA '+config['stage']+'\n\nResult: '+outcome+'\n\n'+(result['summary'] if result else str(error)))
            context['phase']='submit'
            self.tasks.submit(task_id,aid,[str(md.relative_to(self.root))],'QA evidence produced; acceptance requires native review')
            context['phase']='begin_review'
            review_id=str(uuid.uuid4());context['owned_runs'].append(review_id)
            review=self.tasks.begin(task_id,'verification',review=True,actor_id='qa-evidence-gate:'+review_id,execution_mode='local_check',agent_run_id=review_id)
            context['phase']='review'
            review_rows=[{'criterion_id':c['id'],'result':'PASS' if passed and checked.get(c['id'])=='PASS' else 'FAIL' if checked.get(c['id'])=='FAIL' else 'NOT_RUN','evidence':str(report_path.relative_to(self.root))} for c in task['criteria']]
            if task.get('verification_contract'):
                from harness.verification import qa_receipts
                review_rows=qa_receipts(self.tasks,task_id,review,result,review_rows,workspace,base)
            self.tasks.review(task_id,review['agent_run_id'],review_rows,'QA '+outcome+'; local evidence check, not self approval')
            context['phase']='findings'
            attempt={'agent_run_id':aid,'review_run_id':review['agent_run_id'],'outcome':outcome,'report':self.tasks.artifact(str(report_path.relative_to(self.root))),'finding_ids':[],'repair':'NOT_RUN'}
            for f in (result or {}).get('findings',[]):
                kind='design' if f['owner_role']=='design' else 'policy' if f['kind']=='baseline_contradiction' else 'requirements'
                issue=self.tasks.issue(task_id=config['target_task_id'],kind=kind,screen=f['code_ref'],ui_state=config['stage'],observed=f['actual'],expected=f['expected'],severity=f['severity'],recheck='; '.join(f['repro']) or f['reason_code'],evidence=str(report_path.relative_to(self.root)),root_cause=json.dumps([f['owner_role'],f['kind'],f['reason_code'],f['code_ref'],f['baseline_ref'],f['expected']],sort_keys=True))
                def annotate(s,issue_id=issue['id'],finding=f):
                    entry=next(i for i in s['issues'] if i['id']==issue_id);entry['qa_finding']=copy.deepcopy(finding);entry['owner']=finding['owner_role'];entry['qa_task_id']=task_id
                self.tasks._mutate('qa_finding',annotate,task_id);attempt['finding_ids'].append(issue['id'])
            if passed and result.get('reviewed_issue_ids'):
                verified=self._resolve_reviewed_issues(task_id,config['target_task_id'],result,aid,review['agent_run_id'],str(report_path.relative_to(self.root)),source_before)
                attempt['resolved_issue_ids']=verified
            if result and outcome!='PASS':
                workflow=self.tasks.read().get('stage_workflows',{}).get(task['feature_id'])
                if workflow:
                    stages={finding_return_stage(f,workflow,config['target_task_id']) for f in result['findings']}
                    for stage in sorted(stages-{None}):
                        try:
                            returned=self.tasks.return_to_stage(task['feature_id'],stage,'QA finding requires owner correction',str(report_path.relative_to(self.root)),task_id,review['agent_run_id'])
                            attempt.setdefault('stage_returns',[]).append(returned)
                        except ValueError as exc:attempt.setdefault('stage_return_errors',[]).append(str(exc))
                development_findings=[f for f in result['findings'] if f['blocking'] and f['owner_role']=='development' and f['kind']!='improvement' and finding_return_stage(f,workflow,config['target_task_id']) is None]
                if development_findings:attempt['development_coordinator_return']={'target_task_id':config['target_task_id'],'finding_ids':attempt['finding_ids'],'reason':'implementation correction; development-plan approval is not implicitly invalidated'}
            context['phase']='save_attempt'
            self._save(task_id,attempt);last=attempt
            if passed or not repair or modified or source_changed or error:break
            if len(self.tasks.read()['tasks'][task_id]['qa_config']['attempts'])>=task['max_attempts']:break
            # Explicit owner callback only. QA cannot silently alter product or approve repairs.
            context['phase']='owner_repair'
            self.tasks.require_dispatch(task_id, preflight=True)
            repaired=repair(copy.deepcopy(attempt),copy.deepcopy(result),self.root)
            if not isinstance(repaired,dict) or repaired.get('status')!='COMPLETE' or not repaired.get('evidence'):break
            context['phase']='rebase'
            proof=self.tasks.artifact(repaired['evidence'])
            changed_originals=[r['path'] for r in config['original_requests'] if not (self.root/r['path']).is_file() or hashlib.sha256((self.root/r['path']).read_bytes()).hexdigest()!=r['sha256']]
            if changed_originals:
                def stop(s):
                    t=s['tasks'][task_id];t['qa_config']['attempts'][-1]['repair']={'status':'BLOCKED','reason':'repair changed original user request; no delegated policy authority','paths':changed_originals,'evidence':proof}
                self.tasks._mutate('qa_repair_authority_blocked',stop,task_id)
                last=copy.deepcopy(attempt);last['outcome']='BLOCKED';last['repair']='original request changed';break
            latest_state=self.tasks.read();target=latest_state['tasks'][config['target_task_id']]
            paths=list(dict.fromkeys([r['path'] for r in task['inputs']]+[r['path'] for r in target['inputs']+target['outputs']]))
            refs=[self.tasks.artifact(path) for path in paths]
            target_baseline={'declared_baseline':copy.deepcopy(target.get('development_tracking',{}).get('baselines',target['inputs'])),'observed_current_inputs':[self.tasks.artifact(r['path']) for r in target['inputs']],'observed_current_outputs':[self.tasks.artifact(r['path']) for r in target['outputs']]}
            def rebase(s):
                t=s['tasks'][task_id];before_inputs=copy.deepcopy(t['inputs']);t['inputs']=refs
                t.setdefault('input_rebases',[]).append({'before':before_inputs,'after':copy.deepcopy(refs),'reason':'owner repair followed by fresh QA retest','repair_evidence':proof})
                scope=target_scope(target,t['qa_config']['original_requests']);t['qa_config']['manifest_scope']=scope;t['qa_config']['target_manifest']=scoped_manifest(self.root,scope,generated);t['qa_config']['target_baseline']=target_baseline
                t['qa_config']['attempts'][-1]['repair']={'status':'REPORTED_COMPLETE_NOT_VERIFIED','evidence':proof}
                t['qa_config'].setdefault('retest_bases',[]).append({'manifest':scoped_manifest(self.root,scope,generated),'manifest_scope':scope,'inputs':copy.deepcopy(refs),'baseline':target_baseline,'repair':proof})
                self.tasks._event(s,'qa_retest_inputs_rebased',t,observed={'before':before_inputs,'after':refs,'repair':proof})
            self.tasks._mutate('qa_repair_retest_basis',rebase,task_id)
            config=self.tasks.read()['tasks'][task_id]['qa_config']
        return last
