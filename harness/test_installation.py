"""Temporary Git releases/targets only. Mock hooks are not actual Codex proof."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_tested", ROOT / "bootstrap.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


def git(*args, cwd=None):
    result = subprocess.run(["rtk", "proxy", "git", *map(str, args)], cwd=cwd,
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


class InstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.base = Path(cls.shared.name).resolve()
        source = cls.base / "synthetic-source"
        source.mkdir()
        for name in ["bootstrap.py", "VERSION", "AGENTS.md", "README.md", "design.md", "plan.md", ".gitignore"]:
            shutil.copy2(ROOT / name, source / name)
        shutil.copytree(ROOT / "harness", source / "harness", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "docs", source / "docs", ignore=shutil.ignore_patterns("local-environment.md"))
        skill = source / ".agents/skills/fixture-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("synthetic shared skill\n")
        (source / "tools").mkdir()
        (source / "tools/dev-check.py").write_text("raise SystemExit('development only')\n")
        shutil.copy2(ROOT / "tools/check_pr_scope.py", source / "tools/check_pr_scope.py")
        # The harness ignores personal .agents/; only this synthetic skill is forced in.
        (source / "VERSION").write_text("0.1.0\n")  # Synthetic first release, independent of candidate VERSION.
        git("init", "--quiet", source)
        git("add", ".", cwd=source)
        git("add", "-f", ".agents/skills/fixture-skill/SKILL.md", cwd=source)
        git("-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "fixture release one", cwd=source)
        cls.first = git("rev-parse", "HEAD", cwd=source)
        git("tag", "v0.1.0", cwd=source)
        (source / "VERSION").write_text("0.1.1\n")
        git("add", "VERSION", cwd=source)
        git("-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "fixture release two", cwd=source)
        cls.second = git("rev-parse", "HEAD", cwd=source)
        git("tag", "v0.1.1", cwd=source)
        (source / "harness/cli.py").write_text("def invalid(\n")
        git("add", "harness/cli.py", cwd=source)
        git("-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid", "commit", "--quiet", "-m", "fixture invalid release", cwd=source)
        git("tag", "invalid-release", cwd=source)
        cls.remote = cls.base / "fixture-remote.git"
        git("clone", "--quiet", "--bare", source, cls.remote)  # No network or git push.
        cls.url = cls.remote.as_uri()
        cls.source = source

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name).resolve() / "product with spaces"
        self.target.mkdir()
        git("init", "--quiet", self.target)
        (self.target / "AGENTS.md").write_text("# Product\nKeep these policies.\n")
        (self.target / ".gitignore").write_text("# Existing ignores\n.harness/\n")
        (self.target / ".codex").mkdir()
        (self.target / ".codex/config.toml").write_text('model = "product-specific"\n')
        boot.save(self.target / ".codex/hooks.json", {"description": "keep", "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "product-owned-hook"}]}]}})
        for relative in ["docs/requirements.md", "docs/design.md", "prototype/index.html"]:
            path = self.target / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text("original product artifact " + relative)
        (self.target / ".harness/logs").mkdir(parents=True)
        (self.target / ".harness/logs/events.jsonl").write_text('{"event_type":"fixture_existing","event_id":"old","recorded_at":"2000-01-01T00:00:00+00:00"}\n')
        self.owned = {p: p.read_bytes() for p in [
            self.target / ".codex/config.toml", self.target / "docs/requirements.md", self.target / "docs/design.md",
            self.target / "prototype/index.html", self.target / ".harness/logs/events.jsonl"]}

    def tearDown(self):
        # Optional evidence export chosen by the test runner; default tests stay temporary.
        output = os.getenv("KMP_AGENT_TEST_REPORT")
        if not output:
            return
        context = boot.load(ROOT / "harness/context.py", "fixture_result_context").identify(self.target)
        outcome = self._outcome.result
        failed = any(test is self for test, _ in outcome.failures + outcome.errors)
        manifest = boot.read(self.target / boot.MANIFEST, {})
        record = {**context, "case": self.id(), "result": "FAIL" if failed else "PASS",
                  "evidence_kind": "temporary_git_target_fixture", "actual_codex_session": "NOT_RUN",
                  "hook_execution": "MOCK" if "mock_hook" in self._testMethodName else "NOT_RUN",
                  "version": manifest.get("version", "UNKNOWN"), "commit": manifest.get("commit", "UNKNOWN")}
        with Path(output).open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def install(self, ref="v0.1.0", update=False):
        return boot.install(self.target, self.url, ref, update=update)

    def protected(self):
        return {name: (self.target / name).read_bytes() for name in [
            ".kmp-agent/installation.json", ".kmp-agent/agent.py", ".kmp-agent/project.json", "AGENTS.md",
            ".gitignore", ".codex/hooks.json", ".harness/integration.json", ".harness/integration-status.json"]}

    def assert_owned_preserved(self):
        self.assertTrue(all(p.read_bytes() == before for p, before in self.owned.items()))

    def cli(self, *args, input=None, target=None):
        return subprocess.run(["rtk", "proxy", sys.executable, str(self.target / ".kmp-agent/agent.py"), *args],
                              cwd=target or self.target, text=True, input=input, capture_output=True)

    def test_install_init_idempotent_preserves_product_and_trackable_metadata(self):
        result = self.install()
        self.assertEqual(result["installation"]["commit"], self.first)
        self.assertEqual(result["installation"]["version"], "0.1.0")
        self.assertEqual(result["connection"]["runtime"]["result"], "NOT_RUN")
        self.assertEqual(result["connection"]["state"], "RESTART_REQUIRED")
        before = {n: b for n, b in self.protected().items() if n != ".harness/integration-status.json"}
        self.install()
        self.assertEqual(self.cli("init").returncode, 0)
        self.assertTrue(all((self.target / n).read_bytes() == b for n, b in before.items()))
        self.assert_owned_preserved()
        hooks = boot.read(self.target / ".codex/hooks.json")
        commands = [h["command"] for g in hooks["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(len(commands), 2)
        self.assertIn("product-owned-hook", commands)
        self.assertNotIn(str(ROOT), json.dumps(hooks))
        self.assertFalse(Path(result["installation"]["code_path"]).is_absolute())
        self.assertEqual(git("check-ignore", ".kmp-agent/releases/" + self.first + "/VERSION", cwd=self.target),
                         ".kmp-agent/releases/" + self.first + "/VERSION")
        visible = git("ls-files", "--others", "--exclude-standard", cwd=self.target)
        for name in [".kmp-agent/installation.json", ".kmp-agent/project.json", ".kmp-agent/agent.py", ".codex/hooks.json"]:
            self.assertIn(name, visible)
        self.assertNotIn(".kmp-agent/releases/", visible)

    def test_exact_commit_install_and_explicit_update_via_project_entry(self):
        original_project_id = self.install(self.first)["installation"]["project_id"]
        hook_before = (self.target / ".codex/hooks.json").read_bytes()
        missing_ref = self.cli("update")
        self.assertEqual(missing_ref.returncode, 1)
        self.assertEqual(boot.read(self.target / boot.MANIFEST)["commit"], self.first)
        result = self.cli("update", "--ref", "v0.1.1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = boot.read(self.target / boot.MANIFEST)
        self.assertEqual(manifest["project_id"], original_project_id)
        self.assertEqual(manifest["project_id"], boot.read(self.target / ".kmp-agent/project.json")["project_id"])
        self.assertEqual(manifest["commit"], self.second)
        self.assertEqual(manifest["previous"]["commit"], self.first)
        self.assertEqual((self.target / ".codex/hooks.json").read_bytes(), hook_before)
        self.assertTrue((self.target / ".kmp-agent/releases" / self.first).exists())
        self.assert_owned_preserved()
        status = self.cli("status")
        self.assertEqual(status.returncode, 1)  # No real session proof, not falsely active.
        info = json.loads(status.stdout)
        self.assertEqual(info["runtime_identity"]["version"], "0.1.1")
        self.assertEqual(info["runtime_identity"]["commit"], self.second)
        self.assertFalse(info["runtime_identity"]["dirty"])

    def test_product_checkout_excludes_development_files_and_keeps_runtime_identity(self):
        # Product-owned tests/fixtures are not part of the common tool checkout.
        product_test = self.target / "test_product.py"
        product_test.write_text("product test remains\n")
        manifest = self.install()["installation"]
        code = self.target / manifest["code_path"]
        self.assertEqual(manifest["file_profile"], "product-v1")
        self.assertFalse(list((code / "harness").glob("test_*.py")))
        for name in ("docs/examples", "docs/retrospective.md", "docs/memo-real-trial-request.md",
                     "tools/dev-check.py", "harness/run_tests.py", "harness/trial.py",
                     "harness/role_trial.py", "harness/star_trial.py", "harness/role_example_worker.py",
                     "harness/dashboard_fixture.py", "harness/request_link_render_check.js"):
            self.assertFalse((code / name).exists(), name)
            self.assertTrue((self.source / name).exists(), name)
        for name in ("harness/roles.py", "harness/qa.py", "harness/dashboard_assets/app.js",
                     "docs/roles/development.md", "docs/templates/design.md",
                     ".agents/skills/fixture-skill/SKILL.md", "tools/check_pr_scope.py"):
            self.assertTrue((code / name).is_file(), name)
        self.assertEqual(git("rev-parse", "HEAD", cwd=code), self.first)
        self.assertEqual(git("status", "--porcelain", cwd=code), "")
        self.assertEqual(boot.validate(code, self.first), "0.1.0")
        self.assert_owned_preserved()
        status = json.loads(self.cli("status").stdout)
        self.assertEqual(status["runtime_identity"]["commit"], self.first)
        self.assertFalse(status["runtime_identity"]["dirty"])
        self.assertEqual(self.cli("task", "--operation", "show").returncode, 0)
        # A cold process must resolve role definitions, QA and dashboard imports
        # using only the installed files, never this developer test checkout.
        smoke = subprocess.run(["rtk", "proxy", sys.executable, "-B", "-c", """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from harness.roles import Roles, CODE
from harness.qa import validate_result
from harness.dashboard import snapshot
assert CODE == Path(sys.argv[1])
roles = Roles(sys.argv[2], "filtered-runtime-smoke")
roles.tasks.register("F", "P", "planning", "product planning", "fixture only",
                     [{"id": "C", "required": True, "text": "input read"}], ["docs/requirements.md"])
roles.setup("P", "feature")
packet = roles.prepare("P", "planning")
packet = json.loads((Path(sys.argv[2]) / packet["context"]).read_text())
assert "docs/roles/planning.md" in {d["path"] for d in packet["definitions"]}
validate_result({"criteria": [], "findings": [], "recommendation": "NOT_RUN",
                 "summary": "model-free runtime smoke", "reviewed_issue_ids": []})
assert isinstance(snapshot(sys.argv[2]), dict)
""", str(code), str(self.target)], cwd=self.target, text=True, capture_output=True)
        self.assertEqual(smoke.returncode, 0, smoke.stdout + smoke.stderr)
        checker = subprocess.run(["rtk", "proxy", sys.executable, str(code / "tools/check_pr_scope.py"), "--help"],
                                 cwd=self.target, capture_output=True)
        self.assertEqual(checker.returncode, 0, checker.stderr)
        self.assertEqual(product_test.read_text(), "product test remains\n")
        (code / "VERSION").write_text("9.9.9\n")
        with self.assertRaisesRegex(ValueError, "differs from its pinned Git commit"):
            boot.validate(code, self.first)

    def test_legacy_full_checkout_preserved_and_new_update_uses_product_profile(self):
        manifest = self.install()["installation"]
        old_code = self.target / manifest["code_path"]
        git("sparse-checkout", "disable", cwd=old_code)
        self.assertTrue((old_code / "harness/test_installation.py").exists())
        self.assertEqual(boot.file_profile(old_code, "installed"), "full-checkout")
        repeated = self.install()  # Reuse the existing release, no destructive pruning.
        self.assertEqual(repeated["installation"]["file_profile"], "full-checkout")
        self.assertTrue((old_code / "harness/test_installation.py").exists())
        result = self.cli("update", "--ref", "v0.1.1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated = boot.read(self.target / boot.MANIFEST)
        self.assertEqual(updated["file_profile"], "product-v1")
        new_code = self.target / updated["code_path"]
        self.assertFalse((new_code / "harness/test_installation.py").exists())
        self.assertTrue((old_code / "harness/test_installation.py").exists())
        self.assert_owned_preserved()

    def test_missing_legacy_checkout_restores_actual_product_profile(self):
        manifest = self.install()["installation"]
        code = self.target / manifest["code_path"]
        git("sparse-checkout", "disable", cwd=code)
        repeated = self.install()["installation"]
        self.assertEqual(repeated["file_profile"], "full-checkout")
        shutil.rmtree(code)  # Simulate loss of the ignored tool checkout only.
        restored = self.install()["installation"]
        self.assertEqual(restored["file_profile"], "product-v1")
        self.assertFalse((code / "harness/test_installation.py").exists())
        self.assertEqual(git("status", "--porcelain", cwd=code), "")
        self.assert_owned_preserved()

    def test_first_install_command_works_without_an_existing_project_tool(self):
        result = subprocess.run(["rtk", "proxy", sys.executable, str(ROOT / "bootstrap.py"), "install",
                                 "--source", self.url, "--ref", "v0.1.0", "--target", str(self.target)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["installation"]["commit"], self.first)
        self.assert_owned_preserved()

    def test_documented_bootstrap_acquisition_from_pinned_tag(self):
        checkout = Path(self.temp.name) / "bootstrap checkout"
        git("clone", "--quiet", "--no-checkout", self.url, checkout)
        git("-C", checkout, "fetch", "--quiet", "origin", "refs/tags/v0.1.0")
        git("-C", checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        self.assertEqual(git("rev-parse", "HEAD", cwd=checkout), self.first)
        self.assertFalse((self.target / ".kmp-agent").exists())
        result = subprocess.run(["rtk", "proxy", sys.executable, str(checkout / "bootstrap.py"),
                                 "install", "--source", self.url, "--ref", "v0.1.0",
                                 "--target", str(self.target)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["installation"]["version"], "0.1.0")
        self.assertEqual(json.loads(result.stdout)["installation"]["commit"], self.first)
        self.assert_owned_preserved()

    def test_repeated_install_init_failure_rolls_back_settings(self):
        self.install()
        before = self.protected()
        original = boot.init
        def failure(target, code):
            original(target, code)
            raise ValueError("synthetic repeated-init failure")
        boot.init = failure
        try:
            with self.assertRaises(ValueError):
                self.install()
        finally:
            boot.init = original
        self.assertEqual(self.protected(), before)
        self.assertFalse((self.target / boot.JOURNAL).exists())
        self.assert_owned_preserved()

    def test_standalone_init_failure_rolls_back_settings(self):
        import contextlib
        import io
        self.install()
        before = self.protected()
        cli = boot.load(ROOT / "harness/cli.py", "reviewed_cli")
        original_init, original_argv = cli.bootstrap.init, sys.argv
        def failure(target, code):
            original_init(target, code)
            raise ValueError("synthetic standalone-init failure")
        cli.bootstrap.init = failure
        try:
            sys.argv = ["cli.py", "--target", str(self.target), "init"]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = cli.main()
            self.assertEqual(result, 1, output.getvalue())
        finally:
            cli.bootstrap.init, sys.argv = original_init, original_argv
        self.assertEqual(self.protected(), before)
        self.assertFalse((self.target / boot.JOURNAL).exists())
        self.assert_owned_preserved()

    def test_malformed_identity_objects_return_unknown_and_reject_init(self):
        self.install()
        context = boot.load(ROOT / "harness/context.py", "reviewed_identity")
        for relative in (".harness/project.json", ".kmp-agent/installation.json"):
            path = self.target / relative
            previous = path.read_bytes() if path.exists() else None
            path.write_text("[]")
            try:
                self.assertEqual(context.identify(self.target)["project_id"], "UNKNOWN")
                with self.assertRaises(ValueError):
                    context.prepare(self.target)
            finally:
                if previous is None:
                    path.unlink()
                else:
                    path.write_bytes(previous)

    def test_bad_ref_and_invalid_release_leave_healthy_installation_intact(self):
        self.install()
        before = self.protected()
        for ref in ("missing-tag", "invalid-release", "main"):
            with self.assertRaises((ValueError, SyntaxError)):
                self.install(ref, update=True)
            self.assertEqual(self.protected(), before)
            self.assert_owned_preserved()
        self.assertEqual(list((self.target / ".kmp-agent/releases").glob(".staging-*")), [])

    def test_init_failure_rolls_back_all_managed_files_and_then_can_retry(self):
        self.install()
        before = self.protected()
        original = boot.init
        def failure(target, code):
            original(target, code)
            raise ValueError("synthetic post-init failure")
        boot.init = failure
        try:
            with self.assertRaises(ValueError):
                self.install("v0.1.1", update=True)
        finally:
            boot.init = original
        self.assertEqual(self.protected(), before)
        self.assertFalse((self.target / boot.JOURNAL).exists())
        self.assert_owned_preserved()
        self.assertEqual(self.install("v0.1.1", update=True)["installation"]["commit"], self.second)

    def test_interrupted_transaction_recover_restores_settings_not_logs(self):
        self.install()
        before = self.protected()
        boot.save(self.target / boot.JOURNAL, {"snapshot": boot.capture(self.target, [])})
        (self.target / "AGENTS.md").write_text("synthetic interrupted update")
        boot.save(self.target / boot.MANIFEST, {"synthetic": "interrupted"})
        self.assertEqual(json.loads(self.cli("status").stdout)["state"], "RECOVERY_REQUIRED")
        result = self.cli("recover")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.protected(), before)
        self.assert_owned_preserved()

    def test_failure_preserves_concurrent_edit_and_requires_review_before_recovery(self):
        self.install()
        old_agents = (self.target / "AGENTS.md").read_bytes()
        original = boot.init
        def failure(target, code):
            original(target, code)
            (target / "AGENTS.md").write_text("concurrent product edit must survive")
            raise ValueError("synthetic failure after concurrent edit")
        boot.init = failure
        try:
            with self.assertRaises(ValueError):
                self.install("v0.1.1", update=True)
        finally:
            boot.init = original
        self.assertEqual((self.target / "AGENTS.md").read_text(), "concurrent product edit must survive")
        self.assertEqual(boot.read(self.target / boot.MANIFEST)["commit"], self.first)
        self.assertTrue((self.target / boot.JOURNAL).exists())
        self.assertEqual(json.loads(self.cli("status").stdout)["state"], "RECOVERY_REQUIRED")
        (self.target / "AGENTS.md").write_bytes(old_agents)  # Explicit synthetic user resolution.
        self.assertEqual(self.cli("recover").returncode, 0)
        self.assert_owned_preserved()

    def test_selected_skill_update_retargets_only_managed_link(self):
        self.install()
        boot.save(self.target / ".kmp-agent/project.json", {"skills": ["fixture-skill"], "product_note": "keep"})
        self.assertEqual(self.cli("init").returncode, 0)
        link = self.target / ".agents/skills/fixture-skill"
        self.assertIn(self.first, str(link.resolve()))
        self.install("v0.1.1", update=True)
        self.assertIn(self.second, str(link.resolve()))
        self.assertEqual(boot.read(self.target / ".kmp-agent/project.json")["product_note"], "keep")

    def test_project_id_survives_update_move_and_restoring_an_ignored_checkout(self):
        first = self.install()["installation"]
        self.install("v0.1.1", update=True)
        self.assertEqual(boot.read(self.target / boot.MANIFEST)["project_id"], first["project_id"])
        old = self.target
        moved = old.parent / "relocated project"
        shutil.move(old, moved)
        self.target = moved
        self.owned = {moved / p.relative_to(old): b for p, b in self.owned.items()}
        self.assertEqual(self.cli("init").returncode, 0)
        shutil.rmtree(self.target / ".kmp-agent/releases")  # Simulate a product clone without ignored code.
        restored = boot.install(self.target, self.url, "v0.1.1")["installation"]
        self.assertEqual(restored["project_id"], first["project_id"])
        self.assertEqual(restored["commit"], self.second)
        self.assert_owned_preserved()

    def test_existing_project_id_is_reused_and_legacy_logs_stay_unknown(self):
        boot.save(self.target / ".harness/project.json", {"project_id": "legacy-project-id", "project_path": ".."})
        installed = self.install()["installation"]
        self.assertEqual(installed["project_id"], "legacy-project-id")
        logger = boot.load(self.target / installed["code_path"] / "harness/logging.py", "fixture_logger_legacy")
        log = logger.Logger(self.target)
        self.assertNotIn("project_id", log.read()[0])
        self.assertEqual(log.status()["legacy_events_without_project_id"], 1)
        self.assert_owned_preserved()

    def test_child_events_inherit_run_project_context_without_manual_id(self):
        installed = self.install()["installation"]
        logger = boot.load(self.target / installed["code_path"] / "harness/logging.py", "fixture_logger_context")
        log = logger.Logger(self.target)
        run = log.start("HARNESS_BUILD", "verification", "synthetic target context")
        config_path = self.target / ".kmp-agent/project.json"
        config = boot.read(config_path)
        boot.save(config_path, {**config, "project_path": "../wrong-target"})
        child = logger.Logger(self.target)
        self.assertEqual(child.context["project_id"], "UNKNOWN")
        event = child.append("synthetic_child", run)
        self.assertEqual(event["project_id"], installed["project_id"])
        self.assertEqual(event["verification_scope"], "target_project")
        boot.save(config_path, config)

    def test_missing_identity_is_unknown_with_reason_and_never_generated_by_logger(self):
        logger = boot.load(ROOT / "harness/logging.py", "fixture_logger_unknown")
        event = logger.Logger(self.target).append("synthetic_unknown")
        self.assertEqual(event["project_id"], "UNKNOWN")
        self.assertEqual(event["execution_context"]["project_id_reason"], "project_connection_settings_missing")
        self.assertFalse((self.target / ".kmp-agent/project.json").exists())

    def test_identity_conflict_is_reported_without_reassigning_the_project(self):
        installed = self.install()["installation"]
        path = self.target / ".kmp-agent/project.json"
        config = boot.read(path)
        boot.save(path, {**config, "project_id": "another-project"})
        result = json.loads(self.cli("status").stdout)
        self.assertEqual(result["project_id"], "UNKNOWN")
        self.assertEqual(result["project_id_reason"], "installation_project_id_mismatch")
        self.assertEqual(self.cli("init").returncode, 1)
        self.assertEqual(boot.read(self.target / boot.MANIFEST)["project_id"], installed["project_id"])
        boot.save(path, config)
        self.assert_owned_preserved()

    def test_unknown_install_metadata_does_not_prevent_recording_runtime_facts(self):
        installed = self.install()["installation"]
        logger = boot.load(self.target / installed["code_path"] / "harness/logging.py", "fixture_logger_bad_manifest")
        boot.save(self.target / boot.MANIFEST, {"broken": True})
        event = logger.Logger(self.target).append("synthetic_observed_runtime")
        self.assertEqual(event["harness"]["mode"], "UNKNOWN")
        self.assertEqual(event["harness"]["commit"], installed["commit"])
        self.assertEqual(event["project_id"], installed["project_id"])
        boot.save(self.target / boot.MANIFEST, installed)

    def test_mock_hook_and_runtime_log_identity_use_installed_code_and_project_logs(self):
        installed = self.install()["installation"]
        source = self.target / ".harness/synthetic-session.jsonl"
        source.write_text("".join(json.dumps(e) + "\n" for e in [
            {"timestamp": datetime.now(timezone.utc).isoformat(), "ordinal": 0, "type": "session_meta", "payload": {"id": "synthetic-session"}},
            {"ordinal": 1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "synthetic-turn"}},
            {"ordinal": 2, "type": "response_item", "payload": {"type": "message", "role": "user", "id": "synthetic-message", "content": [{"text": "synthetic fixture request"}]}}]))
        payload = {"cwd": str(self.target), "session_id": "synthetic-session", "turn_id": "synthetic-turn", "transcript_path": str(source)}
        for event in ("UserPromptSubmit", "Stop", "Stop"):
            result = self.cli("hook", input=json.dumps({**payload, "hook_event_name": event}))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [json.loads(s) for s in (self.target / ".harness/logs/events.jsonl").read_text().splitlines()]
        messages = [e for e in rows if e.get("observed", {}).get("message_id") == "synthetic-message"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["harness"]["version"], "0.1.0")
        self.assertEqual(messages[0]["harness"]["commit"], installed["commit"])
        self.assertEqual(messages[0]["harness"]["mode"], "installed")
        code = (self.target / installed["code_path"]).resolve()
        self.assertFalse((code / ".harness/logs/events.jsonl").exists())

    def test_development_mode_records_dirty_source_without_copying(self):
        # Invalid fixture commit is repaired only in its working tree, making dirty explicit.
        source = self.base / "synthetic-dev-copy"
        git("clone", "--quiet", self.remote, source)
        git("checkout", "--quiet", "v0.1.0", cwd=source)
        (source / "README.md").write_text("synthetic dirty source")
        try:
            installed = boot.install(self.target, development=source)["installation"]
            self.assertEqual(installed["mode"], "development")
            result = self.cli("status")
            self.assertTrue(json.loads(result.stdout)["runtime_identity"]["dirty"])
            self.assertFalse((self.target / ".kmp-agent/releases").exists())
        finally:
            shutil.rmtree(source)


if __name__ == "__main__":
    unittest.main()
