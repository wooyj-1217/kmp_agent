"""Synthetic worker injection; real disposable Git, file diffs and commands.

No test in this module invokes a model. build_fixture is also usable by the
separate explicitly recorded real-worker trial.
"""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from harness.tasks import Tasks
from harness.delegation import Development
from harness.logging import Logger


def build_fixture(root):
    root=Path(root).resolve(); root.mkdir(parents=True,exist_ok=True)
    def git(*argv):
        return subprocess.run(['rtk','proxy','git',*argv],cwd=root,check=True,capture_output=True)
    git('init','-q');git('config','user.name','Disposable Delegation Test');git('config','user.email','test@example.invalid')
    (root/'.gitignore').write_text('.harness/\n')
    for name in ('planning','design','api','policy','architecture'):
        (root/(name+'.md')).write_text('SYNTHETIC '+name+' contract; test fixture only\n')
    for area,folder in [('kmp','shared'),('web','web'),('server','server'),('android','android'),('ios','ios')]:
        (root/folder).mkdir();(root/folder/'result.txt').write_text('initial\n')
    git('add','.');git('commit','-qm','disposable fixture baseline')
    run_id=Logger(root).start('HARNESS_BUILD','development','Isolated delegation fixture: model-free tests or explicitly recorded native trial')
    manager=Tasks(root,run_id)
    refs={k:k+'.md' for k in ('planning','design','api','policy')}
    manager.register('DELEGATION-FIXTURE','PARENT','development','Synthetic coordinated implementation','fixture only',
                     [{'id':'AC-INTEGRATION','required':True,'text':'separate actual integration assertion'}],list(refs.values()),
                     max_attempts=3,work_type='HARNESS_BUILD',execution_scope='code_implementation',pipeline_stage='development')
    manager.configure_development('PARENT',refs,['shared','web','server','android','ios'],api_required=True,service_version='fixture-v1')
    children=[]
    for area,folder in [('kmp','shared'),('web','web'),('server','server')]:
        children.append(dict(task_id='CHILD-'+area.upper(),area=area,title=area+' fixture implementation',
                             goal='Write the exact UTF-8 bytes implemented\\n (one line with trailing newline) to '+folder+'/result.txt',requirement_ids=['REQ-'+area],
                             acceptance_ids=['AC-'+area],allowed_paths=[folder],dependencies=[],max_attempts=3,
                             verification_commands=[['rtk','proxy','python3','-c',
                                 'from pathlib import Path; assert Path('+repr(str(root/folder/'result.txt'))+').read_text()=="implemented\\n"']],
                             out_of_scope=['baseline changes','other source modules']))
    integration=['rtk','proxy','python3','-c','from pathlib import Path; '+
                 '; '.join('assert Path('+repr(str(root/folder/'result.txt'))+').read_text()=="implemented\\n"' for folder in ('shared','web','server'))]
    spec=dict(parent_task_id='PARENT',children=children,
              architecture={'evidence':['architecture.md'],'modules':{'kmp':['shared'],'web':['web'],'server':['server'],'android':['android'],'ios':['ios']},'ui_owners':{'shared':'kmp'}},
              shared_owners={},integration_commands=[integration],max_parallel=2,executable='not-invoked-by-mock',timeout=30)
    return manager,Development(root,manager.run_id),spec


def mock_worker(manager,tid,aid,workspace,packet,out,executable,timeout):
    out.mkdir(parents=True,exist_ok=True)
    path=packet['allowed_paths'][0]+'/result.txt'
    (workspace/path).write_text('implemented\n')
    return {'returncode':0,'pid':None,'started_at':None,'ended_at':None,'result':{
        'status':'COMPLETE','summary':'synthetic injected worker wrote fixture file',
        'changed_files':[path],'verifications':[],'unresolved':[],
        'contract_change_required':False,'contract_impact':[],'change_reference':None},
        'stdout_path':None,'stderr_path':None,'thread_ids':[],'usage_status':'UNKNOWN'}


class DelegationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.manager,self.dev,self.spec=build_fixture(self.root)
    def configure(self):return self.dev.configure(**self.spec)
    def state(self):return self.manager.read()['tasks']
    def test_three_areas_actual_diff_and_separate_integration(self):
        self.configure();result=self.dev.execute('PARENT',mock_worker)
        self.assertEqual(result.get('handoff'),'READY_FOR_VERIFICATION',result)
        self.assertFalse(result['feature_complete'])
        for tid in ('CHILD-KMP','CHILD-WEB','CHILD-SERVER'):
            self.assertEqual(self.state()[tid]['state'],'DONE',self.state()[tid].get('delegation_reason'))
            self.assertTrue(self.state()[tid].get('change_reference'))
    def test_no_unneeded_platform_children(self):
        self.configure();seen=[]
        def worker(*args):seen.append(args[4]['development_area']);return mock_worker(*args)
        self.dev.execute('PARENT',worker);self.assertEqual(set(seen),{'kmp','web','server'})
        self.assertNotIn('CHILD-ANDROID',self.state());self.assertNotIn('CHILD-IOS',self.state())
    def test_only_requested_platform_selected(self):
        android=copy.deepcopy(self.spec['children'][0]);android.update(task_id='CHILD-ANDROID',area='android',allowed_paths=['android'])
        android['verification_commands']=[['rtk','proxy','python3','-c','pass']]
        self.spec['children']=[android];self.configure();seen=[]
        def worker(*args):seen.append(args[4]['development_area']);return mock_worker(*args)
        self.dev.execute('PARENT',worker);self.assertEqual(seen,['android'])
    def test_disjoint_workers_overlap_and_isolated_workspaces(self):
        self.configure();barrier=threading.Barrier(2);workspaces=set();lock=threading.Lock();maximum=[0];active=[0]
        def worker(*args):
            with lock:active[0]+=1;maximum[0]=max(maximum[0],active[0]);workspaces.add(str(args[3]))
            if args[4]['development_area']!='server':barrier.wait(timeout=10)
            result=mock_worker(*args)
            with lock:active[0]-=1
            return result
        self.dev.execute('PARENT',worker);self.assertEqual(maximum[0],2);self.assertEqual(len(workspaces),3)
    def test_identical_path_rejected_before_any_child_registered(self):
        self.spec['children'][1].update(area='kmp',allowed_paths=['shared/result.txt'])
        with self.assertRaisesRegex(ValueError,'ownership conflict'):self.configure()
        self.assertEqual(set(self.state()),{'PARENT'})
    def test_shared_configuration_requires_owner(self):
        (self.root/'build.gradle.kts').write_text('// fixture shared setting\n')
        with self.assertRaisesRegex(ValueError,'configuration owner'):self.configure()
    def test_predecessor_failure_blocks_dependent_without_dispatch(self):
        self.spec['children'][1]['dependencies']=['CHILD-KMP'];self.configure();seen=[]
        def worker(*args):
            seen.append(args[1]);value=mock_worker(*args)
            if args[1]=='CHILD-KMP':value['returncode']=1
            return value
        result=self.dev.execute('PARENT',worker)
        self.assertEqual(result['state'],'BLOCKED');self.assertNotIn('CHILD-WEB',seen)
        self.assertEqual(self.state()['CHILD-WEB']['delegation_state'],'BLOCKED')
    def test_baseline_change_invalidates_prior_pass_preserving_review(self):
        self.configure();self.dev.execute('PARENT',mock_worker)
        before=copy.deepcopy(self.state()['CHILD-KMP']['reviews']);self.assertTrue(before)
        (self.root/'api.md').write_text('changed synthetic contract\n')
        changed=self.state()['CHILD-KMP'];self.assertEqual(changed['reviews'],before)
        self.assertTrue(any(v['state']=='RECHECK_REQUIRED' for v in changed['validation_status'].values()))
    def test_worker_contract_change_blocks_handoff(self):
        self.configure()
        def worker(*args):
            value=mock_worker(*args);value['result'].update(contract_change_required=True,contract_impact=['API response'])
            return value
        result=self.dev.execute('PARENT',worker);self.assertEqual(result['state'],'BLOCKED')
        self.assertTrue(self.state()['CHILD-KMP'].get('contract_change_request'))
    def test_retry_preserves_attempts_and_completed_parent_no_redispatch(self):
        self.spec['max_parallel']=1;self.configure();attempts=[]
        def failed(*args):attempts.append(args[2]);value=mock_worker(*args);value['returncode']=1;return value
        self.dev.execute('PARENT',failed);self.dev.execute('PARENT',mock_worker)
        self.assertGreaterEqual(len(self.state()['CHILD-KMP']['executions']),2)
        prior=len(self.state()['PARENT']['executions']);called=[]
        self.dev.execute('PARENT',lambda *a:called.append(a))
        self.assertFalse(called);self.assertEqual(prior,len(self.state()['PARENT']['executions']))
    def test_area_pass_does_not_override_failed_integration(self):
        self.spec['integration_commands']=[['rtk','proxy','python3','-c','raise SystemExit(3)']]
        self.configure();result=self.dev.execute('PARENT',mock_worker)
        self.assertEqual(result.get('handoff'),'BLOCKED',result)
        self.assertTrue(all(self.state()[x['task_id']]['state']=='DONE' for x in self.spec['children']))
    def test_parent_child_events_no_synthetic_model_usage(self):
        self.configure();self.dev.execute('PARENT',mock_worker)
        events=self.manager.logger.read();self.assertTrue(any(e['event_type']=='development_child_linked' for e in events))
        self.assertFalse(any(e['event_type']=='model_usage' for e in events))
        self.assertTrue(all(self.state()[x['task_id']]['parent_task_id']=='PARENT' for x in self.spec['children']))
    def test_actual_out_of_scope_diff_rejected_even_self_reported(self):
        self.configure()
        def worker(*args):
            value=mock_worker(*args);(args[3]/'policy.md').write_text('unauthorized\n');value['result']['changed_files'].append('policy.md');return value
        result=self.dev.execute('PARENT',worker);self.assertEqual(result['state'],'BLOCKED')
        self.assertEqual((self.root/'policy.md').read_text(),'SYNTHETIC policy contract; test fixture only\n')
    def test_cycles_and_shared_ui_wrong_owner_rejected(self):
        self.spec['children'][0]['dependencies']=['CHILD-WEB'];self.spec['children'][1]['dependencies']=['CHILD-KMP']
        with self.assertRaisesRegex(ValueError,'cyclic'):self.configure()
        self.spec['children'][0]['dependencies']=[];self.spec['children'][1]['dependencies']=[]
        self.spec['architecture']['ui_owners']={'web':'kmp'}
        with self.assertRaisesRegex(ValueError,'UI/source-set'):self.configure()
    def test_unfinished_parent_prevents_duplicate_worker_dispatch(self):
        self.configure();self.manager.ready('PARENT');self.manager.begin('PARENT','development',execution_mode='local_check')
        called=[]
        with self.assertRaisesRegex(ValueError,'unfinished coordinator'):
            self.dev.execute('PARENT',lambda *args:called.append(args))
        self.assertFalse(called)


if __name__=='__main__':unittest.main()
