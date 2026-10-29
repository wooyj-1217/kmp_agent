"""Real native task/admission records and OS locks; model processes are mocked."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from harness.logging import Logger
from harness.tasks import Tasks
from harness.runtime_limits import configure, model_slot
from harness.delegation_runtime import run_codex
from harness.roles import Roles


class RuntimeLimitsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);(self.root/'input.md').write_text('synthetic runtime admission fixture\n')
        run_id=Logger(self.root).start('HARNESS_BUILD','orchestrator','Isolated runtime limit tests, no model calls')
        self.manager=Tasks(self.root,run_id)
        configure(self.manager,2,20)
        self.runs={}
    def begin(self,role):
        tid='RUNTIME-'+role.upper()
        self.manager.register('RUNTIME-FIXTURE',tid,role,'Synthetic '+role,'documentation fixture only',
                              [{'id':'AC','required':True,'text':'native task records exist'}],['input.md'],
                              work_type='HARNESS_BUILD',execution_scope='documentation')
        self.manager.ready(tid)
        run=self.manager.begin(tid,role,execution_mode='local_check');self.runs[role]=(tid,run['agent_run_id'])
        return self.runs[role]
    def admissions(self):
        return self.manager.read().get('runtime_budgets',{}).get(self.manager.run_id,{}).get('admissions',[])
    def test_all_four_roles_share_maximum_two_actual_os_slots(self):
        pairs=[self.begin(r) for r in ('planning','design','development','verification')]
        barrier=threading.Barrier(2);lock=threading.Lock();active=0;peak=0
        def worker(pair):
            nonlocal active,peak
            with model_slot(self.manager,*pair,timeout=10):
                with lock:active+=1;peak=max(peak,active)
                barrier.wait(timeout=5);time.sleep(0.03)
                with lock:active-=1
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(worker,pairs))
        self.assertEqual(peak,2);self.assertEqual(active,0)
        self.assertEqual(len(self.admissions()),4)
        self.assertTrue(all(a['released_at'] for a in self.admissions()))
    def test_maximum_one_wait_times_out_without_admission(self):
        configure(self.manager,1,20)
        a=self.begin('planning');b=self.begin('design')
        with model_slot(self.manager,*a,timeout=1):
            with self.assertRaisesRegex(TimeoutError,'no model spawned'):
                with model_slot(self.manager,*b,timeout=0.05):self.fail('second process admitted')
        self.assertEqual(len(self.admissions()),1)
        with model_slot(self.manager,*b,timeout=1):pass
        self.assertEqual(len(self.admissions()),2)
    def test_total_budget_blocks_other_role_and_retry(self):
        configure(self.manager,2,1)
        a=self.begin('planning');b=self.begin('verification')
        with model_slot(self.manager,*a):pass
        for pair in (a,b):
            with self.assertRaisesRegex(ValueError,'budget exhausted'):
                with model_slot(self.manager,*pair):self.fail('over budget')
        self.assertEqual(len(self.admissions()),1)
    def test_exception_releases_slot(self):
        configure(self.manager,1,20);pair=self.begin('development')
        with self.assertRaisesRegex(RuntimeError,'fixture failure'):
            with model_slot(self.manager,*pair):raise RuntimeError('fixture failure')
        self.assertTrue(self.admissions()[0]['released_at'])
        with model_slot(self.manager,*pair,timeout=0.2):pass
        self.assertEqual(len(self.admissions()),2)
    def test_limits_cannot_change_with_active_task(self):
        self.begin('development')
        with self.assertRaisesRegex(ValueError,'tasks are active'):configure(self.manager,1,3)
        self.assertEqual(self.manager.read()['runtime_limits'],{'max_parallel':2,'max_executions':20})
    def test_same_agent_repeated_admission_consumes_budget(self):
        configure(self.manager,1,2);pair=self.begin('development')
        for _ in range(2):
            with model_slot(self.manager,*pair):pass
        self.assertEqual(len(self.admissions()),2)
        self.assertEqual({a['agent_run_id'] for a in self.admissions()},{pair[1]})
        with self.assertRaisesRegex(ValueError,'budget exhausted'):
            with model_slot(self.manager,*pair):pass
    def test_native_task_events_and_budget_share_existing_identifiers(self):
        pair=self.begin('design')
        with model_slot(self.manager,*pair):pass
        state=self.manager.read();events=self.manager.logger.read()
        admitted=[e for e in events if e['event_type']=='runtime_process_admitted']
        released=[e for e in events if e['event_type']=='runtime_process_released']
        self.assertEqual(len(admitted),1);self.assertEqual(len(released),1)
        self.assertEqual((admitted[0]['task_id'],admitted[0]['agent_run_id']),pair)
        run=state['tasks'][pair[0]]['executions'][0]
        self.assertEqual(run['runtime_admissions'][0],self.admissions()[0])
        self.assertFalse(any(e['event_type']=='model_usage' for e in events))
    def test_project_slot_shared_between_distinct_run_managers(self):
        configure(self.manager,1,20);a=self.begin('planning')
        run2=Logger(self.root).start('HARNESS_BUILD','design','Second isolated run uses same project slots')
        other=Tasks(self.root,run2)
        other.register('RUNTIME-FIXTURE','SECOND-RUN-DESIGN','design','Second run design fixture','documentation fixture only',
                       [{'id':'AC','required':True,'text':'native task record exists'}],['input.md'],
                       work_type='HARNESS_BUILD',execution_scope='documentation')
        other.ready('SECOND-RUN-DESIGN')
        run=other.begin('SECOND-RUN-DESIGN','design',execution_mode='local_check')
        b=('SECOND-RUN-DESIGN',run['agent_run_id'])
        with model_slot(self.manager,*a):
            with self.assertRaises(TimeoutError):
                with model_slot(other,*b,timeout=0.05):self.fail('project limit bypassed')
        self.assertNotIn(run2,self.manager.read().get('runtime_budgets',{}))
    def test_invalid_configuration_rejected_without_state_change(self):
        for parallel,budget in ((0,2),(9,2),(True,2),(2,0),(2,1001),(2,False)):
            with self.assertRaises(ValueError):configure(self.manager,parallel,budget)
        self.assertEqual(self.manager.read()['runtime_limits'],{'max_parallel':2,'max_executions':20})
    def test_adapter_timeout_terminates_before_slot_release(self):
        tid,aid=self.begin('verification');manager=self.manager
        class Child:
            pid=987654;returncode=None;calls=0
            def __init__(self,argv,**kwargs):
                assert manager.read()['runtime_budgets'][manager.run_id]['admissions'][-1]['released_at'] is None
            def communicate(self,*args,**kwargs):
                self.calls+=1
                assert manager.read()['runtime_budgets'][manager.run_id]['admissions'][-1]['released_at'] is None
                if self.calls==1:raise subprocess.TimeoutExpired('synthetic codex',1)
                self.returncode=-15;return '', ''
        with patch('harness.delegation_runtime.subprocess.Popen',Child),patch('harness.delegation_runtime.os.killpg') as kill,patch.object(Roles,'collect_codex',return_value={'usage':'UNKNOWN'}):
            result=run_codex(manager,tid,aid,self.root,{},self.root/'timeout-evidence','mock-runtime',1)
        self.assertEqual(result['returncode'],124);self.assertEqual(result['error'],'TimeoutExpired')
        kill.assert_called();self.assertTrue(self.admissions()[0]['released_at'])
    def test_adapter_malformed_result_never_becomes_completion(self):
        tid,aid=self.begin('development')
        class Child:
            pid=987654;returncode=0
            def __init__(self,argv,**kwargs):Path(argv[argv.index('-o')+1]).write_text('{}')
            def communicate(self,*args,**kwargs):return '', ''
        with patch('harness.delegation_runtime.subprocess.Popen',Child),patch.object(Roles,'collect_codex',return_value={'usage':'UNKNOWN'}):
            result=run_codex(self.manager,tid,aid,self.root,{},self.root/'malformed-evidence','mock-runtime',1)
        self.assertIsNone(result['result']);self.assertTrue(result['result_error']);self.assertEqual(result['usage_status'],'UNKNOWN')
        self.assertEqual(self.manager.read()['tasks'][tid]['state'],'IN_PROGRESS')




class StreamDeadlineTests(unittest.TestCase):
    def test_large_stdin_obeys_timeout_before_worker_exits(self):
        from types import SimpleNamespace
        from harness.delegation_runtime import _communicate_stream, _drain
        stream = SimpleNamespace(line=lambda line: None, tick=lambda: None)
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3)'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                _communicate_stream(child, 'x' * 1_000_000, .1, stream)
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            _drain(child, timeout=5)


if __name__=='__main__':unittest.main()
