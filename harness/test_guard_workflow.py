"""Guard workflow boundary regressions using synthetic installed projects."""
import json
import unittest
import subprocess
from unittest.mock import patch

from harness import product_guard as guard
from harness.test_product_guard import InstalledProductGuard


class WorkflowBoundaries(unittest.TestCase):
    setUp = InstalledProductGuard.setUp
    tool = InstalledProductGuard.tool
    ledger = InstalledProductGuard.ledger
    denied = InstalledProductGuard.denied
    def broken(self):
        self.ledger()
        (self.root/'.harness/tasks/tasks.yaml').write_text('{broken')

    def test_save_share_reads_and_stop_survive_broken_ledger(self):
        self.broken()
        for command in ('git add docs/notes.md', 'git commit -m checkpoint',
                        'git push --no-follow-tags -u origin HEAD:refs/heads/work/unfinished',
                        'git remote -v', "sed -n '1,30p' docs/notes.md", "rg 'foo|bar;$' docs"):
            with self.subTest(command=command):
                self.assertEqual({}, self.tool(command=command))
        self.assertEqual({},guard.evaluate(self.root,dict(hook_event_name='Stop',cwd=str(self.root))))
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: shared/App.kt\n+x\n*** End Patch'))

    def test_shell_literals_are_not_operators_but_substitutions_remain_denied(self):
        for command in ("rg 'a|b;$()' docs", 'rg "a|b;" docs', r'rg a\|b docs'):
            self.assertEqual({},self.tool(command=command))
        for command in ('cat x | cat', 'cat x; cat', 'cat $(pwd)', 'cat "$(pwd)"',
                        'cat `pwd`', 'cat x > y', 'cat x\ncat y', 'cat <(pwd)',
                        'sed -n "1e touch x" docs/a', 'sed -i x docs/a', "sed -n '1w x' docs/a"):
            with self.subTest(command=command): self.denied(self.tool(command=command))

    def test_git_option_abbreviations_cannot_bypass_hooks_or_rewrite(self):
        for command in ('git commit --am -m rewrite','git commit -qn -m bypass',
                        'git commit --no-ver -m bypass','git add --edit','git add -i'):
            self.denied(self.tool(command=command))
        self.assertEqual({},self.tool(command="git commit -m '-n is a message'"))

    def test_only_explicit_development_branch_pushes_are_sharing(self):
        for command in ('git push', 'git push --tags origin', 'git push --no-follow-tags origin main',
                        'git push --no-follow-tags origin HEAD:refs/tags/v1', 'git push --no-follow-tags origin HEAD:refs/heads/release/v1',
                        'git push --no-follow-tags origin :work', 'git push --force origin work',
                        'git push --mirror origin', 'git push --no-follow-tags origin HEAD:production',
                        'git push --no-follow-tags origin +work:work', 'git push ext::evil work'):
            with self.subTest(command=command): self.denied(self.tool(command=command))
        for command in ('git push --no-follow-tags origin feature', 'git push --no-follow-tags -u origin HEAD:refs/heads/work/qa'):
            self.assertEqual({},self.tool(command=command))

    def test_explicit_share_does_not_publish_configured_follow_tags(self):
        def git(*args):
            return subprocess.check_output(['git',*args],cwd=self.root,stderr=subprocess.STDOUT).decode()
        git('config','user.name','Synthetic')
        git('config','user.email','synthetic@example.invalid')
        git('checkout','-b','feature')
        (self.root/'note.md').write_text('checkpoint')
        git('add','note.md')
        git('commit','-m','checkpoint')
        git('tag','-a','v1','-m','release')
        remote=self.root/'remote.git'
        git('init','--bare',str(remote))
        git('remote','add','origin',str(remote))
        git('config','push.followTags','true')
        self.denied(self.tool(command='git push origin feature'))
        self.assertEqual({},self.tool(command='git push --no-follow-tags origin feature'))
        git('push','--no-follow-tags','origin','feature')
        self.assertIn('refs/heads/feature',git('ls-remote','origin'))
        self.assertNotIn('refs/tags/',git('ls-remote','origin'))

    def test_actual_collaboration_runtime_names(self):
        self.broken()
        for tool in ('collaboration.spawn_agent','collaboration.send_message',
                     'collaboration.wait_agent','collaboration.followup_task',
                     'collaboration.list_agents','collaboration.interrupt_agent',
                     'functions.exec_command'):
            self.assertEqual({},self.tool(tool,'git status --short'))
        self.denied(self.tool('collaboration.unknown','anything'))
        self.denied(self.tool('functions.exec','arbitrary JavaScript'))
        self.denied(self.tool('exec','arbitrary JavaScript'))

    def test_document_extension_is_not_automatic_authority(self):
        self.ledger()
        for path in ('shared/README.md','docs/runtime.json','requirement-lineage.json'):
            self.denied(self.tool('apply_patch',f'*** Begin Patch\n*** Add File: {path}\n+{{}}\n*** End Patch'))
        self.assertEqual({},self.tool('apply_patch','*** Begin Patch\n*** Add File: docs/guard-inputs/task.json\n+{}\n*** End Patch'))
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: docs/guard-inputs/task.json\n+not-json\n*** End Patch'))
        state=self.ledger()
        state['tasks']['CODE']['development_tracking']={'code_paths':['docs']}
        (self.root/'.harness/tasks/tasks.yaml').write_text(json.dumps(state))
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: docs/guard-inputs/task.json\n+{}\n*** End Patch'))

    def test_scoped_document_execution_and_code_overlap(self):
        state=self.ledger({'CODE':dict(task_id='CODE',state='IN_PROGRESS',work_type='PRODUCT',
            execution_scope='documentation',document_scope={'paths':['docs/guide.md']},
            executions=[dict(kind='work',run_id='RUN',ended_at=None)])})
        text='*** Begin Patch\n*** Add File: docs/guide.md\n+guide\n*** End Patch'
        with patch.object(guard.execution_policy,'gate'):
            self.assertEqual({},guard._patch(self.root,state,'synthetic-session',text) or {})
            state['tasks']['CODE']['development_tracking']={'code_paths':['docs']}
            with self.assertRaisesRegex(ValueError,'overlaps'):
                guard._patch(self.root,state,'synthetic-session',text)

    def test_finish_reasons_do_not_certify_incomplete_products(self):
        self.ledger()
        for reason in ('blocked','handoff','user_stopped','paused'):
            guard.finish(self.root,'RUN',end_reason=reason)
            self.assertEqual({},self.tool(command=f'python3 .kmp-agent/agent.py finish --run-id RUN --result partial --end-reason {reason}'))
        with self.assertRaisesRegex(ValueError,'not officially DONE'): guard.finish(self.root,'RUN')
        self.denied(self.tool(command='python3 .kmp-agent/agent.py finish --run-id RUN --result done'))
        with self.assertRaisesRegex(ValueError,'unsupported'): guard.finish(self.root,'RUN','invented')

    def test_logging_preserves_incomplete_end_reason_without_marking_tasks_done(self):
        from harness.logging import Logger
        state=self.ledger()
        logger=Logger(self.root)
        run=logger.start('PRODUCT','development','synthetic incomplete work')
        with self.assertRaises(ValueError): logger.checkpoint(run,'incomplete',finish=True)
        event=logger.checkpoint(run,'environment blocked; resume verification',finish=True,end_reason='blocked')
        self.assertEqual('blocked',event['agent_summary']['end_reason'])
        self.assertEqual(state['tasks'],guard._state(self.root)['tasks'])

    def test_diagnostics_identify_session_and_task_state(self):
        state=self.ledger()
        with self.assertRaisesRegex(ValueError,'bind-execution-session'):
            guard.active(self.root,state,'another-session')
        with self.assertRaisesRegex(ValueError,'CODE: state=TODO'):
            guard.active(self.root,state,'synthetic-session')
        with self.assertRaisesRegex(ValueError,'absent from bound plan'):
            guard.active(self.root,state,'synthetic-session','MISSING')


del InstalledProductGuard
