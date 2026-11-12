"""Synthetic reproductions of installed preparation failures, without product logs."""
import json
import unittest
from unittest.mock import patch

from harness import product_guard as guard
from harness.tasks import Tasks
from harness.test_product_guard import InstalledProductGuard as Fixture


class StagePreparationGuardTests(unittest.TestCase):
    setUp = Fixture.setUp
    tool = Fixture.tool
    denied = Fixture.denied
    ledger = Fixture.ledger

    def test_exact_runtime_names_survive_broken_product_ledger(self):
        self.ledger()
        (self.root/'.harness/tasks/tasks.yaml').write_text('{broken')
        for name in ('collaborationspawn_agent', 'collaborationsend_message',
                     'collaborationwait_agent', 'collaborationfollowup_task',
                     'collaborationlist_agents', 'collaborationinterrupt_agent',
                     'web.run', 'web__run', 'webrun'):
            with self.subTest(name=name):
                self.assertEqual({}, guard.evaluate(self.root, dict(
                    hook_event_name='PreToolUse', cwd=str(self.root),
                    tool_name=name, tool_input={'search_query':[{'q':'synthetic public docs'}]})))
        for name in ('collaborationspawn_agent_extra', 'collaborationunknown',
                     'webwrite', 'web_run', 'untrustedwebrun', 'functions.exec'):
            self.denied(self.tool(name, 'arbitrary input'))

    def test_only_explicit_session_diagnostic_argv(self):
        for command in ('printenv CODEX_THREAD_ID', 'ps -axo pid,args'):
            self.assertEqual({}, self.tool(command=command))
        for command in ('printenv', 'printenv API_KEY', 'printenv CODEX_THREAD_ID API_KEY',
                        'ps aux', 'ps -axo pid,args,env', '/tmp/ps -axo pid,args',
                        'printenv CODEX_THREAD_ID; cat x'):
            self.denied(self.tool(command=command))

    def manager(self, role='design'):
        m=Tasks(self.root,'RUN')
        m.register('F','DOC',role,'Prepare contract documents','Documentation only',
                   [{'id':'A','required':True,'description':'Reviewable draft'}],[],
                   work_type='PRODUCT',execution_scope='documentation')
        return m

    def test_exact_design_and_settings_paths_can_be_frozen(self):
        m=self.manager()
        paths=['docs/feature/mockup.html','prototype/tokens.css','project-settings.json']
        self.assertEqual(paths, m.configure_documents('DOC', paths, 'Design draft and settings proposal')['paths'])
        with self.assertRaisesRegex(ValueError,'frozen'):
            m.configure_documents('DOC', ['docs/other.html'], 'Cannot expand after freezing')

    def test_html_is_design_only_and_not_arbitrary_product_source(self):
        m=self.manager('development')
        for paths in (['docs/mockup.html'],['src/App.kt'],['web/index.html'],
                      ['settings.gradle.kts'],['.codex/config.json']):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                m.configure_documents('DOC',paths,'Not a design-document scope')
        self.assertNotIn('document_scope',m.read()['tasks']['DOC'])

    def test_frozen_html_and_settings_patch_still_needs_planned_active_document_work(self):
        task=dict(task_id='DOC',role='design',work_type='PRODUCT',state='IN_PROGRESS',
                  execution_scope='documentation',document_scope={'paths':['docs/mockup.html','project-settings.json']},
                  executions=[dict(kind='work',run_id='RUN',ended_at=None)])
        state=self.ledger({'DOC':task})
        state['execution_plans']['RUN']['task_ids']=['DOC']
        patch_text='*** Begin Patch\n*** Add File: docs/mockup.html\n+<html>draft</html>\n*** Add File: project-settings.json\n+{}\n*** End Patch'
        with patch.object(guard.execution_policy,'gate'):
            guard._patch(self.root,state,'synthetic-session',patch_text)
            task['state']='TODO'
            with self.assertRaises(ValueError):guard._patch(self.root,state,'synthetic-session',patch_text)
            task['state']='IN_PROGRESS'
            task['development_tracking']={'code_paths':['docs']}
            with self.assertRaisesRegex(ValueError,'overlaps'):
                guard._patch(self.root,state,'synthetic-session',patch_text)


del Fixture
