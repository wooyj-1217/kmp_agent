import unittest
from datetime import datetime,timezone
from harness.dashboard_live import activity_view,recorded_stage,runtime_scopes
from harness.dashboard_usage import apply_recorded_labels

class LiveTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,27,0,5,tzinfo=timezone.utc)
        self.run={'agent_run_id':'a','run_id':'r','role':'verification','kind':'work','pipeline_stage':'verification','started_at':'2026-10-27T00:00:00Z','ended_at':None}
        self.t={'task_id':'t','project_id':'p','work_type':'HARNESS_IMPROVEMENT','state':'IN_PROGRESS','executions':[self.run]}
        self.s={'tasks':{'t':{}},'agent_run_ids':['a']}
    def test_native_run_discovered_without_scope_registration(self):
        es=[{'event_type':'run_started','run_id':'r','project_id':'p','work_type':'HARNESS_IMPROVEMENT','agent_summary':{'request_summary':'real goal'}}]
        scopes=runtime_scopes({'t':self.t},es);self.assertEqual(scopes[0]['agent_run_ids'],['a']);self.assertEqual(scopes[0]['tasks']['t']['stage'],'verification')
    def test_registered_repair_waiting_without_execution_is_discovered(self):
        self.t.update(executions=[],state='READY')
        es=[{'event_type':'run_started','run_id':'r','project_id':'p','work_type':'HARNESS_IMPROVEMENT'},
            {'event_type':'stage_rework_created','run_id':'r','task_id':'t','observed':{'stage':'planning'}}]
        scope=runtime_scopes({'t':self.t},es)[0]
        self.assertIn('t',scope['tasks']);self.assertEqual(scope['agent_run_ids'],[])
        self.assertEqual(activity_view(self.t,scope,es,self.now)['kind'],'waiting')

    def test_open_record_stale_not_running(self):
        self.assertEqual(activity_view(self.t,self.s,[],self.now)['kind'],'observed')
        self.assertEqual(activity_view(self.t,self.s,[],self.now.replace(hour=1))['kind'],'unknown')
    def test_terminal_event_closes_missing_ended_at(self):
        es=[{'event_type':'agent_run_failed','agent_run_id':'a','timestamp':'2026-10-27T00:03:00Z','observed':{'ended_at':'2026-10-27T00:03:00Z'}}]
        view=activity_view(self.t,self.s,es,self.now);self.assertEqual(view['kind'],'blocked');self.assertEqual(view['process_alive'],'UNKNOWN')
    def test_finished_parent_not_stuck_running(self):
        es=[{'event_type':'run_finished','run_id':'r','timestamp':'2026-10-27T00:03:00Z','observed':{'ended_at':'2026-10-27T00:03:00Z'}}]
        self.assertEqual(activity_view(self.t,self.s,es,self.now)['kind'],'unknown');self.assertTrue(activity_view(self.t,self.s,es,self.now)['historical'])
    def test_review_work_is_distinct_from_waiting_for_review(self):
        self.t['state']='IN_REVIEW';self.run['ended_at']='2026-10-27T00:02:00Z'
        self.assertEqual(activity_view(self.t,self.s,[],self.now)['kind'],'waiting')
        self.run.update(kind='review',ended_at=None)
        self.assertEqual(activity_view(self.t,self.s,[],self.now)['kind'],'observed')
    def test_stage_role_activity_axes_and_conflict(self):
        es=[{'event_type':'task_stage_configured','task_id':'t','timestamp':'2026-10-26T00:00:00Z','observed':{'after':{'stage':'ui'}}}]
        self.assertEqual(recorded_stage(self.t,self.run,es)[0],'conflict')
        u={'rows':[{'stage':'수정·재작업','classification':'사후 분류','task_id':'t','agent_run_id':'a'}],'scope_info':{}}
        r=apply_recorded_labels(u,{'t':self.t},[])['rows'][0]
        self.assertEqual(r['stage'],'검증');self.assertEqual(r['role'],'검증 담당');self.assertEqual(r['response_stage'],'수정·재작업')

    def test_existing_role_process_schema_keeps_spawn_distinct_from_model(self):
        es=[{'event_type':'role_process','agent_run_id':'a','timestamp':'2026-10-27T00:01:00Z','observed':{'pid':123,'spawned':True,'adapter':'custom_process'}}]
        p=activity_view(self.t,self.s,es,self.now)['process_evidence']
        self.assertEqual(p['pid'],123);self.assertIs(p['spawned'],True)
        self.assertEqual(p['independent_model_spawned'],'UNKNOWN');self.assertEqual(p['process_alive'],'UNKNOWN')
    def test_delegation_adapter_uses_native_role_process_with_process_state(self):
        es=[{'event_type':'role_process','agent_run_id':'a','timestamp':'2026-10-27T00:01:00Z','observed':{'process_state':'role_process_started','pid':123,'independent_model_spawned':True}},
            {'event_type':'role_process','agent_run_id':'a','timestamp':'2026-10-27T00:02:00Z','observed':{'process_state':'role_process_finished','exit_code':0}}]
        v=activity_view(self.t,self.s,es,self.now);p=v['process_evidence']
        self.assertEqual(p['source'],'role_process.observed.process_state');self.assertIs(p['spawned'],True)
        self.assertIs(p['independent_model_spawned'],True);self.assertEqual(p['exit_code'],0);self.assertEqual(v['kind'],'waiting')
    def test_delegation_area_does_not_replace_native_role(self):
        self.run.update(role='development',parent_task_id='parent',development_area='kmp')
        self.t['delegation']={'parent_task_id':'parent','development_area':'kmp','delegation_state':'RUNNING'}
        v=activity_view(self.t,self.s,[],self.now)
        self.assertEqual(v['role'],'development');self.assertEqual(v['area_label'],'KMP 공통')
        self.assertEqual(v['parent_task_id'],'parent');self.assertEqual(v['kind'],'observed')
        self.assertEqual(activity_view(self.t,self.s,[],self.now.replace(hour=1))['kind'],'unknown')
    def test_delegation_failure_and_recheck_are_not_running(self):
        for state,kind in [('FAILED','failed'),('BLOCKED','blocked'),('RECHECK_REQUIRED','blocked')]:
            self.t['delegation']={'development_area':'server','delegation_state':state,'delegation_reason':'upstream failed'}
            v=activity_view(self.t,self.s,[],self.now)
            self.assertEqual(v['kind'],kind);self.assertEqual(v['delegation_reason'],'upstream failed')
    def test_spawn_event_is_evidence_not_liveness(self):
        es=[{'event_type':'role_process_started','agent_run_id':'a','timestamp':'2026-10-27T00:01:00Z','observed':{'pid':321,'independent_model_spawned':True}},
            {'event_type':'role_process_finished','agent_run_id':'a','timestamp':'2026-10-27T00:03:00Z','observed':{'exit_code':0}}]
        v=activity_view(self.t,self.s,es,self.now)
        self.assertEqual(v['process_evidence']['pid'],321);self.assertIs(v['process_evidence']['independent_model_spawned'],True)
        self.assertEqual(v['process_evidence']['exit_code'],0);self.assertEqual(v['process_evidence']['process_alive'],'UNKNOWN')
        self.assertEqual(v['events'][0]['details']['pid'],321);self.assertEqual(v['kind'],'waiting')
        es[-1]['observed']['exit_code']=1
        self.assertEqual(activity_view(self.t,self.s,es,self.now)['kind'],'failed')
    def test_completed_worker_interval_and_proof_survive_latest_zero_second_review(self):
        self.run.update(role='development',ended_at='2026-10-27T00:03:00Z')
        self.t.update(state='DONE',role='development')
        self.t['executions'].append({'agent_run_id':'review','run_id':'r','role':'verification','kind':'review',
                                     'started_at':'2026-10-27T00:04:00Z','ended_at':'2026-10-27T00:04:00Z'})
        self.s['agent_run_ids'].append('review')
        es=[{'event_type':'role_process','agent_run_id':'a','timestamp':'2026-10-27T00:00:01Z','observed':{'process_state':'role_process_started','spawned':True,'pid':123,'independent_model_spawned':True}},
            {'event_type':'role_process','agent_run_id':'a','timestamp':'2026-10-27T00:03:01Z','observed':{'process_state':'role_process_finished','spawned':True,'exit_code':0,'ended_at':'2026-10-27T00:02:59Z'}}]
        v=activity_view(self.t,self.s,es,self.now)
        self.assertEqual(v['elapsed_seconds'],0);self.assertEqual(v['role'],'verification')
        self.assertEqual(v['task_role_label'],'개발 담당')
        self.assertEqual(v['work_observation']['elapsed_seconds'],180)
        self.assertEqual(v['work_observation']['role'],'development')
        self.assertEqual(v['process_evidence']['agent_run_id'],'a')
        self.assertEqual(v['process_evidence']['started_at'],'2026-10-27T00:00:01Z')
        self.assertEqual(v['process_evidence']['finished_at'],'2026-10-27T00:02:59Z')
        self.assertEqual(v['process_evidence']['pid'],123)
        self.assertEqual(v['kind'],'done')
    def test_ended_worker_does_not_end_new_active_review(self):
        self.run['ended_at']='2026-10-27T00:02:00Z';self.t['state']='IN_REVIEW'
        self.t['executions'].append({'agent_run_id':'review','run_id':'r','role':'verification','kind':'review',
                                     'started_at':'2026-10-27T00:04:00Z','ended_at':None})
        self.s['agent_run_ids'].append('review')
        es=[{'event_type':'role_process_finished','agent_run_id':'a','timestamp':'2026-10-27T00:02:00Z','observed':{'exit_code':1}}]
        v=activity_view(self.t,self.s,es,self.now)
        self.assertEqual(v['kind'],'observed');self.assertIn('검토 진행',v['status'])
        self.assertEqual(v['process_evidence']['exit_code'],1)
        self.assertEqual(v['process_evidence']['process_alive'],'UNKNOWN')
    def test_work_proof_stays_inside_selected_scope_and_latest_attempt(self):
        es=[{'event_type':'role_process_started','agent_run_id':'a','timestamp':'2026-10-27T00:01:00Z','observed':{'pid':123}}]
        later=dict(self.run,agent_run_id='retry',started_at='2026-10-27T00:04:00Z')
        self.t['executions'].append(later)
        v=activity_view(self.t,self.s,es,self.now)
        self.assertEqual(v['work_observation']['agent_run_id'],'a')
        self.s['agent_run_ids'].append('retry')
        v=activity_view(self.t,self.s,es,self.now)
        self.assertEqual(v['work_observation']['agent_run_id'],'retry')
        self.assertEqual(v['process_evidence']['pid'],'UNKNOWN')
    def test_review_only_scope_does_not_inherit_unselected_worker(self):
        self.run['kind']='review'
        v=activity_view(self.t,self.s,[],self.now)
        self.assertIsNone(v['work_observation'])
        self.assertIsNone(v['process_evidence']['agent_run_id'])
        self.assertEqual(v['process_evidence']['spawned'],'UNKNOWN')

if __name__=='__main__':unittest.main()
