import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from harness.acceptance_contract import review_gate


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.n=0
        def valid(a):
            return isinstance(a,dict) and (self.root/a.get('snapshot','missing')).is_file() and hashlib.sha256((self.root/a['snapshot']).read_bytes()).hexdigest()==a.get('snapshot_sha256')
        self.manager=SimpleNamespace(root=self.root,_valid_artifact=valid)
        self.source=self.artifact('user-decision.txt','Explicit Compose Android/iOS and Ktor decision')
        self.design=self.artifact('design.html','approved confirmation state')
        self.capture=self.artifact('capture.txt','synthetic state capture')
        self.contract={'schema_version':1,'agreements':[{'id':'STACK','criterion_id':'AC','authority':'USER_DECISION','decision_basis':'original user decision','expected':'Compose Android/iOS + Ktor','source':self.source}], 'state_comparisons':[{'id':'EXIT','criterion_id':'AC','screen':'editor','state':'unsaved-exit-confirmation','platform':'Android','expected':'show discard confirmation','approved_design':self.design}]}
        self.task={'inputs':[],'outputs':[],'criteria':[{'id':'AC','required':True}]}

    def artifact(self,name,text):
        self.n+=1;p=self.root/str(self.n);p.write_text(text);h=hashlib.sha256(p.read_bytes()).hexdigest();return {'path':name,'snapshot':p.name,'sha256':h,'snapshot_sha256':h}

    def prepare(self,contract=None):
        c=self.artifact('acceptance-contract.json',json.dumps(contract or self.contract));self.task['inputs']=[c]
        report={'tested_outputs':{},'acceptance_contract_sha256':c['sha256'],'acceptance_checks':{'STACK':{'result':'PASS','observations':'actual imports match approved target','method':'AGENT_REVIEW','evidence':[self.capture]},'EXIT':{'result':'PASS','observations':'confirmation compared against approved state','method':'AGENT_REVIEW','evidence':[self.capture],'screen':'editor','state':'unsaved-exit-confirmation','platform':'Android','approved_design_sha256':self.design['sha256']}}}
        return report

    def result(self,report):
        return [{'criterion_id':'AC','result':'PASS','evidence':self.artifact('evidence.json',json.dumps(report))}]

    def test_functional_pass_rejected_without_comparison(self):
        report=self.prepare();report.pop('acceptance_checks')
        with self.assertRaises(ValueError):review_gate(self.manager,self.task,self.result(report))

    def test_exact_state_comparison_accepted(self):
        review_gate(self.manager,self.task,self.result(self.prepare()))

    def test_different_platform_or_baseline_rejected(self):
        for key,value in [('platform','iOS'),('approved_design_sha256','new-design')]:
            report=self.prepare();report['acceptance_checks']['EXIT'][key]=value
            with self.assertRaises(ValueError):review_gate(self.manager,self.task,self.result(report))

    def test_delegation_cannot_override_explicit_agreement(self):
        c=copy.deepcopy(self.contract);c['agreements'][0].update(authority='EXPLICIT_DELEGATION',changes_explicit_agreement=True)
        with self.assertRaises(ValueError):review_gate(self.manager,self.task,self.result(self.prepare(c)))

    def test_old_pass_not_recertified_or_mutated(self):
        t=copy.deepcopy(self.task);review_gate(self.manager,self.task,[]);self.assertEqual(t,self.task)

    def test_changed_contract_cannot_inherit_pass(self):
        report=self.prepare();report['acceptance_contract_sha256']='old'
        with self.assertRaises(ValueError):review_gate(self.manager,self.task,self.result(report))

if __name__=='__main__':unittest.main()
