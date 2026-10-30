"""Real owned-process timeout/lock tests; model-free."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from harness import tracking_io as io
from harness import development_tracking as d
from harness import test_development_tracking as fixture_tests


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_tests.DevelopmentTracking();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.m=self.fixture.t

    def test_batch_identity_binary_newline_deletion_index_and_mode(self):
        f=self.fixture
        f.write('src/space name.txt','before');f.write('src/new\nline.txt','line')
        (self.root/'src/binary.bin').write_bytes(b'\x00\xff\nblob')
        f.commit('special baseline');f.task()
        f.write('src/space name.txt','after');(self.root/'src/binary.bin').unlink()
        f.write('src/untracked.txt','untracked');f.write('src/new\nline.txt','staged');f.git('add','src/new\nline.txt')
        (self.root/'src/app.py').chmod(0o755)
        task=self.m.read()['tasks']['CLIENT']
        with patch('harness.development_tracking.run_git',wraps=io.run_git) as calls:
            proof=d.capture(self.m,task)
        self.assertLessEqual(calls.call_count,8)
        self.assertEqual(proof['files']['src/binary.bin'],None)
        self.assertEqual(proof['files']['src/new\nline.txt'],d.digest(b'staged'))
        self.assertEqual(proof['changed_files']['src/space name.txt']['head_sha256'],d.digest(b'before'))
        self.assertEqual(proof['changed_files']['src/untracked.txt']['head_sha256'],None)
        identity={k:proof[k] for k in ('head','files','index','modes')}
        self.assertEqual(proof['state_sha256'],d.digest(json.dumps(identity,sort_keys=True).encode()))
        self.assertEqual(proof['modes']['src/app.py'],0o755)

    def test_refresh_captures_once_per_task_but_not_across_phases(self):
        self.fixture.passed();state=self.m.read();task=state['tasks']['CLIENT']
        original=copy.deepcopy(task['reviews'][0]);task['reviews'].append({**copy.deepcopy(original),'agent_run_id':'second-review'})
        with patch('harness.development_tracking.capture',wraps=d.capture) as capture:
            d.refresh(self.m,state)
            self.assertEqual(capture.call_count,1)
        (self.root/'src/app.py').write_text('value=3')
        d.refresh(self.m,state)
        self.assertTrue(all(x['state']=='RECHECK_REQUIRED' for x in task['validation_status'].values()))
        with patch('harness.development_tracking.capture',side_effect=AssertionError('must not recertify invalid history')):
            d.refresh(self.m,state)

    def test_git_timeout_reaps_owned_process_and_preserves_state(self):
        original=subprocess.Popen;owned=[]
        def blocked(argv,**kwargs):
            child=original([sys.executable,'-c','import time;time.sleep(30)'],**kwargs);owned.append(child);return child
        with patch.object(io,'GIT_TIMEOUT_SECONDS',.05),patch.object(io.subprocess,'Popen',side_effect=blocked):
            with self.assertRaisesRegex(ValueError,'Git inspection timed out'):io.run_git(self.root,'status')
        self.assertTrue(owned);self.assertTrue(all(p.poll() is not None for p in owned))
        self.assertEqual(io.run_git(self.root,'rev-parse','HEAD').returncode,0)

    def test_capture_total_deadline_not_per_file_multiplier(self):
        with patch.object(io,'CAPTURE_TIMEOUT_SECONDS',.01):
            with io.capture_budget(self.root,'deadline'):
                time.sleep(.02)
                with self.assertRaisesRegex(ValueError,'deadline exceeded'):io.run_git(self.root,'status')

    def test_lock_contender_status_and_interrupt_fail_bounded_then_recover(self):
        entered=threading.Event();release=threading.Event();errors=[]
        def holder():
            try:self.m._mutate('controlled_delay',lambda state:(entered.set(),release.wait(2)))
            except Exception as error:errors.append(error)
        t=threading.Thread(target=holder);t.start();self.assertTrue(entered.wait(2))
        try:
            with patch.object(io,'LOCK_TIMEOUT_SECONDS',.05):
                for action in ('read','interrupt_request'):
                    start=time.monotonic()
                    with self.assertRaisesRegex(TimeoutError,'no stale status'):self.m._mutate(action,lambda state:None)
                    self.assertLess(time.monotonic()-start,.5)
        finally:release.set();t.join(3)
        self.assertFalse(errors);self.assertFalse(t.is_alive());self.m.read()

    def test_timeout_during_refresh_invalidates_and_releases_lock(self):
        self.fixture.passed()
        with patch('harness.development_tracking.capture',side_effect=ValueError('Git inspection timed out')):
            state=self.m.read()
        task=state['tasks']['CLIENT'];self.assertEqual(task['validation_status'][task['reviews'][-1]['agent_run_id']]['state'],'RECHECK_REQUIRED')
        self.m.read()

    def test_operation_change_not_hidden_by_pre_refresh_cache(self):
        self.fixture.passed()
        self.m._mutate('controlled_code_change',lambda state:(self.root/'src/app.py').write_text('value=5'))
        task=self.m.read()['tasks']['CLIENT']
        self.assertEqual(task['validation_status'][task['reviews'][-1]['agent_run_id']]['state'],'RECHECK_REQUIRED')
