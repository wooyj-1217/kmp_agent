"""Synthetic pinned installations; actual CLI/guard execution, no hook-trust claim."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from harness import test_installation as fixture


class ManagedUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.InstallationTests.setUpClass.__func__(cls)
        fixture.git('checkout', '--quiet', '--detach', cls.second, cwd=cls.source)
        with (cls.source/'harness/product_guard.py').open('a') as output:
            output.write('\nREAD_TOOLS.add("synthetic_release_observation")\n')
        (cls.source/'VERSION').write_text('0.1.2\n')
        fixture.git('add', 'VERSION', 'harness/product_guard.py', cwd=cls.source)
        fixture.git('-c', 'user.name=Synthetic Test', '-c', 'user.email=synthetic@example.invalid',
                    'commit', '--quiet', '-m', 'synthetic changed guard', cwd=cls.source)
        cls.next_commit = fixture.git('rev-parse', 'HEAD', cwd=cls.source)
        fixture.git('tag', 'v0.1.2', cwd=cls.source)
        fixture.git('fetch', '--quiet', cls.source, 'refs/tags/v0.1.2:refs/tags/v0.1.2', cwd=cls.remote)

    tearDownClass = classmethod(fixture.InstallationTests.tearDownClass.__func__)
    setUp = fixture.InstallationTests.setUp
    install = fixture.InstallationTests.install
    cli = fixture.InstallationTests.cli
    assert_owned_preserved = fixture.InstallationTests.assert_owned_preserved

    def guard(self, command=None, tool='exec_command', args=None, event='PreToolUse', selected_runtime=None):
        payload = dict(hook_event_name=event, cwd=str(self.target), session_id='synthetic-update',
                       tool_name=tool, tool_input=args if args is not None else {'cmd':command})
        entry = ([str(selected_runtime/'harness/cli.py'), '--target', str(self.target)] if selected_runtime
                 else [str(self.target/'.kmp-agent/agent.py')])
        process = subprocess.run(['rtk','proxy',sys.executable,'-B',*entry,'guard'],
                                 cwd=self.target, input=json.dumps(payload), text=True, capture_output=True, check=True)
        return json.loads(process.stdout)

    def denied(self, decision):
        self.assertEqual(decision['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_official_installed_update_is_allowed_before_product_work_configuration(self):
        self.install(self.first)
        self.assertEqual({}, self.guard('rtk proxy python3 .kmp-agent/agent.py update --ref v0.1.1'))

    def test_guarded_self_update_selects_new_guard_and_preserves_product_and_logs(self):
        before = self.install(self.first)['installation']
        self.denied(self.guard(tool='synthetic_release_observation', args={}))
        command = 'rtk proxy python3 .kmp-agent/agent.py update --ref v0.1.2'
        self.assertEqual({}, self.guard(command))
        result = subprocess.run(shlex.split(command), cwd=self.target, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        after = fixture.boot.read(self.target/fixture.boot.MANIFEST)
        self.assertEqual(after['commit'], self.next_commit)
        self.assertEqual(after['project_id'], before['project_id'])
        self.assertEqual(after['source'], before['source'])
        self.assertEqual(after['previous']['commit'], self.first)
        self.assertEqual({}, self.guard(tool='synthetic_release_observation', args={}))
        self.assert_owned_preserved()
        for event in ('PreToolUse','Stop'):
            handlers = [h for group in fixture.boot.read(self.target/'.codex/hooks.json')['hooks'][event] for h in group['hooks']]
            self.assertEqual(1, sum(h['command'].endswith(' guard') for h in handlers))

    def test_full_commit_ref_is_supported_without_source_override(self):
        self.install(self.first)
        command = 'python3 .kmp-agent/agent.py update --ref '+self.second
        self.assertEqual({}, self.guard(command))
        result = self.cli('update','--ref',self.second)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(fixture.boot.read(self.target/fixture.boot.MANIFEST)['commit'], self.second)

    def test_update_syntax_cannot_expand_into_arbitrary_tools_targets_or_sources(self):
        self.install(self.first)
        original = (self.target/fixture.boot.MANIFEST).read_bytes()
        for command in (
            'python3 .kmp-agent/agent.py update',
            'python3 .kmp-agent/agent.py update --ref v0.1.1 --source '+shlex.quote(self.url),
            'python3 .kmp-agent/agent.py update --ref v0.1.1 --target /synthetic/other',
            'python3 .kmp-agent/agent.py update --ref v0.1.1 --worker evil',
            'python3 .kmp-agent/agent.py update --ref v0.1.1 --dev-source /synthetic/source',
            'python3 .kmp-agent/agent.py update --ref v0.1.1 --timeout 1',
            'python3 .kmp-agent/agent.py update --ref v0.1.1 --ref v0.1.2',
            'python3 .kmp-agent/agent.py update --ref=v0.1.1',
            'python3 .kmp-agent/agent.py update --ref ../branch',
            'python3 .kmp-agent/agent.py update --ref --help',
            'python3 .kmp-agent/agent.py update --ref v0.1.1; python3 evil.py',
            'python3 -c "write()"',
            'python3 /tmp/bootstrap.py update --ref v0.1.1 --target /synthetic/project',
            'git clone https://example.invalid/harness.git /tmp/bootstrap',
        ):
            with self.subTest(command=command):
                self.denied(self.guard(command))
        self.assertEqual((self.target/fixture.boot.MANIFEST).read_bytes(), original)

    def test_cli_rejects_ignored_or_duplicate_options_before_update(self):
        self.install(self.first)
        original = (self.target/fixture.boot.MANIFEST).read_bytes()
        for options in (('--source',self.url), ('--timeout','1'), ('--ref','v0.1.2'), ('--target',str(self.target)),
                        ('--worker','["evil"]'), ('--run-id','other')):
            with self.subTest(options=options):
                result = self.cli('update','--ref','v0.1.1',*options)
                self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertEqual((self.target/fixture.boot.MANIFEST).read_bytes(), original)

    def test_dirty_or_forged_installed_identity_is_not_an_update_authorization(self):
        self.install(self.first)
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        launcher = self.target/'.kmp-agent/agent.py'
        original = launcher.read_text()
        launcher.write_text(original+'\n# forged launcher\n')
        self.denied(self.guard(command))
        launcher.write_text(original)
        manifest = fixture.boot.read(self.target/fixture.boot.MANIFEST)
        code = self.target/manifest['code_path']
        (code/'VERSION').write_text('9.9.9\n')
        self.denied(self.guard(command))
        result = self.cli('update','--ref','v0.1.1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fixture.boot.read(self.target/fixture.boot.MANIFEST)['commit'], self.first)

    def test_unselected_runtime_and_pending_recovery_do_not_update(self):
        self.install(self.first)
        # Direct invocation of another checkout's CLI cannot authorize its update.
        process = subprocess.run(['rtk','proxy',sys.executable,str(fixture.ROOT/'harness/cli.py'),
                                  '--target',str(self.target),'update','--ref','v0.1.1'],
                                 cwd=self.target, text=True, capture_output=True)
        self.assertNotEqual(process.returncode, 0)
        journal = self.target/fixture.boot.JOURNAL
        journal.write_text('{}')
        self.denied(self.guard('python3 .kmp-agent/agent.py update --ref v0.1.1'))
        self.assertEqual(journal.read_text(), '{}')

    def test_blocked_or_malformed_product_ledger_does_not_block_repair_or_change_history(self):
        self.install(self.first)
        ledger = self.target/'.harness/tasks/tasks.yaml'
        ledger.parent.mkdir(parents=True,exist_ok=True)
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        for content in ('{broken', '['*2000+'0'+']'*2000,
                        json.dumps({'tasks':{'CODE':{'state':'BLOCKED','work_type':'PRODUCT'}}})):
            with self.subTest(ledger=content):
                ledger.write_text(content)
                self.assertEqual({}, self.guard(command))
                result = self.cli('update','--ref','v0.1.1')
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertEqual(ledger.read_text(), content)
                self.denied(self.guard('python3 -c "write()"'))
                if content != json.dumps({'tasks':{'CODE':{'state':'BLOCKED','work_type':'PRODUCT'}}}):
                    self.assertEqual(self.guard(event='Stop')['decision'], 'block')
        ledger.write_text('{broken')
        self.denied(self.guard('python3 -c "write()"'))
        self.assertEqual(self.guard(event='Stop')['decision'], 'block')

    def test_manifest_corruption_and_deep_json_return_supported_update_denial(self):
        self.install(self.first)
        manifest_path = self.target/fixture.boot.MANIFEST
        original = manifest_path.read_bytes()
        manifest = json.loads(original)
        code = self.target/manifest['code_path']
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        # Inspect the selected runtime directly so corrupt launcher selection
        # metadata cannot prevent the fixture from reaching the guard itself.
        variants = [b'{broken', ('['*2000+'0'+']'*2000).encode(), b'[]',
                    json.dumps({**manifest,'mode':'development'}).encode(),
                    json.dumps({**manifest,'mode':'UNKNOWN'}).encode(), b'{}',
                    json.dumps({**manifest,'code_path':'../outside'}).encode(),
                    json.dumps({**manifest,'commit':'invalid'}).encode(),
                    json.dumps({**manifest,'source':None}).encode()]
        for content in variants:
            with self.subTest(prefix=content[:40]):
                manifest_path.write_bytes(content)
                self.denied(self.guard(command,selected_runtime=code))
                self.assertEqual(manifest_path.read_bytes(), content)
        manifest_path.write_bytes(original)
        alias = self.target/'untrusted-launcher.py'
        alias.symlink_to(self.target/'.kmp-agent/agent.py')
        self.denied(self.guard('python3 untrusted-launcher.py update --ref v0.1.1'))
        loop = self.target/'looping-launcher.py'
        loop.symlink_to(loop)
        self.denied(self.guard('python3 looping-launcher.py update --ref v0.1.1'))

    def test_unknown_installation_mode_cannot_use_the_development_cli_fallback(self):
        self.install(self.first)
        manifest_path = self.target/fixture.boot.MANIFEST
        original = fixture.boot.read(manifest_path)
        code = self.target/original['code_path']
        for mode in (None, 'UNKNOWN', 'other'):
            manifest = {**original,'mode':mode}
            fixture.boot.save(manifest_path,manifest)
            before = manifest_path.read_bytes()
            process = subprocess.run(['rtk','proxy',sys.executable,str(code/'harness/cli.py'),
                                      '--target',str(self.target),'update','--ref','v0.1.1'],
                                     cwd=self.target,text=True,capture_output=True)
            self.assertNotEqual(process.returncode,0,process.stdout+process.stderr)
            self.assertEqual(manifest_path.read_bytes(),before)

    def test_invalid_nonentry_runtime_source_returns_supported_guard_denial(self):
        self.install(self.first)
        manifest_path = self.target/fixture.boot.MANIFEST
        before = manifest_path.read_bytes()
        code = self.target/json.loads(before)['code_path']
        (code/'harness/unused_update_probe.py').write_text('def invalid(\n')
        self.denied(self.guard('python3 .kmp-agent/agent.py update --ref v0.1.1'))
        self.assertEqual(manifest_path.read_bytes(),before)
        result = self.cli('update','--ref','v0.1.1')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('runtime validation failed',result.stdout)
        self.assertEqual(manifest_path.read_bytes(),before)

    def test_launcher_or_pinned_runtime_symlink_cannot_authorize_update(self):
        self.install(self.first)
        manifest = fixture.boot.read(self.target/fixture.boot.MANIFEST)
        code = self.target/manifest['code_path']
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        launcher = self.target/'.kmp-agent/agent.py'
        saved_launcher = self.target/'.kmp-agent/saved-launcher.py'
        launcher.rename(saved_launcher)
        launcher.symlink_to(saved_launcher)
        self.denied(self.guard(command,selected_runtime=code))
        launcher.unlink()
        saved_launcher.rename(launcher)
        moved = code.with_name(code.name+'-moved')
        code.rename(moved)
        code.symlink_to(moved,target_is_directory=True)
        self.denied(self.guard(command,selected_runtime=moved))

    def test_control_lock_aliases_cannot_change_external_file_bytes_or_mode(self):
        self.install(self.first)
        manifest = (self.target/fixture.boot.MANIFEST).read_bytes()
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory)/'outside.txt'
            outside.write_text('external sentinel\n')
            outside.chmod(0o644)
            for relative in ('.harness/install.lock','.harness/integration.lock'):
                lock = self.target/relative
                original = lock.read_bytes()
                original_mode = lock.stat().st_mode & 0o777
                lock.unlink()
                for alias in ('symlink','hardlink','fifo'):
                    with self.subTest(path=relative,alias=alias):
                        if alias == 'symlink':
                            lock.symlink_to(outside)
                        elif alias == 'hardlink':
                            os.link(outside,lock)
                        else:
                            os.mkfifo(lock)
                        self.denied(self.guard(command))
                        result = self.cli('update','--ref','v0.1.1')
                        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                        self.assertEqual(outside.read_text(),'external sentinel\n')
                        self.assertEqual(outside.stat().st_mode & 0o777,0o644)
                        self.assertEqual((self.target/fixture.boot.MANIFEST).read_bytes(),manifest)
                        lock.unlink()
                lock.write_bytes(original)
                lock.chmod(original_mode)

    def test_control_parent_alias_is_denied_before_installer_writes(self):
        self.install(self.first)
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory)
            outside.chmod(0o755)
            for relative in ('.harness','.codex','.agents'):
                parent = self.target/relative
                backup = self.target/(relative+'-saved')
                present = parent.exists()
                if present:
                    parent.rename(backup)
                parent.symlink_to(outside,target_is_directory=True)
                with self.subTest(path=relative):
                    self.denied(self.guard(command))
                    result = self.cli('update','--ref','v0.1.1')
                    self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertEqual(list(outside.iterdir()),[])
                    self.assertEqual(outside.stat().st_mode & 0o777,0o755)
                parent.unlink()
                if present:
                    backup.rename(parent)

    def test_control_fifo_cannot_block_guard_or_update_error_reporting(self):
        self.install(self.first)
        manifest = fixture.boot.read(self.target/fixture.boot.MANIFEST)
        code = self.target/manifest['code_path']
        command = 'python3 .kmp-agent/agent.py update --ref v0.1.1'
        for relative in (fixture.boot.MANIFEST,'.kmp-agent/project.json','.harness/project.json'):
            path = self.target/relative
            original = path.read_bytes() if path.exists() else None
            if path.exists():
                path.unlink()
            os.mkfifo(path)
            with self.subTest(path=relative):
                # A direct selected-runtime call can inspect invalid selection
                # metadata without asking the launcher to consume that FIFO.
                self.denied(self.guard(command,selected_runtime=code))
                process = subprocess.run(['rtk','proxy',sys.executable,str(code/'harness/cli.py'),
                                          '--target',str(self.target),'update','--ref','v0.1.1'],
                                         cwd=self.target,text=True,capture_output=True,timeout=10)
                self.assertNotEqual(process.returncode,0)
                self.assertEqual(json.loads(process.stdout)['project_id'],'UNKNOWN')
            path.unlink()
            if original is not None:
                path.write_bytes(original)

    def test_shell_metadata_and_ambiguous_command_keys_cannot_change_execution(self):
        self.install(self.first)
        commands = ('python3 .kmp-agent/agent.py update --ref v0.1.1', 'git status --short')
        for tool,key in (('exec_command','cmd'), ('Bash','command')):
            for command in commands:
                with self.subTest(tool=tool,command=command):
                    self.assertEqual({},self.guard(tool=tool,args={key:command}))
                    self.assertEqual({},self.guard(tool=tool,args={key:command,'shell':None}))
                    self.denied(self.guard(tool=tool,args={key:command,'shell':'/synthetic/evil-shell'}))
                    self.denied(self.guard(tool=tool,args={'cmd':command,'command':'python3 -c "write()"'}))
                    self.denied(self.guard(tool=tool,args={'cmd':'python3 -c "write()"','command':command}))
