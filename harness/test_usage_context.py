"""Isolated collection/ownership tests. Native-format replay, no model/API calls."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from harness.logging import Logger
from harness.tasks import Tasks
from harness.usage_context import recover
from harness.usage_collection import register, poll
from harness.usage_projection import project


class UsageContextTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / '.kmp-agent').mkdir()
        (self.root / '.kmp-agent/project.json').write_text(json.dumps({'project_id': 'usage-test', 'project_path': '..'}))
        (self.root / 'input.md').write_text('SYNTHETIC collection protocol test; no model call\n')
        self.logger = Logger(self.root)
        self.rid = self.logger.start('HARNESS_IMPROVEMENT', 'development', 'Isolated usage collection test')
        self.manager = Tasks(self.root, self.rid)

    def begin(self, tid, role='development', purpose='implementation', owner='web',
              repetition='initial', mode='current_agent', **extra):
        self.manager.register('USAGE', tid, role, '같은 제목', 'isolated metadata/collector fixture',
                              [{'id': 'AC', 'required': True, 'text': 'identity preserved'}], ['input.md'],
                              work_type='HARNESS_IMPROVEMENT', execution_scope='documentation',
                              pipeline_stage='verification' if role == 'verification' else 'development' if role == 'development' else role if role in {'planning', 'design'} else 'report')
        self.manager.ready(tid)
        ctx = {'purpose': purpose, 'development_owner': owner if role == 'development' else 'not_applicable',
               'repetition': repetition, 'basis': 'explicit test case declaration', **extra}
        return self.manager.begin(tid, role, execution_mode=mode, usage_context=ctx)

    def usage(self, aid=None, tid=None, session='s', response='r', n=100, **fields):
        value = {'input_tokens': n, 'cached_input_tokens': n//2, 'output_tokens': 20,
                 'reasoning_output_tokens': 5, 'total_tokens': n+20}
        value.update(fields)
        return self.logger.append('model_usage', self.rid, 'HARNESS_IMPROVEMENT', task_id=tid or 'UNKNOWN',
                                 agent_run_id=aid or 'UNKNOWN', observed={'usage': value, 'usage_semantics': 'per_response_increment',
                                 'response_id': response, 'model': 'protocol-fixture', 'occurred_at': '2026-10-28T00:00:00Z'},
                                 source={'session_id': session, 'kind': 'SYNTHETIC'})

    def native(self, session, records):
        p = self.root / (session + '.jsonl')
        data = [{'type': 'session_meta', 'payload': {'id': session}},
                {'type': 'turn_context', 'payload': {'model': 'protocol-fixture'}}]
        for index, (response, turn, n) in enumerate(records):
            data.append({'type': 'token_usage_record', 'ordinal': index, 'timestamp': '2026-10-28T00:00:00Z',
                         'payload': {'thread_id': session, 'turn_id': turn, 'response_id': response,
                                     'usage': {'input_tokens': n, 'cached_input_tokens': 0, 'output_tokens': 20, 'total_tokens': n+20},
                                     'thread_token_usage': {'total_tokens': 999999}}})
        p.write_text(''.join(json.dumps(r)+'\n' for r in data))
        return p

    def test_same_titles_separate_by_task_id_and_independent_axes_reconcile(self):
        a=self.begin('A'); b=self.begin('B','verification','qa_retest',repetition='retest',review_target_task_ids=['A'])
        self.usage(a['agent_run_id'],'A',response='a'); self.usage(b['agent_run_id'],'B',response='b',n=200)
        data=project(self.root)
        self.assertEqual({t['task_id']:t['direct_tokens'] for t in data['tasks']},{'A':120,'B':220})
        self.assertEqual(data['known_tokens'],340)
        for field in ['roles','purposes','repetitions','actors']:
            self.assertEqual(sum(g['tokens'] for g in data[field]),340)
        qa=next(r for r in data['rows'] if r['task_id']=='B')
        self.assertEqual(qa['development_owner'],'not_applicable')
        self.assertEqual(qa['repetition'],'retest')

    def test_main_role_switch_and_parallel_turns_are_exact_not_temporal(self):
        a=self.begin('DEV'); b=self.begin('QA','verification','qa_review'); c=self.begin('ORCH','orchestrator','coordination')
        p=self.native('main',[('dev','t1',100),('qa','t2',200),('orch','t3',50),('free','t4',30)])
        for task,run,turn in [('DEV',a,'t1'),('QA',b,'t2'),('ORCH',c,'t3')]:
            register(self.manager,task,run['agent_run_id'],'main',path=p,turn_id=turn)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:poll(self.manager),range(2)))
        data=project(self.root)
        self.assertEqual({r['response_id']:r['task_id'] for r in data['rows']},{'dev':'DEV','qa':'QA','orch':'ORCH','free':None})
        self.assertEqual(data['known_tokens'],460)
        self.assertEqual(data['unlinked_tokens'],50)
        self.assertEqual(data['deduplicated_events'],0)
        self.assertEqual(data['collection_mode'],'incremental')
        self.assertTrue(all(r['actor']=='main_session' for r in data['rows'] if r['task_id']))
        self.assertEqual(data['quality']['unlinked_origin_unknown_tokens'],50)
        for turn in ['t1','t2','t3']:
            self.logger.append('session_task_complete',self.rid,source={'session_id':'main'},observed={'turn_id':turn})
        poll(self.manager)
        self.assertIsNone(project(self.root,mode='current')['known_tokens'])
        self.assertEqual(project(self.root)['collection_label'],'응답별 수집 기록')
        self.assertTrue(all(self.manager.read()['tasks'][t]['state']=='IN_PROGRESS' for t in ['DEV','QA','ORCH']))

    def test_registered_turn_import_and_execution_run_ownership(self):
        other_id=self.logger.start('HARNESS_IMPROVEMENT','development','explicit separate supplemental run')
        other=Tasks(self.root,other_id)
        original=self.manager
        self.manager=other
        run=self.begin('SUPPLEMENT')
        self.manager=original
        p=self.native('main-scope',[('old','old-turn',100),('new','current-turn',200)])
        register(other,'SUPPLEMENT',run['agent_run_id'],'main-scope',path=p,turn_id='current-turn',import_scope='registered_turns')
        poll(original)  # Server may have been created with a different run ID.
        data=project(self.root)
        self.assertEqual([r['response_id'] for r in data['rows']],['new'])
        self.assertEqual(data['known_tokens'],220)
        self.assertEqual(data['rows'][0]['task_id'],'SUPPLEMENT')
        event=next(e for e in self.logger.read() if e['event_type']=='usage_attributed')
        self.assertEqual(event['run_id'],other_id)
        self.assertEqual(poll(original)['new_bindings'],0)

    def test_one_response_with_two_explicit_roles_is_not_split_or_stolen(self):
        a=self.begin('A'); b=self.begin('B','verification','qa_review')
        p=self.native('mixed',[('one','same-turn',100)])
        register(self.manager,'A',a['agent_run_id'],'mixed',path=p,turn_id='same-turn'); poll(self.manager)
        register(self.manager,'B',b['agent_run_id'],'mixed',path=p,turn_id='same-turn'); poll(self.manager)
        d=project(self.root)
        self.assertEqual(d['known_tokens'],120)
        self.assertEqual(d['unlinked_tokens'],120)
        self.assertEqual(d['quality']['mapping_errors'],1)
        self.assertIsNone(d['rows'][0]['execution_id'])
        self.assertEqual(d['quality']['new_unclassified_tokens'],120)
        self.assertEqual(d['quality']['unlinked_origin_unknown_tokens'],0)
        self.assertEqual(d['quality']['legacy_unclassified_tokens'],0)

    def test_coordinator_does_not_own_child_usage_and_snapshots_are_not_added(self):
        parent=self.begin('P',owner='coordinator',purpose='coordination')
        child=self.begin('C',owner='kmp',parent_execution_id=parent['agent_run_id'])
        path=self.manager.path;state=json.loads(path.read_text());state['tasks']['C']['parent_task_id']='P';state['tasks']['C']['executions'][0]['parent_task_id']='P';path.write_text(json.dumps(state))
        self.usage(parent['agent_run_id'],'P',response='p',n=30)
        e=self.usage(child['agent_run_id'],'C',response='c',n=100)
        with self.logger.path.open('a') as f:f.write(json.dumps(e)+'\n')
        self.logger.append('usage_snapshot',self.rid,observed={'info':{'total_token_usage':{'total_tokens':999999}}})
        d=project(self.root);self.assertEqual(d['known_tokens'],170)
        self.assertEqual({g['code']:g['tokens'] for g in d['development']},{'coordinator':50,'kmp':120})
        self.assertEqual(d['snapshots_not_added'],1);self.assertEqual(d['deduplicated_events'],1)
        self.assertEqual(project(self.root,'P')['known_tokens'],50)
        self.assertEqual(project(self.root,'P',include_children=True)['known_tokens'],170)

    def test_missing_usage_is_not_zero_and_invalid_usage_has_unknown_amount(self):
        self.begin('EMPTY')
        d=project(self.root);self.assertIsNone(d['known_tokens']);self.assertEqual(d['quality']['missing_usage_executions'],1)
        self.usage(response='invalid',cached_input_tokens=None)
        d=project(self.root);self.assertIsNone(d['known_tokens']);self.assertEqual(d['unquantified_records'][0]['tokens'],None)
        self.usage(response='unlinked-valid');d=project(self.root)
        self.assertEqual(d['known_tokens'],120);self.assertEqual(d['unlinked_tokens'],120)

    def test_initial_fix_call_retry_and_qa_retest_are_distinct(self):
        cases=[('I','development','implementation','initial'),('F','development','defect_fix','review_rework'),
               ('R','development','execution_diagnosis','execution_retry'),('Q','verification','qa_retest','retest')]
        for i,(tid,role,purpose,repeat) in enumerate(cases):
            r=self.begin(tid,role,purpose,repetition=repeat,cause_execution_id='recorded-cause' if repeat!='initial' else 'root')
            self.usage(r['agent_run_id'],tid,response=str(i))
        self.assertEqual({g['code'] for g in project(self.root)['repetitions']},{c[3] for c in cases})

    def test_non_developer_owners_not_applicable_and_frozen_context_survives_task_edits(self):
        for role,purpose in [('planning','requirements'),('design','interaction_design'),('verification','qa_review')]:
            r=self.begin(role,role,purpose);self.usage(r['agent_run_id'],role,response=role)
        d=project(self.root);self.assertTrue(all(r['development_owner']=='not_applicable' for r in d['rows']))
        state=json.loads(self.manager.path.read_text());state['tasks']['design']['usage_context_configuration']={'purpose':'implementation'};self.manager.path.write_text(json.dumps(state))
        self.assertEqual(next(r for r in project(self.root)['rows'] if r['task_id']=='design')['purpose'],'interaction_design')

    def test_finished_work_is_not_shown_as_current_even_with_usage(self):
        r=self.begin('DONE');self.usage(r['agent_run_id'],'DONE')
        self.logger.append('run_finished',self.rid)
        d=project(self.root,mode='current');self.assertEqual(d['active_executions'],[]);self.assertEqual(d['time_bars'],[]);self.assertIsNone(d['known_tokens'])
        self.assertEqual(d['project_known_tokens'],120)

    def test_real_process_stream_collects_before_exit_then_finish_sync_is_idempotent(self):
        """A real OS child writes native-format fixture records. No model executable."""
        from harness.delegation_runtime import run_codex
        from harness.runtime_limits import configure
        configure(self.manager, 1, 5)
        run=self.begin('STREAM',mode='independent_process')
        home=self.root/'fake-codex-home';(home/'sessions').mkdir(parents=True)
        worker=self.root/'protocol-worker'
        worker.write_text('#!'+sys.executable+'\n'+'''
import json,os,pathlib,sys,time
packet=json.loads(sys.stdin.read())
assert packet['usage_context']['purpose']=='implementation'
path=pathlib.Path(os.environ['CODEX_HOME'])/'sessions'/'rollout-stream-native.jsonl'
with path.open('w') as f:
 f.write(json.dumps({'type':'session_meta','payload':{'id':'stream-native'}})+'\\n')
 f.write(json.dumps({'type':'turn_context','payload':{'model':'SYNTHETIC_PROTOCOL_ONLY'}})+'\\n');f.flush()
print(json.dumps({'type':'thread.started','thread_id':'stream-native'}),flush=True)
for index,n in enumerate([100,200]):
 with path.open('a') as f:
  f.write(json.dumps({'type':'token_usage_record','ordinal':index,'timestamp':'2026-10-28T00:00:00Z','payload':{'thread_id':'stream-native','turn_id':'t','response_id':'stream-'+str(index),'usage':{'input_tokens':n,'cached_input_tokens':50,'output_tokens':20,'total_tokens':n+20}}})+'\\n');f.flush()
 time.sleep(.9)
result={'status':'COMPLETE','summary':'synthetic protocol fixture, no model called','changed_files':[],'verifications':[],'unresolved':[],'contract_change_required':False,'contract_impact':[],'change_reference':None}
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(json.dumps(result))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':300,'output_tokens':40}}),flush=True)
''')
        worker.chmod(0o700)
        with patch.dict(os.environ,{'CODEX_HOME':str(home)}),ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(run_codex,self.manager,'STREAM',run['agent_run_id'],self.root,{},self.root/'runtime-evidence',str(worker),5)
            deadline=time.monotonic()+4;observed=None
            while time.monotonic()<deadline:
                d=project(self.root,mode='current')
                if d['known_tokens'] is not None:
                    observed=d;self.assertFalse(future.done());break
                time.sleep(.05)
            self.assertIsNotNone(observed,'usage must be visible before process exit')
            self.assertEqual(observed['collection_mode'],'incremental')
            result=future.result(timeout=7)
        self.assertEqual(result['returncode'],0)
        self.assertEqual(project(self.root)['known_tokens'],340)
        self.assertEqual(self.manager.read()['tasks']['STREAM']['state'],'IN_PROGRESS')
        self.assertIsNone(project(self.root,mode='current')['known_tokens'])
        self.assertEqual(project(self.root)['collection_label'],'응답별 수집 기록')
        before=self.logger.path.read_bytes();poll(self.manager)
        self.assertEqual(project(self.root)['known_tokens'],340)
        self.assertEqual(project(self.root)['deduplicated_events'],0)


class ActualRecoveryTests(unittest.TestCase):
    def test_real_web_and_three_same_title_qa_tasks_preserve_totals_and_idempotence(self):
        source=Path(__file__).resolve().parents[2]/'v1/memo-real-20261027'
        if not source.exists():self.skipTest('private real record corpus is not distributed with harness')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for relative in ['.harness/tasks/tasks.yaml','.harness/logs/events.jsonl']:
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/relative,p)
            originals={r:hashlib.sha256((root/r).read_bytes()).hexdigest() for r in ['.harness/tasks/tasks.yaml','.harness/logs/events.jsonl']}
            before=project(root);first=recover(root);blob=(root/'.harness/usage/classifications.jsonl').read_bytes();second=recover(root);after=project(root)
            self.assertGreater(first['added'],0);self.assertEqual(second['added'],0)
            self.assertEqual(blob,(root/'.harness/usage/classifications.jsonl').read_bytes())
            self.assertEqual(before['known_tokens'],2927905);self.assertEqual(after['known_tokens'],before['known_tokens'])
            self.assertEqual(project(root,'FIX-WEB-CHILD')['known_tokens'],178168)
            self.assertEqual(project(root,'FIX-WEB-CHILD')['purposes'][0]['code'],'defect_fix')
            sums={t['task_id']:t['direct_tokens'] for t in after['tasks']}
            self.assertEqual([sums[k] for k in ['QA-IMPLEMENTATION-R2-RETEST','QA-IMPLEMENTATION-FINAL','QA-USER-GOAL']],[280738,286266,645902])
            self.assertEqual(sum(sums[k] for k in ['QA-IMPLEMENTATION-R2-RETEST','QA-IMPLEMENTATION-FINAL','QA-USER-GOAL']),1212906)
            self.assertEqual(originals,{r:hashlib.sha256((root/r).read_bytes()).hexdigest() for r in originals})


if __name__=='__main__':unittest.main()
