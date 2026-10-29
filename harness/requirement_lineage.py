"""Frozen source/derivation contract. Structural checks are not semantic QA.

Uses native artifacts, verification tasks and agent_run IDs; no parallel ledger.
No platform names or product-specific limits belong here.
"""
import hashlib
import json
from pathlib import Path

NAME = 'requirement-lineage.json'
KINDS = {'USER_ORIGINAL', 'APPROVED_REQUIREMENTS', 'AGENT_DERIVED'}


def file_ref(root, path):
    root = Path(root).resolve()
    p = root / path
    if not isinstance(path, str) or Path(path).is_absolute() or '..' in Path(path).parts:
        raise ValueError('lineage paths must be project relative')
    if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file():
        raise ValueError('lineage source missing or unsafe: ' + path)
    return {'path': path, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def load(root):
    path = Path(root) / NAME
    if not path.is_file():
        raise ValueError('requirement lineage missing; legacy evidence is not certified')
    c = json.loads(path.read_text())
    if c.get('schema_version') != 1 or c.get('scope') not in {'PRODUCT', 'HARNESS_TRIAL'}:
        raise ValueError('explicit PRODUCT or HARNESS_TRIAL lineage required')
    if not c.get('purpose') or not c.get('sources') or not c.get('requirements') or not isinstance(c.get('derived_items'), list):
        raise ValueError('purpose, typed sources and both requirement inventories required')
    sources = {}
    for s in c['sources']:
        if s.get('kind') not in KINDS or not s.get('anchor') or s.get('id') in sources:
            raise ValueError('unique typed source and source anchor required')
        if file_ref(root, s['path'])['sha256'] != s.get('sha256'):
            raise ValueError('source changed: ' + s['path'])
        sources[s['id']] = s
    if not any(s['kind'] == 'USER_ORIGINAL' for s in sources.values()):
        raise ValueError('literal user source required; agent text is not original')
    if c['scope'] == 'HARNESS_TRIAL':
        auth = sources.get(c.get('scope_authorization'))
        if not auth or auth['kind'] != 'USER_ORIGINAL' or c.get('product_pass_claim') is not False:
            raise ValueError('trial requires original authorization and explicit no product PASS')
    paths = {}
    for s in sources.values():
        if s['path'] in paths and paths[s['path']] != s['kind']:
            raise ValueError('same source cannot be both agent-derived and original/approved')
        paths[s['path']] = s['kind']
    reqs = {}
    for r in c['requirements']:
        source = sources.get(r.get('source'))
        if not r.get('id') or r['id'] in reqs or not source or source['kind'] == 'AGENT_DERIVED' or not r.get('anchor') or not isinstance(r.get('expected'), dict) or not r['expected']:
            raise ValueError('authoritative requirement needs unique ID, expectation and source')
        reqs[r['id']] = r
    ids = set()
    for d in c['derived_items']:
        s = sources.get(d.get('source'))
        if not d.get('id') or d['id'] in ids or not s or s['kind'] != 'AGENT_DERIVED' or not d.get('anchor') or not isinstance(d.get('expected'), dict):
            raise ValueError('derived item requires agent source, unique ID and expectation')
        if not isinstance(d.get('source_ids'), list) or set(d['source_ids']) - set(reqs):
            raise ValueError('derived item has unknown original IDs')
        ids.add(d['id'])
    return c


def compare(root):
    c = load(root)
    sources = {s['id']: s for s in c['sources']}
    authority_issues = []
    for source in sources.values():
        if source['kind'] == 'APPROVED_REQUIREMENTS':
            approval = source.get('approval', {})
            origin = sources.get(approval.get('source'))
            if not origin or origin['kind'] != 'USER_ORIGINAL' or not approval.get('anchor') or approval.get('approved_sha256') != source['sha256']:
                authority_issues.append({'source_id': source['id'], 'status': 'APPROVAL_UNCONFIRMED', 'reason': 'approved baseline needs original user approval/authorization source and anchor'})
    deltas = []
    for r in c['requirements']:
        linked = [d for d in c['derived_items'] if r['id'] in d['source_ids']]
        if not linked:
            deltas.append({'id': 'omitted:' + r['id'], 'kind': 'OMITTED', 'requirement_id': r['id'], 'expected': r['expected'], 'actual': None})
        for d in linked:
            kind = 'EXCLUDED' if d.get('excluded') else 'CHANGED' if d['expected'] != r['expected'] else None
            if kind:
                deltas.append({'id': r['id'] + ':' + d['id'], 'kind': kind, 'requirement_id': r['id'], 'derived_id': d['id'], 'expected': r['expected'], 'actual': d['expected']})
    for d in c['derived_items']:
        if not d['source_ids']:
            deltas.append({'id': 'added:' + d['id'], 'kind': 'ADDED', 'derived_id': d['id'], 'expected': None, 'actual': d['expected']})
    decisions = c.get('decisions', [])
    if len({x.get('delta_id') for x in decisions}) != len(decisions) or any(x.get('delta_id') not in {d['id'] for d in deltas} for x in decisions):
        raise ValueError('decision must refer to one current exact delta')
    for d in deltas:
        decision = next((x for x in decisions if x['delta_id'] == d['id']), {})
        # Approval binds BOTH values, not just a reusable change ID/string.
        source = sources.get(decision.get('source'))
        approved = bool(source and source['kind'] == 'USER_ORIGINAL' and decision.get('anchor') and decision.get('expected') == d['expected'] and decision.get('actual') == d['actual'] and decision.get('status') == 'APPROVED')
        trial = c['scope'] == 'HARNESS_TRIAL' and decision.get('status') == 'TRIAL_ONLY' and bool(decision.get('reason')) and decision.get('expected') == d['expected'] and decision.get('actual') == d['actual']
        d['status'] = 'APPROVED' if approved else 'TRIAL_ONLY' if trial else 'DECISION_REQUIRED'
        d['decision'] = decision or None
    return {'scope': c['scope'], 'purpose': c['purpose'], 'contract': file_ref(root, NAME), 'sources': c['sources'], 'requirements': c['requirements'], 'derived_items': c['derived_items'], 'deltas': deltas, 'authority_issues': authority_issues, 'structurally_ready': not authority_issues and all(d['status'] != 'DECISION_REQUIRED' for d in deltas), 'product_requirements_pass': 'NOT_ESTABLISHED', 'execution_path_pass': 'NOT_ESTABLISHED', 'semantic_review': 'REQUIRED'}


def criteria(root):
    c = load(root)
    return [{'id': 'LINEAGE-INVENTORY', 'required': True, 'description': 'Read literal source and approved documents independently. Confirm complete original inventory; do not trust derived inventory or filenames as authority.'}] + [
        {'id': 'LINEAGE-' + r['id'], 'required': True, 'description': 'Compare original item ' + r['id'] + ' against ALL derived items. Identify omissions, value/behavior changes and exclusions; verify actual user approval. Trial-only limits never establish product compliance.'} for r in c['requirements']
    ] + [{'id': 'LINEAGE-DERIVED', 'required': True, 'description': 'Read every derived item; verify source links, additions, source classification, trial purpose, scope authorization and non-inheritance of product PASS.'}]


def require_review(manager, target, allow_mock=False):
    comparison = compare(manager.root)
    if not comparison['structurally_ready']:
        raise ValueError('unapproved requirement differences: supplement planning or request user decision')
    contract = manager.artifact(NAME)
    if not any(a.get('path') == NAME and a.get('sha256') == contract['sha256'] for a in target.get('inputs', [])):
        raise ValueError('development task must freeze the current lineage contract')
    expected = {x['id'] for x in criteria(manager.root)}
    state = manager.read()
    for qa in state['tasks'].values():
        config = qa.get('qa_config', {})
        if qa.get('state') != 'DONE' or config.get('stage') != 'requirements' or config.get('target_task_id') != target['task_id']:
            continue
        if not any(a.get('path') == NAME and a.get('sha256') == contract['sha256'] and manager._valid_artifact(a) for a in qa['inputs']):
            continue
        if not expected <= {x['id'] for x in qa['criteria'] if x.get('required')}:
            continue
        for attempt in reversed(config.get('attempts', [])):
            if attempt.get('outcome') != 'PASS':
                continue
            run = next((x for x in qa['executions'] if x['agent_run_id'] == attempt['agent_run_id']), {})
            # A local synthetic worker is not an independent model review.
            if run.get('execution_mode') != 'independent_process' and not allow_mock:
                continue
            if not allow_mock:
                events_path = manager.root / '.harness/logs/events.jsonl'
                events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
                process = [e.get('observed', {}) for e in events if e.get('agent_run_id') == run['agent_run_id'] and e.get('event_type') == 'role_process']
                if not any(e.get('process_state') == 'role_process_started' and e.get('independent_model_spawned') is True for e in process) or not any(e.get('process_state') == 'role_process_finished' and e.get('exit_code') == 0 for e in process):
                    continue
            from harness.qa import scoped_manifest
            if scoped_manifest(manager.root, config['manifest_scope']) != config['target_manifest']:
                continue
            report = attempt.get('report', {})
            if not manager._valid_artifact(report):
                continue
            content = json.loads((manager.root / report['snapshot']).read_text())
            if content.get('result') != 'PASS' or not all(content.get('criteria', {}).get(key) == 'PASS' for key in expected):
                continue
            if content.get('requirement_lineage', {}).get('contract') != comparison['contract']:
                continue
            if content.get('claim_scope') != comparison['scope']:
                continue
            return {'qa_task_id': qa['task_id'], 'qa_agent_run_id': run['agent_run_id'], 'comparison': comparison, 'synthetic': run.get('execution_mode') != 'independent_process'}
    raise ValueError('independent pre-development requirements QA missing or stale')


def development_gate(manager, task_id):
    target = manager.read()['tasks'][task_id]
    try:
        proof = require_review(manager, target)
    except ValueError as exc:
        reason = str(exc)
        def blocked(state):
            task = state['tasks'][task_id]
            task['state'] = 'BLOCKED'
            task['blocked_reason'] = reason
            manager._event(state, 'requirement_lineage_blocked', task, observed={'reason': reason, 'owner_role': 'planning', 'next_action': 'supplement source mapping or obtain actual user decision; independent requirements QA before implementation', 'product_requirements_pass': 'NOT_ESTABLISHED'})
        manager._mutate('requirement_lineage_gate', blocked, task_id=task_id)
        raise
    def accepted(state):
        task = state['tasks'][task_id]
        manager._event(state, 'requirement_lineage_checked', task, observed=proof)
    manager._mutate('requirement_lineage_gate', accepted, task_id=task_id)
    return proof


def configure_qa(root, run_id, task_id, target_task_id):
    from harness.qa import QA
    c = load(root)
    original = list(dict.fromkeys(s['path'] for s in c['sources'] if s['kind'] != 'AGENT_DERIVED'))
    context = list(dict.fromkeys([NAME] + [s['path'] for s in c['sources']]))
    return QA(root, run_id).configure(task_id, 'requirements', target_task_id, original, criteria(root), context_files=context)


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['compare', 'configure-qa'])
    p.add_argument('--root', required=True)
    p.add_argument('--run-id')
    p.add_argument('--task-id')
    p.add_argument('--target-task-id')
    a = p.parse_args()
    result = compare(a.root) if a.action == 'compare' else configure_qa(a.root, a.run_id, a.task_id, a.target_task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
