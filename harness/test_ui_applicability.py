import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harness.roles import Roles
from harness.ui_applicability import validate
from harness.requirement_lineage import file_ref


class UIApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roles = Roles(self.root, 'SYNTHETIC-NONVISUAL')
        self.tasks = self.roles.tasks
        self.process_inspection = patch('harness.ui_applicability._independent_process', return_value=True)
        self.process_inspection.start()
        self.addCleanup(self.process_inspection.stop)
        (self.root / 'original.md').write_text('Synthetic trial: CLI only, no graphical interface. No PRODUCT PASS claim.')
        self.value = {'schema_version':1, 'status':'NOT_APPLICABLE', 'reason':'CLI only; no graphical interface', 'interfaces':['cli'], 'requirement_id':'REQ-CLI'}
        (self.root / 'ui.json').write_text(json.dumps(self.value))
        original = file_ref(self.root, 'original.md')
        contract = {'schema_version':1, 'scope':'HARNESS_TRIAL', 'purpose':'synthetic CLI contract test',
                    'scope_authorization':'ORIGINAL', 'product_pass_claim':False,
                    'sources':[dict(original, id='ORIGINAL', kind='USER_ORIGINAL', anchor='full text')],
                    'requirements':[{'id':'REQ-CLI','source':'ORIGINAL','anchor':'CLI only','expected':{'ui_applicability':{k:v for k,v in self.value.items() if k not in {'schema_version','requirement_id'}}}}],
                    'derived_items':[]}
        contract['sources'].append(dict(file_ref(self.root, 'ui.json'), id='DERIVED', kind='AGENT_DERIVED', anchor='full declaration'))
        contract['derived_items'] = [{'id':'DESIGN-CLI', 'source':'DERIVED', 'source_ids':['REQ-CLI'], 'anchor':'full declaration', 'expected':copy.deepcopy(contract['requirements'][0]['expected'])}]
        (self.root / 'requirement-lineage.json').write_text(json.dumps(contract))

    def register(self, tid, role, deps=None, visual=False, applicable=False, planning=None):
        self.tasks.register('CLI',tid,role,'synthetic CLI','synthetic tests',[{'id':'C','required':True,'text':'nonvisual interfaces and errors match original'}],['original.md'],deps,3,visual_required=visual,work_type='HARNESS_IMPROVEMENT',execution_scope='documentation')
        if role in {'planning','design','development'}:

            self.roles.setup(tid,'feature',planning_version=planning,ui_applicability='ui.json' if applicable else None)

    def submit(self, tid, role):
        context = self.roles.prepare(tid,role)
        name = 'requirements.md' if role == 'planning' else 'design.md'
        self.roles.accept(tid,context['agent_run_id'],{'status':'submitted','summary':'synthetic interface contract','files':[{'path':name,'content':'CLI command echo INPUT; stdout INPUT; invalid arguments exit 2; REQ-CLI'}]})
        return context

    def review(self, tid, independent=False):
        (self.root / 'evidence.md').write_text('Synthetic inspection of CLI inputs, outputs and errors; no visual observations.')
        run = self.tasks.begin(tid,'verification',review=True,execution_mode='independent_process' if independent else 'current_agent')
        self.tasks.review(tid,run['agent_run_id'],[{'criterion_id':'C','result':'PASS','evidence':'evidence.md'}],'synthetic review')

    def design(self, independent=True):
        self.register('P','planning');self.submit('P','planning');self.review('P')
        self.register('D','design',['P'],applicable=True,planning='P-001')
        self.tasks.handoff('P','D')
        context = self.submit('D','design')
        self.review('D',independent)
        self.register('DEV','development',['D'],applicable=True,planning='P-001')
        return context

    def test_real_role_context_archive_review_handoff(self):
        context = self.design()
        task = self.tasks.read()['tasks']['D']
        frozen = json.loads((self.root / task['executions'][0]['role_context']['snapshot']).read_text())
        self.assertIn('NOT_APPLICABLE',frozen['instruction'])
        self.assertEqual(task['design_status']['visual_review'],'NOT_APPLICABLE')
        self.assertEqual(task['design_status']['mockup'],'NOT_APPLICABLE')
        self.assertFalse((self.root / 'feature/prototype').exists())
        self.tasks.handoff('D','DEV')
        self.assertIn('feature/design.md',[a['path'] for a in self.tasks.read()['tasks']['DEV']['inputs']])

    def test_local_review_cannot_authorize_handoff(self):
        self.design(independent=False)
        with self.assertRaisesRegex(ValueError,'independent'):
            self.tasks.handoff('D','DEV')

    def test_source_and_declaration_tamper_block(self):
        self.design()
        (self.root / 'ui.json').write_text(json.dumps(dict(self.value,reason='changed')))
        with self.assertRaises(ValueError): self.tasks.handoff('D','DEV')

    def test_authority_mapping_and_visual_conflict(self):
        self.register('V','design',visual=True)
        with self.assertRaises(ValueError):
            from harness.ui_applicability import bind
            bind(self.tasks,self.tasks.read()['tasks']['V'],'ui.json')
        value = dict(self.value,reason='agent changed scope')
        (self.root / 'ui.json').write_text(json.dumps(value))
        self.tasks.register('CLI','M','design','test','test',[{'id':'C','required':True,'text':'test'}],['original.md'],work_type='HARNESS_IMPROVEMENT')
        with self.assertRaises(ValueError):
            self.roles.setup('M','another',ui_applicability='ui.json')

    def test_trial_cannot_authorize_product(self):
        self.tasks.register('CLI','PRODUCT','design','test','test',[{'id':'C','required':True,'text':'test'}],['original.md'],work_type='PRODUCT')
        with self.assertRaisesRegex(ValueError,'PRODUCT'):
            self.roles.setup('PRODUCT','feature',ui_applicability='ui.json')

    def test_frozen_snapshot_tamper_blocks(self):
        self.design()
        task = self.tasks.read()['tasks']['D']
        binding = task['role_contract']['ui_applicability']
        (self.root / binding['inputs'][0]['snapshot']).write_text('tampered snapshot')
        with self.assertRaises(ValueError): validate(self.tasks,task,reviewed=True)

    def test_visual_pass_cannot_be_submitted_for_nonvisual_design(self):
        self.register('D','design',applicable=True)
        self.tasks.ready('D')
        run = self.tasks.begin('D','design')
        (self.root / 'design.md').write_text('Synthetic CLI contract')
        with self.assertRaises(ValueError):
            self.tasks.submit('D',run['agent_run_id'],['design.md'],'fake visual PASS',
                {'specification':'COMPLETE','mockup':'NOT_APPLICABLE','visual_review':'PASS'})

    def test_declared_independent_without_process_evidence_is_insufficient(self):
        self.design()
        self.process_inspection.stop()
        with self.assertRaisesRegex(ValueError,'independent'):
            self.tasks.handoff('D','DEV')

    def test_missing_development_binding_is_blocked(self):
        self.design()
        self.tasks.register('CLI','UNBOUND','development','synthetic','unbound target',
            [{'id':'C','required':True,'text':'test'}],['original.md'],['D'],work_type='HARNESS_IMPROVEMENT',execution_scope='documentation')
        with self.assertRaisesRegex(ValueError,'same explicit'):
            self.tasks.handoff('D','UNBOUND')

    def test_trial_only_derived_mapping_is_explicit_and_product_cannot_reuse_it(self):
        path = self.root / 'requirement-lineage.json'
        contract = json.loads(path.read_text())
        original = {'validation':'exercise explicit UI applicability contract'}
        contract['requirements'][0]['expected'] = original
        contract['decisions'] = [{'delta_id':'REQ-CLI:DESIGN-CLI','status':'TRIAL_ONLY','reason':'CLI is a derived trial case, not original product scope','expected':original,'actual':contract['derived_items'][0]['expected']}]
        path.write_text(json.dumps(contract))
        self.register('D','design',applicable=True)
        self.assertIsNotNone(validate(self.tasks,self.tasks.read()['tasks']['D']))
        self.tasks.register('CLI','PRODUCT','design','test','test',[{'id':'C','required':True,'text':'test'}],['original.md'],work_type='PRODUCT')
        with self.assertRaisesRegex(ValueError,'PRODUCT'):
            self.roles.setup('PRODUCT','another',ui_applicability='ui.json')
        contract['decisions'] = []
        path.write_text(json.dumps(contract))
        with self.assertRaises(ValueError): validate(self.tasks,self.tasks.read()['tasks']['D'])

    def test_synthetic_process_events_are_not_model_authority(self):
        self.process_inspection.stop()
        from harness.ui_applicability import _independent_process
        path = self.root / '.harness/logs/events.jsonl'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(json.dumps({'event_type':'role_process','agent_run_id':'fake','observed':e}) for e in [
            {'process_state':'role_process_started','independent_model_spawned':True,'synthetic_fixture':True},
            {'process_state':'role_process_finished','exit_code':0}])+'\n')
        self.assertFalse(_independent_process(self.root,'fake'))

    def test_product_exact_mapping_still_requires_native_human_authorization(self):
        path = self.root / 'requirement-lineage.json'
        contract = json.loads(path.read_text())
        contract['scope'] = 'PRODUCT'
        path.write_text(json.dumps(contract))
        self.tasks.register('CLI','PRODUCT','design','test','test',[{'id':'C','required':True,'text':'test'}],['original.md'],work_type='PRODUCT')
        with self.assertRaisesRegex(ValueError,'approval'):
            self.roles.setup('PRODUCT','feature',ui_applicability='ui.json')

    def test_stage_domain_and_orchestrator_freeze_include_nonvisual_contract(self):
        from harness.stage_readiness import DOMAINS, contract_hash
        from harness.orchestrator import _task_contract
        stages = {}
        for stage,role,tid in [('planning','planning','P'),('design','design','D'),('development_plan','development','DEV')]:
            domains = ('interfaces','inputs_outputs','errors') if stage == 'design' else DOMAINS[stage]
            checks = {k:stage+'-'+k for k in domains}
            self.tasks.register('STAGED',tid,role,'test','test',[{'id':v,'required':True,'text':k} for k,v in checks.items()],['original.md'],work_type='HARNESS_IMPROVEMENT',execution_scope='documentation')
            self.roles.setup(tid,'staged',ui_applicability='ui.json' if stage != 'planning' else None)
            stages[stage] = {'task_id':tid,'checks':checks}
        self.tasks.configure_stage_workflow('STAGED',stages)
        task = self.tasks.read()['tasks']['D']
        frozen = _task_contract(task)
        before = contract_hash(task,stages['design'])
        task['role_contract']['ui_applicability']['value']['reason'] = 'changed scope'
        self.assertNotEqual(frozen,_task_contract(task))
        self.assertNotEqual(before,contract_hash(task,stages['design']))

    def test_legacy_visual_false_is_not_nonvisual_authority(self):
        self.tasks.register('LEGACY','D','design','legacy','document only',
            [{'id':'C','required':True,'text':'test'}],['original.md'],visual_required=False,work_type='HARNESS_IMPROVEMENT',execution_scope='documentation')
        self.tasks.ready('D')
        run = self.tasks.begin('D','design')
        (self.root / 'design.md').write_text('Legacy document without a UI applicability contract')
        self.tasks.submit('D',run['agent_run_id'],['design.md'],'legacy fixture',
            {'specification':'COMPLETE','mockup':'NOT_PRODUCED','visual_review':'NOT_RUN'})
        self.review('D')
        self.tasks.register('LEGACY','DEV','development','legacy','unbound',
            [{'id':'C','required':True,'text':'test'}],['original.md'],['D'],work_type='HARNESS_IMPROVEMENT',execution_scope='documentation')
        with self.assertRaisesRegex(ValueError,'document-only'):
            self.tasks.handoff('D','DEV')


if __name__ == '__main__':
    unittest.main()
