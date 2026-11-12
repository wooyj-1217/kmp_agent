"""Synthetic observation capabilities and denied mutation regressions."""
import json
import os
import pty
import subprocess
import tempfile
from pathlib import Path

from harness import test_product_guard


class ObservationGuard(test_product_guard.InstalledProductGuard):
    def cua(self, code=None, **fields):
        args = dict(fields)
        if code is not None:
            args['code'] = code
        return self.payload('mcp__cua_repl__js', args)

    def payload(self, tool, args):
        from harness.product_guard import evaluate
        return evaluate(self.root, dict(hook_event_name='PreToolUse', session_id='synthetic-session',
                        cwd=str(self.root), tool_name=tool, tool_input=args))

    def test_inventory_queries_before_product_configuration(self):
        for code in ('await cua.getState();', 'await cua.listApps()',
                     'await cua.listBrowsers();', 'await cua.listTabs({"browser":"chrome","emit":false});'):
            with self.subTest(code=code):
                self.assertEqual({}, self.cua(code))
        self.assertEqual({}, self.cua(completion_summary='확인한 조회 결과'))

    def test_scripts_handles_and_interactions_are_not_observations(self):
        for code in ('await cua.getState(); await evil();',
                     'let tab = await cua.getTab("1");', 'await tab.getAXState();',
                     'await cua.getApp("Terminal");', 'await cua.createBrowserTab("chrome", "https://example.invalid");',
                     'await tab.click(1);', 'await tab.typeText(1, "save");',
                     'await cua.getState({"emit":evil()});',
                     'await cua.getState({"emit":true,"other":1});',
                     'await cua.getState.constructor("evil")();',
                     'await cua["getState"]();', 'await cua.getState(/* comment */);',
                     'await cua.getState({"emit":"false"});',
                     'await cua.listTabs({"browser":{}});'):
            with self.subTest(code=code):
                self.denied(self.cua(code))
        self.denied(self.cua('await cua.getState();', completion_summary='hide script'))
        self.denied(self.payload('mcp__cua_repl__js_reset', {}))

    def test_nested_and_oversized_options_return_supported_deny(self):
        for size in (980, 2000, 100000):
            self.denied(self.cua('await cua.getState({"emit":' + '['*size + 'true' + ']'*size + '});'))
        self.denied(self.cua('await cua.getState();' + ' '*2048))

    def test_thread_discovery_does_not_grant_thread_creation_or_root_switch(self):
        self.assertEqual({}, self.payload('mcp__codex_tui__list_threads', {}))
        self.denied(self.payload('mcp__codex_tui__create_thread', {'prompt':'mutate'}))
        self.denied(self.payload('mcp__other__list_threads', {}))

    def test_external_status_requires_fixed_safe_options(self):
        with tempfile.TemporaryDirectory() as other:
            subprocess.run(['rtk','proxy','git','init','-q',other], check=True, capture_output=True)
            command = f'git --no-pager --no-optional-locks -c core.fsmonitor=false -C "{other}" status --short --branch'
            self.assertEqual({}, self.tool(command=command))
            subprocess.run(command, shell=True, cwd=self.root, check=True, capture_output=True)
            for suffix in ('add .', 'commit -m change', 'push origin main', 'diff', 'status --ignored',
                           'status --porcelain --untracked-files=all'):
                self.denied(self.tool(command=f'git --no-pager --no-optional-locks -c core.fsmonitor=false -C "{other}" {suffix}'))
            self.denied(self.tool(command=f'git -C "{other}" status --short --branch'))
            self.denied(self.tool(command=f'git --no-optional-locks -c core.fsmonitor=false -C "{other}" status --short --branch'))
            self.denied(self.tool(command=f'git -c core.fsmonitor=evil -C "{other}" status'))

    def test_external_status_does_not_execute_configured_fsmonitor_or_update_index(self):
        with tempfile.TemporaryDirectory() as other:
            other = Path(other)
            subprocess.run(['rtk','proxy','git','init','-q',str(other)], check=True, capture_output=True)
            marker = other/'executed'
            monitor = other/'monitor'
            monitor.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\n')
            monitor.chmod(0o700)
            subprocess.run(['rtk','proxy','git','-C',str(other),'config','core.fsmonitor',str(monitor)], check=True)
            command = f'git --no-pager --no-optional-locks -c core.fsmonitor=false -C "{other}" status --short --branch'
            self.assertEqual({}, self.tool(command=command))
            subprocess.run(command, shell=True, cwd=self.root, check=True, capture_output=True)
            self.assertFalse(marker.exists())
            self.assertFalse((other/'.git/index').exists())

    def test_external_status_disables_configured_pager_on_a_terminal(self):
        with tempfile.TemporaryDirectory() as other:
            other = Path(other)
            subprocess.run(['rtk','proxy','git','init','-q',str(other)], check=True, capture_output=True)
            marker = other/'pager-executed'
            for key, value in [('pager.status','true'), ('core.pager',f'touch "{marker}"')]:
                subprocess.run(['rtk','proxy','git','-C',str(other),'config',key,value], check=True)
            argv = ['git','--no-pager','--no-optional-locks','-c','core.fsmonitor=false',
                    '-C',str(other),'status','--short','--branch']
            import shlex
            self.assertEqual({}, self.tool(command=shlex.join(argv)))
            master, slave = pty.openpty()
            try:
                env = dict(os.environ, TERM='xterm')
                env.pop('GIT_PAGER', None)
                subprocess.run(argv, stdout=slave, stderr=slave, env=env, check=True, timeout=10)
            finally:
                os.close(slave)
                os.close(master)
            self.assertFalse(marker.exists())
