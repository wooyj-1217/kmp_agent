"""Synthetic native-source replay tests; no real user/store or product authority."""
import contextlib
import json
import unittest
from unittest.mock import patch

from harness.decisions import digest
from harness.approvals import human_approval
from harness.test_execution_policy import ExecutionPolicyTests as Fixture
from harness.test_completion_cli import CompletionCliTests as CliFixture


class DecisionRecoveryTests(unittest.TestCase):
    setUp = Fixture.setUp
    step = Fixture.step
    write_native = Fixture.write_native
    activate = Fixture.activate
    reply = Fixture.reply
    invoke = CliFixture.invoke

    def question(self, option_id='approve', legacy=False):
        self.activate()
        options=[dict(id=option_id,label='Approve synthetic transport scope'),
                 dict(id='reject',label='Reject synthetic transport scope')]
        kwargs=dict(approval_purpose='transport_probe',approval_subject={'kind':'synthetic'},
                    approval_artifacts=['scope.md'])
        # Model an existing v0.4.6 question, not a registration exemption.
        with patch('harness.decisions._validate_approval_options', create=True) if legacy else contextlib.nullcontext():
            return self.m.open_question('Q', ('한글로 된 긴 시험 질문입니다.\n'*25), ['T'], options, **kwargs)

    def proof(self, question, truncate=True):
        labels=[o['label'] for o in question['options']]
        self.records.append(dict(type='response_item',payload=dict(type='function_call',
            name='request_user_input_async',call_id='recovery-call',
            arguments=json.dumps({'questions':[{'title':question['question'],'options':labels}]}))))
        item=json.dumps(['request_user_input_async','recovery-call',0],separators=(',',':'))
        echoed=question['question']
        if truncate:
            echoed=echoed.replace('\n',' ').encode()[:512].decode('utf-8',errors='ignore')
        text='<send_user_message_question_reply>\n'+json.dumps([
            {'answer':labels[0],'question':echoed,'questionItemId':item}])+'\n</send_user_message_question_reply>'
        proof=self.reply(text)
        return dict(question_id='Q',reason='Restore original synthetic native choice',
                    expected_contract_sha256=digest(question['decision_contract']),
                    question_item_id=item,**proof)

    def test_truncated_original_is_recovered_consumed_and_audited_without_native_rewrite(self):
        q=self.question();proof=self.proof(q);before=self.native.read_bytes()
        result=self.m.recover_question(**proof)
        self.assertEqual(result['status'],'ANSWERED')
        self.assertEqual(self.native.read_bytes(),before)
        self.assertEqual(result['decision_contract'],q['decision_contract'])
        history=result['recovery_history'][0]
        self.assertEqual((history['result'],history['status_before'],history['original_option_id']),('RESTORED','OPEN','approve'))
        self.assertTrue(history['approval_consumable'])
        self.assertEqual(history['source'],result['answer']['source'])
        receipt=human_approval(self.root,self.m.read(),'Q','T','transport_probe',
                               {'kind':'synthetic'},q['decision_contract']['artifacts'])
        self.assertIsNotNone(receipt)
        events=[e for e in self.m.logger.read() if e['event_type']=='required_question_answer_recovered']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['observed']['recovery_id'],history['recovery_id'])

    def test_exact_same_proof_is_revalidated_idempotently(self):
        q=self.question();proof=self.proof(q)
        first=self.m.recover_question(**proof)
        again=self.m.recover_question(**dict(proof,reason='Repeated explicit recovery'))
        self.assertEqual(first,again)
        self.assertEqual(len(again['recovery_history']),1)

    def test_wrong_item_or_original_hash_does_not_write_answer_or_success_event(self):
        q=self.question();proof=self.proof(q)
        bad_proofs=(dict(proof,question_item_id='["request_user_input_async","wrong-call",0]'),
                    dict(proof,expected_contract_sha256='0'*64),dict(proof,payload_sha256='0'*64))
        for bad in bad_proofs:
            with self.subTest(bad=bad), self.assertRaises(ValueError):self.m.recover_question(**bad)
            current=self.m.read()['required_questions']['Q']
            self.assertEqual(current['status'],'OPEN');self.assertIsNone(current['answer'])
            self.assertNotIn('recovery_history',current)
        self.assertFalse(any(e['event_type'] in {'required_question_answered','required_question_answer_recovered'}
                             for e in self.m.logger.read()))
        rejected=[e for e in self.m.logger.read() if e['event_type']=='required_question_recovery_rejected']
        self.assertEqual(len(rejected),len(bad_proofs))
        for event,bad in zip(rejected,bad_proofs):
            audit=event['observed']
            self.assertEqual((event['task_id'],audit['question_id'],audit['result']),('T','Q','REJECTED'))
            self.assertEqual(audit['expected_contract_sha256'],bad['expected_contract_sha256'])
            self.assertEqual(audit['question_item_id'],bad['question_item_id'])
            self.assertEqual(audit['source']['payload_sha256'],bad['payload_sha256'])
            self.assertEqual(audit['source']['record_ordinal'],bad['record_ordinal'])
            self.assertEqual(audit['reason'],bad['reason']);self.assertTrue(audit['cause'])

    def test_changed_approval_artifact_cannot_be_recovered(self):
        q=self.question();proof=self.proof(q);(self.root/'scope.md').write_text('changed after asking')
        with self.assertRaisesRegex(ValueError,'contract/input changed'):self.m.recover_question(**proof)
        current=self.m.read()['required_questions']['Q']
        self.assertEqual((current['status'],current['answer']),('OPEN',None))
        self.assertNotIn('recovery_history',current)
        rejected=[e for e in self.m.logger.read() if e['event_type']=='required_question_recovery_rejected']
        self.assertEqual(len(rejected),1)
        self.assertIn('contract/input changed',rejected[0]['observed']['cause'])

    def test_unknown_question_is_not_assigned_to_an_unrelated_task(self):
        q=self.question();proof=self.proof(q)
        with self.assertRaisesRegex(ValueError,'no task attribution inferred'):
            self.m.recover_question(**dict(proof,question_id='UNKNOWN'))
        self.assertFalse(any(e['event_type']=='required_question_recovery_rejected' for e in self.m.logger.read()))
        self.assertEqual(self.m.read()['required_questions']['Q']['status'],'OPEN')

    def test_invalid_history_is_not_silently_replaced(self):
        q=self.question();proof=self.proof(q)
        self.m._mutate('synthetic_invalid_history',lambda s:s['required_questions']['Q'].update(recovery_history={'retain':'original'}))
        with self.assertRaisesRegex(ValueError,'invalid recovery history'):self.m.recover_question(**proof)
        current=self.m.read()['required_questions']['Q']
        self.assertEqual((current['status'],current['answer']),('OPEN',None))
        self.assertEqual(current['recovery_history'],{'retain':'original'})

    def test_valid_existing_answer_is_reverified_without_overwrite(self):
        q=self.question();proof=self.proof(q,truncate=False)
        answer_args={k:v for k,v in proof.items() if k in {'record_ordinal','payload_sha256','user_input_record_ordinal','user_input_payload_sha256'}}
        original=self.m.answer_question('Q',**answer_args)['answer']
        result=self.m.recover_question(**proof)
        self.assertEqual(result['answer'],original)
        self.assertEqual(result['recovery_history'][0]['result'],'REVERIFIED')
        bad=dict(proof,user_input_payload_sha256='0'*64)
        with self.assertRaises(ValueError):self.m.recover_question(**bad)
        self.assertEqual(self.m.read()['required_questions']['Q']['answer'],original)

    def test_repeated_recovery_checks_source_again(self):
        q=self.question();proof=self.proof(q);self.m.recover_question(**proof)
        self.records[-1]['payload']['content'][0]['text']='tampered original source'
        self.write_native()
        with self.assertRaisesRegex(ValueError,'not currently valid'):self.m.recover_question(**proof)
        self.assertEqual(len(self.m.read()['required_questions']['Q']['recovery_history']),1)

    def test_legacy_option_id_is_preserved_and_not_promoted_to_approval(self):
        q=self.question('APPROVE-T1',legacy=True);proof=self.proof(q)
        result=self.m.recover_question(**proof)
        self.assertEqual(result['answer']['option']['id'],'APPROVE-T1')
        self.assertEqual(result['decision_contract'],q['decision_contract'])
        self.assertFalse(result['recovery_history'][0]['approval_consumable'])
        self.assertIsNone(human_approval(self.root,self.m.read(),'Q','T','transport_probe',
                                         {'kind':'synthetic'},q['decision_contract']['artifacts']))

    def test_official_selected_task_cli_routes_recovery(self):
        q=self.question();proof=self.proof(q);self.rid='run'
        data=self.root/'recovery.json';data.write_text(json.dumps(proof))
        code,result=self.invoke('task',operation='recover-question',data=data)
        self.assertEqual((code,result['status']),(0,'ANSWERED'))
        self.assertEqual(result['recovery_history'][0]['source'],result['answer']['source'])


del Fixture, CliFixture
