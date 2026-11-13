"""Exact native text choices bound to a frozen, actually presented question."""
import json

from harness.decisions import digest, input_text


def render_prompt(question):
    """A full text presentation usable when the selection UI is unavailable."""
    return (question['question'] + '\n\n텍스트 선택지:\n'
            + '\n'.join('- ' + option['label'] for option in question['options'])
            + '\n\n선택지 문구 하나만 그대로 답하세요. 일반적인 진행 요청은 승인으로 처리하지 않습니다.'
            + '\nQuestion contract: ' + digest(question['decision_contract']))


def _selected(text, question):
    if not isinstance(text, str):
        return None
    value = text.strip()
    if '\n' in value or '\r' in value:
        return None
    variants = {value}
    if value.startswith(('- ', '* ')):
        variants.add(value[2:])
    matches = [o['label'] for o in question['options'] if o['label'] in variants]
    return matches[0] if len(matches) == 1 else None


def _human_call(record):
    payload = record.get('payload', {})
    return (record.get('type') == 'response_item' and payload.get('type') == 'function_call'
            and payload.get('name') in {'request_user_input', 'request_user_input_async',
                                       'functions.request_user_input', 'functions.request_user_input_async'})


def _questions(payload):
    if payload.get('namespace') not in (None, 'functions'):
        return []
    args = payload.get('arguments', {})
    try:
        args = json.loads(args) if isinstance(args, str) else args
    except ValueError:
        return []
    questions = args.get('questions', []) if isinstance(args, dict) else []
    return questions if isinstance(questions, list) else []


def _labels(prompt):
    options = prompt.get('options', []) if isinstance(prompt, dict) else []
    if not isinstance(options, list):
        return []
    return [o if isinstance(o, str) else o.get('label') if isinstance(o, dict) else None
            for o in options]


def _matches(prompt, question):
    return (isinstance(prompt, dict)
            and prompt.get('question', prompt.get('title', prompt.get('prompt'))) == question['question']
            and _labels(prompt) == [o['label'] for o in question['options']])


def _assistant_text(record):
    payload = record.get('payload', {})
    if (record.get('type') != 'response_item' or payload.get('type') != 'message'
            or payload.get('role') != 'assistant'):
        return None
    content = payload.get('content', [])
    if content and all(isinstance(c, dict) and c.get('type') == 'output_text' for c in content):
        return '\n'.join(c.get('text', '') for c in content)
    return None


def _choice_at(records, boundary, ordinal, question, direct=True):
    selected = _selected(input_text(records[ordinal - 1]), question)
    if selected is None:
        return None
    # A bare choice is a direct response to the latest actual presentation,
    # never to an assistant's retrospective attribution of a prior message.
    presentation = None
    rendered = render_prompt(question)
    for index in range(boundary['records'], ordinal - 1):
        record = records[index]
        payload = record.get('payload', {})
        if _human_call(record):
            presentation = (index + 1, payload, False)
        elif ((assistant_text := _assistant_text(record)) is not None
              and '\n\n텍스트 선택지:\n' in assistant_text and 'Question contract:' in assistant_text):
            presentation = (index + 1, payload, True)
        elif (direct and record.get('type') == 'response_item' and payload.get('type') == 'message'
              and payload.get('role') == 'user'):
            presentation = None
    if presentation is None:
        return None
    prompt_ordinal, payload, is_text = presentation
    if is_text:
        if _assistant_text(records[prompt_ordinal - 1]) != rendered or question.get('question_item_id'):
            return None  # A pinned UI item cannot silently change identity.
        item = json.dumps(['native_text', digest(question['decision_contract'])], separators=(',', ':'))
    else:
        prompts = _questions(payload)
        candidates = [(i, p) for i, p in enumerate(prompts) if selected in _labels(p)]
        if len(candidates) != 1 or not _matches(candidates[0][1], question):
            return None  # Identical labels in a batch do not identify a scope.
        call_id = payload.get('call_id')
        if (not isinstance(call_id, str) or not call_id
                or sum(r.get('type') == 'response_item'
                       and r.get('payload', {}).get('type') == 'function_call'
                       and r.get('payload', {}).get('call_id') == call_id
                       for r in records[:ordinal - 1]) != 1):
            return None
        identity = [payload['name'].removeprefix('functions.'), call_id, candidates[0][0]]
        pinned = question.get('question_item_id')
        if pinned and json.loads(pinned) != identity:
            return None
        item = pinned or json.dumps(identity, separators=(',', ':'))
    return dict(transport='NATIVE_TEXT', text=selected, question_item_id=item,
                prompt_record_ordinal=prompt_ordinal, prompt_payload_sha256=digest(payload),
                decision_contract_sha256=digest(question['decision_contract']))


def ensure_unique_reply(records, boundary, question, reply_ordinal):
    """Check all text/UI answers through the current native tail at consumption."""
    identities = set()
    for index, record in enumerate(records, 1):
        if index <= boundary['records'] or not _human_call(record):
            continue
        payload = record['payload']
        for item_index, prompt in enumerate(_questions(payload)):
            if _matches(prompt, question):
                identities.add((payload['name'].removeprefix('functions.'), payload.get('call_id'), item_index))
    occurrences = []
    prefix, suffix = '<send_user_message_question_reply>\n', '\n</send_user_message_question_reply>'
    for ordinal, record in enumerate(records, 1):
        if ordinal <= boundary['records'] or record.get('type') != 'response_item':
            continue
        text = input_text(record)
        if not isinstance(text, str):
            continue
        # A subsequent exact rejection is a conflict even without redisplay.
        # Initial binding remains stricter: it must be a direct answer.
        if _choice_at(records, boundary, ordinal, question, direct=False) is not None:
            occurrences.append(ordinal)
        if text.startswith(prefix) and text.endswith(suffix):
            try:
                replies = json.loads(text[len(prefix):-len(suffix)])
            except ValueError:
                continue  # No identifiable question item in unrelated malformed input.
            if not isinstance(replies, list):
                continue
            for reply in replies:
                if not isinstance(reply, dict):
                    continue
                try:
                    key = json.loads(reply.get('questionItemId', 'null'))
                except (ValueError, TypeError):
                    continue
                if (isinstance(key, list) and len(key) == 3 and isinstance(key[0], str)
                        and isinstance(key[1], str) and type(key[2]) is int and tuple(key) in identities):
                    occurrences.append(ordinal)
    if len(occurrences) != 1 or occurrences[0] not in (reply_ordinal, reply_ordinal + 1):
        raise ValueError('one unique native text/UI answer for this frozen question required; conflicting replies cannot be selected')


def choice(records, boundary, reply_ordinal, question, check_unique=True):
    result = _choice_at(records, boundary, reply_ordinal, question)
    if result is not None and check_unique:
        ensure_unique_reply(records, boundary, question, reply_ordinal)
    return result
