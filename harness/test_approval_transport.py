"""Synthetic native transport regressions; actual UI proof is recorded separately."""
import copy
import json
import unittest

from harness import approvals, decisions
from harness.test_execution_policy import ExecutionPolicyTests as Fixture


class ApprovalTransportTests(unittest.TestCase):
    setUp = Fixture.setUp
    step = Fixture.step
    write_native = Fixture.write_native
    activate = Fixture.activate
    reply = Fixture.reply

    def question(self, qid='Q', **extra):
        return self.m.open_question(qid, '긴 승인 전송 시험입니다.\n' + '한글과 원본 계약을 정확히 검증합니다. ' * 30,
            ['T'], [{'id':'approve','label':'Approve this exact scope'}, {'id':'reject','label':'Reject'}],
            approval_purpose='transport_probe', approval_subject={'scope':'synthetic'},
            approval_artifacts=['scope.md'], **extra)

    def call(self, q, call_id='call-real', *, body=None, labels=None):
        payload={'type':'function_call','name':'request_user_input_async','call_id':call_id,
                 'arguments':json.dumps({'questions':[{'title':q['question'] if body is None else body,
                      'options':labels or [o['label'] for o in q['options']]}]})}
        self.records.append({'type':'response_item','payload':payload})
        return json.dumps(['request_user_input_async',call_id,0],separators=(',',':'))

    def structured(self, entries):
        return self.reply('<send_user_message_question_reply>\n'+json.dumps(entries)+'\n</send_user_message_question_reply>')

    def entry(self,q,item,echo=None,answer='Approve this exact scope'):
        return {'question':q['question'] if echo is None else echo,'answer':answer,'questionItemId':item}

    def consume(self,q):
        return approvals.human_approval(self.root,self.m.read(),q['id'],'T','transport_probe',
                                       q['decision_contract']['subject'],q['decision_contract']['artifacts'])

    def test_exact_normalized_and_utf8_truncated_echo_bind_full_native_call(self):
        self.activate()
        for i,form in enumerate(('exact','normalized','utf8_512')):
            with self.subTest(form=form):
                q=self.question('Q'+str(i));item=self.call(q,'call-'+str(i))
                normalized=q['question'].replace('\n',' ')
                echo={'exact':q['question'],'normalized':normalized,
                      'utf8_512':normalized.encode()[:512].decode('utf-8',errors='ignore')}[form]
                proof=self.structured([self.entry(q,item,echo)])
                result=self.m.answer_question(q['id'],**proof)
                self.assertEqual('approve',result['answer']['option']['id'])
                self.assertEqual('NATIVE_USER_INPUT',self.consume(q)['authority'])

    def test_prefix_echo_cannot_authorize_a_different_full_prompt(self):
        self.activate();q=self.question()
        normalized=q['question'].replace('\n',' ')
        echo=normalized.encode()[:512].decode('utf-8',errors='ignore')
        item=self.call(q,body=q['question']+' altered hidden approval scope')
        with self.assertRaises(ValueError):self.m.answer_question('Q',**self.structured([self.entry(q,item,echo)]))
        self.assertIsNone(self.consume(q))

    def test_batch_answers_with_different_question_opening_boundaries(self):
        self.activate();early=self.question('EARLY');early_item=self.call(early,'early-call')
        self.write_native()
        # Different full text makes these distinct questions in one UI reply.
        later=self.m.open_question('LATER','A different later question',['U'],
            [{'id':'approve','label':'Approve this exact scope'},{'id':'reject','label':'Reject'}],
            approval_purpose='transport_probe',approval_subject={'scope':'later'},approval_artifacts=['scope.md'])
        later_item=self.call(later,'later-call')
        proof=self.structured([self.entry(early,early_item),self.entry(later,later_item)])
        self.m.answer_question('EARLY',**proof)
        self.assertEqual('ANSWERED',self.m.answer_question('LATER',**proof)['status'])

    def test_same_full_prompt_call_before_opening_cannot_be_reused(self):
        self.activate();old=self.question('OLD');item=self.call(old,'before-open');self.write_native()
        later=self.question('LATER');self.assertEqual(old['question'],later['question'])
        with self.assertRaises(ValueError):self.m.answer_question('LATER',**self.structured([self.entry(later,item)]))
        self.assertIsNone(self.consume(later))

    def test_wrong_locator_option_and_arbitrary_short_echo_are_rejected(self):
        self.activate()
        for i,kind in enumerate(('call','index','method','answer','labels','short_echo','pinned_item')):
            with self.subTest(kind=kind):
                extra={'question_item_id':json.dumps(['request_user_input_async','pinned',0])} if kind=='pinned_item' else {}
                q=self.question('Q'+str(i),**extra)
                item=self.call(q,'call-'+str(i),labels=['Different option','Reject'] if kind=='labels' else None)
                key=json.loads(item)
                if kind=='call':key[1]='missing'
                if kind=='index':key[2]=1
                if kind=='method':key[0]='untrusted_input'
                entry=self.entry(q,json.dumps(key),q['question'][:20] if kind=='short_echo' else None,
                                 answer='Not a registered option' if kind=='answer' else 'Approve this exact scope')
                with self.assertRaises(ValueError):self.m.answer_question(q['id'],**self.structured([entry]))
                self.assertIsNone(self.consume(q))

    def test_duplicate_items_calls_and_ambiguous_replies_are_rejected(self):
        self.activate()
        for i,kind in enumerate(('duplicate_item','duplicate_call','two_prompts')):
            with self.subTest(kind=kind):
                q=self.question('Q'+str(i));item=self.call(q,'call-'+str(i));entries=[self.entry(q,item)]
                if kind=='duplicate_item':entries.append(copy.deepcopy(entries[0]))
                if kind=='duplicate_call':self.records.append(copy.deepcopy(self.records[-1]))
                if kind=='two_prompts':entries.append(self.entry(q,self.call(q,'second-'+str(i))))
                with self.assertRaises(ValueError):self.m.answer_question(q['id'],**self.structured(entries))
                self.assertIsNone(self.consume(q))

    def test_separate_duplicate_or_conflicting_native_replies_cannot_be_cherry_picked(self):
        self.activate()
        for i,answer in enumerate(('Approve this exact scope','Reject')):
            with self.subTest(answer=answer):
                q=self.question('Q'+str(i));item=self.call(q,'duplicate-'+str(i))
                first=self.structured([self.entry(q,item)])
                self.structured([self.entry(q,item,answer=answer)])
                with self.assertRaises(ValueError):self.m.answer_question(q['id'],**first)
                self.assertIsNone(self.consume(q))

    def test_later_conflicting_native_reply_invalidates_approval_at_consumption(self):
        self.activate();q=self.question();item=self.call(q)
        self.m.answer_question('Q',**self.structured([self.entry(q,item)]))
        self.assertIsNotNone(self.consume(q))
        self.structured([self.entry(q,item,answer='Reject')])
        self.assertIsNone(self.consume(q))

    def test_current_artifact_changes_reject_binding_and_later_consumption(self):
        self.activate();q=self.question();item=self.call(q);proof=self.structured([self.entry(q,item)])
        (self.root/'scope.md').write_text('changed after question')
        with self.assertRaisesRegex(ValueError,'contract/input changed'):self.m.answer_question('Q',**proof)
        (self.root/'scope.md').write_text('approved scope')
        self.m.answer_question('Q',**proof);self.assertIsNotNone(self.consume(q))
        (self.root/'scope.md').write_text('changed after approval')
        self.assertIsNone(self.consume(q))

    def test_typed_approval_rejects_noncanonical_ids_before_opening(self):
        self.activate()
        for options in ([{'id':'APPROVE-T1','label':'Approve'}],[{'id':'yes','label':'Approve'}]):
            with self.assertRaisesRegex(ValueError,'approve'):
                self.m.open_question('BAD','Bad approval',['T'],options,approval_purpose='transport_probe',approval_subject={})
            self.assertNotIn('BAD',self.m.read().get('required_questions',{}))
            self.assertFalse(any(self.m.directory.glob('question-*.json')))


del Fixture
