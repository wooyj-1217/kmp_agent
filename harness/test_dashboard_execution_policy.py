import json
from pathlib import Path
import tempfile
import unittest

from harness.dashboard import snapshot
from harness.dashboard_fixture import write_fixture


class ExecutionPolicyViewTests(unittest.TestCase):
    def test_question_scope_and_private_source_are_not_leaked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            write_fixture(root)
            path=root/'.harness/tasks/tasks.yaml'
            state=json.loads(path.read_text())
            normal='normal-work'
            other='parallel-work'
            gate={'status':'BLOCKED','question_ids':['visible'],'plan_registered':True,
                  'task_plan_registered':True}
            state['tasks'][normal]['execution_gate']=gate
            state['required_questions']={
                'visible':{'id':'visible','question':'공유 방식을 선택하세요','status':'OPEN',
                           'propagated_task_ids':[normal], 'options':[{'id':'sync','label':'서버 공유'}],
                           'opened_source_boundary':{'private':'must-not-leak'},
                           'answer':{'source':{'path':'must-not-leak'}}},
                'outside':{'id':'outside','question':'다른 실행 질문','status':'OPEN',
                           'propagated_task_ids':[other]}}
            path.write_text(json.dumps(state,ensure_ascii=False))
            result=snapshot(root,'normal')
            self.assertEqual([q['id'] for q in result['required_questions']],['visible'])
            self.assertEqual(result['tasks'][0]['execution_gate'],gate)
            self.assertNotIn('must-not-leak',json.dumps(result['required_questions']))
            filtered=snapshot(root,'normal',agent_version='UNKNOWN')
            self.assertEqual(filtered['required_questions'],result['required_questions'])

