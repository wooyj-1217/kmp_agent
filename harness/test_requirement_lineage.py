import json
from pathlib import Path
import tempfile
import unittest
from harness.requirement_lineage import compare, file_ref, configure_qa, require_review
from harness.tasks import Tasks
from harness.qa import QA
from harness.delegation import Development

class LineageTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        for name in ['user.md','approved.md','derived.md']:(self.root/name).write_text(name)
        self.c={'schema_version':1,'scope':'PRODUCT','purpose':'unchanged implementation','sources':[dict(id=i,kind=k,anchor='paragraph1',**file_ref(self.root,p)) for i,k,p in [('U','USER_ORIGINAL','user.md'),('A','APPROVED_REQUIREMENTS','approved.md'),('D','AGENT_DERIVED','derived.md')]],'requirements':[{'id':'R','source':'A','anchor':'R','expected':{'limit':12,'behavior':'retain'}}],'derived_items':[{'id':'D1','source':'D','anchor':'D1','source_ids':['R'],'expected':{'limit':12,'behavior':'retain'}}]};self.c['sources'][1]['approval']={'source':'U','anchor':'approved requirements','approved_sha256':self.c['sources'][1]['sha256']};self.save()
    def save(self):(self.root/'requirement-lineage.json').write_text(json.dumps(self.c))
    def task(self):
        m=Tasks(self.root,'lineage-test');m.register('F','TARGET','development','target','test',[{'id':'A','description':'target','required':True}],['user.md','approved.md','derived.md','requirement-lineage.json'],execution_scope='documentation');return m
    def review(self,m):
        configure_qa(self.root,'lineage-test','PRE-QA','TARGET')
        def worker(w,p):
            self.assertEqual(p['qa_stage'],'requirements');self.assertNotIn('derived.md',[r['path'] for r in p['original_requests']])
            (w/'qa-tools'/'proof.txt').write_text('Synthetic source comparison only')
            return {'criteria':[{'criterion_id':c['id'],'result':'PASS','observation':'fixture compared','evidence':'qa-tools/proof.txt'} for c in p['criteria']],'findings':[],'recommendation':'PASS','summary':'synthetic fixture','reviewed_issue_ids':[]}
        return QA(self.root,'lineage-test').execute('PRE-QA',worker)
    def test_approved_label_without_original_authorization_is_unknown(self):
        del self.c['sources'][1]['approval'];self.save()
        result=compare(self.root);self.assertFalse(result['structurally_ready']);self.assertEqual(result['authority_issues'][0]['status'],'APPROVAL_UNCONFIRMED')
    def test_conflicting_source_kinds_rejected(self):
        self.c['sources'][2].update(path='user.md',sha256=file_ref(self.root,'user.md')['sha256']);self.save()
        with self.assertRaisesRegex(ValueError,'both agent-derived'):compare(self.root)
    def test_developer_packet_carries_original_derived_scope(self):
        from types import SimpleNamespace
        m=self.task();t=m.read()['tasks']['TARGET'];t['development_tracking']={'baselines':{}}
        dev=Development(self.root,'lineage-test');dev.tasks=SimpleNamespace(read=lambda:{'tasks':{'TARGET':t}})
        spec={'task_id':'TARGET','area':'web','goal':'fixture','requirement_ids':['R'],'acceptance_ids':['A'],'allowed_paths':['web'],'out_of_scope':[],'verification_commands':[]}
        packet=dev.packet({'task_id':'PARENT','development_delegation':{'shared_owners':{}}},spec,{'agent_run_id':'synthetic','baseline':{},'inputs':[],'code_state_start':{}},self.root)
        self.assertEqual(packet['requirement_lineage']['requirements'][0]['id'],'R')
        self.assertEqual(packet['requirement_lineage']['derived_items'][0]['source_ids'],['R'])
        self.assertEqual(packet['requirement_lineage']['product_requirements_pass'],'NOT_ESTABLISHED')
    def test_trial_integration_report_cannot_claim_product_pass(self):
        self.c.update(scope='HARNESS_TRIAL',scope_authorization='U',product_pass_claim=False);self.save()
        dev=Development(self.root,'lineage-test');out=self.root/'proof';out.mkdir()
        relative=dev.report(out,'integration.json',{'result':'PASS'})
        result=json.loads((self.root/relative).read_text())
        self.assertEqual(result['development_integration_result'],'PASS')
        self.assertEqual(result['claim_scope'],'HARNESS_TRIAL')
        self.assertEqual(result['product_requirements_fulfillment'],'NOT_ESTABLISHED')
        self.assertEqual(result['execution_path_validation'],'NOT_ESTABLISHED')
    def test_equal_still_requires_semantic_review(self):
        r=compare(self.root);self.assertTrue(r['structurally_ready']);self.assertEqual(r['semantic_review'],'REQUIRED')
    def test_changed_value_and_behavior(self):
        for key,value in [('limit',2),('behavior','discard')]:
            self.c['derived_items'][0]['expected'][key]=value;self.save();self.assertFalse(compare(self.root)['structurally_ready'])
    def test_omitted_added_excluded(self):
        self.c['derived_items'][0]['source_ids']=[];self.save();self.assertEqual({d['kind'] for d in compare(self.root)['deltas']},{'OMITTED','ADDED'})
        self.c['derived_items'][0].update(source_ids=['R'],excluded=True);self.save();self.assertEqual(compare(self.root)['deltas'][0]['kind'],'EXCLUDED')
    def test_all_original_items_omitted(self):
        self.c['derived_items']=[];self.save();r=compare(self.root)
        self.assertEqual(r['deltas'][0]['kind'],'OMITTED');self.assertFalse(r['structurally_ready'])
    def test_agent_cannot_authorize(self):
        self.c['requirements'][0]['source']='D';self.save()
        with self.assertRaisesRegex(ValueError,'authoritative'):compare(self.root)
    def test_unknown_link(self):
        self.c['derived_items'][0]['source_ids']=['UNKNOWN'];self.save()
        with self.assertRaises(ValueError):compare(self.root)
    def test_exact_approval_and_stale_approval(self):
        self.c['derived_items'][0]['expected']={'limit':3};self.c['decisions']=[{'delta_id':'R:D1','status':'APPROVED','source':'D','anchor':'decision','expected':self.c['requirements'][0]['expected'],'actual':{'limit':3}}];self.save();self.assertFalse(compare(self.root)['structurally_ready'])
        self.c['decisions'][0]['source']='U';self.save();self.assertTrue(compare(self.root)['structurally_ready'])
        self.c['derived_items'][0]['expected']={'limit':4};self.save();self.assertFalse(compare(self.root)['structurally_ready'])
    def test_trial_does_not_inherit_product_pass(self):
        self.c.update(scope='HARNESS_TRIAL',scope_authorization='U',product_pass_claim=False);self.c['derived_items'][0]['expected']={'limit':3};self.c['decisions']=[{'delta_id':'R:D1','status':'TRIAL_ONLY','reason':'execution-path test; product pending','expected':self.c['requirements'][0]['expected'],'actual':{'limit':3}}];self.save();r=compare(self.root);self.assertTrue(r['structurally_ready']);self.assertEqual(r['product_requirements_pass'],'NOT_ESTABLISHED')
        self.c['product_pass_claim']=True;self.save()
        with self.assertRaises(ValueError):compare(self.root)
    def test_changed_source(self):
        (self.root/'approved.md').write_text('new')
        with self.assertRaisesRegex(ValueError,'source changed'):compare(self.root)
    def test_refreshed_baseline_hash_does_not_refresh_approval(self):
        (self.root/'approved.md').write_text('new baseline')
        self.c['sources'][1]['sha256']=file_ref(self.root,'approved.md')['sha256'];self.save()
        self.assertFalse(compare(self.root)['structurally_ready'])
    def test_missing_contract_blocks_spawn(self):
        m=self.task();(self.root/'requirement-lineage.json').unlink()
        with self.assertRaisesRegex(ValueError,'lineage missing'):Development(self.root,'lineage-test').execute('TARGET')
        self.assertEqual(m.read()['tasks']['TARGET']['executions'],[])
    def test_qa_rejects_derived_original(self):
        self.task()
        with self.assertRaisesRegex(ValueError,'agent-derived'):QA(self.root,'lineage-test').configure('BAD','planning','TARGET',['derived.md'],[{'id':'Q','required':True,'description':'test'}])
    def test_mock_pass_not_independent(self):
        m=self.task();r=self.review(m);self.assertEqual(r['outcome'],'PASS');require_review(m,m.read()['tasks']['TARGET'],allow_mock=True)
        with self.assertRaisesRegex(ValueError,'independent'):require_review(m,m.read()['tasks']['TARGET'])
        report=json.loads((self.root/r['report']['path']).read_text());self.assertEqual(report['product_requirements_fulfillment'],'NOT_ESTABLISHED')
    def test_missing_and_stale_review(self):
        m=self.task()
        with self.assertRaisesRegex(ValueError,'independent'):require_review(m,m.read()['tasks']['TARGET'])
        self.review(m);self.c['purpose']='new purpose';self.save()
        with self.assertRaises(ValueError):require_review(m,m.read()['tasks']['TARGET'],allow_mock=True)
    def test_implementation_change_does_not_invalidate_source_alignment(self):
        m=self.task();self.review(m);(self.root/'implementation.txt').write_text('new code')
        require_review(m,m.read()['tasks']['TARGET'],allow_mock=True)
    def test_claimed_independent_mode_without_process_evidence_rejected(self):
        m=self.task();self.review(m)
        def change(state):
            qa=state['tasks']['PRE-QA']
            for run in qa['executions']:
                if run['kind']=='work':run['execution_mode']='independent_process'
        m._mutate('synthetic_fixture',change,task_id='PRE-QA')
        with self.assertRaisesRegex(ValueError,'independent'):require_review(m,m.read()['tasks']['TARGET'])
    def test_unapproved_change_blocks_qa(self):
        self.c['derived_items'][0]['expected']['limit']=3;self.save();m=self.task();self.assertEqual(self.review(m)['outcome'],'BLOCKED')

if __name__=='__main__':unittest.main()
