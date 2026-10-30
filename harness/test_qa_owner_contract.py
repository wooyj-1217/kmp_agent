"""Synthetic model metadata only: owner/QA contract bridge regression tests.

These tests never invoke a model or claim real native execution. A fake runtime
exercises the production QA/receipt/acceptance paths in disposable directories.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.tasks import Tasks
from harness.qa import QA
from harness.execution_plan import attach_existing
from harness.test_verification_procedure import example
from harness.verification import artifact_status


class OwnerContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        (self.root/'input.md').write_text('Synthetic original request: include values A and B')
        (self.root/'output.md').write_text('draft')
        (self.root/'procedure.json').write_text(json.dumps(example()))
        (self.root/'environment.json').write_text('{"fixture":"synthetic owner bridge; no real model"}')
        self.m=Tasks(self.root,'synthetic-owner-contract')
        self.owner_criteria=[{'id':x,'required':True,'text':'Synthetic observable '+x} for x in ('A','B')]
        self.m.register('F','OWNER','planning','Synthetic owner','contract fixture',self.owner_criteria,['input.md'],execution_scope='documentation')
        self.contract('OWNER',['A','B'],['output.md'])
        self.m.configure_collection('OWNER',shared_resources=[])
        attach_existing(self.m,['OWNER'],'IMPLEMENT','delivery_with_qa','Synthetic owner contract flow','input.md','test fixture registration before work')
        self.m.ready('OWNER');run=self.m.begin('OWNER','planning',actor_id='synthetic-builder')
        (self.root/'output.md').write_text('implemented A and B')
        self.m.submit('OWNER',run['agent_run_id'],['output.md'],'synthetic author output, not quality PASS')
        self.qa=QA(self.root,self.m.run_id)

    def contract(self,tid,ids,writes,method='synthetic journey'):
        self.m.configure_verification(tid,procedure='procedure.json',environment='environment.json',
            criteria=[{'id':cid,'platforms':['web'],'method':method,'evidence_required':True,'kind':'execution'} for cid in ids],
            writable_paths=writes,forbidden_paths=[],integrator='synthetic-main',goal='Fixture contract acceptance')

    def execute_qa(self,links=None,method='synthetic journey',native_metadata=True):
        if links is None:links={'A':['QA-A'],'B':['QA-B']}
        self.qa.configure('QA','planning','OWNER',['input.md'],
            [{'id':'QA-'+x,'description':'Synthetic observation '+x,'required':True} for x in ('A','B')],
            repair_task_id='OWNER',repair_criteria=links,executable='never-invoked-synthetic-runtime',timeout=5)
        self.contract('QA',['QA-A','QA-B'],['.harness'],method)
        self.m.configure_collection('QA',shared_resources=[])
        def rows(workspace,packet):
            result=[]
            for name in ('A','B'):
                path='qa-tools/proof-'+name+'.txt'
                (workspace/path).write_text('Synthetic fixture observation '+name+'; not model evidence')
                result.append({'criterion_id':'QA-'+name,'result':'PASS','observation':'Synthetic '+name,'evidence':path,
                    'platform_results':[{'platform':'web','result':'PASS','environment':'synthetic fixture, no browser/model',
                        'command_or_steps':'synthetic fixture compares '+name,'expected':'present '+name,'observed':'present '+name,
                        'doctor':'PASS','drive':'PASS','cleanup':'PASS','evidence':[path]}]})
            return {'criteria':result,'findings':[],'recommendation':'PASS','summary':'synthetic metadata test','reviewed_issue_ids':[]}
        def fake_runtime(*args,**kwargs):
            return {'returncode':0,'pid':424242,'thread_ids':['synthetic-native-fixture'],
                    'result':rows(args[3],args[4]),'usage_status':'UNKNOWN'}
        if native_metadata:
            with patch('harness.delegation_runtime.run_codex',side_effect=fake_runtime):
                self.attempt=self.qa.execute('QA')
        else:self.attempt=self.qa.execute('QA',rows)
        self.assertEqual(self.attempt['outcome'],'PASS',self.attempt)
        return self.attempt

    def owner(self):return self.m.read()['tasks']['OWNER']

    def test_complete_mapping_binds_each_source_receipt_and_preserves_evidence(self):
        self.execute_qa();accepted=self.qa.accept_owner('QA')
        self.assertEqual(accepted['outcome'],'DONE')
        owner=self.owner();self.assertEqual(owner['state'],'DONE')
        rows=owner['reviews'][-1]['results'];self.assertEqual({r['criterion_id'] for r in rows},{'A','B'})
        for row in rows:
            proof=json.loads((self.root/row['evidence']['snapshot']).read_text())
            self.assertEqual(proof['source_qa']['criterion_id'],'QA-'+row['criterion_id'])
            source=json.loads((self.root/proof['source_qa']['receipt']['snapshot']).read_text())
            self.assertEqual(proof['platform_results'],source['platform_results'])
            for ref in proof['platform_results'][0]['evidence']:
                self.assertEqual(artifact_status(self.root,ref)['state'],'VALID')

    def test_synthetic_local_worker_is_not_actual_model_provenance(self):
        self.execute_qa(native_metadata=False)
        with self.assertRaisesRegex(ValueError,'actual independent model provenance'):
            self.qa.accept_owner('QA')
        self.assertEqual(self.owner()['state'],'IN_REVIEW')

    def test_changed_source_cannot_inherit_old_qa_pass(self):
        self.execute_qa();(self.root/'output.md').write_text('changed observable A only')
        with self.assertRaisesRegex(ValueError,'changed|current'):
            self.qa.accept_owner('QA')
        self.assertNotEqual(self.owner()['state'],'DONE')

    def test_partial_criterion_mapping_cannot_complete_owner(self):
        self.execute_qa(links={'A':['QA-A']})
        with self.assertRaisesRegex(ValueError,'criterion'):
            self.qa.accept_owner('QA')
        self.assertNotEqual(self.owner()['state'],'DONE')

    def test_procedure_method_mismatch_rejected(self):
        self.execute_qa(method='different synthetic journey')
        with self.assertRaisesRegex(ValueError,'method differs'):
            self.qa.accept_owner('QA')
        self.assertNotEqual(self.owner()['state'],'DONE')

    def test_accepted_owner_cannot_replay_attempt(self):
        self.execute_qa();self.qa.accept_owner('QA')
        before=copy.deepcopy(self.owner()['reviews'])
        with self.assertRaisesRegex(ValueError,'submitted owner'):
            self.qa.accept_owner('QA')
        self.assertEqual(self.owner()['reviews'],before)

    def test_mapping_change_between_precheck_and_begin_is_rejected_atomically(self):
        self.execute_qa();original=self.qa.tasks.begin
        def changed(*args,**kwargs):
            if args[0]=='OWNER':
                self.m._mutate('synthetic_mapping_race',lambda state:state['tasks']['QA']['qa_config']['repair_criteria'].update(A=['QA-B']),'QA')
            return original(*args,**kwargs)
        with patch.object(self.qa.tasks,'begin',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'QA|criterion|mapping'):
                self.qa.accept_owner('QA')
        self.assert_terminal_rejection()

    def test_owner_observations_cannot_differ_from_bound_source_receipt(self):
        self.execute_qa();original=self.qa.tasks.review
        def altered(tid,rid,rows,*args,**kwargs):
            if tid=='OWNER':
                path=self.root/rows[0]['evidence'];payload=json.loads(path.read_text())
                payload['platform_results'][0]['observed']='invented observation absent from QA source'
                path.write_text(json.dumps(payload))
            return original(tid,rid,rows,*args,**kwargs)
        with patch.object(self.qa.tasks,'review',side_effect=altered):
            with self.assertRaisesRegex(ValueError,'QA|source|receipt|observations'):
                self.qa.accept_owner('QA')
        self.assert_terminal_rejection()

    def assert_terminal_rejection(self):
        owner=self.owner()
        self.assertEqual(owner['state'],'BLOCKED')
        reviews=[r for r in owner['executions'] if r['kind']=='review']
        self.assertTrue(reviews)
        self.assertTrue(all(r.get('ended_at') for r in reviews))
        self.assertEqual(owner['qa_failures'][-1]['phase'],'owner_review')


if __name__=='__main__':unittest.main()
