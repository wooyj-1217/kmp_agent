"""Synthetic batching, atomic ownership prevalidation and bounded read costs."""
import json
import unittest
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from harness.logging import Logger
from unittest.mock import patch
from harness import test_usage_context as fixtures
from harness.usage_collection import register, poll


def concurrent_writer(arguments):
    root,index=arguments
    logger=Logger(root)
    record={'event_type':'synthetic','source_key':f'concurrent-{index}'}
    return logger.append_many([record,record]) if index%2 else logger.append(**record)


class UsageBatchTests(unittest.TestCase):
    setUp=fixtures.UsageContextTests.setUp
    begin=fixtures.UsageContextTests.begin
    native=fixtures.UsageContextTests.native

    def imported(self,n=50):
        path=self.native('main',[(f'r-{i}','turn',100) for i in range(n)])
        self.logger.sync(path)
        return path,[{'session_id':'main','response_id':f'r-{i}'} for i in range(n)]

    def test_batch_matches_single_binding_and_is_idempotent_with_bounded_reads(self):
        run=self.begin('BATCH');_,bindings=self.imported()
        original_open=Path.open;opens=[]
        def counted_open(path,*args,**kwargs):
            if path==self.logger.path:opens.append(args[0] if args else kwargs.get('mode','r'))
            return original_open(path,*args,**kwargs)
        with patch.object(self.manager.logger,'read',wraps=self.manager.logger.read) as reads, \
             patch.object(Path,'open',new=counted_open):
            self.assertEqual(self.manager.bind_usage_batch('BATCH',run['agent_run_id'],bindings+bindings,'synthetic'),50)
            self.assertEqual(reads.call_count,1)
        self.assertEqual(len(opens),2,'one source-index read plus one durable outbox batch read')
        state=self.manager.read();actual=state['tasks']['BATCH']['executions'][0]['usage_bindings']
        self.assertEqual(actual,bindings)
        attributed=[e for e in self.logger.read() if e['event_type']=='usage_attributed']
        self.assertEqual(len(attributed),50)
        self.assertTrue(all(e['observed']['source_event_ids'] for e in attributed))
        before=self.logger.path.read_bytes()
        self.assertEqual(self.manager.bind_usage_batch('BATCH',run['agent_run_id'],bindings,'synthetic'),0)
        self.assertEqual(self.logger.path.read_bytes(),before)

    def test_conflicting_owner_or_missing_response_rejects_whole_batch(self):
        a=self.begin('A');b=self.begin('B');_,bindings=self.imported(3)
        self.manager.bind_usage('A',a['agent_run_id'],'main','r-2','existing owner')
        with self.assertRaisesRegex(ValueError,'another execution'):
            self.manager.bind_usage_batch('B',b['agent_run_id'],bindings,'synthetic')
        self.assertEqual(self.manager.read()['tasks']['B']['executions'][0]['usage_bindings'],[])
        with self.assertRaisesRegex(ValueError,'imported'):
            self.manager.bind_usage_batch('B',b['agent_run_id'],[bindings[0],{'session_id':'main','response_id':'missing'}],'synthetic')
        self.assertEqual(self.manager.read()['tasks']['B']['executions'][0]['usage_bindings'],[])
        self.assertEqual(len([e for e in self.logger.read() if e['event_type']=='usage_attributed']),1)

    def test_poll_uses_one_owner_batch_for_fifty_responses(self):
        run=self.begin('POLL');path,bindings=self.imported()
        register(self.manager,'POLL',run['agent_run_id'],'main',path=path,turn_id='turn')
        with patch.object(self.manager,'bind_usage_batch',wraps=self.manager.bind_usage_batch) as batches, \
             patch.object(self.manager,'bind_usage',side_effect=AssertionError('per-response mutation')):
            self.assertEqual(poll(self.manager)['new_bindings'],50)
            self.assertEqual(batches.call_count,1)
        self.assertEqual(self.manager.read()['tasks']['POLL']['executions'][0]['usage_bindings'],bindings)
        self.assertEqual(poll(self.manager)['new_bindings'],0)

    def test_poll_quarantines_only_existing_owner_conflict(self):
        previous=self.begin("PREVIOUS");current=self.begin("CURRENT")
        path,bindings=self.imported(2)
        self.manager.bind_usage("PREVIOUS",previous["agent_run_id"],"main","r-1","existing exact owner")
        register(self.manager,"CURRENT",current["agent_run_id"],"main",path=path,turn_id="turn")
        self.assertEqual(poll(self.manager)["new_bindings"],1)
        run=self.manager.read()["tasks"]["CURRENT"]["executions"][0]
        self.assertEqual(run["usage_bindings"],[bindings[0]])
        limits=[json.loads(line) for line in (self.root/".harness/usage/attribution-limits.jsonl").read_text().splitlines()]
        self.assertEqual([entry["response_id"] for entry in limits],["r-1"])
        self.assertEqual(poll(self.manager)["new_bindings"],0)

    def test_batch_rejection_does_not_invent_response_conflicts(self):
        run=self.begin("POLL");path,_=self.imported(2)
        register(self.manager,"POLL",run["agent_run_id"],"main",path=path,turn_id="turn")
        with patch.object(self.manager,"bind_usage_batch",side_effect=ValueError("concurrent state change")):
            result=poll(self.manager)
        self.assertEqual(result["sessions"][0]["status"],"collection_error")
        self.assertFalse((self.root/".harness/usage/attribution-limits.jsonl").exists())
        self.assertEqual(poll(self.manager)["new_bindings"],2)

    def test_append_many_is_atomic_idempotent_and_redacts_each_event(self):
        before=self.logger.path.read_bytes()
        good={'event_type':'synthetic','source_key':'batch-one','observed':{'password':'must-not-leak'}}
        with self.assertRaises(ValueError):
            self.logger.append_many([good,{'event_type':'human_intervention'}])
        self.assertEqual(self.logger.path.read_bytes(),before)
        with self.assertRaises(TypeError):
            self.logger.append_many([good,{'event_type':'synthetic','observed':{'bad':object()}}])
        self.assertEqual(self.logger.path.read_bytes(),before)
        result=self.logger.append_many([good,good,{'event_type':'synthetic','source_key':'batch-two'}])
        self.assertIsNone(result[1]);self.assertIsInstance(result[0],dict)
        self.assertEqual(result[2]['sequence'],result[0]['sequence']+1)
        self.assertNotIn('must-not-leak',self.logger.path.read_text())
        after=self.logger.path.read_bytes()
        self.assertEqual(self.logger.append_many([good]),[None])
        self.assertEqual(self.logger.path.read_bytes(),after)

    def test_mixed_concurrent_append_and_append_many_keep_unique_sequences(self):
        before=len(self.logger.read())
        with ProcessPoolExecutor(max_workers=2) as pool:
            list(pool.map(concurrent_writer,[(str(self.root),index) for index in range(20)]))
        events=self.logger.read();self.assertEqual(len(events),before+20)
        self.assertEqual([e['sequence'] for e in events],list(range(1,len(events)+1)))
        self.assertEqual(len({e['event_id'] for e in events}),len(events))

    def test_fifty_batch_bindings_have_same_response_evidence_as_single_api(self):
        batch=self.begin('BATCH');single=self.begin('SINGLE')
        _,bindings=self.imported()
        second=self.native('other',[(f'r-{i}','turn',100) for i in range(50)])
        self.logger.sync(second)
        self.manager.bind_usage_batch('BATCH',batch['agent_run_id'],bindings,'same reason')
        for binding in bindings:
            self.assertTrue(self.manager.bind_usage('SINGLE',single['agent_run_id'],'other',binding['response_id'],'same reason'))
        events=self.logger.read()
        indexed={e['event_id']:e for e in events}
        normalized={}
        for execution in [batch['agent_run_id'],single['agent_run_id']]:
            normalized[execution]=[
                (e['observed']['response_id'],e['agent_summary'],
                 [indexed[source]['observed']['usage'] for source in e['observed']['source_event_ids']])
                for e in events if e['event_type']=='usage_attributed' and e['agent_run_id']==execution]
        self.assertEqual(normalized[batch['agent_run_id']],normalized[single['agent_run_id']])

if __name__=='__main__':unittest.main()
