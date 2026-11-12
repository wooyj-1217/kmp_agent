"""Installed empty-project read/bootstrap boundaries; no product state is invented."""
import json
import unittest
from unittest.mock import patch

from harness import product_guard as guard
from harness.test_product_guard import InstalledProductGuard as _Fixture

_fixture_setup = _Fixture.setUp


class PreparationReadTests(unittest.TestCase):
    def setUp(self):
        _fixture_setup(self)
        from bootstrap import LAUNCHER
        (self.root/'.kmp-agent/agent.py').write_text(LAUNCHER)

    tool = _Fixture.tool
    ledger = _Fixture.ledger
    denied = _Fixture.denied

    def invoke(self, tool, args):
        return guard.evaluate(self.root,dict(hook_event_name='PreToolUse',cwd=str(self.root),
                              session_id='synthetic-session',tool_name=tool,tool_input=args))

    def test_headroom_original_output_is_a_read_before_any_task_exists(self):
        for name in ('mcp__headroom__headroom_retrieve','mcp__headroom.headroom_retrieve'):
            self.assertEqual({},self.invoke(name,{'hash':'abc123def456'}))
        self.assertFalse((self.root/'.harness/tasks/tasks.yaml').exists())

    def test_read_and_help_are_independent_of_broken_ledger(self):
        self.ledger();(self.root/'.harness/tasks/tasks.yaml').write_text('{broken')
        self.assertEqual({},self.invoke('mcp__headroom__headroom_retrieve',{'hash':'abc123'}))
        for command in ('python3 .kmp-agent/agent.py --help','rtk proxy python3 .kmp-agent/agent.py -h',
                        'python3 .kmp-agent/agent.py task --help','python3 .kmp-agent/agent.py planning --help'):
            with self.subTest(command=command): self.assertEqual({},self.tool(command=command))

    def test_headroom_read_checks_real_input_schema(self):
        for args in ({}, {'hash':''}, {'hash':17}, {'hash':'x','command':'write'},
                     {'hash':'../local-file'}, {'hash':'x\nwrite'}, 'not-an-object'):
            with self.subTest(args=args): self.denied(self.invoke('mcp__headroom__headroom_retrieve',args))

    def test_unknown_tools_do_not_report_missing_ui_contract(self):
        for name in ('mcp__unregistered__read','exec','functions.exec','mcp__headroom__not_retrieve'):
            with self.subTest(tool=name), patch('harness.verification_capabilities.authorize_tool',side_effect=AssertionError('not a UI action')):
                result=self.invoke(name,{'hash':'abc123'})
                self.denied(result)
                reason=result['hookSpecificOutput']['permissionDecisionReason']
                self.assertIn('unsupported tool capability',reason)
                self.assertIn(name,reason)
                self.assertNotIn('UI tool/input',reason)

    def test_known_ui_input_still_requires_exact_frozen_contract(self):
        result=self.invoke('mcp__synthetic_ui__screenshot',{'app_id':'synthetic'})
        self.denied(result)
        self.assertIn('exact frozen verification fixture',result['hookSpecificOutput']['permissionDecisionReason'])

    def test_help_cannot_authorize_extra_execution_or_target_overrides(self):
        for command in ('python3 -c "write()" --help','python3 .kmp-agent/agent.py --help extra',
                        'python3 .kmp-agent/agent.py --help --target /other',
                        'python3 .kmp-agent/agent.py task --help --worker evil',
                        'python3 /tmp/another-launcher.py --help'):
            with self.subTest(command=command): self.denied(self.tool(command=command))

    def test_help_rejects_control_aliases_and_modified_launcher(self):
        launcher=self.root/'.kmp-agent/agent.py'
        official=launcher.read_text()
        alias=self.root/'alias.py';alias.symlink_to(launcher)
        self.denied(self.tool(command=f'python3 {alias} --help'))
        outside=self.root/'outside.py';outside.write_text('print("untrusted")')
        launcher.unlink();launcher.symlink_to(outside)
        self.denied(self.tool(command=f'python3 {outside} --help'))
        self.denied(self.tool(command='python3 .kmp-agent/agent.py --help'))
        launcher.unlink();launcher.write_text(official+'\nprint("untrusted")\n')
        self.denied(self.tool(command='python3 .kmp-agent/agent.py --help'))

    def test_separate_simple_reads_work_without_enabling_compound_shell(self):
        for command in ('pwd', "rg 'plan|contract' docs", "sed -n '1,50p' AGENTS.md"):
            self.assertEqual({},self.tool(command=command))
        result=self.tool(command='pwd; rg --files')
        self.denied(result)
        self.assertIn('one simple command',result['hookSpecificOutput']['permissionDecisionReason'])
        self.denied(self.tool('apply_patch','*** Begin Patch\n*** Add File: src/App.kt\n+fun App() {}\n*** End Patch'))


del _Fixture
