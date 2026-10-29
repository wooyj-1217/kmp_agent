import copy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness.agent_flow import project

class AgentFlowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.tasks={};self.events=[];self.issues=[];self.plans={};self.decisions=[];self.now=datetime.now(timezone.utc).isoformat()
 def task(self,tid,role='development',state='TODO',area=None,parent=None,active=False,independent=False,verdict='UNKNOWN',hours=0):
  when=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat();aid=tid+'-run'
  t={'task_id':tid,'title':tid+' 실제 작업','feature_id':'F','project_id':'P','work_type':'HARNESS_BUILD','role':role,'pipeline_stage':{'verification':'verification'}.get(role,role),'state':state,'max_attempts':3,'dependencies':[],'executions':[],'reviews':[],'criteria':[{'id':'A','required':True,'description':'검증'}],'inputs':[],'outputs':[],'handoffs':[],'blocked_reason':None,'synthetic':True,'test_verdict':verdict}
  if active or state=='DONE':t['executions']=[{'agent_run_id':aid,'run_id':'R','kind':'work','role':role,'execution_mode':'independent_process' if independent else 'current_agent','started_at':when,'ended_at':None if active else when}]
  if area:t.update(development_area=area,parent_task_id=parent,delegation_state='RUNNING' if active else 'PLANNED')
  if active and independent:self.events.append({'event_type':'role_process','task_id':tid,'agent_run_id':aid,'run_id':'R','timestamp':when,'observed':{'process_state':'role_process_started','pid':99999,'independent_model_spawned':True,'synthetic':True}})
  self.tasks[tid]=t;return t
 def graph(self):
  def view(root,t,scope,tasks):return {'id':t['task_id'],'raw_state':t['state'],'title':t['title'],'kind':'documentation','criteria':t['criteria'],'blocked':t['blocked_reason'],'verdict':t['test_verdict'],'compliance':'UNKNOWN'}
  pp={'groups':[{'project_id':'P','work_type':'HARNESS_BUILD','feature_id':'F','name':'합성 흐름','tasks':[{'task_id':tid} for tid in self.tasks]}],'decisions':self.decisions}
  with patch('harness.dashboard.task_view',view):return project(self.root,self.tasks,self.events,self.issues,pp,list(self.tasks),self.plans,{'kind':'SYNTHETIC'})
 def node(self,key):return next(n for n in self.graph()['groups'][0]['nodes'] if n['key']==key)
 def test_design_qa_target_visible(self):
  self.task('design','design',state='DONE',verdict='PASS');q=self.task('review','verification',state='IN_PROGRESS',active=True,independent=True);q['qa_config']={'stage':'design','target_task_id':'design','attempts':[]}
  self.assertIn('design 실제 작업',self.node('qa')['task']);self.assertTrue(self.node('qa')['active'])
 def test_parallel_actual_assignments_only(self):
  self.task('coordinator');self.task('shared',area='kmp',parent='coordinator',state='IN_PROGRESS',active=True,independent=True);self.task('browser',area='web',parent='coordinator',state='IN_PROGRESS',active=True,independent=True)
  nodes=self.graph()['groups'][0]['nodes'];children=[n for n in nodes if n['kind']=='development_child'];self.assertEqual(len(children),2);self.assertTrue(all(n['active'] for n in children));self.assertFalse(any(n['key']=='area:ios' for n in nodes))
 def test_request_not_actual_spawn(self):
  self.task('worker',area='server',state='IN_PROGRESS',active=True,independent=False)['executions'][0]['execution_mode']='independent_process'
  n=self.node('area:server');self.assertFalse(n['active']);self.assertIn('실행 미확인',n['status'])
 def test_predecessor_wait_explained(self):
  self.task('contract','planning',state='BLOCKED')['blocked_reason']='정책 입력 대기';self.task('web',area='web')['dependencies']=['contract']
  n=self.node('area:web');self.assertEqual(n['status'],'대기');self.assertIn('contract',n['reason'])
 def test_open_qa_return_resolved_history_preserved(self):
  self.task('dev');q=self.task('qa','verification');q['qa_config']={'target_task_id':'dev','stage':'implementation','repair_task_id':'dev','attempts':[]}
  self.issues=[{'id':'I','feature_id':'F','qa_task_id':'qa','owner':'development','task_id':'dev','observed':'중복 저장','status':'OPEN'}]
  self.assertEqual(len([e for e in self.graph()['groups'][0]['edges'] if e['kind']=='qa_return']),1)
  self.issues[0]['status']='RESOLVED';g=self.graph()['groups'][0];self.assertFalse(any(e['kind']=='qa_return' for e in g['edges']));self.assertEqual(len(g['returns']),1)
 def test_partial_block_does_not_block_active_other_work(self):
  self.task('blocked',state='BLOCKED')['blocked_reason']='입력 미확정';self.task('unrelated',state='IN_PROGRESS',active=True,independent=True)
  n=self.node('development');self.assertTrue(n['active']);self.assertNotEqual(n['status'],'차단');self.assertEqual(n['blocked_count'],1)
 def test_explicit_human_question(self):
  self.task('planning','planning');self.decisions=[{'question':'보존 정책 선택?','basis':'literal user scope'}];self.assertEqual(self.graph()['decisions'],self.decisions)
 def test_required_target_unverified_not_shared_pass(self):
  self.task('shared',area='kmp',state='DONE',verdict='PASS');self.plans={'R':{'task_ids':['shared'],'targets':['Handheld','Desktop']}}
  g=self.graph()['groups'][0];self.assertEqual(len(g['platforms']),2);self.assertTrue(all(p['checks']['qa']=='미검증' for p in g['platforms']))
 def test_call_failure_not_quality_fail(self):
  t=self.task('qa','verification',state='IN_PROGRESS',active=True,independent=True);t['executions'][0]['ended_at']=self.now;t['state']='BLOCKED';t['qa_config']={'stage':'implementation','target_task_id':'qa','attempts':[{'outcome':'NOT_RUN'}]}
  self.events.append({'event_type':'role_process','task_id':'qa','agent_run_id':'qa-run','run_id':'R','timestamp':self.now,'observed':{'process_state':'role_process_finished','exit_code':7,'process_error':'spawn failed','synthetic':True}})
  row=self.node('qa')['tasks'][0];self.assertTrue(row['runtime_failure']);self.assertEqual(row['quality_outcome'],'NOT_RUN');self.assertFalse(row['active'])
 def test_old_event_not_live_failure(self):
  self.task('web',area='web',state='IN_PROGRESS',active=True,independent=True,hours=2)
  n=self.node('area:web');self.assertFalse(n['active']);self.assertEqual(n['status'],'상태 확인 필요')
 def test_closed_process_not_left_running(self):
  self.task('web',area='web',state='IN_PROGRESS',active=True,independent=True)
  self.events.append({'event_type':'role_process','task_id':'web','agent_run_id':'web-run','run_id':'R','timestamp':self.now,'observed':{'process_state':'role_process_finished','exit_code':0,'ended_at':self.now,'synthetic':True}})
  n=self.node('area:web');self.assertFalse(n['active']);self.assertEqual(n['status'],'검토 중')
 def test_historical_and_synthetic_not_live(self):
  self.task('done','planning',state='DONE',verdict='PASS');g=self.graph()['groups'][0];self.assertTrue(g['synthetic']);self.assertTrue(self.node('planning')['complete']);self.assertEqual(g['completion'],'PROJECT_COMPLETION_NOT_ESTABLISHED')
 def test_main_orchestrator_not_independent_process(self):
  self.task('main',state='IN_PROGRESS',active=True);n=self.node('orchestrator');self.assertEqual(n['execution_kind'],'UNCONFIRMED');self.assertEqual(n['status'],'조율 기록 없음')

 def test_no_assignment_separate_from_verification(self):
  self.task('dev');self.assertEqual(self.node('qa')['status'],'미배정');row=self.node('development')['tasks'][0];self.assertEqual(row['verification_status'],'미검증');self.assertEqual(row['assignment'],'배정됨');self.assertEqual(row['execution_observation'],'현재 실행 여부 미확인')
 def test_done_main_actor_retained_without_live_claim(self):
  self.task('done',state='DONE',verdict='RECHECK_REQUIRED');r=self.node('development')['tasks'][0];self.assertEqual(r['raw_state'],'DONE');self.assertEqual(r['execution_kind'],'MAIN_SESSION');self.assertEqual(r['execution_observation'],'종료 확인');self.assertEqual(r['verification_status'],'RECHECK_REQUIRED');self.assertFalse(r['active'])
 def test_unsupported_exclusion_is_not_excluded(self):
  t=self.task('dev');t['applicability']={'status':'EXCLUDED'};self.assertNotEqual(self.node('development')['tasks'][0]['assignment'],'적용 제외')

if __name__=='__main__':unittest.main()
