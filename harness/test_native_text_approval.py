"""Native exact-choice text is a transport, never an inferred approval."""
import copy
import json
import unittest
from unittest.mock import patch

from harness import decisions
from harness.test_approval_transport import ApprovalTransportTests as Fixture
from harness.tasks import Tasks
from harness.test_execution_policy import SESSION


class NativeTextApprovalTests(unittest.TestCase):
    setUp = Fixture.setUp
    step = Fixture.step
    write_native = Fixture.write_native
    activate = Fixture.activate
    reply = Fixture.reply
    call = Fixture.call
    entry = Fixture.entry
    structured = Fixture.structured
    consume = Fixture.consume

    def question(self, qid='Q', **extra):
        return self.m.open_question(qid, 'Approve the frozen scope for ' + qid, ['T'],
            [{'id':'approve','label':'Approve this exact scope'}, {'id':'reject','label':'Reject'}],
            approval_purpose='transport_probe', approval_subject={'scope':'synthetic'},
            approval_artifacts=['scope.md'], **extra)

    def test_exact_label_and_single_bullet_from_real_native_pair(self):
        self.activate()
        for i, text in enumerate(('Approve this exact scope', '- Approve this exact scope',
                                  '  * Approve this exact scope  ')):
            q = self.question('Q' + str(i))
            self.call(q, 'call-' + str(i))
            answer = self.m.answer_question(q['id'], **self.reply(text))['answer']
            self.assertEqual('approve', answer['option']['id'])
            self.assertEqual('NATIVE_TEXT', answer['text_prompt']['transport'])
            self.assertIsNone(answer['structured_prompt'])
            self.assertEqual('NATIVE_USER_INPUT', self.consume(q)['authority'])

    def test_same_item_user_message_companion_can_precede_event(self):
        self.activate(); q = self.question(); self.call(q)
        proof = self.reply('- Approve this exact scope')
        self.records[-2:] = list(reversed(self.records[-2:]))
        event = {'type': 'event_msg', 'payload': {'type': 'item_completed',
            'thread_id': '00000000-0000-4000-8000-000000000001',
            'item': {'type': 'UserMessage', 'content': [{'type': 'text', 'text': '- Approve this exact scope'}]}}}
        self.records[-1] = event; self.write_native()
        proof.update(record_ordinal=len(self.records), payload_sha256=decisions.digest(event['payload']),
            user_input_record_ordinal=len(self.records)-1,
            user_input_payload_sha256=decisions.digest(self.records[-2]['payload']))
        self.m.answer_question('Q', **proof)
        self.assertIsNotNone(self.consume(q))

    def test_generic_quoted_or_multiple_choices_never_select(self):
        self.activate()
        for i, text in enumerate(('진행해', 'approve', 'yes', '> Approve this exact scope',
                '"Approve this exact scope"', 'Please Approve this exact scope',
                '- Approve this exact scope\n- Reject', 'Approve this exact scope\nReject')):
            q = self.question('Q' + str(i)); self.call(q, 'call-' + str(i))
            with self.assertRaises(ValueError): self.m.answer_question(q['id'], **self.reply(text))
            self.assertIsNone(self.consume(q))

    def test_missing_altered_wrong_namespace_or_wrong_options_prompt_rejected(self):
        self.activate()
        for i, kind in enumerate(('missing', 'body', 'labels', 'namespace', 'duplicate_call')):
            q = self.question('Q' + str(i))
            if kind != 'missing':
                self.call(q, 'call-' + str(i),
                    body=q['question']+' hidden change' if kind == 'body' else None,
                    labels=['Different', 'Reject'] if kind == 'labels' else None)
                if kind == 'namespace': self.records[-1]['payload']['namespace'] = 'untrusted'
                if kind == 'duplicate_call': self.records.append(copy.deepcopy(self.records[-1]))
            with self.assertRaises(ValueError):
                self.m.answer_question(q['id'], **self.reply('Approve this exact scope'))

    def test_unrelated_later_prompt_and_intervening_user_text_are_not_attributed(self):
        self.activate(); q = self.question(); self.call(q)
        self.reply('Which scope?')
        with self.assertRaises(ValueError):
            self.m.answer_question('Q', **self.reply('Approve this exact scope'))
        self.call(q, 'repeated')
        self.records.append({'type':'response_item','payload':{'type':'function_call',
            'name':'request_user_input_async','call_id':'other',
            'arguments':json.dumps({'questions':[{'title':'Unrelated', 'options':['Approve this exact scope']}]})}})
        with self.assertRaises(ValueError):
            self.m.answer_question('Q', **self.reply('Approve this exact scope'))

    def test_repeated_ui_presentations_do_not_need_another_click(self):
        self.activate(); q = self.question(); self.call(q)
        proof = self.reply('- Approve this exact scope')
        self.reply('Display UI again')
        self.call(q, 'retry'); self.write_native()
        self.m.answer_question('Q', **proof)
        self.assertIsNotNone(self.consume(q))

    def test_batch_shared_label_and_identical_pending_contracts_are_ambiguous(self):
        self.activate(); q = self.question(); self.call(q)
        payload = self.records[-1]['payload']
        args = json.loads(payload['arguments'])
        args['questions'].append({'title':'Other scope','options':['Approve this exact scope']})
        payload['arguments'] = json.dumps(args)
        with self.assertRaises(ValueError):
            self.m.answer_question('Q', **self.reply('Approve this exact scope'))
        other = self.m.open_question('OTHER', 'Approve the frozen scope for Q', ['T'],
            [{'id':'approve','label':'Approve this exact scope'}, {'id':'reject','label':'Reject'}],
            approval_purpose='transport_probe', approval_subject={'scope':'synthetic'}, approval_artifacts=['scope.md'])
        self.call(other, 'both')
        with self.assertRaises(ValueError):
            self.m.answer_question('Q', **self.reply('Approve this exact scope'))

    def test_text_reject_never_grants_authority(self):
        self.activate(); q = self.question(); self.call(q)
        self.assertEqual('reject', self.m.answer_question('Q', **self.reply('Reject'))['answer']['option']['id'])
        self.assertIsNone(self.consume(q))

    def test_text_duplicates_and_later_structured_conflict_invalidate_consumption(self):
        self.activate()
        for i, transport in enumerate(('text', 'structured')):
            q = self.question('Q' + str(i)); self.call(q, 'initial-' + str(i))
            self.m.answer_question(q['id'], **self.reply('Approve this exact scope'))
            self.assertIsNotNone(self.consume(q))
            item = self.call(q, 'conflict-' + str(i))
            if transport == 'text': self.reply('Reject')
            else: self.structured([self.entry(q, item, answer='Reject')])
            self.assertIsNone(self.consume(q))

    def test_structured_approval_cannot_hide_a_later_text_conflict(self):
        self.activate(); q = self.question(); item = self.call(q)
        self.m.answer_question('Q', **self.structured([self.entry(q, item)]))
        self.assertIsNotNone(self.consume(q))
        self.call(q, 'new-call'); self.reply('Reject')
        self.assertIsNone(self.consume(q))

    def test_conflicting_text_without_another_prompt_is_not_cherry_picked(self):
        self.activate(); q = self.question(); self.call(q)
        self.m.answer_question('Q', **self.reply('Approve this exact scope'))
        self.assertIsNotNone(self.consume(q))
        self.reply('Reject')
        self.assertIsNone(self.consume(q))

    def test_scope_and_prompt_proof_are_revalidated_at_consumption(self):
        self.activate(); q = self.question(); self.call(q)
        self.m.answer_question('Q', **self.reply('Approve this exact scope'))
        self.assertIsNotNone(self.consume(q))
        (self.root/'scope.md').write_text('changed scope')
        self.assertIsNone(self.consume(q))
        (self.root/'scope.md').write_text('approved scope')
        self.assertIsNotNone(self.consume(q))
        self.records[1]['payload']['arguments'] = '{}'; self.write_native()
        self.assertIsNone(self.consume(q))

    def test_text_only_official_presentation_and_status_without_ui_tool(self):
        self.activate(); q = self.question()
        presentation = self.m.question_status()['Q']['text_fallback_prompt']
        self.assertIn(q['question'], presentation)
        self.assertIn(decisions.digest(q['decision_contract']), presentation)
        self.records.append({'type':'response_item','payload':{'type':'message','role':'assistant',
            'content':[{'type':'output_text','text':presentation}]}})
        self.m.answer_question('Q', **self.reply('- Approve this exact scope'))
        self.assertIsNotNone(self.consume(q))

    def test_newer_text_presentation_for_another_scope_is_a_barrier(self):
        from harness.decision_text import render_prompt
        self.activate(); q = self.question(); self.call(q)
        other = copy.deepcopy(q)
        other.update(id='OTHER', question='A different unregistered scope')
        other['decision_contract'].update(question_id='OTHER', run_id='OTHER-RUN')
        self.records.append({'type':'response_item','payload':{'type':'message','role':'assistant',
            'content':[{'type':'output_text','text':render_prompt(other)}]}})
        with self.assertRaises(ValueError):
            self.m.answer_question('Q', **self.reply('Approve this exact scope'))

    def test_bullet_prefix_cannot_change_a_different_literal_choice(self):
        self.activate()
        q = self.m.open_question('Q', 'Literal versus bullet choices', ['T'],
            [{'id':'approve','label':'Choice'}, {'id':'reject','label':'- Choice'}],
            approval_purpose='transport_probe', approval_subject={})
        self.call(q)
        with self.assertRaises(ValueError): self.m.answer_question('Q', **self.reply('- Choice'))

    def test_pinned_ui_item_accepts_only_its_actual_full_presentation(self):
        self.activate()
        item = json.dumps(['request_user_input_async', 'pinned-call', 0], separators=(',', ':'))
        q = self.question(question_item_id=item)
        status = self.m.question_status()['Q']
        self.assertNotIn('text_fallback_prompt', status)
        self.assertIn('pinned', status['text_fallback_unavailable_reason'])
        self.call(q, 'pinned-call')
        self.m.answer_question('Q', **self.reply('Approve this exact scope'))
        self.assertIsNotNone(self.consume(q))

    def test_unidentifiable_unrelated_malformed_tail_does_not_revoke_approval(self):
        self.activate(); q = self.question(); item = self.call(q)
        self.m.answer_question('Q', **self.structured([self.entry(q, item)]))
        self.reply('<send_user_message_question_reply>\nnot JSON\n</send_user_message_question_reply>')
        self.records.append({'type':'response_item','payload':{'type':'function_call',
            'name':'request_user_input_async','call_id':'unrelated', 'arguments':'not JSON'}})
        self.write_native()
        self.assertIsNotNone(self.consume(q))

    def test_same_root_cross_run_question_is_still_ambiguous(self):
        self.activate(); q = self.question()
        other_manager = Tasks(self.root, 'another-run')
        other_manager.bind_execution_session(str(self.native), SESSION)
        other = other_manager.open_question('OTHER', 'Approve the frozen scope for Q', ['T'],
            [{'id':'approve','label':'Approve this exact scope'}, {'id':'reject','label':'Reject'}],
            approval_purpose='transport_probe', approval_subject={'scope':'synthetic'},
            approval_artifacts=['scope.md'])
        self.assertEqual(q['question'], other['question'])
        self.call(other, 'other-run-call')
        proof = self.reply('Approve this exact scope')
        with self.assertRaisesRegex(ValueError, 'multiple questions'):
            self.m.answer_question('Q', **proof)

    def test_explicit_supersession_preserves_old_question_and_contract(self):
        self.activate()
        with patch('harness.decisions._validate_approval_options'):
            old = self.m.open_question('OLD', 'Original contract', ['T'],
                [{'id':'APPROVE-T1','label':'Approve old'},{'id':'reject','label':'Reject old'}],
                approval_purpose='transport_probe',approval_subject={'scope':'synthetic'},
                approval_artifacts=['scope.md'])
        q = self.question(supersedes_question_id='OLD'); self.call(q)
        self.m.answer_question('Q', **self.reply('- Approve this exact scope'))
        state = self.m.read()
        self.assertEqual(old, state['required_questions']['OLD'])
        self.assertEqual('approve', decisions.resolved_answer(state, 'OLD', root=self.root)['option_id'])
        self.assertIsNone(decisions.validate_answer(state, 'OLD', root=self.root))

    def test_recovery_replays_original_text_without_rewriting_source(self):
        self.activate(); q = self.question(); item = self.call(q)
        proof = self.reply('- Approve this exact scope'); original = self.native.read_bytes()
        result = self.m.recover_question('Q', reason='UI could not emit a reply; replay exact native choice',
            expected_contract_sha256=decisions.digest(q['decision_contract']), question_item_id=item, **proof)
        self.assertEqual('RESTORED', result['recovery_history'][0]['result'])
        self.assertEqual(original, self.native.read_bytes())
        self.assertIsNotNone(self.consume(q))


del Fixture
