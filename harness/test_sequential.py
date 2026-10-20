"""Synthetic evidence in disposable projects only; no production history enrichment."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bootstrap
from harness.tasks import Tasks
from harness.logging import Logger
from harness import sequential as seq

ROOT = Path(__file__).resolve().parents[1]


class SequentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name, value in {"input.md": "input", "output.md": "output", "decision.md": "decision"}.items():
            (self.root / name).write_text(value)
        self.logger = Logger(self.root)
        self.run_id = self.logger.start("PRODUCT", "orchestrator", "synthetic sequential collection")
        self.tasks = Tasks(self.root, self.run_id)

    def register(self, tid="T", deps=None):
        return self.tasks.register("F", tid, "planning", "fixture", "docs", [{"id": "AC", "required": True}],
                                   ["input.md"], dependencies=deps)

    def start(self, tid="T"):
        self.tasks.ready(tid)
        return self.tasks.begin(tid, "planning")

    def test_dependencies_order_only_does_not_gate_or_infer(self):
        self.register("A")
        self.register("B")
        self.tasks.configure_collection("B", dependency_relations=[{"task_id": "A", "kind": "ORDER_ONLY", "reason": "operator preference"}],
                                        shared_modules=[], shared_resources="UNKNOWN")
        self.start("B")  # A remains TODO; order-only is not a data dependency.
        self.assertEqual(self.tasks.read()["tasks"]["A"]["state"], "TODO")
        self.register("C", ["A"])
        with self.assertRaises(ValueError):
            self.tasks.configure_collection("C", dependency_relations=[])
        with self.assertRaises(ValueError):
            self.tasks.ready("C")
        self.assertEqual(seq.report(self.root)["tasks"]["A"]["dependencies"]["status"], "MISSING")

    def test_attempt_wait_file_delta_and_unknown_actor(self):
        seq.save_settings(self.root, {"schema_version": 1, "modules": {"docs": ["output.md"]}})
        self.register()
        self.tasks.configure_collection("T", dependency_relations=[], shared_modules=["docs"], shared_resources=[], feature_version="feature-r1")
        run = self.start()
        self.tasks.checkpoint("T", run["agent_run_id"], "approval", "input.md", wait_type="DECISION", wait_target="approval-1")
        self.tasks.resume("T", run["agent_run_id"], "decision.md")
        (self.root / "output.md").write_text("changed")
        self.tasks.submit("T", run["agent_run_id"], ["output.md"], "done")
        current = self.tasks.read()["tasks"]["T"]["executions"][0]
        self.assertEqual(current["attempt_id"], run["agent_run_id"])
        self.assertEqual(current["waits"][0]["outcome"], "RELEASED")
        self.assertIsNotNone(current["waits"][0]["ended_at"])
        self.assertEqual(current["collection"]["modification_actor"], "UNKNOWN")
        self.assertEqual(current["collection"]["observed_modules"]["output.md"], ["docs"])
        self.assertEqual([f["path"] for f in current["collection"]["changed_files"]], ["output.md"])
        report = seq.report(self.root)["tasks"]["T"]["executions"][0]
        self.assertEqual(report["harness"]["status"], "COLLECTED")
        self.assertTrue(report["baseline_id"]["value"].startswith("sha256:"))
        self.assertEqual(report["feature_version"]["value"], "feature-r1")

    def test_named_command_timing_link_failure_and_unlinked(self):
        seq.save_settings(self.root, {"schema_version": 1, "commands": {"check": {
            "kind": "test", "argv": ["rtk", "proxy", sys.executable, "-c", "raise SystemExit(7)"]}}})
        self.register()
        run = self.start()
        self.assertEqual(self.logger.command(self.run_id, task_id="T", agent_run_id=run["agent_run_id"],
                         attempt_id=run["attempt_id"], command_name="check"), 7)
        self.assertEqual(self.logger.command(self.run_id, ["rtk", "proxy", sys.executable, "-c", "pass"]), 0)
        report = seq.report(self.root)
        linked, unlinked = report["commands"]
        self.assertEqual(linked["returncode"]["value"], 7)
        self.assertEqual(linked["kind"]["value"], "test")
        self.assertGreaterEqual(linked["elapsed_seconds"]["value"], 0)
        self.assertEqual(linked["link"]["status"], "COLLECTED")
        self.assertEqual(unlinked["task_id"], "UNKNOWN")
        self.assertEqual(report["commands_without_links"], 1)
        self.assertEqual(report["commands_outside_wrapper"], "UNKNOWN")
        with self.assertRaises(ValueError):
            self.logger.command(self.run_id, ["rtk", "true"], task_id="T")
        with self.assertRaises(ValueError):
            self.logger.command(self.run_id, ["rtk", "true"], task_id="T", agent_run_id=run["agent_run_id"], attempt_id="wrong")

    def test_missing_command_finish_is_not_zero(self):
        self.logger.append("command_started", self.run_id, observed={"call_id": "interrupted", "started_at": "observed"})
        command = seq.report(self.root)["commands"][0]
        self.assertEqual(command["ended_at"]["status"], "MISSING")
        self.assertEqual(command["returncode"]["value"], "UNKNOWN")

    def test_fail_closes_wait_as_cancelled_and_records_delta(self):
        self.register()
        run = self.start()
        self.tasks.checkpoint("T", run["agent_run_id"], "waiting", "input.md")
        with self.assertRaises(ValueError):
            self.logger.command(self.run_id, ["rtk", "true"], task_id="T", agent_run_id=run["agent_run_id"], attempt_id=run["attempt_id"])
        self.tasks.fail("T", run["agent_run_id"], "cancel")
        current = self.tasks.read()["tasks"]["T"]["executions"][0]
        self.assertEqual(current["waits"][0]["outcome"], "CANCELLED")
        self.assertEqual(current["waits"][0]["type"], "UNKNOWN")
        self.assertEqual(current["collection"]["changed_files"], [])

    def test_integration_links_existing_cr_and_preserves_evidence(self):
        self.register()
        run = self.start()
        def fixture(state):
            state["deliverables"] = {"feature": {"changes": [{"id": "CR-001", "impacts": {"tasks": ["T"]}}]}}
        self.tasks._mutate("synthetic_cr", fixture)
        record = self.tasks.integration("T", run["agent_run_id"], kind="CONFLICT", reason="actual synthetic conflict",
            evidence="input.md", cr={"folder": "feature", "id": "CR-001"}, conflict_files=["output.md"])
        self.assertEqual(record["before_commit"], "UNKNOWN")
        self.assertTrue(self.tasks._valid_artifact(record["evidence"]))
        with self.assertRaises(ValueError):
            self.tasks.integration("T", run["agent_run_id"], kind="REWORK", reason="fixture", evidence="input.md",
                                   cr={"folder": "feature", "id": "CR-missing"})

    def test_legacy_history_readonly_and_no_backfill(self):
        self.register()
        run = self.start()
        state = json.loads(self.tasks.path.read_text())
        historical = state["tasks"]["T"]["executions"][0]
        historical.pop("collection")
        historical.pop("attempt_id")
        self.tasks._save(state)
        before = self.tasks.path.read_bytes()
        events = self.logger.path.read_bytes()
        result = seq.report(self.root)["tasks"]["T"]["executions"][0]
        self.assertEqual(result["files"]["status"], "MISSING")
        self.assertEqual(result["harness"]["status"], "MISSING")
        self.assertEqual(self.tasks.path.read_bytes(), before)
        self.assertEqual(self.logger.path.read_bytes(), events)
        self.tasks.submit("T", run["agent_run_id"], ["output.md"], "legacy remains supported")
        self.assertNotIn("collection", self.tasks.read()["tasks"]["T"]["executions"][0])

    def test_settings_reject_escape_and_no_auto_execution(self):
        with self.assertRaises(ValueError):
            seq.save_settings(self.root, {"schema_version": 1, "commands": {"bad": {"kind": "build", "argv": ["rtk", "true"], "cwd": "../other"}}})
        saved = seq.save_settings(self.root, {"schema_version": 1, "modules": {"m": ["src"]}})
        self.assertFalse(saved["automatic_execution"])

    def test_late_declaration_is_not_a_rewritten_start(self):
        self.register()
        run = self.start()
        with self.assertRaises(ValueError):
            self.tasks.configure_collection("T", shared_modules=["docs"])
        self.tasks.configure_collection("T", agent_run_id=run["agent_run_id"], shared_modules=["docs"], shared_resources="UNKNOWN")
        with self.assertRaises(ValueError):
            self.tasks.configure_collection("T", agent_run_id=run["agent_run_id"], feature_version="invented-later")
        current = self.tasks.read()["tasks"]["T"]["executions"][0]
        self.assertNotIn("shared_modules", current["collection"])
        self.assertEqual(current["collection_declarations"][0]["shared_modules"], ["docs"])


class TemporaryProjectCLI(unittest.TestCase):
    def test_init_task_command_coverage_and_init_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "applied project"
            root.mkdir()
            subprocess.run(["rtk", "proxy", "git", "init", "-q", str(root)], check=True)
            (root / "input.md").write_text("synthetic input")
            (root / "output.md").write_text("synthetic output")
            (root / "src").mkdir()
            (root / "src/app.py").write_text("value = 1\n")
            (root / ".gitignore").write_text(".harness/\n.kmp-agent/\n.codex/\n")
            def git(*args):
                return subprocess.run(["rtk", "proxy", "git", *args], cwd=root, check=True, capture_output=True)
            git("add", ".")
            git("-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-qm", "disposable baseline")
            bootstrap.install(root, development=ROOT)
            env = {k: v for k, v in os.environ.items() if k != "CODEX_THREAD_ID"}
            def cli(action, **options):
                argv = ["rtk", "proxy", sys.executable, "-B", str(root / ".kmp-agent/agent.py"), action]
                for name, value in options.items():
                    argv.extend(["--" + name.replace("_", "-"), str(value)])
                proc = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                return json.loads(proc.stdout)
            config = Path(temporary) / "settings.json"
            config.write_text(json.dumps({"schema_version": 1, "modules": {"app": ["src"]}, "commands": {
                "test": {"kind": "test", "argv": ["rtk", "proxy", sys.executable, "-c", "pass"]}}}))
            cli("init", tracking_settings=config)
            settings_before = (root / seq.SETTINGS).read_bytes()
            cli("init")
            self.assertEqual((root / seq.SETTINGS).read_bytes(), settings_before)
            run_id = cli("start", request="synthetic applied project run")["run_id"]
            def task(operation, data):
                path = Path(temporary) / "operation.json"
                path.write_text(json.dumps(data))
                return cli("task", operation=operation, data=path, run_id=run_id)
            task("register", {"feature_id": "F", "task_id": "T", "role": "development", "execution_scope": "code_implementation",
                "title": "synthetic", "scope": "code", "criteria": [{"id": "AC", "required": True}], "inputs": ["input.md"]})
            task("configure-development", {"task_id": "T", "baselines": {"planning": "input.md"}, "code_paths": ["src"]})
            task("configure-collection", {"task_id": "T", "dependency_relations": [], "shared_modules": ["app"], "shared_resources": []})
            task("ready", {"task_id": "T"})
            run = task("begin", {"task_id": "T", "role": "development"})
            cli("command", run_id=run_id, task_id="T", agent_run_id=run["agent_run_id"], attempt_id=run["attempt_id"], command_name="test")
            (root / "src/app.py").write_text("value = 2\n")
            task("submit", {"task_id": "T", "agent_run_id": run["agent_run_id"], "outputs": ["src/app.py"], "summary": "synthetic"})
            result = cli("collection-report")
            self.assertEqual(result["commands_without_links"], 0)
            self.assertEqual(result["commands"][0]["returncode"]["value"], 0)
            execution = result["tasks"]["T"]["executions"][0]
            self.assertEqual(execution["files"]["value"][0]["path"], "src/app.py")
            self.assertEqual(execution["observed_modules"]["value"]["src/app.py"], ["app"])
            self.assertEqual(execution["modification_actor"], "UNKNOWN")
            self.assertEqual(result["parallelization_verdict"], "NOT_EVALUATED")
            self.assertTrue((root / ".harness/logs/sequential-coverage.json").is_file())
            self.assertEqual(execution["harness"]["value"]["mode"], "development")
            cli("finish", run_id=run_id, result="synthetic complete")
            bootstrap.install(root, development=ROOT, update=True)
            self.assertEqual((root / seq.SETTINGS).read_bytes(), settings_before)


if __name__ == "__main__":
    unittest.main()
