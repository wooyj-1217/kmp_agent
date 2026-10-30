import copy
import json
from pathlib import Path
import tempfile
import unittest
from harness.human_progress import project,message
from harness.dashboard import snapshot
from harness.dashboard_fixture import write_fixture
from harness.tasks import Tasks

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.raw={};self.data={'selected':'run','scope':{'goal':'저장과 복구 개선'},'tasks':[]}
    def add(self,tid,state='waiting',parent=None,deps=None,verdict='NOT_RUN',raw_state='TODO',kind='documentation'):
        self.raw[tid]={'task_id':tid,'state':raw_state,'parent_task_id':parent,'dependencies':deps or [],'criteria':[{'id':'A','required':True,'description':'필수 동작과 근거 확인'}],'executions':[]}
        view={'id':tid,'title':tid+' 작업','verdict':verdict,'kind':kind,'compliance':'PASS','raw_state':raw_state,'criteria':self.raw[tid]['criteria'],'activity':{'kind':{'active':'observed','complete':'done','blocked':'blocked','waiting':'waiting'}[state],'role_label':'개발 담당','events':[]}}
        if state=='active':
            self.raw[tid]['executions']=[{'agent_run_id':tid+'-work','kind':'work','execution_mode':'current_agent','ended_at':None}]
            view['activity']['work_observation']={'agent_run_id':tid+'-work'}
        self.data['tasks'].append(view);return view
    def test_unselected_has_no_funnel(self):
        self.assertEqual(project({'selected':None}, {})['steps'],[])
    def test_unregistered_has_no_invented_steps(self):
        self.assertEqual(project(self.data,{})['steps'],[])
    def test_actual_evidence_needed_for_done(self):
        self.add('작성',raw_state='DONE',state='complete')
        p=project(self.data,self.raw);self.assertEqual(p['steps'][0]['state'],'waiting');self.assertNotIn('[x]',message(p))
    def test_verified_complete(self):
        self.add('작성',verdict='PASS',raw_state='DONE',state='complete')
        self.assertIn('[x] 작성 작업',message(project(self.data,self.raw)))
    def test_missing_required_conditions_not_complete(self):
        t=self.add('작성',verdict='PASS',state='complete');t['criteria']=[]
        self.assertEqual(project(self.data,self.raw)['steps'][0]['state'],'waiting')
    def test_request_without_independent_process_is_not_running(self):
        t=self.add('호출',state='active',raw_state='IN_PROGRESS');self.raw['호출']['executions'][0]['execution_mode']='independent_process'
        self.assertNotEqual(project(self.data,self.raw)['steps'][0]['state'],'active')
        t['activity']['process_evidence']={'independent_model_spawned':True,'finished_at':None}
        self.assertEqual(project(self.data,self.raw)['steps'][0]['state'],'active')
        t['activity']['process_evidence']['finished_at']='2026-10-28T00:00:00Z'
        self.assertNotEqual(project(self.data,self.raw)['steps'][0]['state'],'active')
    def test_code_compliance_not_inherited(self):
        t=self.add('작성',verdict='PASS',state='complete',kind='code_implementation');t['compliance']='NON_COMPLIANT'
        self.assertNotEqual(project(self.data,self.raw)['steps'][0]['state'],'complete')
    def test_harness_work_uses_own_conditions_not_product_contract(self):
        t=self.add('하네스',verdict='PASS',raw_state='DONE',state='complete',kind='code_implementation');t['compliance']='UNKNOWN';self.raw['하네스']['work_type']='HARNESS_IMPROVEMENT'
        self.assertEqual(project(self.data,self.raw)['steps'][0]['state'],'complete')
        self.raw['하네스']['work_type']='PRODUCT'
        self.assertNotEqual(project(self.data,self.raw)['steps'][0]['state'],'complete')
    def test_active_retry_does_not_reuse_old_pass(self):
        self.add('재시도',verdict='PASS',raw_state='IN_PROGRESS',state='active')
        self.assertEqual(project(self.data,self.raw)['steps'][0]['state'],'active')
    def test_parent_cycle_blocks_checkmarks(self):
        self.add('가',parent='나',verdict='PASS',raw_state='DONE',state='complete');self.add('나',parent='가',verdict='PASS',raw_state='DONE',state='complete')
        p=project(self.data,self.raw);self.assertTrue(p['cycle_detected']);self.assertTrue(all(s['state']=='blocked' for s in p['steps']))
    def test_parallel_active_steps_kept(self):
        self.add('웹',state='active');self.add('서버',state='active')
        p=project(self.data,self.raw);self.assertEqual(p['current'],[1,2]);self.assertEqual(message(p).count('**'),4)
    def test_dependency_order_not_source_dictionary_order(self):
        self.add('재검토',deps=['수정']);self.add('수정',state='active')
        self.assertEqual([s['task_id'] for s in project(self.data,self.raw)['steps']],['수정','재검토'])
    def test_predecessor_failure_blocks_successor(self):
        t=self.add('수정',state='blocked');t['blocked']='계약 충돌';self.add('통합',state='active',deps=['수정'])
        self.assertEqual(project(self.data,self.raw)['steps'][1]['state'],'blocked')
    def test_children_not_extra_major_steps(self):
        self.add('개발');self.add('서버',parent='개발',state='active')
        p=project(self.data,self.raw);self.assertEqual(len(p['steps']),1);self.assertEqual(p['steps'][0]['state'],'active')
    def test_retries_do_not_reset_plan(self):
        self.add('수정',state='active');self.raw['수정']['executions']=[{'kind':'work'},{'kind':'review'},{'kind':'work'}]
        p=project(self.data,self.raw);self.assertEqual(len(p['steps']),1);self.assertIn('재시도 2회',message(p))
    def test_recheck_unchecks_prior_pass(self):
        self.add('수정',state='complete',verdict='RECHECK_REQUIRED',raw_state='DONE')
        p=project(self.data,self.raw);self.assertEqual(p['steps'][0]['state'],'blocked');self.assertNotIn('[x]',message(p))
    def test_human_decision_only_explicit_question_with_basis(self):
        self.data['scope']['decisions']=[{'requires_human':True,'status':'OPEN','question':'선택?', 'basis':'원문'}, {'requires_human':False,'status':'OPEN','question':'자동 보완','basis':'명세'}]
        p=project(self.data,self.raw);self.assertEqual(len(p['decisions']),1)
    def test_required_question_overrides_observed_activity_and_cmd_shares_ledger(self):
        self.add('작업',state='active',raw_state='BLOCKED')
        self.data['required_questions']=[{'id':'Q','question':'어느 범위로 진행할까요?',
            'status':'OPEN','affected_task_ids':['작업'],'options':[{'id':'all','label':'전체 범위'}]}]
        p=project(self.data,self.raw)
        self.assertEqual(p['steps'][0]['state'],'blocked')
        self.assertEqual(p['decisions'][0]['question'],'어느 범위로 진행할까요?')
        self.assertIn('답변 대기',message(p));self.assertIn('전체 범위',message(p))
        self.data['required_questions'][0]['status']='ANSWERED'
        self.assertIn('답변 확인 완료',message(project(self.data,self.raw)))
    def test_missing_work_plan_is_visible_as_start_gate(self):
        view=self.add('작업')
        view['execution_gate']={'status':'BLOCKED','finish_status':'BLOCKED','reasons':['assigned detailed work plan required']}
        p=project(self.data,self.raw)
        self.assertEqual(p['steps'][0]['state'],'blocked')
        self.assertIn('착수 조건 대기',message(p))
    def test_native_error_category_not_guessed_from_text(self):
        self.add('검증',state='blocked',raw_state='BLOCKED');self.raw['검증']['executions']=[{'kind':'work','failure':'network exploded'}]
        self.assertIsNone(project(self.data,self.raw)['steps'][0]['failure'])
    def test_native_environment_issue_and_action(self):
        self.add('검증',state='blocked',raw_state='BLOCKED');self.raw['검증']['executions']=[{'kind':'work','failure_context':{'category':'ENVIRONMENT','next_action':'SDK 경로 확인','requires_human':False}}]
        text=message(project(self.data,self.raw));self.assertIn('시험 환경 문제',text);self.assertIn('SDK 경로 확인',text)
    def test_historical_and_period_are_explicit(self):
        self.add('검토');self.data['scope']['provenance']={'kind':'POSTHOC_CONNECTION'};self.data['period']={'active':True}
        text=message(project(self.data,self.raw));self.assertIn('과거 실행',text);self.assertIn('선택 기간',text)
    def test_exclusion_is_not_checked(self):
        t=self.add('제외',raw_state='TODO');t['applicability']={'status':'EXCLUDED','reason':'사용자 제외'};t['applicability_valid']=True
        p=project(self.data,self.raw);self.assertEqual(p['steps'][0]['state'],'excluded');self.assertNotIn('[x]',message(p));self.assertIn('사용자 제외',message(p))
    def test_qa_and_repair_stay_in_original_todo(self):
        self.add('개발');self.add('검토');self.add('수정');self.raw['검토']['qa_config']={'target_task_id':'개발','repair_task_id':'수정'}
        self.assertEqual(len(project(self.data,self.raw)['steps']),1)
    def test_same_target_acceptance_owner_does_not_create_self_parent(self):
        self.add('TARGET',verdict='PASS',raw_state='DONE',state='complete')
        self.add('QA',verdict='PASS',raw_state='DONE',state='complete')
        self.raw['QA']['qa_config']={'target_task_id':'TARGET','repair_task_id':'TARGET'}
        self.data['execution_plan']={'task_ids':['TARGET','QA']}
        p=project(self.data,self.raw)
        self.assertFalse(p['cycle_detected'])
        self.assertEqual([step['task_id'] for step in p['steps']],['TARGET'])
        self.assertEqual(p['steps'][0]['state'],'complete')
        self.assertEqual([child['task_id'] for child in p['steps'][0]['children']],['QA'])

    def test_same_target_acceptance_preserves_blocked_qa_history(self):
        self.add('TARGET',verdict='PASS',raw_state='DONE',state='complete')
        old=self.add('QA-OLD',verdict='FAIL',raw_state='BLOCKED',state='blocked');old['blocked']='actual past QA environment failure'
        self.add('QA-NEW',verdict='PASS',raw_state='DONE',state='complete')
        for name in ('QA-OLD','QA-NEW'):
            self.raw[name]['qa_config']={'target_task_id':'TARGET','repair_task_id':'TARGET'}
        before=copy.deepcopy((self.data,self.raw));p=project(self.data,self.raw)
        self.assertFalse(p['cycle_detected'])
        self.assertEqual(p['steps'][0]['state'],'blocked')
        self.assertNotIn('[x]',message(p))
        self.assertEqual({child['task_id'] for child in p['steps'][0]['children']},{'QA-OLD','QA-NEW'})
        self.assertEqual((self.data,self.raw),before)

    def test_same_target_owner_does_not_hide_unverified_required_qa(self):
        self.add('TARGET',verdict='PASS',raw_state='DONE',state='complete')
        self.add('QA',verdict='NOT_RUN',raw_state='DONE',state='complete')
        self.raw['QA']['qa_config']={'target_task_id':'TARGET','repair_task_id':'TARGET'}
        p=project(self.data,self.raw)
        self.assertFalse(p['cycle_detected'])
        self.assertNotEqual(p['steps'][0]['state'],'complete')
        self.assertNotIn('[x]',message(p))

    def test_self_owner_link_does_not_mask_another_real_repair_parent(self):
        for name in ('ROOT','OWNER','SELF-QA','REPAIR-QA'):self.add(name)
        self.raw['SELF-QA']['qa_config']={'target_task_id':'OWNER','repair_task_id':'OWNER'}
        self.raw['REPAIR-QA']['qa_config']={'target_task_id':'ROOT','repair_task_id':'OWNER'}
        p=project(self.data,self.raw)
        self.assertFalse(p['cycle_detected'])
        self.assertEqual([step['task_id'] for step in p['steps']],['ROOT'])
        self.assertEqual({child['task_id'] for child in p['steps'][0]['children']},{'OWNER','SELF-QA','REPAIR-QA'})

    def test_real_repair_parent_cycle_still_blocks(self):
        for name in ('A','B','QA-A','QA-B'):self.add(name,verdict='PASS',raw_state='DONE',state='complete')
        self.raw['QA-A']['qa_config']={'target_task_id':'A','repair_task_id':'B'}
        self.raw['QA-B']['qa_config']={'target_task_id':'B','repair_task_id':'A'}
        p=project(self.data,self.raw)
        self.assertTrue(p['cycle_detected'])
        self.assertTrue(all(step['state']=='blocked' for step in p['steps']))
        self.assertNotIn('[x]',message(p))

    def test_explicit_self_parent_remains_a_real_cycle(self):
        self.add('TARGET',parent='TARGET',verdict='PASS',raw_state='DONE',state='complete')
        self.add('QA',verdict='PASS',raw_state='DONE',state='complete')
        self.raw['QA']['qa_config']={'target_task_id':'TARGET','repair_task_id':'TARGET'}
        p=project(self.data,self.raw)
        self.assertTrue(p['cycle_detected'])
        self.assertTrue(all(step['state']=='blocked' for step in p['steps']))

    def test_cmd_location_and_no_project_completion_claim(self):
        self.add('현재',state='active');text=message(project(self.data,self.raw));self.assertIn('위치:',text);self.assertIn('프로젝트 전체 완료 판정과 별개',text)
    def test_pure_projection_does_not_mutate_state(self):
        self.add('검토');before=copy.deepcopy((self.data,self.raw));project(self.data,self.raw);self.assertEqual((self.data,self.raw),before)
    def test_cycle_is_reported_not_silently_ordered(self):
        self.add('가',deps=['나']);self.add('나',deps=['가']);self.assertTrue(project(self.data,self.raw)['cycle_detected'])
    def test_snapshot_and_message_same_source_readonly(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_fixture(root);path=root/'.harness/tasks/tasks.yaml';before=path.read_bytes()
            s=snapshot(root,'normal');self.assertEqual(s['human_progress']['agent_message'],message(s['human_progress']));self.assertEqual(path.read_bytes(),before)
    def test_native_failure_annotations_preserve_retry_history(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'request.md').write_text('request');(root/'error.md').write_text('actual SDK not available')
            m=Tasks(root,'run');m.register('F','T','improvement','검증','fixture',[{'id':'A','required':True,'description':'검증'}],['request.md'],max_attempts=2,execution_scope='documentation')
            m.ready('T');r=m.begin('T','improvement',execution_mode='local_check')
            with self.assertRaises(ValueError):m.fail('T',r['agent_run_id'],'error',failure_category='ENVIRONMENT')
            m.fail('T',r['agent_run_id'],'SDK 없음',failure_category='ENVIRONMENT',failure_evidence='error.md',next_action='SDK 설치',requires_human=True,decision_question='SDK를 설치할까요?')
            m.ready('T');r2=m.begin('T','improvement',execution_mode='local_check');state=m.read()['tasks']['T'];self.assertEqual(len(state['executions']),2);self.assertEqual(state['executions'][0]['failure_context']['category'],'ENVIRONMENT');self.assertNotEqual(r2['agent_run_id'],r['agent_run_id'])

if __name__=='__main__':unittest.main()
