"""Typed approval consumers. Local role/QA records are never human authority.

Native input validation establishes local provenance, not OS account isolation.
Deploy an independent native input service to resist same-account source edits.
"""
import json
from pathlib import Path


def human_approval(root, state, question_id, task_id, purpose, subject, artifacts):
    from harness.decisions import resolved_answer
    question = state.get('required_questions', {}).get(question_id, {})
    receipt = resolved_answer(state, question, root=Path(root))
    if not receipt or receipt.get('purpose') != purpose or receipt.get('option_id') != 'approve':
        return None
    if task_id not in receipt.get('task_ids', []) or receipt.get('subject') != subject:
        return None
    if receipt.get('artifacts') != artifacts:
        return None
    return {**receipt, 'approval_type': 'HUMAN_APPROVAL',
            'identity_assurance': 'LOCAL_NATIVE_INPUT_ONLY'}


def ledger(root):
    root = Path(root).resolve()
    path = root / '.harness/tasks/tasks.yaml'
    if not path.resolve().is_relative_to(root):
        raise ValueError('approval ledger escapes project')
    return json.loads(path.read_text())
