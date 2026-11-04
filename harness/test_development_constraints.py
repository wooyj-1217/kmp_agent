"""Synthetic architecture regressions, never evidence of an actual product build."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from harness.test_project_contract import ProjectContract
from harness.requirement_lineage import file_ref
from harness import development_constraints as guard


class DevelopmentConstraints(unittest.TestCase):
    settings = ProjectContract.settings
    def setUp(self):
        ProjectContract.setUp(self)
        self.policy = {
            'settings': {'implementation_targets':['android','web'], 'ui_technology':'Compose Multiplatform',
                         'database':{'engine':'PostgreSQL','location':'server','role':'primary'},
                         'server_mode':'new','code_ownership':'shared client and server'},
            'ui_sharing':'shared','ui_owners':{'shared':'kmp'},
            'platform_entrypoints':{'android':['android/Main.kt'],'web':['web/Main.kt']},
            'target_commands':{'android':[['rtk','proxy','python3','-c','print("synthetic android")']],
                               'web':[['rtk','proxy','python3','-c','print("synthetic web")']]},
            'source_rules':[{'glob':'dependencies.txt','required_patterns':['postgresql'], 'forbidden_patterns':['sqlite']},
                            {'glob':'shared/*.kt','required_patterns':['@Composable'], 'forbidden_patterns':[]},
                            {'glob':'web/*.kt','required_patterns':['SharedApp'], 'forbidden_patterns':['@Composable']}]}
        for name, content in {'original.md':'Synthetic user request: shared UI, Android and web, server database.',
                              'approved.md':'Synthetic approval fixture; not a real user approval.',
                              'derived.md':'Synthetic implementation plan.', 'dependencies.txt':'postgresql',
                              'shared/App.kt':'@Composable fun SharedApp() {}',
                              'android/Main.kt':'SharedApp()', 'web/Main.kt':'SharedApp()'}.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
        self.lineage={'schema_version':1,'scope':'PRODUCT','purpose':'synthetic structural regression',
                      'sources':[dict(id=i,kind=k,anchor='fixture',**file_ref(self.root,p)) for i,k,p in
                                 [('U','USER_ORIGINAL','original.md'),('A','APPROVED_REQUIREMENTS','approved.md'),('D','AGENT_DERIVED','derived.md')]],
                      'requirements':[{'id':'TECH','source':'A','anchor':'fixture','expected':{guard.KEY:self.policy}}],
                      'derived_items':[{'id':'PLAN','source':'D','anchor':'fixture','source_ids':['TECH'],'expected':{guard.KEY:copy.deepcopy(self.policy)}}]}
        self.lineage['sources'][1]['approval']={'source':'U','anchor':'fixture','approved_sha256':self.lineage['sources'][1]['sha256']}
        self.save_lineage()

    def save_lineage(self):
        (self.root/'requirement-lineage.json').write_text(json.dumps(self.lineage))

    def configured(self):
        data=self.settings('new')
        for key,value in self.policy['settings'].items():data[key]['value']=value
        self.t.register('FIXTURE','DEV','development','synthetic guard','not product acceptance',
                        [{'id':'C','required':True,'text':'synthetic check'}],['requirements.md'])
        (self.root/'settings.json').write_text(json.dumps(data))
        self.t.configure_stage('DEV','ui','settings.json')
        return self.t.read()['tasks']['DEV']

    def test_product_without_source_cannot_start_even_explicit_tracking(self):
        (self.root/'requirement-lineage.json').unlink()
        self.t.register('F','P','development','product','fixture',[{'id':'C','required':True,'text':'C'}],
                        ['requirements.md'],work_type='PRODUCT')
        self.t.configure_development('P',{'planning':'requirements.md'},['shared'])
        self.assertTrue(self.t.read()['tasks']['P'].get('development_tracking'))
        with self.assertRaisesRegex(ValueError,'authoritative'):
            guard.gate(self.t,self.t.read()['tasks']['P'])

    def test_self_confirmed_database_and_omitted_web_rejected(self):
        self.configured()
        for key,value in [('database',{'engine':'SQLite','location':'local','role':'primary'}),('implementation_targets',['android'])]:
            data=json.loads((self.root/'settings.json').read_text());data[key]['value']=value
            (self.root/'changed.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'differs'):
                self.t.configure_stage('DEV','ui','changed.json')

    def test_approval_and_current_source_are_required(self):
        task=self.configured()
        (self.root/'approved.md').write_text('changed approval')
        with self.assertRaisesRegex(ValueError,'source changed'):guard.load(self.t,task)
        # A fresh registry hash alone does not manufacture renewed approval.
        self.lineage['sources'][1]['sha256']=file_ref(self.root,'approved.md')['sha256'];self.save_lineage()
        with self.assertRaises(ValueError):self.t.configure_stage('DEV','ui','settings.json')

    def test_missing_web_proof_and_platform_ui_owner_are_invalid(self):
        for field in ('platform_entrypoints','target_commands'):
            policy=copy.deepcopy(self.policy);del policy[field]['web']
            with self.assertRaisesRegex(ValueError,'every approved target'):guard.validate(policy)
        policy=copy.deepcopy(self.policy);policy['ui_owners']={'web':'web'}
        with self.assertRaisesRegex(ValueError,'shared UI'):guard.validate(policy)

    def test_real_source_checks_reject_sqlite_split_ui_and_missing_web(self):
        task=self.configured();guard.check_code(self.t,task)
        for name,wrong in [('dependencies.txt','sqlite'),('web/Main.kt','@Composable fun WebOnly() {}')]:
            path=self.root/name;before=path.read_text();path.write_text(wrong)
            with self.assertRaisesRegex(ValueError,'forbidden'):guard.check_code(self.t,task,complete=False)
            path.write_text(before)
        (self.root/'web/Main.kt').unlink()
        with self.assertRaisesRegex(ValueError,'missing'):guard.check_code(self.t,task)

    def test_plan_cannot_drop_web_command_or_change_ui_ownership(self):
        task=self.configured();commands=[c for rows in self.policy['target_commands'].values() for c in rows]
        guard.check_plan(self.t,task,{'ui_owners':self.policy['ui_owners']},[],commands)
        with self.assertRaisesRegex(ValueError,'command'):guard.check_plan(self.t,task,{'ui_owners':self.policy['ui_owners']},[],commands[:1])
        with self.assertRaisesRegex(ValueError,'UI'):guard.check_plan(self.t,task,{'ui_owners':{'web':'web'}},[],commands)

    def test_trial_decision_cannot_authorize_product(self):
        task=self.configured();task['work_type']='PRODUCT'
        self.lineage.update(scope='HARNESS_TRIAL',scope_authorization='U',product_pass_claim=False);self.save_lineage()
        with self.assertRaisesRegex(ValueError,'trial'):guard.bind(self.t,task)

    def test_explicitly_approved_local_cache_is_allowed(self):
        self.policy['settings']['database']={'engine':'SQLite','location':'client','role':'cache'}
        self.policy['source_rules'][0].update(required_patterns=['sqlite'],forbidden_patterns=[])
        self.lineage['derived_items'][0]['expected'][guard.KEY]=copy.deepcopy(self.policy)
        self.save_lineage();(self.root/'dependencies.txt').write_text('sqlite')
        guard.check_code(self.t,self.configured())

    def test_forged_or_stale_target_receipts_rejected(self):
        task=self.configured();task['outputs']=[]
        task['executions']=[{'kind':'work','ended_at':'synthetic','outputs':[],'agent_run_id':'WORK','run_id':'RUN'}]
        events=[];rows=[]
        for target,commands in self.policy['target_commands'].items():
            argv=commands[0];call=target
            common={'task_id':'DEV','agent_run_id':'WORK','run_id':'RUN'}
            events.extend([dict(common,event_type='command_started',sequence=len(events),observed={'call_id':call,'argv_sha256':hashlib.sha256(json.dumps(argv).encode()).hexdigest()}),
                           dict(common,event_type='command_finished',sequence=len(events)+1,observed={'call_id':call,'returncode':0,'stdout_sha256':'stdout','stderr_sha256':'stderr'})])
            rows.append({'target':target,'result':'PASS','commands':[{'argv':argv,'exit_code':0,'call_id':call,'stdout_sha256':'stdout','stderr_sha256':'stderr'}]})
        report={'constraints_sha256':task['stage_contract'][guard.KEY]['sha256'],'constraint_review_run_id':'WORK','constraint_target_results':rows}
        for event in events:event['observed'].update(cwd='.',code_state_sha256='CURRENT')
        with patch('harness.development_tracking.capture',return_value={'state_sha256':'CURRENT'}), patch.object(self.t.logger,'read',return_value=events):
            guard.review_gate(self.t,task,report)
            forged=copy.deepcopy(report);forged['constraint_target_results'][1]['commands'][0]['stdout_sha256']='forged'
            with self.assertRaisesRegex(ValueError,'differs'):guard.review_gate(self.t,task,forged)
            stale=copy.deepcopy(report);stale['constraint_review_run_id']='OLD'
            with self.assertRaisesRegex(ValueError,'submitted work'):guard.review_gate(self.t,task,stale)
            events[0]['observed']['cwd']='another-project'
            with self.assertRaisesRegex(ValueError,'submitted code'):guard.review_gate(self.t,task,report)
            events[0]['observed'].update(cwd='.',code_state_sha256='OLD')
            with self.assertRaisesRegex(ValueError,'submitted code'):guard.review_gate(self.t,task,report)
            events[0]['observed']['code_state_sha256']='CURRENT'
        with patch('harness.development_tracking.capture',return_value={'state_sha256':'CURRENT'}), patch.object(self.t.logger,'read',return_value=events[:-1]):
            with self.assertRaisesRegex(ValueError,'start/finish'):guard.review_gate(self.t,task,report)

    def test_gitignored_architecture_source_cannot_escape_fingerprint(self):
        task=self.configured()
        self.t.configure_development('DEV',{'planning':'requirements.md'},['dependencies.txt','shared','android','web'])
        task=self.t.read()['tasks']['DEV']
        guard.check_code(self.t,task)
        with (self.root/'.gitignore').open('a') as stream:stream.write('dependencies.txt\n')
        with self.assertRaisesRegex(ValueError,'fingerprint'):guard.check_code(self.t,task)
        task['development_tracking'].update(code_paths=[],scope_policy='full_repository')
        with self.assertRaisesRegex(ValueError,'fingerprint'):guard.check_code(self.t,task)
