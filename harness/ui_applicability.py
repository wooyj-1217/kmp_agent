"""Explicit, source-bound nonvisual interface contract; never visual PASS."""
import json
from harness import requirement_lineage as lineage


def declaration(root, path):
    ref = lineage.file_ref(root, path)
    value = json.loads((root / path).read_text())
    if (value.get('schema_version') != 1 or value.get('status') != 'NOT_APPLICABLE'
            or not isinstance(value.get('reason'), str) or not value['reason'].strip()
            or not isinstance(value.get('interfaces'), list) or not value['interfaces']
            or any(x not in {'cli', 'server', 'library', 'background_service'} for x in value['interfaces'])
            or not value.get('requirement_id')):
        raise ValueError('explicit nonvisual interfaces, reason and requirement ID required')
    return ref, value


def bind(manager, task, path):
    ref, value = declaration(manager.root, path)
    comparison = lineage.compare(manager.root)
    if not comparison['structurally_ready'] or not comparison['authorization_ready']:
        raise ValueError('UI applicability requires current authoritative requirement approval')
    if task.get('work_type') == 'PRODUCT' and comparison['scope'] != 'PRODUCT':
        raise ValueError('trial UI applicability cannot authorize PRODUCT')
    receipt = comparison['human_authorization'].get('receipt')
    if receipt and task['task_id'] not in receipt.get('task_ids', []):
        raise ValueError('UI applicability authorization belongs to another task')
    expected = {k: v for k, v in value.items() if k not in {'schema_version', 'requirement_id'}}
    requirement = next((r for r in comparison['requirements'] if r['id'] == value['requirement_id']), {})
    trial_mapping = comparison['scope'] == 'HARNESS_TRIAL' and any(
        d.get('expected', {}).get('ui_applicability') == expected and value['requirement_id'] in d['source_ids']
        and any(delta.get('derived_id') == d['id'] and delta.get('requirement_id') == value['requirement_id']
                and delta.get('status') == 'TRIAL_ONLY' for delta in comparison['deltas'])
        for d in comparison['derived_items'])
    if requirement.get('expected', {}).get('ui_applicability') != expected and not trial_mapping:
        raise ValueError('UI applicability must exactly match an authoritative requirement')
    if task.get('visual_required') or task.get('role_contract', {}).get('design_targets'):
        raise ValueError('nonvisual applicability conflicts with visual targets')
    paths = [path, lineage.NAME] + [s['path'] for s in comparison['sources']]
    refs = [{k:v for k,v in manager.artifact(p).items() if k != 'git_commit'} for p in dict.fromkeys(paths)]
    return {'declaration': ref, 'value': value, 'inputs': refs}


def validate(manager, task, *, reviewed=False):
    binding = task.get('role_contract', {}).get('ui_applicability')
    if not binding:
        return None
    current = bind(manager, task, binding['declaration']['path'])
    if current != binding:
        raise ValueError('UI applicability source or frozen contract changed; new reviewed task required')
    inputs = {(a['path'], a['sha256']) for a in task.get('inputs', [])}
    if any((a['path'], a['sha256']) not in inputs or not manager._valid_artifact(a) for a in binding['inputs']):
        raise ValueError('UI applicability requires every frozen source input')
    if reviewed:
        review = (task.get('reviews') or [{}])[-1]
        run = next((r for r in task.get('executions', []) if r['agent_run_id'] == review.get('agent_run_id')), {})
        actual_process = _independent_process(manager.root, run.get('agent_run_id'))
        if (not actual_process or task.get('state') != 'DONE' or review.get('ui_applicability') != binding
                or run.get('execution_mode') != 'independent_process'
                or review.get('outputs') != task.get('outputs')):
            raise ValueError('nonvisual handoff requires an independent current role review')
    return binding


def _independent_process(root, agent_run_id):
    path = root / '.harness/logs/events.jsonl'
    events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    process = [e.get('observed', {}) for e in events if e.get('agent_run_id') == agent_run_id and e.get('event_type') == 'role_process']
    if any(e.get('synthetic') or e.get('synthetic_fixture') for e in process):
        return False
    return (any(e.get('process_state') == 'role_process_started' and e.get('independent_model_spawned') is True for e in process)
            and any(e.get('process_state') == 'role_process_finished' and e.get('exit_code') == 0 for e in process))
