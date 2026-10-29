"""Declared work targets are not inferred from collection location or titles."""
import json
from pathlib import Path


def valid_id(value):
    return isinstance(value, str) and value.strip() == value and value not in {'', 'UNKNOWN', 'unknown'}


def registered_targets(root):
    root = Path(root)
    config = root / '.kmp-agent/project.json'
    metadata = json.loads(config.read_text()) if config.exists() else {}
    identity = metadata.get('project_id') if isinstance(metadata, dict) else None
    path = root / '.harness/tasks/tasks.yaml'
    ledger = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(ledger, dict) or not isinstance(ledger.get('tasks', {}), dict):
        raise ValueError('unconfirmed task ledger')
    tasks = ledger.get('tasks', {})
    if any(not isinstance(t, dict) for t in tasks.values()):
        raise ValueError('unconfirmed task target')
    targets = {t.get('project_id') for t in tasks.values() if valid_id(t.get('project_id'))}
    if valid_id(identity):
        targets.add(identity)
    return identity if valid_id(identity) else None, targets


def partition(rows, tasks, selected_project_id=None):
    """Keep every response; only a linked task can establish its work target.

    Imported event project_id describes collection context. In particular it is
    not evidence that an unlinked shared-session response is product work.
    """
    for row in rows:
        task = tasks.get(row['task_id'], {})
        target = task.get('project_id')
        row['target_project_id'] = target if valid_id(target) else 'UNKNOWN'
        row['target_basis'] = 'registered_task_project_id' if valid_id(target) else 'work_target_unconfirmed'
        row['work_type'] = task.get('work_type') if valid_id(target) else None
    buckets = {'selected_target': [], 'other_targets': [], 'unknown_target': []}
    for row in rows:
        key = ('unknown_target' if row['target_project_id'] == 'UNKNOWN' else
               'selected_target' if row['target_project_id'] == selected_project_id else 'other_targets')
        buckets[key].append(row)
    summary = {key: {'tokens': sum(r['tokens'] for r in value), 'responses': len(value)}
               for key, value in buckets.items()}
    selected = buckets['selected_target']
    summary.update({'selected_project_id': selected_project_id,
                    'product_work_tokens': sum(r['tokens'] for r in selected if r['work_type'] == 'PRODUCT'),
                    'repository_known_tokens': sum(r['tokens'] for r in rows),
                    'repository_responses': len(rows),
                    'repository_scope': 'all recorded targets plus work-target-unconfirmed responses; deduplicated within this repository',
                    'selection_scope': 'registered task project_id; collection location is not attribution',
                    'unknown_response_keys': [{'session_id': r['session_id'], 'response_id': r['response_id']}
                                              for r in buckets['unknown_target']]})
    return summary
