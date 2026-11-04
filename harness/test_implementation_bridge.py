"""Reviewed plan -> real disposable Git diffs/commands; no model invocation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.implementation_bridge import parse, prepare, execute
from harness.roles import Roles
from harness.stage_readiness import DOMAINS
from harness.test_delegation import build_fixture, mock_worker


class BridgeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.m,self.dev,delegation=build_fixture(self.root)
        self.value={'schema_version':1,'task_id':'IMPLEMENT','title':'Implement reviewed fixture',
            'goal':'Implement approved synthetic source scopes','criteria':[{'id':'INTEGRATED','description':'separate fixture integration','required':True}],
            'baselines':{'planning':'planning.md','design':'design.md','api':'api.md','policy':'policy.md'},
            'code_paths':['shared','web','server'],'api_required':True,'service_version':'fixture-v1',
            'stage':None,**{k:copy.deepcopy(delegation[k]) for k in ('children','architecture','shared_owners','integration_commands','max_parallel','timeout')}}
        self.refs=['planning.md','design.md','api.md','policy.md','architecture.md']
        stages={}
        for name,role,tid in [('planning','planning','PLAN'),('design','design','DESIGN'),('development_plan','development','DEVPLAN')]:
            checks={key:name+'-'+key for key in DOMAINS[name]}
            self.m.register('DELEGATION-FIXTURE',tid,role,name,'reviewed stage',
                [{'id':v,'description':k,'required':True} for k,v in checks.items()],self.refs,
                max_attempts=3,execution_scope='documentation')
            stages[name]={'task_id':tid,'checks':checks}
        self.m.configure_stage_workflow('DELEGATION-FIXTURE',stages)

    def approve(self,name):
        tid={'planning':'PLAN','design':'DESIGN','development_plan':'DEVPLAN'}[name]
        refs=self.refs[:]
        if name=='development_plan':
            path=self.root/'feature/development-plan.md';path.parent.mkdir()
            path.write_text('# Reviewed implementation plan\n\n```development-execution\n'+json.dumps(self.value)+'\n```\n')
            outputs=['feature/development-plan.md']
        else:outputs=[name+'.md']
        self.m.bind_stage_inputs(tid,refs,'exact approved stage inputs')
        self.m.ready(tid);role=self.m.read()['tasks'][tid]['role'];run=self.m.begin(tid,role)
        kwargs={'design_status':{'specification':'COMPLETE','mockup':'NOT_PRODUCED','visual_review':'NOT_RUN'}} if role=='design' else {}
        self.m.submit(tid,run['agent_run_id'],outputs,'synthetic stage source',**kwargs)
        review=self.m.begin(tid,'verification',review=True)
        evidence='review-'+tid+'.md';(self.root/evidence).write_text('Synthetic explicit stage review; not product QA.')
        criteria=self.m.read()['tasks'][tid]['criteria']
        self.m.review(tid,review['agent_run_id'],[{'criterion_id':c['id'],'result':'PASS','evidence':evidence} for c in criteria],'synthetic approval')

    def approved(self):
        for name in ('planning','design','development_plan'):self.approve(name)

    def test_approved_plan_runs_real_diffs_integration_and_no_duplicate_dispatch(self):
        self.approved();seen=[]
        def worker(*args):seen.append(args[1]);return mock_worker(*args)
        result=execute(self.m,'DEVPLAN',worker)
        self.assertEqual(result.get('handoff'),'READY_FOR_VERIFICATION',result)
        self.assertEqual(set(seen),{'CHILD-KMP','CHILD-WEB','CHILD-SERVER'})
        self.assertFalse(result['feature_complete'])
        state=self.m.read();parent=state['tasks']['IMPLEMENT']
        self.assertEqual(parent['execution_scope'],'code_implementation')
        self.assertEqual(parent['implementation_origin']['plan_task_id'],'DEVPLAN')
        self.assertIn('IMPLEMENT',state['execution_plans'][self.m.run_id]['task_ids'])
        self.assertIn('feature/development-plan.md',{a['path'] for a in parent['inputs']})
        attempts=len(parent['executions']);seen.clear()
        result=execute(self.m,'DEVPLAN',worker)
        self.assertTrue(result['cached']);self.assertFalse(seen)
        self.assertEqual(len(self.m.read()['tasks']['IMPLEMENT']['executions']),attempts)
        for area in ('shared','web','server'):
            self.assertEqual((self.root/area/'result.txt').read_text(),'implemented\n')

    def test_unreviewed_stage_creates_no_implementation(self):
        self.approve('planning');self.approve('design')
        with self.assertRaisesRegex(ValueError,'approval missing or stale'):prepare(self.m,'DEVPLAN')
        self.assertNotIn('IMPLEMENT',self.m.read()['tasks'])

    def test_modified_plan_or_upstream_source_requires_recheck(self):
        self.approved();(self.root/'feature/development-plan.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'approval missing or stale'):prepare(self.m,'DEVPLAN')
        self.assertNotIn('IMPLEMENT',self.m.read()['tasks'])

    def test_baseline_must_be_current_approved_stage_output(self):
        self.value['baselines']['planning']='policy.md';self.approved()
        with self.assertRaisesRegex(ValueError,'approved planning output'):prepare(self.m,'DEVPLAN')
        self.assertNotIn('IMPLEMENT',self.m.read()['tasks'])

    def test_unreviewed_architecture_or_settings_never_create_children(self):
        self.value['architecture']['evidence']=['unreviewed.md'];self.approved()
        with self.assertRaisesRegex(ValueError,'reviewed plan input'):prepare(self.m,'DEVPLAN')
        self.assertFalse(any(k.startswith('CHILD-') for k in self.m.read()['tasks']))

    def test_existing_task_cannot_be_adopted(self):
        self.value['task_id']='PARENT';self.approved()
        with self.assertRaisesRegex(ValueError,'already belongs'):prepare(self.m,'DEVPLAN')

    def test_standard_development_entrypoint_continues_after_approval(self):
        self.approved()
        with patch('harness.implementation_bridge.execute',return_value={'implementation_task_id':'IMPLEMENT'}) as runner:
            result=Roles(self.root,self.m.run_id).execute('DEVPLAN','development')
        self.assertEqual(result,{'implementation_task_id':'IMPLEMENT'})
        runner.assert_called_once()

    def test_registered_stage_setup_selects_full_plan_not_interpretation(self):
        role=Roles(self.root,self.m.run_id)
        role.setup('DEVPLAN','feature',planning_version='P-001',design_version='D-001')
        self.assertEqual(self.m.read()['tasks']['DEVPLAN']['role_contract']['scope'],'development_plan')

    def test_invalid_machine_plan_is_rejected_without_guessing(self):
        for change in ({'schema_version':2},{'code_paths':['.']},{'integration_commands':[]},{'timeout':False},{'max_parallel':99}):
            value=dict(self.value,**change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                parse('```development-execution\n'+json.dumps(value)+'\n```\n')
        with self.assertRaises(ValueError):parse('# No executable plan')
        with self.assertRaises(ValueError):parse(('```development-execution\n'+json.dumps(self.value)+'\n```\n')*2)

    def test_child_scope_cannot_exceed_parent_plan(self):
        self.value['code_paths']=['shared']
        with self.assertRaisesRegex(ValueError,'exceeds approved parent'):
            parse('```development-execution\n'+json.dumps(self.value)+'\n```\n')

    def test_full_plan_packet_and_acceptance_reject_incomplete_execution_block(self):
        self.approve('planning');self.approve('design')
        roles=Roles(self.root,self.m.run_id)
        roles.setup('DEVPLAN','feature',planning_version='P-001',design_version='D-001')
        self.m.ready('DEVPLAN');run=self.m.begin('DEVPLAN','development',execution_mode='independent_process')
        prepared=roles.context('DEVPLAN',run['agent_run_id'])
        packet=json.loads((self.root/prepared['context']).read_text())
        self.assertIn('implementation_plan_contract',packet)
        self.assertNotIn('Development is input interpretation ONLY',packet['instruction'])
        self.assertNotIn('Map REQs to KMP/Clean Architecture',packet['instruction'])
        task=self.m.read()['tasks']['DEVPLAN']
        response={'status':'submitted','summary':'synthetic reviewed plan draft','files':[{'path':'development-plan.md','content':'# Missing execution block'}],
            'input_receipt':{'planning_version':'P-001','design_version':'D-001','artifacts':[{'path':r['path'],'sha256':r['sha256']} for r in task['inputs']],
            'acceptance_ids':['INTEGRATED'],'interpretation':'synthetic explicit scope'}}
        with self.assertRaisesRegex(ValueError,'exactly one'):roles.accept('DEVPLAN',run['agent_run_id'],response)
        self.assertFalse((self.root/'feature/development-plan.md').exists())
        response['files'][0]['content']='# Complete fixture plan\n\n```development-execution\n'+json.dumps(self.value)+'\n```\n'
        result=roles.accept('DEVPLAN',run['agent_run_id'],response)
        self.assertEqual(result['scope'],'development_plan')
        current=self.m.read()['tasks']['DEVPLAN']
        self.assertIn('development_plan_receipt',current)
        self.assertNotIn('input_confirmation',current)

    def test_legacy_interpretation_cannot_be_promoted_by_late_workflow(self):
        self.approved()
        self.m._mutate('synthetic_legacy_contract',lambda s:s['tasks']['DEVPLAN'].update(role_contract={'scope':'input_interpretation_only'}),'DEVPLAN')
        with self.assertRaisesRegex(ValueError,'legacy input interpretation'):prepare(self.m,'DEVPLAN')
        self.assertNotIn('IMPLEMENT',self.m.read()['tasks'])

    def test_child_retry_budget_cannot_expand_plan_budget(self):
        self.value['children'][0]['max_attempts']=99;self.approved()
        with self.assertRaisesRegex(ValueError,'retry budget'):prepare(self.m,'DEVPLAN')
        self.assertNotIn('IMPLEMENT',self.m.read()['tasks'])
