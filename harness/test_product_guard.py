"""Synthetic installed-target regressions; no product data or actual hook-trust claim."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness import projects
from harness import product_guard as guard


class InstalledProductGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(['rtk','proxy','git','init','-q'],cwd=self.root,check=True,capture_output=True)
        (self.root/'.kmp-agent').mkdir()
        (self.root/'.kmp-agent/installation.json').write_text('{}')

    def tool(self, name='Bash', command='python3 -c "print(1)"', **extra):
        return guard.evaluate(self.root, dict(hook_event_name='PreToolUse', session_id='synthetic-session',
                              cwd=str(self.root), tool_name=name, tool_input={'command':command}, **extra))

    def denied(self, result):
        self.assertEqual('deny',result['hookSpecificOutput']['permissionDecision'])

    def ledger(self, tasks=None):
        value = {'tasks':tasks or {'CODE':{'task_id':'CODE','role':'development','work_type':'PRODUCT','state':'TODO','executions':[]}},
                 'execution_policy_bindings':{'RUN':{'root_session_id':'synthetic-session'}},
                 'execution_plans':{'RUN':{'task_ids':['CODE']}}}
        path = self.root/'.harness/tasks/tasks.yaml';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value));return value

    def test_installed_target_has_tool_and_stop_guards(self):
        desired, _, _ = projects.plan(self.root, [])
        hooks = json.loads(desired[self.root/'.codex/hooks.json'])['hooks']
        self.assertIn('PreToolUse',hooks)
        for event in ('PreToolUse','Stop'):
            handlers = [h for g in hooks[event] for h in g['hooks']]
            self.assertEqual(1,sum(h['command'].endswith(' guard') for h in handlers))

    def test_unregistered_source_edit_and_interpreter_are_denied_before_side_effect(self):
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: server/app.py\n+print(1)\n*** End Patch'))
        self.denied(self.tool())
        self.assertFalse((self.root/'server/app.py').exists())

    def test_todo_plan_is_not_a_work_authorization_or_completion(self):
        self.ledger()
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: shared/App.kt\n+fun App() {}\n*** End Patch'))
        result=guard.evaluate(self.root,dict(hook_event_name='Stop',session_id='synthetic-session',cwd=str(self.root)))
        self.assertEqual({},result)
        self.assertEqual({},self.tool(command='git push --no-follow-tags origin feature'))
        self.assertEqual({},self.tool(command='git commit -m feature'))
        with self.assertRaisesRegex(ValueError,'not officially DONE'):
            guard.complete(self.root,guard._state(self.root),{'RUN'})

    def test_readonly_and_planning_are_available_before_configuration(self):
        for command in ('rtk proxy git status --short','rtk proxy cat README.md','rtk proxy rg Compose docs'):
            self.assertEqual({},self.tool(command=command))
        self.assertEqual({},self.tool('apply_patch','*** Begin Patch\n*** Add File: docs/guard-inputs/settings.json\n+{}\n*** End Patch'))
        self.assertEqual({},self.tool(command='rtk proxy python3 .kmp-agent/agent.py task --operation register --data docs/task.json'))

    def test_readonly_impersonation_shell_wrappers_and_unknown_mutators_are_denied(self):
        for command in ('./evil/cat README.md','git -c alias.diff=malicious diff','cat x; python3 x',
                        'rtk proxy python3 -c "write()"','rg --pre=evil x','git diff --output=x'):
            self.denied(self.tool(command=command))
        self.denied(self.tool('mcp__filesystem__write_file', 'anything'))

    def test_git_read_options_cannot_launch_programs_or_write_files(self):
        for command in (
                'git ls-remote --upload-pack="touch guard-bypassed" .',
                'git ls-remote -u "touch guard-bypassed" .',
                'git ls-remote -utouch .',
                'git ls-remote --upload="touch guard-bypassed" .',
                'git ls-remote "ext::touch guard-bypassed"',
                'git ls-remote custom-helper://argument',
                'git cat-file --filters HEAD:shared/App.kt',
                'git cat-file --fil HEAD:shared/App.kt',
                'git diff --out=guard-bypassed',
                'git show --ext HEAD',
                'git show --text HEAD'):
            with self.subTest(command=command):
                self.denied(self.tool(command=command))

    def test_ordinary_git_reads_and_option_like_paths_remain_available(self):
        for command in ('git ls-remote origin', 'git ls-remote https://example.invalid/repo.git',
                        'git cat-file -p HEAD', 'git diff -- --output=source.txt'):
            with self.subTest(command=command):
                self.assertEqual({}, self.tool(command=command))

    def test_denied_git_upload_pack_never_creates_marker(self):
        # Dispatch exactly as a hook-aware runner would; this executed touch on
        # the original guard even though git subsequently exited with 128.
        command = 'git ls-remote --upload-pack="touch guard-bypassed" .'
        decision = self.tool(command=command)
        if decision.get('hookSpecificOutput', {}).get('permissionDecision') != 'deny':
            subprocess.run(command, shell=True, cwd=self.root, capture_output=True)
        self.assertFalse((self.root/'guard-bypassed').exists())
        self.denied(decision)

    def test_role_worker_and_target_override_are_not_metadata(self):
        for extra in ('--worker \'["python3","evil.py"]\'', '--worker=evil', '--target /other'):
            self.denied(self.tool(command='python3 .kmp-agent/agent.py planning --task-id PLAN '+extra))
        from harness.roles import Roles
        with self.assertRaisesRegex(ValueError,'arbitrary worker'):
            Roles(self.root,'RUN').execute('missing','planning',['python3','evil.py'])

    def test_control_escape_move_and_symlink_are_denied_even_for_planning(self):
        for name in ('../outside.md','.codex/hooks.json','AGENTS.md','.harness/tasks/tasks.yaml'):
            self.denied(self.tool('apply_patch',f'*** Begin Patch\n*** Add File: {name}\n+value\n*** End Patch'))
        (self.root/'docs').symlink_to(self.root/'.kmp-agent',target_is_directory=True)
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: docs/guide.md\n+value\n*** End Patch'))

    def test_guard_errors_return_supported_deny_not_fail_open(self):
        self.ledger();(self.root/'.harness/tasks/tasks.yaml').write_text('{broken')
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: a.kt\n+x\n*** End Patch'))

    def test_docs_only_done_plan_cannot_certify_product(self):
        self.ledger({'CODE':{'task_id':'CODE','role':'planning','execution_scope':'documentation','work_type':'PRODUCT','state':'DONE','executions':[]}})
        self.assertEqual({},self.tool(command='git push --no-follow-tags origin feature'))
        with self.assertRaisesRegex(ValueError,'documentation-only'):
            guard.complete(self.root,guard._state(self.root),{'RUN'})

    def test_stop_with_no_product_plan_allows_readonly_conversation(self):
        self.assertEqual({},guard.evaluate(self.root,dict(hook_event_name='Stop',session_id='synthetic-session',cwd=str(self.root))))

    def test_malformed_pending_question_does_not_trap_stopping(self):
        state=self.ledger()
        state['required_questions']={'BROKEN':{'id':'BROKEN','status':'OPEN','affected_task_ids':['CODE']}}
        (self.root/'.harness/tasks/tasks.yaml').write_text(json.dumps(state))
        result=guard.evaluate(self.root,dict(hook_event_name='Stop',session_id='synthetic-session',cwd=str(self.root)))
        self.assertEqual({},result)

    def test_explicit_task_selection_handles_active_parent_and_child(self):
        # Selection/unit wiring test; native authorizations are deliberately not
        # claimed by the mocked gate results.
        task=lambda tid:dict(task_id=tid,work_type='PRODUCT',role='development',state='IN_PROGRESS',
            development_tracking={'code_paths':['shared']},executions=[{'kind':'work','run_id':'RUN','ended_at':None}])
        state=self.ledger({'CODE':task('CODE'),'CHILD':task('CHILD')})
        state['execution_plans']['RUN']['task_ids'].append('CHILD');state['execution_policy']={'version':1}
        with patch.object(guard.execution_policy,'gate'), patch('harness.stage_readiness.gate',return_value=None), \
                patch('harness.project_contract.gate'), patch.object(guard.development_tracking,'ensure') as ensure:
            _,selected=guard.active(self.root,state,'synthetic-session',task_id='CHILD')
            self.assertEqual('CHILD',selected['task_id'])
            self.assertEqual(selected['executions'][0],ensure.call_args.kwargs['run'])
            with self.assertRaisesRegex(ValueError,'ambiguous active tasks'):
                guard.active(self.root,state,'synthetic-session')

    def test_complete_requires_current_validation_even_for_done_task(self):
        state=self.ledger()
        task=state['tasks']['CODE'];task.update(state='DONE',executions=[{'kind':'work','run_id':'RUN','ended_at':'synthetic'}],
            reviews=[{'agent_run_id':'REVIEW'}],validation_status={'REVIEW':{'state':'RECHECK_REQUIRED'}})
        with patch.object(guard.development_constraints,'check_code'),patch.object(guard.development_tracking,'refresh'), \
                patch('harness.completion.gate') as completion:
            with self.assertRaisesRegex(ValueError,'stale'):
                guard.complete(self.root,state,{'RUN'})
            completion.assert_not_called()
            task['validation_status']['REVIEW']['state']='CURRENT'
            guard.complete(self.root,state,{'RUN'});completion.assert_called_once()

    def test_noninstalled_harness_development_remains_unaffected(self):
        (self.root/'.kmp-agent/installation.json').unlink()
        self.assertEqual({},self.tool())

    def test_finish_api_cannot_turn_an_unregistered_product_run_into_completion(self):
        from harness.logging import Logger
        logger=Logger(self.root);run=logger.start('PRODUCT','development','synthetic incomplete work')
        with self.assertRaisesRegex(ValueError,'bound native execution plan'):
            logger.checkpoint(run,'claimed completion',finish=True)
        self.assertFalse(any(e['event_type']=='run_finished' for e in logger.read()))

    def test_guard_cli_outputs_explicit_denial_for_runtime_not_a_hook_error(self):
        result=subprocess.run(['rtk','proxy','python3','-B','-m','harness.cli','--target',str(self.root),'guard'],
            input=json.dumps({'hook_event_name':'PreToolUse','cwd':str(self.root),'session_id':'synthetic-session',
                              'tool_name':'Bash','tool_input':{'command':'python3 -c "write()"'}}),
            text=True,capture_output=True,cwd=Path(__file__).resolve().parents[1],check=True)
        self.denied(json.loads(result.stdout))

    def test_installation_preserves_other_hooks_and_rejects_duplicate_guards(self):
        hook_path=self.root/'.codex/hooks.json';hook_path.parent.mkdir()
        hook_path.write_text(json.dumps({'hooks':{'Stop':[{'hooks':[{'type':'command','command':'product-owned'}]}]}}))
        desired,_,_=projects.plan(self.root,[]);hooks=json.loads(desired[hook_path])
        self.assertEqual('product-owned',hooks['hooks']['Stop'][0]['hooks'][0]['command'])
        hook_path.write_text(desired[hook_path]);desired,_,_=projects.plan(self.root,[])
        self.assertNotIn(hook_path,desired)
        hooks['hooks']['PreToolUse']*=2;hook_path.write_text(json.dumps(hooks))
        with self.assertRaisesRegex(ValueError,'duplicate product guard'):projects.plan(self.root,[])


class TechnologyPatchGuard(unittest.TestCase):
    def setUp(self):
        from harness.test_development_constraints import DevelopmentConstraints
        self.fixture=DevelopmentConstraints('test_real_source_checks_reject_sqlite_split_ui_and_missing_web')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.manager=self.fixture.t
        self.task=self.fixture.configured()
        self.task['development_tracking']={'code_paths':['shared','web','android','dependencies.txt']}
        # Unit fixture supplies the result of lifecycle validation. Separate tests above
        # exercise missing/invalid lifecycle rejection; this fixture tests source rules.
        self.active=patch.object(guard,'active',return_value=(self.manager,self.task));self.active.start();self.addCleanup(self.active.stop)

    def check(self, text):
        guard._patch(self.root,{},'synthetic-session',text)

    def test_allowed_common_ui_edit_is_previewed_without_writing(self):
        before=(self.root/'shared/App.kt').read_text()
        self.check('*** Begin Patch\n*** Update File: shared/App.kt\n@@\n-@Composable fun SharedApp() {}\n+@Composable fun SharedApp() { /* approved shared UI */ }\n*** End Patch')
        self.assertEqual(before,(self.root/'shared/App.kt').read_text())

    def test_platform_ui_and_database_switch_are_rejected_before_write(self):
        for name,text in [('web/Main.kt','@Composable fun IndependentUi() {}'),('dependencies.txt','sqlite')]:
            with self.assertRaisesRegex(ValueError,'technology'):
                self.check(f'*** Begin Patch\n*** Add File: {name}\n+{text}\n*** End Patch')

    def test_python_server_can_be_forbidden_by_product_contract(self):
        # Product-specific technology, never a global Kotlin default.
        policy=self.fixture.policy
        policy['source_rules'].append({'glob':'**/*.py','required_patterns':[], 'forbidden_patterns':['(?s).']})
        self.fixture.lineage['derived_items'][0]['expected'][guard.development_constraints.KEY]=json.loads(json.dumps(policy))
        self.fixture.save_lineage()
        self.task=self.manager.configure_stage('DEV','ui','settings.json') or self.manager.read()['tasks']['DEV']
        self.task=self.manager.read()['tasks']['DEV'];self.task['development_tracking']={'code_paths':['server']}
        self.active.stop();self.active=patch.object(guard,'active',return_value=(self.manager,self.task));self.active.start();self.addCleanup(self.active.stop)
        with self.assertRaisesRegex(ValueError,'technology'):
            self.check('*** Begin Patch\n*** Add File: server/app.py\n+print(1)\n*** End Patch')

    def test_patch_outside_code_ownership_and_malformed_hunks_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'code paths'):
            self.check('*** Begin Patch\n*** Add File: other/main.kt\n+fun Other() {}\n*** End Patch')
        with self.assertRaisesRegex(ValueError,'match'):
            self.check('*** Begin Patch\n*** Update File: shared/App.kt\n@@\n-not current code\n+new\n*** End Patch')

    def test_patch_move_checks_both_scopes(self):
        with self.assertRaisesRegex(ValueError,'code paths'):
            self.check('*** Begin Patch\n*** Update File: shared/App.kt\n*** Move to: outside/App.kt\n@@\n-@Composable fun SharedApp() {}\n+@Composable fun SharedApp() {}\n*** End Patch')

    def test_managed_command_must_match_authoritative_argv(self):
        (self.root/'.kmp-agent').mkdir(exist_ok=True);(self.root/'.kmp-agent/installation.json').write_text('{}')
        self.task.update(state='IN_PROGRESS',executions=[{'kind':'work','run_id':self.manager.run_id,'ended_at':None}])
        state={'tasks':{'DEV':dict(self.task,work_type='PRODUCT')},
               'execution_policy_bindings':{self.manager.run_id:{'root_session_id':'synthetic-session'}}}
        approved=self.fixture.policy['target_commands']['android'][0]
        # Source-rule unit fixture only; real native approval validation has its
        # own negative regression below and the existing approvals/lineage suites.
        with patch('harness.requirement_lineage._human_authorization',return_value={'status':'CONFIRMED'}):
            guard.authorize_command(self.root,state,'DEV',approved)
            with self.assertRaisesRegex(ValueError,'target_commands'):
                guard.authorize_command(self.root,state,'DEV',['rtk','proxy','python3','-c','unapproved code'])

    def test_source_labels_cannot_replace_native_technology_authorization(self):
        with patch('harness.requirement_lineage._human_authorization',return_value={'status':'UNCONFIRMED'}):
            with self.assertRaisesRegex(ValueError,'human authorization'):
                guard.development_constraints._authoritative(self.manager,archive=False,product=True)

    def test_configured_adapter_allows_native_document_review_but_not_subprocess_escape(self):
        (self.root/'.kmp-agent').mkdir(exist_ok=True);(self.root/'.kmp-agent/installation.json').write_text('{}')
        guard.configured_adapter(self.manager,{},[],'codex')
        with self.assertRaisesRegex(ValueError,'arbitrary executables'):
            guard.configured_adapter(self.manager,{},[],'python3')
        with self.assertRaisesRegex(ValueError,'PRODUCT'):
            guard.configured_adapter(self.manager,{},[['rtk','proxy','python3','evil.py']],'codex')
        self.task['work_type']='PRODUCT'
        with patch('harness.requirement_lineage._human_authorization',return_value={'status':'CONFIRMED'}):
            guard.configured_adapter(self.manager,self.task,[self.fixture.policy['target_commands']['android'][0]],'codex')
            with self.assertRaisesRegex(ValueError,'target_commands'):
                guard.configured_adapter(self.manager,self.task,[['rtk','proxy','python3','evil.py']],'codex')

    def test_qa_rejects_custom_executable_before_registering_task(self):
        from harness.qa import QA
        (self.root/'.kmp-agent').mkdir(exist_ok=True);(self.root/'.kmp-agent/installation.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'arbitrary executables'):
            QA(self.root,self.manager.run_id).configure('QA','requirements','DEV',['original.md'],
                [{'id':'Q','description':'synthetic source check','required':True}],executable='python3')
        self.assertNotIn('QA',self.manager.read()['tasks'])

class InstalledDelegationAdapter(unittest.TestCase):
    def test_custom_executable_is_rejected_before_creating_children(self):
        from harness.test_delegation import build_fixture
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();manager,development,spec=build_fixture(root)
            (root/'.kmp-agent').mkdir();(root/'.kmp-agent/installation.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'arbitrary executables'):
                development.configure(**spec)
            self.assertEqual(['PARENT'],list(manager.read()['tasks']))
