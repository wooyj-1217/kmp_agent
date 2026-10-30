"""Required human questions in the native task ledger, backed by native input.

No logger event or assistant interpretation can answer a required question.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import pwd
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def native_store():
    return (Path(pwd.getpwuid(os.getuid()).pw_dir) / '.codex' / 'sessions').resolve()


def native_records(path, session_id):
    path = Path(path).resolve(strict=True)
    # Trust the actual user's native storage, never CODEX_HOME supplied by a worker.
    trusted = native_store()
    if not path.is_relative_to(trusted):
        raise ValueError('root native session must reside in the fixed user native session store')
    if str(uuid.UUID(session_id)) != session_id:
        raise ValueError('canonical root session UUID required')
    raw = path.read_bytes()
    complete = raw[:raw.rfind(b'\n') + 1]
    records = [json.loads(line) for line in complete.splitlines()]
    metas = [r.get('payload', {}) for r in records if r.get('type') == 'session_meta']
    if len(metas) != 1 or metas[0].get('id') != session_id:
        raise ValueError('native root session UUID mismatch')
    source = metas[0].get('source')
    if source not in ('cli', 'vscode', 'exec', 'desktop', 'app'):
        raise ValueError('root human session source required; subagent sessions forbidden')
    return records, complete


def open_question(manager, question_id, question, affected_task_ids, options=None,
                  answer_mode='EXPLICIT_CHOICE', question_item_id=None):
    if not isinstance(question_id, str) or not question_id.strip() or not isinstance(question, str) or not question.strip():
        raise ValueError('question ID and text required')
    if answer_mode not in {'EXPLICIT_CHOICE', 'FREEFORM'}:
        raise ValueError('unsupported answer mode')
    options = copy.deepcopy(options or [])
    if answer_mode == 'EXPLICIT_CHOICE' and (not options or any(not isinstance(o, dict) or not isinstance(o.get('id'), str) or not o['id'].strip() or not isinstance(o.get('label'), str) or not o['label'].strip() for o in options)):
        raise ValueError('explicit choice requires human-readable option IDs and labels')
    if len({o['id'] for o in options}) != len(options) or len({o['label'] for o in options}) != len(options):
        raise ValueError('unique option IDs and labels required')
    def op(state):
        policy = state.get('execution_policy_bindings', {}).get(manager.run_id)
        if not policy:
            raise ValueError('activate execution policy with a fixed native root first')
        if question_id in state.get('required_questions', {}):
            raise ValueError('question ID already exists')
        if not isinstance(affected_task_ids, list) or not affected_task_ids or any(t not in state['tasks'] for t in affected_task_ids):
            raise ValueError('explicit existing affected tasks required')
        records, raw = native_records(policy['root_session_path'], policy['root_session_id'])
        from harness.execution_policy import dependency_closure
        affected = dependency_closure(state, affected_task_ids)
        q = {'id': question_id, 'run_id': manager.run_id, 'question': question,
             'status': 'OPEN', 'answer_mode': answer_mode, 'options': options,
             'question_item_id': question_item_id,
             'affected_task_ids': list(affected_task_ids), 'propagated_task_ids': sorted(affected),
             'opened_source_boundary': {'records': len(records), 'bytes': len(raw),
                                        'sha256': hashlib.sha256(raw).hexdigest()},
             'answer': None, 'human_review_required': answer_mode == 'FREEFORM'}
        state.setdefault('required_questions', {})[question_id] = q
        # A durable checkpoint preserves active attempts and their partial outputs.
        checkpoint = manager.directory / ('question-' + digest(question_id) + '.json')
        checkpoint.write_text(json.dumps(q, ensure_ascii=False, indent=2))
        ref = manager.artifact(str(checkpoint.relative_to(manager.root)))
        q['checkpoint'] = ref
        for tid in affected:
            task = state['tasks'][tid]
            if task['state'] == 'DONE':
                continue  # Historical completed work is not reinterpreted.
            for run in task['executions']:
                if not run.get('ended_at'):
                    if run.get('checkpoint'):
                        run.setdefault('checkpoint_history', []).append(copy.deepcopy(run['checkpoint']))
                    run['checkpoint'] = copy.deepcopy(ref)
                    run['checkpoint_capabilities'] = {'execution_resume': True, 'code_restore': False}
                    run['required_question_wait'] = question_id
                    run.setdefault('required_question_waits', []).append(question_id)
            task.update(state='BLOCKED', blocked_reason='required human answer pending: ' + question_id)
        manager._event(state, 'required_question_opened', state['tasks'][affected_task_ids[0]], observed=q)
        return copy.deepcopy(q)
    return manager._mutate('open_question', op)


def refresh_waits(manager, state):
    """New native dependency links immediately inherit the same question wait."""
    from harness.execution_policy import pending
    for tid, task in state['tasks'].items():
        if task['state'] == 'DONE':
            continue
        for qid in pending(state, tid):
            q = state['required_questions'][qid]
            if tid not in q['propagated_task_ids']:
                q['propagated_task_ids'].append(tid)
                q['propagated_task_ids'].sort()
            task.update(state='BLOCKED', blocked_reason='required human answer pending: ' + qid)
            for run in task['executions']:
                if not run.get('ended_at') and qid not in run.get('required_question_waits', []):
                    if run.get('checkpoint'):
                        run.setdefault('checkpoint_history', []).append(copy.deepcopy(run['checkpoint']))
                    run['checkpoint'] = copy.deepcopy(q['checkpoint'])
                    run['checkpoint_capabilities'] = {'execution_resume': True, 'code_restore': False}
                    run['required_question_wait'] = qid
                    run.setdefault('required_question_waits', []).append(qid)


def input_text(record):
    payload = record.get('payload', {})
    if record.get('type') == 'event_msg' and payload.get('type') == 'user_message':
        return payload.get('message')
    if record.get('type') == 'event_msg' and payload.get('type') == 'item_completed':
        item = payload.get('item', {})
        if item.get('type') == 'UserMessage':
            content = item.get('content', [])
            if content and all(c.get('type') == 'text' for c in content):
                return '\n'.join(c.get('text', '') for c in content)
    if record.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
        content = payload.get('content', [])
        if content and all(c.get('type') == 'input_text' for c in content):
            return '\n'.join(c.get('text', '') for c in content)
    return None


def structured_choice(text, records, boundary, reply_ordinal, question):
    """Resolve a real UI question reply against its native assistant prompt call."""
    prefix, suffix = '<send_user_message_question_reply>\n', '\n</send_user_message_question_reply>'
    if not (text.startswith(prefix) and text.endswith(suffix)):
        return None
    replies = json.loads(text[len(prefix):-len(suffix)])
    if not isinstance(replies, list) or not replies or any(not isinstance(r, dict) for r in replies):
        raise ValueError('structured question replies required')
    candidates = [r for r in replies if r.get('question') == question['question'] and
                  (not question.get('question_item_id') or r.get('questionItemId') == question['question_item_id'])]
    if len(candidates) != 1:
        raise ValueError('one unambiguous structured reply for this question required')
    reply = candidates[0]
    item = reply.get('questionItemId')
    key = json.loads(item)
    if not isinstance(key, list) or len(key) != 3 or key[0] not in {'request_user_input_async', 'request_user_input'} or type(key[2]) is not int or key[2] < 0:
        raise ValueError('native question item locator required')
    if question.get('question_item_id') and question['question_item_id'] != item:
        raise ValueError('reply belongs to another prompt item')
    calls = [(i + 1, r.get('payload', {})) for i, r in enumerate(records)
             if boundary['records'] < i + 1 < reply_ordinal and r.get('type') == 'response_item'
             and r.get('payload', {}).get('type') == 'function_call'
             and r.get('payload', {}).get('call_id') == key[1]]
    if len(calls) != 1:
        raise ValueError('question must match a native prompt call after opening')
    ordinal, call = calls[0]
    if call.get('name') not in {key[0], 'functions.' + key[0]}:
        raise ValueError('human input prompt call required')
    args = json.loads(call['arguments']) if isinstance(call.get('arguments'), str) else call.get('arguments', {})
    questions = args.get('questions', [])
    if key[2] >= len(questions):
        raise ValueError('native prompt question index invalid')
    prompt = questions[key[2]]
    body = prompt.get('question', prompt.get('title', prompt.get('prompt')))
    if body != question['question'] or reply.get('question') != body:
        raise ValueError('native prompt question text mismatch')
    labels = [o if isinstance(o, str) else o.get('label') for o in prompt.get('options', [])]
    if labels != [o['label'] for o in question['options']] or reply.get('answer') not in labels:
        raise ValueError('native prompt option labels mismatch')
    return {'text': reply['answer'], 'question_item_id': item,
            'prompt_record_ordinal': ordinal, 'prompt_payload_sha256': digest(call)}


def answer_question(manager, question_id, record_ordinal, payload_sha256,
                    user_input_record_ordinal, user_input_payload_sha256):
    """Ordinals are one-based native JSONL records, not imported Logger events."""
    def op(state):
        q = state['required_questions'][question_id]
        policy = state['execution_policy_bindings'][q['run_id']]
        if q['run_id'] != manager.run_id or q['status'] != 'OPEN':
            raise ValueError('an OPEN question in this run is required')
        records, raw = native_records(policy['root_session_path'], policy['root_session_id'])
        boundary = q['opened_source_boundary']
        if hashlib.sha256(raw[:boundary['bytes']]).hexdigest() != boundary['sha256']:
            raise ValueError('native root prefix changed since question')
        indexes = (record_ordinal, user_input_record_ordinal)
        if any(type(i) is not int or i <= boundary['records'] or i > len(records) for i in indexes):
            raise ValueError('answer must be actually received after the question')
        event, user = (records[i - 1] for i in indexes)
        if digest(event.get('payload')) != payload_sha256 or digest(user.get('payload')) != user_input_payload_sha256:
            raise ValueError('native answer locator/hash mismatch')
        if event.get('type') != 'event_msg' or input_text(event) is None or user.get('type') != 'response_item':
            raise ValueError('native human user_message and paired user input required')
        if event.get('payload', {}).get('type') == 'item_completed' and event['payload'].get('thread_id') != policy['root_session_id']:
            raise ValueError('UserMessage companion thread must equal native root session')
        text = input_text(event)
        if not isinstance(text, str) or text != input_text(user) or abs(record_ordinal - user_input_record_ordinal) != 1:
            raise ValueError('adjacent matching native human input required; agent/tool/notifications forbidden')
        if any(marker in text.lower() for marker in ('<subagent', '<environment', '<notification', 'message type: new_task', 'message type: message')):
            raise ValueError('injected agent/environment messages are not human answers')
        locator = {'session_id': policy['root_session_id'], 'record_ordinal': record_ordinal,
                   'payload_sha256': payload_sha256, 'user_input_record_ordinal': user_input_record_ordinal,
                   'user_input_payload_sha256': user_input_payload_sha256}
        try:
            structured = structured_choice(text, records, boundary, min(indexes), q) if q['answer_mode'] == 'EXPLICIT_CHOICE' else None
        except (TypeError, KeyError, IndexError, AttributeError) as error:
            raise ValueError('invalid native structured choice; keep waiting') from error
        for other in state['required_questions'].values():
            previous = other.get('answer') or {}
            previous_source = previous.get('source', {})
            if (previous_source.get('session_id'), previous_source.get('record_ordinal')) != (locator['session_id'], record_ordinal):
                continue
            old_item = (previous.get('structured_prompt') or {}).get('question_item_id')
            if not structured or not old_item or old_item == structured['question_item_id']:
                raise ValueError('native answer already used')
        selected_text = structured['text'] if structured else text
        matching = []
        for qid, other in state['required_questions'].items():
            if other['status'] != 'OPEN' or other['run_id'] != manager.run_id or other['answer_mode'] != 'EXPLICIT_CHOICE':
                continue
            if structured and qid != question_id:
                continue
            for option in other['options']:
                if selected_text in (option['id'], option['label']):
                    matching.append((qid, option))
        if q['answer_mode'] == 'FREEFORM':
            q['received_freeform'] = {'source': locator, 'text': text}
            q['human_review_required'] = True
            return copy.deepcopy(q)
        if len(matching) != 1 or matching[0][0] != question_id:
            raise ValueError('answer does not uniquely select this pending question; keep waiting')
        q.update(status='ANSWERED', answer={'source': locator, 'text': text, 'option': matching[0][1],
                                          'structured_prompt': structured})
        manager._event(state, 'required_question_answered', state['tasks'][q['affected_task_ids'][0]], observed=q)
        return copy.deepcopy(q)
    return manager._mutate('answer_question', op)
