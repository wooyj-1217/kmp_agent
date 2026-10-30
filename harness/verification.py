"""Criterion execution receipts in the existing task/artifact/validation registry."""
import copy
import json
from pathlib import Path
from harness.logging import digest


def artifact_status(root, ref):
    root = Path(root).resolve()
    if not isinstance(ref, dict) or not ref.get('snapshot') or not ref.get('snapshot_sha256'):
        return {'state': 'MISSING', 'recovery': 'UNAVAILABLE'}
    path = (root / ref['snapshot']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        state = 'MISSING'
    elif digest(path.read_bytes()) != ref['snapshot_sha256']:
        state = 'HASH_MISMATCH'
    else:
        state = 'VALID'
    original = (root / ref.get('path', '')).resolve()
    recoverable = original.is_relative_to(root) and original.is_file() and digest(original.read_bytes()) == ref.get('sha256')
    return {'state': state, 'recovery': 'SNAPSHOT_AVAILABLE' if state == 'VALID' else 'SOURCE_AVAILABLE' if recoverable else 'UNAVAILABLE',
            'archive': 'NOT_ESTABLISHED', 'automatic_restore': False}


def text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() not in {'UNKNOWN','TODO','TBD'}


def configure(manager, task_id, procedure, environment, criteria, writable_paths, forbidden_paths, integrator, goal):
    def operation(state):
        task = state['tasks'][task_id]
        if task['executions'] or task['state'] not in {'TODO','READY'} or task.get('verification_contract'):
            raise ValueError('verification contract must be frozen once before execution')
        if not all(text(x) for x in (goal, integrator)) or not isinstance(writable_paths,list) or not writable_paths or not isinstance(forbidden_paths,list):
            raise ValueError('goal, integrator and explicit writable/forbidden paths required')
        for path in writable_paths + forbidden_paths:
            if not text(path) or Path(path).is_absolute() or '..' in Path(path).parts:
                raise ValueError('ownership paths must be project relative')
        from harness.verification_procedure import validate
        pref, eref = manager.artifact(procedure), manager.artifact(environment)
        proc = validate(json.loads((manager.root / pref['snapshot']).read_text()))
        if not isinstance(criteria,list) or len(criteria)!=len(task['criteria']) or {c.get('id') for c in criteria}!={c['id'] for c in task['criteria']}:
            raise ValueError('verification definitions must cover every criterion exactly once')
        for c in criteria:
            if set(c)!={'id','platforms','method','evidence_required','kind'} or not text(c['method']) or c['evidence_required'] is not True or c['kind'] not in {'execution','requirements'}:
                raise ValueError('criterion requires method, evidence and execution/requirements kind')
            if not isinstance(c['platforms'],list) or not c['platforms'] or len(set(c['platforms']))!=len(c['platforms']) or not set(c['platforms']).issubset(proc['platforms']):
                raise ValueError('criterion requires distinct supported platforms')
            if c['kind']=='execution' and any(proc['platforms'][p]['procedure'] is None for p in c['platforms']):
                raise ValueError('execution criterion needs an actual platform procedure')
        required = {p for p,c in proc['platforms'].items() if c['required']}
        covered = {p for c in criteria if c['kind']=='execution' and next(x for x in task['criteria'] if x['id']==c['id'])['required'] for p in c['platforms']}
        if not required.issubset(covered):
            raise ValueError('every required platform must bind a required criterion')
        contract = {'goal':goal,'integrator':integrator,'writable_paths':writable_paths,'forbidden_paths':forbidden_paths,
                    'procedure':pref,'environment':eref,'criteria':copy.deepcopy(criteria)}
        task['verification_contract']=contract
        for ref in (pref,eref):
            if ref not in task['inputs']: task['inputs'].append(ref)
        manager._event(state,'verification_contract_configured',task,observed=copy.deepcopy(contract))
        return copy.deepcopy(contract)
    return manager._mutate('configure_verification',operation,task_id)


def context(manager, task):
    contract = task['verification_contract']
    for ref in task['inputs'] + [contract['procedure'],contract['environment']]:
        if artifact_status(manager.root,ref)['state']!='VALID':
            raise ValueError('input snapshot missing or hash mismatch')
        path=(manager.root/ref['path']).resolve()
        if not path.is_relative_to(manager.root) or not path.is_file() or digest(path.read_bytes())!=ref['sha256']:
            raise ValueError('input, procedure or environment changed; recheck required')
    return {'inputs':{r['path']:r['sha256'] for r in task['inputs']},
            'procedure_sha256':contract['procedure']['sha256'],'environment_sha256':contract['environment']['sha256']}


def review_gate(manager, task, run, results):
    if not task.get('verification_contract'): return None
    basis=context(manager,task)
    work=[r for r in task['executions'] if r['kind']=='work'][-1]
    if not run.get('actor_id') or not work.get('actor_id') or run['actor_id']==work['actor_id']:
        raise ValueError('verification requires separately identified implementation and reviewer actors')
    code = None
    if task.get('development_tracking'):
        from harness.development_tracking import capture
        code=capture(manager,task)['state_sha256']
    expected_outputs={a['path']:a['sha256'] for a in task['outputs']}
    proofs=[]
    for row in results:
        if row['result']!='PASS': continue
        report=json.loads((manager.root/row['evidence']['snapshot']).read_text())
        definition=next(c for c in task['verification_contract']['criteria'] if c['id']==row['criterion_id'])
        if report.get('task_id')!=task['task_id'] or report.get('criterion_id')!=row['criterion_id'] or report.get('review_run_id')!=run['agent_run_id'] or report.get('actor_id')!=run['actor_id']:
            raise ValueError('receipt must bind exact task, criterion and reviewer execution')
        if any(report.get(k)!=v for k,v in basis.items()) or report.get('tested_outputs')!=expected_outputs or report.get('code_state_sha256')!=code:
            raise ValueError('receipt target/input/environment mismatch')
        if report.get('kind')!=definition['kind'] or report.get('method')!=definition['method']:
            raise ValueError('execution and requirement completeness reviews cannot substitute')
        executions=report.get('platform_results',[])
        if not isinstance(executions,list) or len(executions)!=len(definition['platforms']) or {x.get('platform') for x in executions}!=set(definition['platforms']):
            raise ValueError('every criterion platform must be verified separately')
        for item in executions:
            if item.get('result')!='PASS' or not all(text(item.get(k)) for k in ('environment','command_or_steps','expected','observed')):
                raise ValueError('unexecuted, failed or blocked platform is not PASS')
            if definition['kind']=='execution' and (item.get('doctor')!='PASS' or item.get('drive')!='PASS' or item.get('cleanup')!='PASS'):
                raise ValueError('build/API alone cannot establish user drive and cleanup')
            refs=item.get('evidence',[])
            if not refs or any(artifact_status(manager.root,a)['state']!='VALID' for a in refs):
                raise ValueError('actual observation evidence missing or hash mismatch after cleanup')
            proofs.extend(copy.deepcopy(refs))
    return {'basis':basis,'evidence':proofs,'actor_id':run['actor_id'],'contract':copy.deepcopy(task['verification_contract'])}


def current_reasons(manager, task, review):
    reasons=[]
    for ref in task.get('inputs',[]) + review.get('outputs',[]):
        status=artifact_status(manager.root,ref)
        if status['state']!='VALID': reasons.append(status['state']+': '+ref.get('path','?')+'; recovery='+status['recovery'])
        path=(manager.root/ref.get('path','')).resolve()
        if not path.is_relative_to(manager.root) or not path.is_file() or digest(path.read_bytes())!=ref.get('sha256'):
            reasons.append('current input/output differs: '+ref.get('path','?'))
    for row in review.get('results',[]):
        if row.get('result')=='PASS' and artifact_status(manager.root,row.get('evidence'))['state']!='VALID':
            reasons.append('review evidence missing or hash mismatch')
    proof=review.get('verification_evidence')
    if task.get('verification_contract'):
        try:
            if not proof or proof['basis']!=context(manager,task) or proof['contract']!=task['verification_contract']:
                reasons.append('verification contract/environment changed or proof absent')
            for ref in (proof or {}).get('evidence',[]):
                status=artifact_status(manager.root,ref)
                if status['state']!='VALID': reasons.append('observation '+status['state']+'; recovery='+status['recovery'])
        except (ValueError,OSError,KeyError,TypeError): reasons.append('verification context cannot be established')
    return sorted(set(reasons))


def refresh(manager,state):
    for task in state['tasks'].values():
        for review in task.get('reviews',[]):
            reasons=current_reasons(manager,task,review)
            key=review['agent_run_id']
            old=task.setdefault('validation_status',{}).get(key,{})
            if reasons and old.get('state')!='RECHECK_REQUIRED':
                status={'state':'RECHECK_REQUIRED','reasons':reasons}
                task['validation_status'][key]=status
                manager._event(state,'verification_invalidated',task,key,observed=status)


def submission_gate(manager, task, run, outputs):
    contract=task['verification_contract']
    def matches(path, scopes):
        return any(base=='.' or path==base.rstrip('/') or path.startswith(base.rstrip('/')+'/') for base in scopes)
    changed=set(outputs)
    from harness.logging import snapshot
    before=run.get('ownership_files_start')
    if before is None: raise ValueError('ownership start snapshot missing')
    after=snapshot(manager.root)
    changed.update(p for p in before.keys() | after.keys() if before.get(p)!=after.get(p))
    if task.get('development_tracking'):
        from harness.development_tracking import capture
        before=run['code_state_start']['files'];after=capture(manager,task)['files']
        changed.update(p for p in before.keys() | after.keys() if before.get(p)!=after.get(p))
    if any(not matches(p,contract['writable_paths']) or matches(p,contract['forbidden_paths']) for p in changed):
        raise ValueError('submission changed paths outside writable ownership or inside forbidden scope')


def qa_receipts(manager, task_id, run, result, rows, workspace, base):
    """Archive actual per-platform QA observations; never infer them from build exit codes."""
    import shutil
    task=manager.read()['tasks'][task_id]
    basis=context(manager,task)
    for row in rows:
        if row['result']!='PASS': continue
        observed=next(c for c in result['criteria'] if c['criterion_id']==row['criterion_id'])
        definition=next(c for c in task['verification_contract']['criteria'] if c['id']==row['criterion_id'])
        platforms=copy.deepcopy(observed.get('platform_results',[]))
        if not platforms: raise ValueError('configured QA requires actual per-platform observations, not generic PASS')
        for item in platforms:
            refs=[]
            for relative in item.get('evidence',[]):
                path=(workspace/relative).resolve()
                if not path.is_relative_to(workspace) or not path.is_file():
                    raise ValueError('QA platform evidence missing or outside isolated workspace')
                dest=base/'evidence'/digest((row['criterion_id']+item['platform']+relative).encode())
                dest.parent.mkdir(exist_ok=True);shutil.copyfile(path,dest)
                refs.append(manager.artifact(str(dest.relative_to(manager.root))))
            item['evidence']=refs
        payload={**basis,'task_id':task_id,'criterion_id':row['criterion_id'],'review_run_id':run['agent_run_id'],
                 'actor_id':run['actor_id'],'kind':definition['kind'],'method':definition['method'],
                 'tested_outputs':{a['path']:a['sha256'] for a in task['outputs']},'code_state_sha256':None,
                 'platform_results':platforms}
        path=base/('receipt-'+digest(row['criterion_id'].encode())+'.json')
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        row['evidence']=str(path.relative_to(manager.root))
    return rows
