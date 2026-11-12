"""Explicit replay of authentic native answers, never an approval-ID migration."""
import copy

from harness.decisions import _contract_current, digest, validate_answer


def recover_question(manager, question_id, reason, expected_contract_sha256,
                     question_item_id, record_ordinal, payload_sha256,
                     user_input_record_ordinal, user_input_payload_sha256):
    def attempt(state):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('approval recovery requires an explicit reason')
        if not isinstance(question_item_id, str) or not question_item_id:
            raise ValueError('approval recovery requires the exact native question item ID')
        if not isinstance(expected_contract_sha256, str) or not expected_contract_sha256:
            raise ValueError('approval recovery requires the original decision contract hash')
        if not isinstance(question_id, str) or question_id not in state.get('required_questions', {}):
            raise ValueError('recovery requires an existing question; no task attribution inferred')
        q = state['required_questions'][question_id]
        contract = q.get('decision_contract')
        if (q.get('run_id') != manager.run_id or q.get('answer_mode') != 'EXPLICIT_CHOICE'
                or not isinstance(contract, dict) or contract.get('version') != 1):
            raise ValueError('recovery requires a bound explicit-choice question in this run')
        if expected_contract_sha256 != digest(contract) or not _contract_current(state, q, manager.root):
            raise ValueError('recovery decision contract/input changed; no answer restored')
        policy = state['execution_policy_bindings'][q['run_id']]
        expected_source = dict(session_id=policy['root_session_id'],
            record_ordinal=record_ordinal, payload_sha256=payload_sha256,
            user_input_record_ordinal=user_input_record_ordinal,
            user_input_payload_sha256=user_input_payload_sha256)
        before = q.get('status')
        previous = copy.deepcopy(q.get('answer'))
        if before == 'OPEN':
            if previous is not None:
                raise ValueError('recovery cannot overwrite an existing answer claim')
            from harness.decisions import _answer_question
            _answer_question(manager, state, question_id, record_ordinal, payload_sha256,
                             user_input_record_ordinal, user_input_payload_sha256)
        elif before != 'ANSWERED':
            raise ValueError('recovery requires an OPEN or valid ANSWERED question')
        answer = q.get('answer') or {}
        structured = answer.get('structured_prompt') or {}
        if answer.get('source') != expected_source or structured.get('question_item_id') != question_item_id:
            raise ValueError('recovery native answer/item differs; existing claims are not replaced')
        receipt = validate_answer(state, q, root=manager.root)
        if not receipt:
            raise ValueError('recovery native answer or approval scope is not currently valid')
        identity = dict(question_id=question_id, contract_sha256=expected_contract_sha256,
                        source=expected_source, question_item_id=question_item_id,
                        original_option_id=receipt['option_id'])
        recovery_id = digest(identity)
        history = q.get('recovery_history', [])
        if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
            raise ValueError('invalid recovery history; prior records must be preserved')
        if any(entry.get('recovery_id') == recovery_id for entry in history):
            return copy.deepcopy(q)  # Revalidate above even on an idempotent replay.
        from harness.logging import now
        record = dict(identity, recovery_id=recovery_id, reason=reason, recovered_at=now(),
            status_before=before, status_after=q['status'],
            result='RESTORED' if before == 'OPEN' else 'REVERIFIED',
            original_answer_sha256=digest(previous) if previous is not None else None,
            structured_prompt=copy.deepcopy(structured),
            validation=copy.deepcopy(answer['validation']),
            approval_consumable=bool(receipt.get('purpose') and receipt['option_id'] == 'approve'))
        history.append(record)
        q['recovery_history'] = history
        manager._event(state, 'required_question_answer_recovered',
                       state['tasks'][q['affected_task_ids'][0]], observed=record)
        return copy.deepcopy(q)

    def op(state):
        # The answer helper only reads source files and appends to this state's
        # outbox. Stage both claims and events so a rejected replay cannot leave
        # a success claim while its separate rejection audit is made durable.
        staged = copy.deepcopy(state)
        try:
            result = attempt(staged)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError) as error:
            q = state.get('required_questions', {}).get(question_id) if isinstance(question_id, str) else None
            task = next((state['tasks'][tid] for tid in (q or {}).get('affected_task_ids', [])
                         if tid in state.get('tasks', {})), None)
            if task is not None:
                from harness.logging import now
                policy = state.get('execution_policy_bindings', {}).get(q.get('run_id'), {})
                source = dict(session_id=policy.get('root_session_id'),
                    record_ordinal=record_ordinal, payload_sha256=payload_sha256,
                    user_input_record_ordinal=user_input_record_ordinal,
                    user_input_payload_sha256=user_input_payload_sha256)
                manager._event(state, 'required_question_recovery_rejected', task,
                    observed=dict(result='REJECTED', question_id=question_id, reason=reason,
                        cause=str(error), error_type=type(error).__name__, rejected_at=now(),
                        expected_contract_sha256=expected_contract_sha256,
                        question_item_id=question_item_id, source=source))
            return {'ok': False, 'cause': str(error)}
        state.clear()
        state.update(staged)
        return {'ok': True, 'question': result}

    result = manager._mutate('recover_question', op)
    if not result['ok']:
        raise ValueError(result['cause'])
    return result['question']
