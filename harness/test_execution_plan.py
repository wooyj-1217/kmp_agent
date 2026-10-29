import json
from pathlib import Path
import tempfile
import unittest
from harness.tasks import Tasks
from harness.execution_plan import register,revise,exclude,reopen,exclusion_valid,require
from harness.requirement_lineage import file_ref

class ExecutionPlanTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();(self.root/'scope.md').write_text('user scope and change reason');self.m=Tasks(self.root,'plan-run')
 def step(self,tid='T',deps=None):return {'feature_id':'F','task_id':tid,'role':'improvement','title':tid+' 주요 작업','scope':'approved local work','criteria':[{'id':'A','required':True,'description':'actual check'}],'inputs':['scope.md'],'dependencies':deps or [],'execution_scope':'documentation'}
 def plan(self,steps=None,**extra):return register(self.m,'HARNESS_IMPROVEMENT','local_change_validation','사용자 목표',steps or [self.step()],'scope.md',**extra)
 def lineage(self):
  for name in ['user.txt','approved.txt','agent.txt']:(self.root/name).write_text(name)
  src=[dict(id=i,kind=k,anchor='literal authority',**file_ref(self.root,p)) for i,k,p in [('U','USER_ORIGINAL','user.txt'),('A','APPROVED_REQUIREMENTS','approved.txt'),('D','AGENT_DERIVED','agent.txt')]];src[1]['approval']={'source':'U','anchor':'approval','approved_sha256':src[1]['sha256']}
  c={'schema_version':1,'scope':'PRODUCT','purpose':'target scope','sources':src,'requirements':[{'id':'SCOPE','source':'A','anchor':'scope','expected':{'targets':['Reader','Console','Endpoint']}}],'derived_items':[{'id':'DS','source':'D','anchor':'scope','source_ids':['SCOPE'],'expected':{'targets':['Reader','Console','Endpoint']}}]};(self.root/'requirement-lineage.json').write_text(json.dumps(c))
 def test_all_todos_registered_atomically_and_order_kept(self):
  p=self.plan([self.step('A'),self.step('B',['A'])]);s=self.m.read();self.assertEqual(p['task_ids'],['A','B']);self.assertTrue(all(t['state']=='TODO' for t in s['tasks'].values()));self.assertFalse(any('status' in x for x in s['execution_plans'].values()))
 def test_invalid_late_step_does_not_leave_partial_plan(self):
  b=self.step('B');b['criteria']=[]
  with self.assertRaises(ValueError):self.plan([self.step('A'),b])
  self.assertEqual(self.m.read()['tasks'],{})
 def test_type_and_procedure_selected_explicitly(self):
  with self.assertRaises(ValueError):register(self.m,'VERIFY','local_change_validation','goal',[self.step()],'scope.md')
 def test_target_criteria_come_only_from_original_binding(self):
  self.lineage();s=self.step();s['target_criterion']={'id':'VERIFY-{target_index}','description':'{target} 실제 동작 확인','required':True}
  self.plan([s],target_binding={'requirement_id':'SCOPE','property':'targets'});criteria=self.m.read()['tasks']['T']['criteria'];self.assertEqual([c['target'] for c in criteria if 'target' in c],['Reader','Console','Endpoint'])
 def test_unknown_scope_not_guessed(self):
  s=self.step();s['target_criterion']={'id':'V-{target_index}','description':'{target}','required':True}
  with self.assertRaises(ValueError):self.plan([s])
  self.assertEqual(self.m.read()['tasks'],{})
 def test_revision_preserves_previous_order_and_reason(self):
  self.plan();revise(self.m,[self.step('B',['T'])],'add regression','scope.md');p=self.m.read()['execution_plans']['plan-run'];self.assertEqual(p['task_ids'],['T','B']);self.assertEqual(len(p['history']),2)
 def test_exclusion_requires_original_authority_and_never_marks_done(self):
  self.lineage();self.plan()
  with self.assertRaises(ValueError):exclude(self.m,'T','not applicable','D','agent says yes')
  exclude(self.m,'T','user excludes this scope','U','literal decision');t=self.m.read()['tasks']['T'];self.assertTrue(exclusion_valid(self.root,t));self.assertEqual(t['state'],'TODO')
  with self.assertRaises(ValueError):self.m.ready('T')
  (self.root/'user.txt').write_text('new authority');self.assertFalse(exclusion_valid(self.root,t))
 def test_unregistered_native_call_is_blocked_before_spawn(self):
  self.m.register(**self.step())
  with self.assertRaises(ValueError):require(self.m,'T')
  t=self.m.read()['tasks']['T'];self.assertEqual(t['state'],'BLOCKED');self.assertEqual(t['executions'],[])
 def test_registered_qa_child_has_same_plan_without_new_todo(self):
  self.plan();self.m.register(**self.step('QA'))
  def connect(state):state['tasks']['QA']['qa_config']={'target_task_id':'T','stage':'planning'}
  self.m._mutate('synthetic_link',connect,task_id='QA');self.assertEqual(require(self.m,'QA')['task_ids'],['T'])
 def test_mixed_work_types_rejected_atomically(self):
  a=self.step('A');b=self.step('B');b['work_type']='PRODUCT'
  with self.assertRaises(ValueError):self.plan([a,b])
  self.assertEqual(self.m.read()['tasks'],{})
 def test_reopen_keeps_same_task_and_old_attempts(self):
  self.plan();self.m.ready('T');r=self.m.begin('T','improvement',execution_mode='current_agent');reopen(self.m,'T','supplement requested','scope.md');t=self.m.read()['tasks']['T'];self.assertEqual(t['state'],'BLOCKED');self.assertEqual(t['executions'][0]['outcome'],'RETURNED_FOR_SUPPLEMENT');self.assertEqual(len(t['return_history']),1)

if __name__=='__main__':unittest.main()
