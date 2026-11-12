"""Separate-session repair guidance preserves the installed product cwd boundary."""
import unittest

from harness import product_guard as guard
from harness.test_product_guard import InstalledProductGuard as Fixture


class GuardHandoffTests(unittest.TestCase):
    setUp = Fixture.setUp
    denied = Fixture.denied

    def test_wrong_cwd_denies_and_explains_separate_source_session(self):
        installation = self.root/'.kmp-agent/installation.json'
        before = installation.read_bytes()
        result = guard.evaluate(self.root, dict(hook_event_name='PreToolUse',
            cwd=str(self.root.parent/'source-checkout'), tool_name='exec_command',
            tool_input={'cmd':'git status --short'}))
        self.denied(result)
        reason = result['hookSpecificOutput']['permissionDecisionReason']
        for required in ('hook cwd differs from target project root', str(self.root),
                         'separate Codex session', '.kmp-agent/installation.json',
                         'remote URL', 'docs/guard-inputs/', 'harness-defect-pr.md'):
            self.assertIn(required, reason)
        self.assertEqual(before, installation.read_bytes())
        self.assertFalse((self.root/'.harness/tasks/tasks.yaml').exists())

    def test_product_root_reads_still_work_without_cross_root_authority(self):
        self.assertEqual({}, guard.evaluate(self.root, dict(hook_event_name='PreToolUse',
            cwd=str(self.root), tool_name='exec_command',
            tool_input={'cmd':'git status --short'})))
        denied = guard.evaluate(self.root, dict(hook_event_name='PreToolUse',
            cwd=str(self.root), tool_name='exec_command',
            tool_input={'cmd':'git status --short','workdir':str(self.root.parent)}))
        self.denied(denied)


del Fixture
