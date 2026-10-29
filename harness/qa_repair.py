"""Explicitly configured owner repair callback, run by the active QA workflow.

No daemon or inferred policy authority. The original user request is immutable.
"""
import json
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
        manager.ready(tid);execution=manager.begin(tid,owner['role'],execution_mode='independent_process');aid=execution['agent_run_id']
        coordinator=Development(root,manager.run_id)
        try:
            ws,out,before,head=coordinator.workspace(tid,aid)
            packet={'parent_task_id':task['task_id'],'task_id':tid,'agent_run_id':aid,'responsible_role':owner['role'],'goal':'Repair only the QA omission using the immutable original user request. Do not invent policy or scope. If a new decision is required return BLOCKED.',
                'findings':result['findings'],'qa_report':attempt['report'],'original_requests':config['original_requests'],'inputs':execution['inputs'],'allowed_paths':paths,'out_of_scope':['original user request changes','new product policy','unrelated files','Git commits','deployment'],
                'instructions':'Read original request files at their path. Restore the explicitly requested missing behavior in the target document only. Do not resolve issues or claim quality PASS yourself. Return COMPLETE only when scoped output exists; a separate QA retest decides quality.'}
            runtime=run_codex(manager,tid,aid,ws,packet,out/'process',config['executable'],config['timeout'])
            claim=validate_result(runtime.get('result'))
            if runtime['returncode']!=0 or claim['status']!='COMPLETE' or claim['contract_change_required'] or claim['unresolved']:raise ValueError('owner repair failed or needs decision')
            after=manifest(ws);changed=sorted(p for p in before.keys()|after.keys() if before.get(p)!=after.get(p))
            if not changed or set(changed)!=set(claim['changed_files']) or any(not any(inside(p,a) for a in paths) for p in changed):raise ValueError('owner repair actual diff outside declared target outputs')
            for name in changed:
                if digest(root/name)!=before.get(name):raise ValueError('repair source changed concurrently')
                if not (ws/name).is_file():raise ValueError('repair may not delete target document')
            for name in changed:shutil.copy2(ws/name,root/name)
            manager.submit(tid,aid,changed,'scoped owner artifact produced; pending independent QA retest',design_status={'specification':'COMPLETE','mockup':'COMPLETE','visual_review':'NOT_RUN'} if owner['role']=='design' else None)
            proof=out/'repair-report.json';proof.write_text(json.dumps({'result':'REPORTED_COMPLETE_NOT_QUALITY_PASS','worker':runtime,'changed_files':changed,'qa_parent_task_id':task['task_id']},ensure_ascii=False,indent=2))
            return {'status':'COMPLETE','evidence':str(proof.relative_to(root))}
        except BaseException as exc:
            for execution in manager.read()['tasks'][tid]['executions']:
                if not execution.get('ended_at'):manager.fail(tid,execution['agent_run_id'],str(exc))
            raise
    return repair


def execute_with_owner(qa,task_id):
    qa._workflow_task_id=task_id
    result=qa.execute(task_id,repair=owner_repair(qa))
    config=qa.tasks.read()['tasks'][task_id]['qa_config'];tid=config.get('repair_task_id')
    if result.get('outcome')=='PASS' and tid:
        owner=qa.tasks.read()['tasks'][tid]
        if owner['state']=='IN_REVIEW':
            review=qa.tasks.begin(tid,'verification',review=True,execution_mode='local_check')
            qa.tasks.review(tid,review['agent_run_id'],[{'criterion_id':c['id'],'result':'PASS','evidence':result['report']['path']} for c in owner['criteria'] if c['required']], 'separate actual QA retest and current target evidence')
    return result
