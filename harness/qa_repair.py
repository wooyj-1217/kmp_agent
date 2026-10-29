"""Explicitly configured owner repair callback, run by the active QA workflow.

No daemon or inferred policy authority. The original user request is immutable.
"""
import json
import copy
import hashlib
import uuid
from pathlib import Path
import shutil
from harness.delegation import Development,manifest,inside,digest,normalized
from harness.delegation_runtime import run_codex,validate_result
from harness.roles import Roles


def owner_repair(qa):
    def repair(attempt,result,root):
        manager=qa.tasks;task=manager.read()['tasks'][qa._workflow_task_id];config=task['qa_config']
        tid=config.get('repair_task_id')
        if not tid:return {'status':'BLOCKED','evidence':None}
        state=manager.read();owner=state['tasks'][tid];target=state['tasks'][config['target_task_id']]
        if (owner.get('feature_id'),owner.get('project_id'),owner.get('work_type'))!=(target.get('feature_id'),target.get('project_id'),target.get('work_type')):raise ValueError('repair owner belongs outside the target feature/project/work scope')
        if owner['role'] not in {'planning','design','development'}:raise ValueError('repair owner must be responsible author role')
        if any(f.get('blocking') and f['owner_role']!=owner['role'] for f in result['findings']):return {'status':'BLOCKED','evidence':None}
        if owner.get('development_delegation'):
            if owner['state']=='DONE':return {'status':'BLOCKED','evidence':None,'reason':'accepted implementation is not a new repair; configure a separate authorized repair revision'}
            outcome=Roles(root,manager.run_id).execute(tid,'development')
            proof=manager.directory/'qa-repair-result.json';proof.write_text(json.dumps(outcome))
            return {'status':'COMPLETE' if outcome.get('handoff')=='READY_FOR_VERIFICATION' else 'BLOCKED','evidence':str(proof.relative_to(root))}
        if owner.get('execution_scope')!='documentation':return {'status':'BLOCKED','evidence':None}
        paths=[normalized(a['path']) for a in target.get('outputs',[]) if not a['path'].startswith('.harness/')]
        if not paths:raise ValueError('explicit target output paths required for owner repair')
        originals={r['path'] for r in config['original_requests']}
        if any(any(inside(p,o) or inside(o,p) for o in originals) for p in paths):raise ValueError('owner repair may not include immutable original request paths')
        context={'phase':'owner_begin','owned_runs':[],'owns_result':True}
        try:
            manager.ready(tid);aid=str(uuid.uuid4());context['owned_runs'].append(aid)
            execution=manager.begin(tid,owner['role'],execution_mode='independent_process',agent_run_id=aid)
            context['phase']='owner_prepare_workspace'
            coordinator=Development(root,manager.run_id)
            ws,out,before,head=coordinator.workspace(tid,aid)
            packet={'parent_task_id':task['task_id'],'task_id':tid,'agent_run_id':aid,'responsible_role':owner['role'],'goal':'Repair only the QA omission using the immutable original user request. Do not invent policy or scope. If a new decision is required return BLOCKED.',
                'findings':result['findings'],'qa_report':attempt['report'],'original_requests':config['original_requests'],'inputs':execution['inputs'],'allowed_paths':paths,'out_of_scope':['original user request changes','new product policy','unrelated files','Git commits','deployment'],
                'instructions':'Read original request files at their path. Restore the explicitly requested missing behavior in the target document only. Do not resolve issues or claim quality PASS yourself. Return COMPLETE only when scoped output exists; a separate QA retest decides quality.'}
            context['phase']='owner_worker'
            runtime=run_codex(manager,tid,aid,ws,packet,out/'process',config['executable'],config['timeout'])
            claim=validate_result(runtime.get('result'))
            if runtime['returncode']!=0 or claim['status']!='COMPLETE' or claim['contract_change_required'] or claim['unresolved']:raise ValueError('owner repair failed or needs decision')
            context['phase']='owner_result_processing'
            after=manifest(ws);changed=sorted(p for p in before.keys()|after.keys() if before.get(p)!=after.get(p))
            if not changed or set(changed)!=set(claim['changed_files']) or any(not any(inside(p,a) for a in paths) for p in changed):raise ValueError('owner repair actual diff outside declared target outputs')
            for name in changed:
                if digest(root/name)!=before.get(name):raise ValueError('repair source changed concurrently')
                if not (ws/name).is_file():raise ValueError('repair may not delete target document')
            context['phase']='owner_apply'
            for name in changed:shutil.copy2(ws/name,root/name)
            context['phase']='owner_submit'
            manager.submit(tid,aid,changed,'scoped owner artifact produced; pending independent QA retest',design_status={'specification':'COMPLETE','mockup':'COMPLETE','visual_review':'NOT_RUN'} if owner['role']=='design' else None)
            context['phase']='owner_publish_result'
            proof=out/'repair-report.json';proof.write_text(json.dumps({'result':'REPORTED_COMPLETE_NOT_QUALITY_PASS','worker':runtime,'changed_files':changed,'qa_parent_task_id':task['task_id']},ensure_ascii=False,indent=2))
            return {'status':'COMPLETE','evidence':str(proof.relative_to(root))}
        except BaseException as exc:
            from harness.qa_failure import record_failure
            record_failure(manager,tid,context,exc)
            raise
    return repair


def _owner_review(qa,qa_task_id,attempt,owner,context):
    """Transfer only explicitly linked, current per-criterion QA evidence."""
    from harness.qa import scoped_manifest
    manager=qa.tasks;state=manager.read();task=state['tasks'][qa_task_id];config=task['qa_config']
    ref=attempt['report'];path=manager.root/ref['path']
    problems=[];data={}
    if not manager._valid_artifact(ref) or not path.is_file() or digest(path)!=ref['sha256']:
        problems.append('QA report is missing or changed')
    else:data=json.loads((manager.root/ref['snapshot']).read_text())
    qa_review=next((r for r in task['reviews'] if r['agent_run_id']==attempt.get('review_run_id')),None)
    current_review={r['criterion_id']:r for r in (qa_review or {}).get('results',[])}
    if task['state']!='DONE' or data.get('result')!='PASS' or not qa_review or not task['qa_config']['attempts'] or task['qa_config']['attempts'][-1]['agent_run_id']!=attempt['agent_run_id']:
        problems.append('latest native QA review is not current PASS')
    if data.get('target_task_id')!=config['target_task_id'] or data.get('target_scope')!=config['manifest_scope'] or data.get('generated_paths')!=config.get('generated_paths',[]):
        problems.append('QA target or generated-output policy changed since QA')
    if data.get('criterion_definitions')!=task['criteria'] or data.get('repair_criteria')!=config.get('repair_criteria',{}):
        problems.append('criterion definitions or links changed since QA')
    if scoped_manifest(manager.root,config['manifest_scope'],config.get('generated_paths',[]))!=data.get('target_manifest'):
        problems.append('target changed after QA')
    outputs=owner['outputs']
    if not outputs or any(not manager._valid_artifact(r) or digest(manager.root/r['path'])!=r['sha256'] for r in outputs):
        problems.append('owner outputs missing or changed after submission')
    scope=config['manifest_scope']
    if scope.get('mode')=='target_paths' and any(not any(p==base or p.startswith(base+'/') for base in scope['paths']) for p in owner.get('development_tracking',{}).get('code_paths',[])):
        problems.append('QA scope does not cover owner code paths')
    if any(data.get('target_manifest',{}).get(r['path'])!=r['sha256'] for r in outputs if not r['path'].startswith('.harness/')):
        problems.append('QA target does not cover owner outputs')
    rows=[];links=data.get('repair_criteria',{});definitions=data.get('repair_criteria_definitions',{})
    for criterion in owner['criteria']:
        ids=links.get(criterion['id'],[]);evidence={q:data.get('evidence_refs',{}).get(q) for q in ids}
        valid=(not problems and bool(ids) and definitions.get(criterion['id'])==criterion
               and all(data.get('criteria',{}).get(q)=='PASS' and current_review.get(q,{}).get('result')=='PASS'
                       and current_review[q].get('evidence',{}).get('sha256')==ref['sha256']
                       and manager._valid_artifact(current_review[q]['evidence'])
                       and evidence[q] and manager._valid_artifact(evidence[q]) for q in ids))
        result='PASS' if valid else 'NOT_RUN'
        proof={'result':result,'owner_task_id':owner['task_id'],'owner_criterion':criterion,
               'qa_task_id':qa_task_id,'qa_agent_run_id':attempt['agent_run_id'],'qa_review_run_id':attempt.get('review_run_id'),
               'qa_criterion_ids':ids,'qa_evidence':evidence,'qa_report':ref,
               'tested_outputs':{r['path']:r['sha256'] for r in outputs},'problems':problems,
               'claim_scope':data.get('claim_scope','LEGACY_UNCERTIFIED')}
        if not valid:proof['problems']=problems+['criterion lacks matching current QA PASS and evidence']
        if owner.get('development_tracking'):
            from harness.development_tracking import capture,baseline
            proof.update(code_state_sha256=capture(manager,owner)['state_sha256'],baseline=baseline(owner))
        filename=hashlib.sha256((owner['task_id']+criterion['id']).encode()).hexdigest()+'.json'
        dest=path.parent/'owner-review'/filename;dest.parent.mkdir(exist_ok=True)
        if dest.exists():raise ValueError('owner review proof already exists; use a fresh QA retest')
        dest.write_text(json.dumps(proof,ensure_ascii=False,indent=2))
        rows.append({'criterion_id':criterion['id'],'result':result,'evidence':str(dest.relative_to(manager.root))})
    context['phase']='owner_begin_review'
    review_id=str(uuid.uuid4());context['owned_runs'].append(review_id)
    review=manager.begin(owner['task_id'],'verification',review=True,execution_mode='local_check',agent_run_id=review_id)
    context['phase']='owner_review'
    outcome=manager.review(owner['task_id'],review['agent_run_id'],rows,'explicit QA criterion IDs, current target and preserved per-criterion evidence; no whole-PASS copy')
    return {'outcome':outcome,'criteria':rows,'review_run_id':review['agent_run_id']}


def execute_with_owner(qa,task_id):
    qa._workflow_task_id=task_id
    result=qa.execute(task_id,repair=owner_repair(qa))
    if result.get('outcome')!='PASS':return result
    tid=None;context={'phase':'owner_result_processing','owned_runs':[],'owns_result':False}
    try:
        config=qa.tasks.read()['tasks'][task_id]['qa_config'];tid=config.get('repair_task_id')
        if tid:
            owner=qa.tasks.read()['tasks'][tid]
            target=qa.tasks.read()['tasks'][config['target_task_id']]
            if (owner.get('feature_id'),owner.get('project_id'),owner.get('work_type'))!=(target.get('feature_id'),target.get('project_id'),target.get('work_type')):
                raise ValueError('owner acceptance is outside QA target feature/project/work scope')
            if owner['state']=='IN_REVIEW':
                context['owns_result']=True
                result['owner_review']=_owner_review(qa,task_id,result,owner,context)
    except BaseException as error:
        from harness.qa_failure import record_failure
        failure=record_failure(qa.tasks,tid if context['owns_result'] else task_id,context,error)
        result['owner_review']=failure
        if not isinstance(error,Exception):raise
    if result.get('owner_review'):result['owner_acceptance']='PASS' if result['owner_review']['outcome']=='DONE' else 'NOT_PASSED'
    return result
