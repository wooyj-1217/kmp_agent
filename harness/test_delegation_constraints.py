"""Coordinator boundary tests; policy validation has independent contract tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from harness.test_synthetic_authority import synthetic_authority
from unittest.mock import patch

from harness.test_delegation import build_fixture, mock_worker
from harness import test_project_contract
from harness.requirement_lineage import file_ref


class DelegationConstraintTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.synthetic_authority=synthetic_authority(self,self.root)
        self.manager,self.dev,self.spec=build_fixture(self.root)

    def test_invalid_plan_creates_no_children(self):
        with patch('harness.delegation.constraints.check_plan',side_effect=ValueError('web target omitted')):
            with self.assertRaisesRegex(ValueError,'web target omitted'):
                self.dev.configure(**self.spec)
        self.assertEqual(set(self.manager.read()['tasks']),{'PARENT'})

    def test_worker_receives_normative_contract_packet(self):
        self.dev.configure(**self.spec);seen=[]
        normative={'policy':{'database':'server PostgreSQL'},'sha256':'frozen-proof'}
        def worker(*args):
            seen.append(copy.deepcopy(args[4]['development_constraints']))
            return mock_worker(*args)
        with patch('harness.delegation.constraints.packet',return_value=normative):
            result=self.dev.execute('PARENT',worker)
        self.assertEqual(result['handoff'],'READY_FOR_VERIFICATION')
        self.assertEqual(seen,[normative]*3)

    def test_worker_prohibition_is_checked_before_merge(self):
        self.dev.configure(**self.spec)
        def check(manager,task,root=None,complete=True):
            if not complete and task['task_id']=='CHILD-KMP':
                self.assertEqual((Path(root)/'shared/result.txt').read_text(),'implemented\n')
                raise ValueError('forbidden SQLite replacement')
        with patch('harness.delegation.constraints.check_code',side_effect=check):
            result=self.dev.execute('PARENT',mock_worker)
        self.assertEqual(result['state'],'BLOCKED')
        self.assertEqual((self.root/'shared/result.txt').read_text(),'initial\n')
        self.assertIn('forbidden SQLite',self.manager.read()['tasks']['CHILD-KMP']['delegation_reason'])

    def test_final_required_sources_failure_prevents_parent_pass(self):
        self.dev.configure(**self.spec)
        def check(manager,task,root=None,complete=True):
            if complete:raise ValueError('required web entrypoint missing')
        with patch('harness.delegation.constraints.check_code',side_effect=check):
            with self.assertRaisesRegex(ValueError,'required web entrypoint'):
                self.dev.execute('PARENT',mock_worker)
        parent=self.manager.read()['tasks']['PARENT']
        self.assertNotEqual(parent['state'],'DONE')
        self.assertFalse(any(r.get('result')=='PASS' for r in parent.get('reviews',[])))

    def test_guarded_acceptance_stage_cannot_be_delegated_as_implementation(self):
        def stage(state):state['tasks']['PARENT']['stage_contract']={'stage':'integration_verification'}
        self.manager._mutate('test_stage',stage,task_id='PARENT')
        with patch('harness.delegation.constraints.check_plan'),patch('harness.delegation.constraints.load',return_value={'policy':{}}):
            with self.assertRaisesRegex(ValueError,'separate product acceptance'):
                self.dev.configure(**self.spec)
        self.assertEqual(set(self.manager.read()['tasks']),{'PARENT'})

    def test_real_frozen_policy_and_logged_target_commands_complete(self):
        """Actual guard and commands; independent model lineage QA is outside this fixture."""
        policy={'settings':{'implementation_targets':['android','web'],
                           'ui_technology':'Compose Multiplatform',
                           'database':{'engine':'PostgreSQL','location':'server','role':'primary'},
                           'server_mode':'new','code_ownership':'shared client and server'},
                'ui_sharing':'shared','ui_owners':{'shared':'kmp'},
                'platform_entrypoints':{'android':['android/result.txt'],'web':['web/result.txt']},
                'target_commands':{target:copy.deepcopy(self.spec['integration_commands']) for target in ['android','web']},
                'source_rules':[{'glob':'shared/result.txt','required_patterns':['implemented'], 'forbidden_patterns':['sqlite']}]}
        for name in ['original.md','derived.md']:(self.root/name).write_text('synthetic architecture source')
        lineage={'schema_version':1,'scope':'PRODUCT','purpose':'synthetic contract execution, not product acceptance',
                 'sources':[dict(id=i,kind=k,anchor='fixture',**file_ref(self.root,p)) for i,k,p in
                            [('U','USER_ORIGINAL','original.md'),('D','AGENT_DERIVED','derived.md')]],
                 'requirements':[{'id':'TECH','source':'U','anchor':'fixture','expected':{'development_constraints':policy}}],
                 'derived_items':[{'id':'PLAN','source':'D','anchor':'fixture','source_ids':['TECH'],'expected':{'development_constraints':copy.deepcopy(policy)}}]}
        (self.root/'requirement-lineage.json').write_text(json.dumps(lineage))
        settings=test_project_contract.ProjectContract.settings(self,'new')
        for name,value in policy['settings'].items():settings[name]['value']=value
        settings['api_contract']['value']='api.md'
        settings['policy_responsibility']['value']='policy.md'
        (self.root/'contract.md').write_text('synthetic API contract')
        (self.root/'settings.json').write_text(json.dumps(settings))
        self.manager.configure_stage('PARENT','ui','settings.json')
        self.dev.configure(**self.spec)
        tasks=self.manager.read()['tasks']
        for spec in self.spec['children']:
            self.assertEqual(tasks[spec['task_id']]['stage_contract'],tasks['PARENT']['stage_contract'])
        with patch('harness.requirement_lineage.development_gate'):
            outcome=self.dev.execute('PARENT',mock_worker)
        self.assertEqual(outcome.get('handoff'),'READY_FOR_VERIFICATION',outcome)
        parent=self.manager.read()['tasks']['PARENT']
        self.assertEqual(parent['state'],'DONE')
        evidence=next((self.root/'.harness/tasks/delegation').glob('*/integration-review.json'))
        report=json.loads(evidence.read_text())
        self.assertEqual({row['target'] for row in report['constraint_target_results']},{'android','web'})
        self.assertTrue(all(row['commands'][0]['call_id'] for row in report['constraint_target_results']))
        review_id=parent['reviews'][-1]['agent_run_id']
        self.assertTrue(parent['reviews'][-1]['results'])
        self.assertEqual(parent['validation_status'][review_id]['state'],'CURRENT')
        lost_call=report['constraint_target_results'][0]['commands'][0]['call_id']
        events_path=self.root/'.harness/logs/events.jsonl'
        original=events_path.read_text()
        events=[json.loads(line) for line in original.splitlines()]
        events_path.write_text('\n'.join(json.dumps(event) for event in events if not (
            event['event_type']=='command_finished' and event.get('observed',{}).get('call_id')==lost_call))+'\n')
        refreshed=self.manager.read()['tasks']['PARENT']
        self.assertEqual(refreshed['validation_status'][review_id]['state'],'RECHECK_REQUIRED')
        self.assertEqual(refreshed['reviews'],parent['reviews'])


if __name__=='__main__':unittest.main()
