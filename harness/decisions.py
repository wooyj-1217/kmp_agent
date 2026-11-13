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


def _files(root, refs):
    """Bind current source bytes, not only the ledger's cached input hashes."""
    result = {}
    for ref in refs:
        name = ref['path'] if isinstance(ref, dict) else ref
        if not isinstance(name, str) or not name:
            raise ValueError('explicit approval artifact path required')
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('approval artifact must be a file inside the project')
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _task_basis(state, root, ids, include_code=False):
    result = {tid: {'feature_id': state['tasks'][tid]['feature_id'],
                  'role': state['tasks'][tid]['role'],
                  'scope': state['tasks'][tid]['scope'],
                  'inputs': copy.deepcopy(state['tasks'][tid].get('inputs', [])),
                  'input_bytes': _files(root, state['tasks'][tid].get('inputs', []))}
            for tid in sorted(ids)}
    if include_code:
        from types import SimpleNamespace
        from harness.development_tracking import capture
        for tid in result:
            task = state['tasks'][tid]
            tracking = task.get('development_tracking')
            if tracking:
                observed = capture(SimpleNamespace(root=root), task)
                result[tid]['code_basis'] = {'state_sha256': observed['state_sha256'],
                    'scope': observed['scope'], 'code_paths': copy.deepcopy(tracking.get('code_paths')),
                    'scope_policy': tracking.get('scope_policy')}
            else:
                result[tid]['code_basis'] = None
    return result


def _approval_suffix(purpose, subject, artifacts, task_ids, supersedes=None, tasks=None):
    return '\n\nApproval scope: ' + json.dumps({'purpose': purpose,
        'subject_sha256': digest(subject), 'artifacts': artifacts,
        'task_ids': sorted(task_ids), 'supersedes': supersedes,
        'task_basis_sha256': digest(tasks)}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _replacement_binding(state, q, previous_id):
    """Only explicitly bound, same-scope new questions may replace old ones."""
    previous = state['required_questions'][previous_id]
    old = previous.get('decision_contract')
    new = q['decision_contract']
    if not isinstance(old, dict) or old.get('version') != 1:
        raise ValueError('legacy questions need explicit migration before supersession')
    root = Path(old['root']).resolve(strict=True)
    checkpoint = previous['checkpoint']
    snapshot = (root / checkpoint['snapshot']).resolve(strict=True)
    if not snapshot.is_relative_to(root) or hashlib.sha256(snapshot.read_bytes()).hexdigest() != checkpoint['snapshot_sha256']:
        raise ValueError('superseded question checkpoint changed')
    if json.loads(snapshot.read_text()).get('decision_contract') != old:
        raise ValueError('superseded question contract changed')
    if sorted(previous['affected_task_ids']) != old['affected_task_ids'] or any(previous.get(k) != old[k] for k in ('question', 'options', 'answer_mode', 'question_item_id')):
        raise ValueError('superseded question identity/scope changed')
    if previous_id == q['id'] or previous['run_id'] != q['run_id']:
        raise ValueError('supersession requires a different question in the same run')
    if any(old.get(k) != new.get(k) for k in ('root', 'purpose', 'affected_task_ids')):
        raise ValueError('supersession must preserve root, purpose and affected tasks')
    seen = {q['id']}
    cursor = previous
    while cursor is not None:
        if cursor['id'] in seen:
            raise ValueError('cyclic question supersession forbidden')
        seen.add(cursor['id'])
        link = (cursor.get('decision_contract') or {}).get('supersedes')
        cursor = state['required_questions'][link['question_id']] if link else None
    return {'question_id': previous_id, 'decision_contract_sha256': digest(old)}


def _validate_approval_options(options):
    if not any(option['id'] == 'approve' for option in options):
        raise ValueError("typed approval requires canonical option id 'approve' before displaying the question; option IDs are never inferred from labels")


def open_question(manager, question_id, question, affected_task_ids, options=None,
                  answer_mode='EXPLICIT_CHOICE', question_item_id=None,
                  approval_purpose=None, approval_artifacts=None, approval_subject=None,
                  supersedes_question_id=None):
    if not isinstance(question_id, str) or not question_id.strip() or not isinstance(question, str) or not question.strip():
        raise ValueError('question ID and text required')
    if answer_mode not in {'EXPLICIT_CHOICE', 'FREEFORM'}:
        raise ValueError('unsupported answer mode')
    options = copy.deepcopy(options or [])
    if answer_mode == 'EXPLICIT_CHOICE' and (not options or any(not isinstance(o, dict) or not isinstance(o.get('id'), str) or not o['id'].strip() or not isinstance(o.get('label'), str) or not o['label'].strip() for o in options)):
        raise ValueError('explicit choice requires human-readable option IDs and labels')
    if len({o['id'] for o in options}) != len(options) or len({o['label'] for o in options}) != len(options):
        raise ValueError('unique option IDs and labels required')
    if approval_purpose is not None and (not isinstance(approval_purpose, str) or not approval_purpose.strip() or answer_mode != 'EXPLICIT_CHOICE' or not isinstance(approval_subject, dict)):
        raise ValueError('typed approval requires purpose, subject object and explicit choices')
    if approval_purpose is None and (approval_artifacts is not None or approval_subject is not None):
        raise ValueError('approval artifacts/subject require explicit purpose')
    if approval_artifacts is not None and not isinstance(approval_artifacts, list):
        raise ValueError('approval artifacts must be an explicit list')
    # Reject non-JSON/NaN payloads before opening any question.
    if approval_subject is not None:
        json.dumps(approval_subject, allow_nan=False)
    if approval_purpose is not None:
        _validate_approval_options(options)
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
        root = manager.root.resolve()
        artifacts = _files(root, approval_artifacts or [])
        prompt = question
        q = {'id': question_id, 'run_id': manager.run_id, 'question': prompt,
             'status': 'OPEN', 'answer_mode': answer_mode, 'options': options,
             'question_item_id': question_item_id,
             'affected_task_ids': list(affected_task_ids), 'propagated_task_ids': sorted(affected),
             'opened_source_boundary': {'records': len(records), 'bytes': len(raw),
                                        'sha256': hashlib.sha256(raw).hexdigest()},
             'answer': None, 'human_review_required': answer_mode == 'FREEFORM'}
        q['decision_contract'] = {'version': 1, 'root': str(root),
            'question_id': question_id, 'run_id': manager.run_id,
            'question': prompt, 'options': copy.deepcopy(options),
            'answer_mode': answer_mode, 'question_item_id': question_item_id,
            'affected_task_ids': sorted(affected_task_ids),
            'tasks': _task_basis(state, root, affected_task_ids, include_code=bool(approval_purpose)),
            'purpose': approval_purpose, 'subject': copy.deepcopy(approval_subject),
            'artifacts': artifacts}
        if supersedes_question_id is not None:
            if answer_mode != 'EXPLICIT_CHOICE' or not any(o['id'] == 'approve' for o in options):
                raise ValueError('supersession requires explicit approve option')
            q['decision_contract']['supersedes'] = _replacement_binding(state, q, supersedes_question_id)
        if approval_purpose or supersedes_question_id is not None:
            prompt += _approval_suffix(approval_purpose, approval_subject, artifacts,
                affected_task_ids, q['decision_contract'].get('supersedes'), q['decision_contract']['tasks'])
            q['question'] = q['decision_contract']['question'] = prompt
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


def _display_echo_matches(body, echo):
    """Known UI display transforms only. The full native call is authority."""
    if not isinstance(echo, str):
        return False
    normalized = body.replace('\r\n', '\n').replace('\r', '\n').replace('\n', ' ')
    variants = {body, normalized}
    variants.update(value.encode('utf-8')[:512].decode('utf-8', errors='ignore')
                    for value in (body, normalized) if len(value.encode('utf-8')) > 512)
    return echo in variants


def _unique_native_reply(records, identity, reply_ordinal):
    """Count user response_items, not their adjacent mirror event records.

    Scan through the current native tail also at consumption. A caller cannot
    select an earlier approval locator while hiding a second reply/rejection.
    """
    prefix, suffix = '<send_user_message_question_reply>\n', '\n</send_user_message_question_reply>'
    occurrences = []
    for ordinal, record in enumerate(records, 1):
        if record.get('type') != 'response_item':
            continue
        text = input_text(record)
        if not isinstance(text, str) or not text.startswith(prefix) or not text.endswith(suffix):
            continue
        try:
            replies = json.loads(text[len(prefix):-len(suffix)])
        except ValueError:
            continue
        if not isinstance(replies, list):
            continue
        for reply in replies:
            try:
                key = json.loads(reply['questionItemId'])
            except (ValueError, KeyError, TypeError):
                continue
            if key == list(identity):
                occurrences.append(ordinal)
    if len(occurrences) != 1 or occurrences[0] not in {reply_ordinal, reply_ordinal + 1}:
        raise ValueError('one unique native user response for this question item required; duplicate/conflicting replies cannot be selected individually')


def structured_choice(text, records, boundary, reply_ordinal, question):
    """Resolve a real UI question reply against its native assistant prompt call."""
    prefix, suffix = '<send_user_message_question_reply>\n', '\n</send_user_message_question_reply>'
    if not (text.startswith(prefix) and text.endswith(suffix)):
        return None
    replies = json.loads(text[len(prefix):-len(suffix)])
    if not isinstance(replies, list) or not replies or any(not isinstance(r, dict) for r in replies):
        raise ValueError('structured question replies required')
    candidates, seen = [], set()
    for reply in replies:
        item = reply.get('questionItemId')
        if not isinstance(item, str):
            raise ValueError('native question item locator required')
        key = json.loads(item)
        if (not isinstance(key, list) or len(key) != 3
                or key[0] not in {'request_user_input_async', 'request_user_input'}
                or not isinstance(key[1], str) or not key[1]
                or type(key[2]) is not int or key[2] < 0):
            raise ValueError('native question item locator required')
        identity = tuple(key)
        if identity in seen:
            raise ValueError('duplicate native question reply item')
        seen.add(identity)
        calls = [(i + 1, r.get('payload', {})) for i, r in enumerate(records)
                 if i + 1 < reply_ordinal and r.get('type') == 'response_item'
                 and r.get('payload', {}).get('type') == 'function_call'
                 and r.get('payload', {}).get('call_id') == key[1]]
        if len(calls) != 1:
            raise ValueError('question must match one native prompt call after opening')
        ordinal, call = calls[0]
        if call.get('name') not in {key[0], 'functions.' + key[0]} or call.get('namespace') not in {None, 'functions'}:
            raise ValueError('human input prompt call required')
        args = json.loads(call['arguments']) if isinstance(call.get('arguments'), str) else call.get('arguments', {})
        questions = args.get('questions', [])
        if not isinstance(questions, list) or key[2] >= len(questions):
            raise ValueError('native prompt question index invalid')
        prompt = questions[key[2]]
        body = prompt.get('question', prompt.get('title', prompt.get('prompt')))
        # Select by authenticated full call content and locator, never by an
        # echoed prefix. The current contract separately checks scope/files.
        if body != question['question']:
            continue
        if question.get('question_item_id') and question['question_item_id'] != item:
            continue
        if ordinal <= boundary['records']:
            raise ValueError('question must match one native prompt call after opening')
        labels = [o if isinstance(o, str) else o.get('label') for o in prompt.get('options', [])]
        if labels != [o['label'] for o in question['options']] or reply.get('answer') not in labels:
            raise ValueError('native prompt option labels mismatch')
        if not _display_echo_matches(body, reply.get('question')):
            raise ValueError('native prompt display echo is not an exact supported UI transform')
        _unique_native_reply(records, identity, reply_ordinal)
        candidates.append({'text': reply['answer'], 'question_item_id': item,
                           'prompt_record_ordinal': ordinal, 'prompt_payload_sha256': digest(call)})
    if len(candidates) != 1:
        raise ValueError('one unambiguous structured reply for this full native question required')
    if (question.get('decision_contract') or {}).get('purpose') or (question.get('decision_contract') or {}).get('supersedes'):
        from harness.decision_text import ensure_unique_reply
        ensure_unique_reply(records, boundary, question, reply_ordinal)
    return candidates[0]


def _contract_current(state, q, root=None):
    contract = q.get('decision_contract')
    # The opening checkpoint prevents silently downgrading a new bound question
    # to a historical untyped record by deleting its contract fields.
    if root is None:
        root = (contract or {}).get('root')
    if root is None and q.get('affected_task_ids'):
        root = state['tasks'][q['affected_task_ids'][0]].get('target_repository')
    if root is not None:
        root = Path(root).resolve(strict=True)
        ref = q.get('checkpoint')
        if ref:
            snapshot = (root / ref['snapshot']).resolve(strict=True)
            if not snapshot.is_relative_to(root) or hashlib.sha256(snapshot.read_bytes()).hexdigest() != ref['snapshot_sha256']:
                return False
            opened = json.loads(snapshot.read_text())
            if opened.get('decision_contract') != contract:
                return False
    if contract is None:
        return not (q.get('answer') or {}).get('validation')
    if not isinstance(contract, dict) or contract.get('version') != 1:
        return False
    root = Path(root or contract['root']).resolve(strict=True)
    if str(root) != contract['root']:
        return False
    if contract.get('question_id') != q['id'] or contract.get('run_id') != q['run_id']:
        return False
    for key in ('question', 'options', 'answer_mode', 'question_item_id'):
        if q.get(key) != contract[key]:
            return False
    ids = sorted(q['affected_task_ids'])
    if ids != contract['affected_task_ids'] or _task_basis(state, root, ids, include_code=bool(contract.get('purpose'))) != contract['tasks']:
        return False
    if _files(root, list(contract['artifacts'])) != contract['artifacts']:
        return False
    if contract.get('purpose') or contract.get('supersedes'):
        if contract.get('purpose') and not isinstance(contract.get('subject'), dict):
            return False
        if contract.get('supersedes') != (_replacement_binding(state, q, contract['supersedes']['question_id']) if contract.get('supersedes') else None):
            return False
        suffix = _approval_suffix(contract['purpose'], contract['subject'], contract['artifacts'], ids, contract.get('supersedes'), contract['tasks'])
        if not q['question'].endswith(suffix):
            return False
    return True


def _native_text_choice(state, q, records, reply_ordinal):
    from harness.decision_text import choice
    result = choice(records, q['opened_source_boundary'], reply_ordinal, q)
    if result:
        root_session = state['execution_policy_bindings'][q['run_id']]['root_session_id']
        for other in state.get('required_questions', {}).values():
            other_session = state.get('execution_policy_bindings', {}).get(other.get('run_id'), {}).get('root_session_id')
            if (other.get('id') != q['id'] and other_session == root_session
                    and other.get('status') in {'OPEN', 'ANSWERED'}
                    and other.get('answer_mode') == 'EXPLICIT_CHOICE'
                    and other.get('decision_contract')
                    and choice(records, other['opened_source_boundary'], reply_ordinal, other, check_unique=False)):
                raise ValueError('native text choice matches multiple questions; present an unambiguous full question')
    return result


def _answer_source(q, policy, source, state):
    records, raw = native_records(policy['root_session_path'], policy['root_session_id'])
    if source['session_id'] != policy['root_session_id']:
        raise ValueError('answer root session mismatch')
    boundary = q['opened_source_boundary']
    if hashlib.sha256(raw[:boundary['bytes']]).hexdigest() != boundary['sha256']:
        raise ValueError('native root prefix changed since question')
    indexes = source['record_ordinal'], source['user_input_record_ordinal']
    if any(type(i) is not int or i <= boundary['records'] or i > len(records) for i in indexes):
        raise ValueError('answer must be received after question')
    event, user = (records[i - 1] for i in indexes)
    if digest(event.get('payload')) != source['payload_sha256'] or digest(user.get('payload')) != source['user_input_payload_sha256']:
        raise ValueError('native answer locator/hash mismatch')
    if event.get('type') != 'event_msg' or user.get('type') != 'response_item':
        raise ValueError('native paired user input required')
    if event.get('payload', {}).get('type') == 'item_completed' and event['payload'].get('thread_id') != policy['root_session_id']:
        raise ValueError('native UserMessage thread mismatch')
    text = input_text(event)
    if not isinstance(text, str) or text != input_text(user) or abs(indexes[0] - indexes[1]) != 1:
        raise ValueError('adjacent matching native human input required')
    if any(marker in text.lower() for marker in ('<subagent', '<environment', '<notification', 'message type: new_task', 'message type: message')):
        raise ValueError('injected messages are not human answers')
    structured = structured_choice(text, records, boundary, min(indexes), q)
    typed = (q.get('decision_contract') or {}).get('purpose') or (q.get('decision_contract') or {}).get('supersedes')
    text_prompt = _native_text_choice(state, q, records, min(indexes)) if typed and not structured else None
    return text, structured, text_prompt, raw


def validate_answer(state, question, root=None):
    """Return current native provenance receipt, or None (fail closed).

    This detects stale/forged ledger claims, not an attacker rewriting both the
    OS user's native session and ledger. Typed approval always requires a real
    authenticated full-question binding; an ordinary answer cannot acquire a purpose.
    """
    try:
        q = state['required_questions'][question] if isinstance(question, str) else question
        if q.get('status') != 'ANSWERED' or q.get('answer_mode') != 'EXPLICIT_CHOICE' or not _contract_current(state, q, root):
            return None
        answer = q['answer']
        policy = state['execution_policy_bindings'][q['run_id']]
        text, structured, text_prompt, raw = _answer_source(q, policy, answer['source'], state)
        if (text != answer['text'] or structured != answer.get('structured_prompt')
                or text_prompt != answer.get('text_prompt')):
            return None
        choice = structured or text_prompt
        selected = choice['text'] if choice else text
        matches = [o for o in q['options'] if selected in (o['id'], o['label'])]
        if len(matches) != 1 or answer.get('option') != matches[0]:
            return None
        contract = q.get('decision_contract') or {}
        purpose = contract.get('purpose')
        receipt = answer.get('validation')
        if contract:
            if not isinstance(receipt, dict) or receipt.get('contract_sha256') != digest(contract):
                return None
            boundary = receipt['native_boundary']
            if type(boundary['bytes']) is not int or len(raw) < boundary['bytes'] or hashlib.sha256(raw[:boundary['bytes']]).hexdigest() != boundary['sha256']:
                return None
        if (purpose or contract.get('supersedes')) and not choice:
            return None
        # Native record reuse is permitted only for distinct structured items.
        for other in state.get('required_questions', {}).values():
            if other.get('id') == q.get('id'):
                continue
            previous = other.get('answer') or {}
            source = previous.get('source') or {}
            if (source.get('session_id'), source.get('record_ordinal')) == (answer['source']['session_id'], answer['source']['record_ordinal']):
                old_item = (previous.get('structured_prompt') or previous.get('text_prompt') or {}).get('question_item_id')
                if not choice or not old_item or old_item == choice['question_item_id']:
                    return None
        return {'authority': 'NATIVE_USER_INPUT', 'question_id': q['id'],
                'purpose': purpose, 'subject': copy.deepcopy(contract.get('subject')),
                'artifacts': copy.deepcopy(contract.get('artifacts', {})),
                'task_ids': sorted(q['affected_task_ids']), 'option_id': matches[0]['id'],
                'source': copy.deepcopy(answer['source']),
                'issued_at': answer.get('issued_at'),
                'supersedes': copy.deepcopy(contract.get('supersedes')),
                'decision_contract_sha256': digest(contract) if contract else None}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError):
        return None


def resolved_answer(state, question, root=None):
    """Resolve only explicit, unambiguous approved replacement chains.

    The returned source remains the new native answer. Old records are neither
    mutated nor treated as independently valid after they become stale.
    """
    try:
        q = state['required_questions'][question] if isinstance(question, str) else question
        def resolve(old, seen):
            if old['id'] in seen:
                return None
            seen = seen | {old['id']}
            candidates = []
            for newer in state.get('required_questions', {}).values():
                link = (newer.get('decision_contract') or {}).get('supersedes')
                if not link or link.get('question_id') != old['id']:
                    continue
                if _replacement_binding(state, newer, old['id']) != link:
                    continue
                receipt = resolve(newer, seen)
                if receipt and receipt['option_id'] == 'approve':
                    receipt = copy.deepcopy(receipt)
                    receipt['supersession_trace'] = [copy.deepcopy(link)] + receipt.get('supersession_trace', [])
                    candidates.append(receipt)
            if len(candidates) > 1:
                return None
            if candidates:
                return candidates[0]
            return validate_answer(state, old, root=root)
        return resolve(q, set())
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError):
        return None


def is_superseded(state, question):
    qid = question if isinstance(question, str) else question.get('id')
    if not any(((q.get('decision_contract') or {}).get('supersedes') or {}).get('question_id') == qid
               for q in state.get('required_questions', {}).values()):
        return False
    receipt = resolved_answer(state, question)
    return bool(receipt and receipt.get('supersession_trace'))


def _answer_question(manager, state, question_id, record_ordinal, payload_sha256,
                     user_input_record_ordinal, user_input_payload_sha256):
    q = state['required_questions'][question_id]
    policy = state['execution_policy_bindings'][q['run_id']]
    if q['run_id'] != manager.run_id or q['status'] != 'OPEN':
        raise ValueError('an OPEN question in this run is required')
    if not _contract_current(state, q, manager.root):
        raise ValueError('question contract/input changed; new question required')
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
    typed = (q.get('decision_contract') or {}).get('purpose') or (q.get('decision_contract') or {}).get('supersedes')
    text_prompt = _native_text_choice(state, q, records, min(indexes)) if typed and not structured else None
    choice = structured or text_prompt
    if typed and not choice:
        raise ValueError('typed human approval requires an authenticated full question and exact native choice; use question-status text_fallback_prompt when UI is unavailable')
    for other in state['required_questions'].values():
        previous = other.get('answer') or {}
        previous_source = previous.get('source', {})
        if (previous_source.get('session_id'), previous_source.get('record_ordinal')) != (locator['session_id'], record_ordinal):
            continue
        old_item = (previous.get('structured_prompt') or previous.get('text_prompt') or {}).get('question_item_id')
        if not choice or not old_item or old_item == choice['question_item_id']:
            raise ValueError('native answer already used')
    selected_text = choice['text'] if choice else text
    matching = []
    for qid, other in state['required_questions'].items():
        if other['status'] != 'OPEN' or other['run_id'] != manager.run_id or other['answer_mode'] != 'EXPLICIT_CHOICE':
            continue
        if choice and qid != question_id:
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
    from harness.logging import now
    q.update(status='ANSWERED', answer={'source': locator, 'text': text, 'option': matching[0][1],
                                      'structured_prompt': structured, 'issued_at': now()})
    if text_prompt:
        q['answer']['text_prompt'] = text_prompt
    if q.get('decision_contract'):
        q['answer']['validation'] = {'contract_sha256': digest(q['decision_contract']),
            'native_boundary': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
    manager._event(state, 'required_question_answered', state['tasks'][q['affected_task_ids'][0]], observed=q)
    return copy.deepcopy(q)


def answer_question(manager, question_id, record_ordinal, payload_sha256,
                    user_input_record_ordinal, user_input_payload_sha256):
    """Ordinals are one-based native JSONL records, not imported Logger events."""
    return manager._mutate('answer_question', lambda state: _answer_question(
        manager, state, question_id, record_ordinal, payload_sha256,
        user_input_record_ordinal, user_input_payload_sha256))
