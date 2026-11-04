"""Connect an approved development-plan task to the existing code coordinator.

No approval inference, new scheduler, or implicit conversion of interpretation tasks.
"""
import copy
import fcntl
import hashlib
import json
from pathlib import Path
import re

from harness.delegation import Development, normalized, inside
from harness.stage_readiness import assess

FIELDS = {'schema_version', 'task_id', 'title', 'goal', 'criteria', 'baselines',
          'code_paths', 'api_required', 'service_version', 'stage', 'children',
          'architecture', 'shared_owners', 'integration_commands'}
OPTIONAL = {'max_parallel', 'timeout'}


def parse(text):
    blocks = re.findall(r'^```development-execution\s*\n(.*?)^```\s*$', text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError('development-plan.md requires exactly one development-execution JSON block')
    value = json.loads(blocks[0])
    if not isinstance(value, dict) or not FIELDS <= set(value) or set(value) - FIELDS - OPTIONAL:
        raise ValueError('development-execution has missing or unknown fields')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported development-execution schema')
    for key in ('task_id', 'title', 'goal', 'service_version'):
        if not isinstance(value[key], str) or not value[key].strip() or value[key] in {'TODO', 'UNKNOWN'}:
            raise ValueError('concrete development-execution '+key+' required')
    if Path(value['task_id']).name != value['task_id'] or value['task_id'] in {'.', '..'}:
        raise ValueError('implementation task ID must be a single name')
    if type(value['api_required']) is not bool:
        raise ValueError('api_required must be explicit boolean')
    if not isinstance(value['baselines'], dict) or not {'planning', 'design', 'policy'} <= set(value['baselines']) or set(value['baselines']) - {'planning', 'design', 'api', 'policy'}:
        raise ValueError('explicit planning/design/policy baseline paths required')
    if value['api_required'] and 'api' not in value['baselines']:
        raise ValueError('API baseline required')
    if not isinstance(value['code_paths'], list) or not value['code_paths']:
        raise ValueError('explicit code_paths required')
    for path in value['code_paths']:
        if normalized(path) != path or path == '.' or path == 'verification' or path.startswith('verification/'):
            raise ValueError('code_paths must be normalized product source scopes')
    criteria = value['criteria']
    if not isinstance(criteria, list) or not criteria or any(not isinstance(c, dict) or not c.get('id') or not c.get('description') or type(c.get('required')) is not bool for c in criteria) or not any(c['required'] for c in criteria) or len({c['id'] for c in criteria}) != len(criteria):
        raise ValueError('implementation needs distinct explicit acceptance criteria')
    if not isinstance(value['children'], list) or not value['children'] or not isinstance(value['architecture'], dict) or not isinstance(value['shared_owners'], dict):
        raise ValueError('explicit children, architecture and shared owners required')
    for child in value['children']:
        if not isinstance(child, dict) or not all(child.get(k) for k in ('task_id', 'area', 'title', 'goal', 'requirement_ids', 'acceptance_ids', 'allowed_paths', 'verification_commands')) or 'out_of_scope' not in child:
            raise ValueError('each child needs scope, requirement/acceptance IDs and commands')
        if Path(child['task_id']).name != child['task_id'] or child['task_id'] in {'.', '..'}:
            raise ValueError('child task ID must be a single name')
        if any(not any(inside(normalized(p), scope) for scope in value['code_paths']) for p in child['allowed_paths']):
            raise ValueError('child ownership exceeds approved parent code_paths')
        for command in child['verification_commands']:
            Development._command(command)
    if not isinstance(value['integration_commands'], list) or not value['integration_commands']:
        raise ValueError('separate integration commands required')
    for command in value['integration_commands']:
        Development._command(command)
    for key, low, high in [('max_parallel', 1, 8), ('timeout', 1, None)]:
        if key in value and (type(value[key]) is not int or value[key] < low or high is not None and value[key] > high):
            raise ValueError('invalid development-execution '+key)
    stage = value['stage']
    if stage is not None and (not isinstance(stage, dict) or set(stage) != {'settings', 'stage'} or stage['stage'] not in {'ui', 'client_integration', 'server_implementation'} or not isinstance(stage['settings'], str)):
        raise ValueError('implementation stage needs project settings; product integration acceptance stays separate')
    return value


def _approved(manager, task_id):
    state = manager.read()
    task = state['tasks'][task_id]
    flow = state.get('stage_workflows', {}).get(task['feature_id'])
    if not flow or flow['stages']['development_plan']['task_id'] != task_id:
        raise ValueError('implementation requires the current independently reviewed development-plan stage')
    if task.get('role_contract', {}).get('scope') == 'input_interpretation_only':
        raise ValueError('legacy input interpretation is not an approved implementation plan; create a stage revision')
    readiness = assess(manager.root, state, task['feature_id'])
    if readiness['status'] != 'PASS':
        raise ValueError('planning/design/development-plan approval missing or stale: '+str([(s['stage'], s['status']) for s in readiness['stages'] if s['status'] != 'PASS']))
    refs = [a for a in task['outputs'] if Path(a['path']).name == 'development-plan.md']
    if len(refs) != 1:
        raise ValueError('one approved canonical development-plan.md required')
    ref = refs[0]
    value = parse((manager.root/ref['snapshot']).read_text())
    approved = {a['path']: a for a in task['inputs'] + task['outputs']}
    for stage in ('planning', 'design'):
        upstream = state['tasks'][flow['stages'][stage]['task_id']]
        if value['baselines'][stage] not in {a['path'] for a in upstream['outputs']}:
            raise ValueError('implementation baseline must be the approved '+stage+' output')
    for path in list(value['baselines'].values()) + value['architecture'].get('evidence', []):
        if path not in approved:
            raise ValueError('implementation source must already be a reviewed plan input: '+str(path))
    for child in value['children']:
        attempts=child.get('max_attempts',task['max_attempts'])
        if type(attempts) is not int or not 1 <= attempts <= task['max_attempts']:
            raise ValueError('child attempts exceed approved plan task retry budget')
    if task['work_type'] == 'PRODUCT' and value['stage'] is None:
        raise ValueError('PRODUCT implementation requires approved project stage/settings')
    if value['stage']:
        from harness.project_contract import DOCUMENTS, validate
        path = value['stage']['settings']
        if path not in approved:
            raise ValueError('project settings must already be a reviewed plan input')
        settings = validate(json.loads((manager.root/approved[path]['snapshot']).read_text()))
        for key in DOCUMENTS:
            item = settings[key]
            if item['status'] in {'CONFIRMED', 'PROPOSED'} and item['value'] not in approved:
                raise ValueError('project contract document must be a reviewed plan input: '+key)
    # Assess checked current bytes too; retain the exact frozen refs, not new copies.
    return state, task, value, ref, readiness['basis']


def prepare(manager, task_id):
    """Derive native code tasks from reviewed bytes; never modify the approved plan."""
    lockpath = manager.directory/('implementation-'+hashlib.sha256(task_id.encode()).hexdigest()+'.lock')
    with lockpath.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state, task, value, ref, basis = _approved(manager, task_id)
        tid = value['task_id']
        origin = {'plan_task_id':task_id, 'artifact':ref, 'stage_basis':basis}
        previous = state['tasks'].get(tid)
        if previous:
            if previous.get('implementation_origin') != origin:
                raise ValueError('implementation task ID already belongs to another source; create a reviewed revision')
            if not previous.get('development_delegation'):
                raise ValueError('unfinished implementation configuration preserved; inspect and explicitly recover')
            return tid
        sources = {a['path']:a for a in task['inputs'] + task['outputs']}
        manager.register(task['feature_id'], tid, 'development', value['title'], value['goal'],
                         value['criteria'], list(sources), dependencies=[task_id],
                         max_attempts=task['max_attempts'], work_type=task['work_type'],
                         execution_scope='code_implementation', pipeline_stage='development')
        def link(current):
            parent=current['tasks'][tid]
            parent['inputs']=list(copy.deepcopy(sources).values())
            parent['implementation_origin']=copy.deepcopy(origin)
            current['tasks'][task_id]['implementation_task_id']=tid
            manager._event(current,'implementation_plan_connected',parent,observed=origin)
        manager._mutate('connect_implementation_plan',link,tid)
        if value['stage']:
            manager.configure_stage(tid, **value['stage'])
        manager.configure_development(tid,value['baselines'],value['code_paths'],value['api_required'],value['service_version'])
        Development(manager.root,manager.run_id).configure(tid,value['children'],value['architecture'],
                value['shared_owners'],value['integration_commands'],value.get('max_parallel',2),timeout=value.get('timeout',600))
        children = [c['task_id'] for c in value['children']]
        # Reuse the existing Todo source, preserving all preceding steps/history.
        def todo(current):
            plan=current.setdefault('execution_plans',{}).get(manager.run_id)
            if plan:
                for new in [tid]+children:
                    if new not in plan['task_ids']:plan['task_ids'].append(new)
                plan['history'].append({'reason':'approved development plan connected to implementation','evidence':ref,'task_ids':plan['task_ids'][:]})
                manager._event(current,'execution_plan_revised',current['tasks'][tid],observed={'source_plan_task_id':task_id,'task_ids':[tid]+children})
        if manager.run_id in manager.read().get('execution_plans',{}):
            manager._mutate('connect_implementation_todo',todo,tid)
        else:
            from harness.execution_plan import attach_existing
            attach_existing(manager,[task_id,tid]+children,'IMPLEMENT','delivery_with_qa',value['goal'],ref['path'],'approved plan continuation; new code tasks have not executed yet')
        _approved(manager,task_id)
        return tid


def execute(manager, task_id, worker=None):
    tid=prepare(manager,task_id)
    result=Development(manager.root,manager.run_id).execute(tid,worker)
    return dict(result, source_plan_task_id=task_id, implementation_task_id=tid)
