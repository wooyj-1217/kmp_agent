"""Synthetic native lineage and explicit lifecycle ownership regression tests."""
import json
from unittest.mock import patch
import unittest
from harness import test_usage_context as fixtures
from harness.logging import Logger, resolve_session
from harness.incremental_sync import collect
from harness.usage_collection import register, poll, WorkerStream
from harness.usage_projection import project
from harness import codex_sync
from harness.dashboard import usage_view
from harness.dashboard_usage import native_identity_conflict, enrich_usage
from harness.dashboard_filter import filter_result


class UsageLifecycleTests(unittest.TestCase):
    setUp = fixtures.UsageContextTests.setUp
    begin = fixtures.UsageContextTests.begin
    native = fixtures.UsageContextTests.native

    def child(self):
        path = self.native('child',[('response','turn',100)])
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        rows[0]['payload']['session_id'] = 'parent'
        rows[0]['payload']['source'] = {'subagent':{'thread_spawn':{'parent_thread_id':'parent','agent_path':'/root/worker'}}}
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        return path

    def test_child_native_id_resolves_and_full_incremental_poll_agree(self):
        path = self.child()
        self.assertEqual(resolve_session(path,'child'),path.resolve())
        with self.assertRaises(ValueError): resolve_session(path,'parent')
        self.logger.sync(path)
        collect(self.logger,path)
        events=[e for e in self.logger.read() if e['event_type']=='model_usage']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['source']['session_id'],'child')
        run=self.begin('CHILD',mode='independent_process')
        register(self.manager,'CHILD',run['agent_run_id'],'child',path=path,independent=True)
        self.assertEqual(poll(self.manager)['new_bindings'],1)
        self.assertEqual(poll(self.manager)['new_bindings'],0)
        self.assertEqual(project(self.root)['known_tokens'],120)

    def test_full_sync_automatically_binds_only_exact_registered_main_turn(self):
        run=self.begin('MAIN')
        path=self.native('main',[('known','registered',100),('free','unregistered',200)])
        register(self.manager,'MAIN',run['agent_run_id'],'main',path=path,turn_id='registered')
        self.logger.sync(path)
        bindings=self.manager.read()['tasks']['MAIN']['executions'][0]['usage_bindings']
        self.assertEqual([b['response_id'] for b in bindings],['known'])
        before=self.logger.path.read_bytes();self.logger.sync(path)
        self.assertEqual(self.logger.path.read_bytes(),before)

    def test_hook_after_child_stream_registration_binds_without_manual_poll(self):
        path=self.child();run=self.begin('WORKER',mode='independent_process')
        stream=WorkerStream(self.manager,'WORKER',run['agent_run_id'])
        stream.line(json.dumps({'type':'thread.started','thread_id':'child'}))
        # Hook supplies exact native child identity, never its parent's session_id.
        with patch.object(codex_sync,'repository_root',return_value=self.root):
            codex_sync.handle({'cwd':str(self.root),'session_id':'child','transcript_path':str(path),'hook_event_name':'Stop'})
        self.assertEqual(len(self.manager.read()['tasks']['WORKER']['executions'][0]['usage_bindings']),1)
        self.assertEqual(project(self.root)['known_tokens'],120)

    def test_conflicting_explicit_contexts_remain_unbound(self):
        a=self.begin('A');b=self.begin('B')
        path=self.native('mixed',[('same','turn',100)])
        for task,run in [('A',a),('B',b)]:
            register(self.manager,task,run['agent_run_id'],'mixed',path=path,turn_id='turn')
        self.logger.sync(path)
        for task in ['A','B']:
            self.assertEqual(self.manager.read()['tasks'][task]['executions'][0]['usage_bindings'],[])
        limits=(self.root/'.harness/usage/attribution-limits.jsonl').read_text()
        self.assertIn('multiple_explicit_contexts_for_one_response',limits)

    def test_unregistered_source_stays_unknown_and_other_collection_status_is_preserved(self):
        a=self.begin('A');b=self.begin('B')
        pa=self.native('main-a',[('a','turn-a',100)])
        pb=self.native('main-b',[('b','turn-b',200)])
        for task,run,session,path,turn in [('A',a,'main-a',pa,'turn-a'),('B',b,'main-b',pb,'turn-b')]:
            register(self.manager,task,run['agent_run_id'],session,path=path,turn_id=turn)
        poll(self.manager)
        state=self.root/'.harness/usage/collection-state.json'
        before=next(r for r in json.loads(state.read_text())['sessions'] if r['session_id']=='main-b')
        self.logger.sync(pa)
        after=next(r for r in json.loads(state.read_text())['sessions'] if r['session_id']=='main-b')
        self.assertEqual(before,after)
        unregistered=self.native('free',[('free-response','free-turn',500)])
        self.logger.sync(unregistered)
        bindings=[binding for task in self.manager.read()['tasks'].values() for run in task['executions'] for binding in run['usage_bindings']]
        self.assertEqual({b['response_id'] for b in bindings},{'a','b'})

    def test_repeated_incremental_response_never_adds_cumulative_totals(self):
        run=self.begin('MAIN')
        path=self.native('main',[('response','turn',100)])
        register(self.manager,'MAIN',run['agent_run_id'],'main',path=path,turn_id='turn')
        self.logger.sync(path)
        row=json.loads(path.read_text().splitlines()[-1]);row['ordinal']=999
        with path.open('a') as handle:handle.write(json.dumps(row)+'\n')
        self.logger.sync(path)
        self.assertEqual(project(self.root)['known_tokens'],120)
        self.assertEqual(len(self.manager.read()['tasks']['MAIN']['executions'][0]['usage_bindings']),1)

    def test_legacy_parent_stamped_history_is_quarantined_without_rewriting(self):
        path=self.child();source_before=path.read_bytes()
        with patch('harness.logging.native_session_id',side_effect=lambda meta:meta.get('session_id') or meta.get('id')):
            self.logger.sync(path)
        legacy_bytes=self.logger.path.read_bytes()
        legacy=project(self.root)
        self.assertIsNone(legacy['known_tokens'])
        self.assertEqual(legacy['unquantified_records'][0]['reason'],'native_identity_conflict')
        self.logger.sync(path)
        corrected=project(self.root)
        self.assertEqual(corrected['known_tokens'],120)
        self.assertEqual(len(corrected['unquantified_records']),1)
        self.assertTrue(self.logger.path.read_bytes().startswith(legacy_bytes))
        after=self.logger.path.read_bytes();self.logger.sync(path)
        self.assertEqual(self.logger.path.read_bytes(),after)
        self.assertEqual(project(self.root)['known_tokens'],120)
        self.assertEqual(path.read_bytes(),source_before)

    def test_scope_view_excludes_legacy_identity_even_with_manual_task_attribution(self):
        run=self.begin('SCOPED')
        path=self.child()
        payload=json.loads(path.read_text().splitlines()[-1])['payload']
        self.logger.append('model_usage',self.rid,task_id='SCOPED',agent_run_id=run['agent_run_id'],
            source={'session_id':'parent'},observed={**payload,'model':'protocol-fixture','usage_semantics':'per_response_increment'})
        state_before=self.manager.read()
        scope={'agent_run_ids':[run['agent_run_id']]}
        legacy=usage_view(self.logger.read(),scope,[],{},state_before['tasks'])
        self.assertEqual(legacy['rows'],[])
        self.assertTrue(legacy['conflicts'])
        def filtered(view):
            enriched=enrich_usage(self.root,view,scope)
            return filter_result({'usage':enriched,'tasks':[],'stages':[]},self.logger.read())['usage']
        legacy=filtered(legacy)
        self.assertIsNone(legacy['totals']['tokens'])
        self.assertIsNone(legacy['universe']['tokens'])
        self.assertEqual(len(legacy['universe']['identity_conflicts']),1)
        register(self.manager,'SCOPED',run['agent_run_id'],'child',path=path,turn_id='turn')
        self.logger.sync(path)
        view=usage_view(self.logger.read(),scope,[],{},self.manager.read()['tasks'])
        self.assertEqual(sum(r['tokens'] for r in view['rows']),120)
        view=filtered(view)
        self.assertEqual(view['totals']['tokens'],120)
        self.assertEqual(view['universe']['tokens'],120)
        self.assertEqual(len(view['universe']['identity_conflicts']),1)
        self.assertEqual(project(self.root)['known_tokens'],120)

    def test_identity_helper_preserves_missing_native_metadata_policy(self):
        self.assertTrue(native_identity_conflict({'source':{'session_id':'parent'},'observed':{'thread_id':'child'}}))
        for thread in [None,'','UNKNOWN']:
            self.assertFalse(native_identity_conflict({'source':{'session_id':'parent'},'observed':{'thread_id':thread}}))
        self.assertFalse(native_identity_conflict({'source':{'session_id':'child'},'observed':{'thread_id':'child'}}))

if __name__=='__main__':unittest.main()
