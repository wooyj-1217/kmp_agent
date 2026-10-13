import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("harness_tasks", Path(__file__).with_name("tasks.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.md").write_text("synthetic input")
        (self.root / "output.md").write_text("synthetic output")
        (self.root / "review.md").write_text("synthetic review evidence")
        self.run = module.logging.Logger(self.root).start("HARNESS_BUILD", "orchestrator", "synthetic task tests")
        self.tasks = module.Tasks(self.root, self.run)

    def register(self, task_id="TASK-001", role="planning", deps=None, visual=False):
        return self.tasks.register("FEAT-001", task_id, role, "synthetic", "document only",
                                   [{"id": "FEAT-001-AC-001", "required": True, "text": "synthetic criterion"}],
                                   ["input.md"], dependencies=deps, visual_required=visual)

    def submit(self, task_id="TASK-001", role="planning", design_status=None):
        self.tasks.ready(task_id)
        run = self.tasks.begin(task_id, role)
        self.tasks.submit(task_id, run["agent_run_id"], ["output.md"], "synthetic submit", design_status)
        return run

    def review(self, task_id="TASK-001", result="PASS"):
        reviewer = self.tasks.begin(task_id, "verification", review=True)
        state = self.tasks.review(task_id, reviewer["agent_run_id"],
                                  [{"criterion_id": "FEAT-001-AC-001", "result": result, "evidence": "review.md"}], "synthetic review")
        return state

    def test_planning_review_handoff_and_log_ids(self):
        self.register()
        self.register("TASK-002", "design", ["TASK-001"])
        with self.assertRaises(ValueError):
            self.tasks.ready("TASK-002")
        work = self.submit()
        self.assertEqual(self.review(), "DONE")
        handoff = self.tasks.handoff("TASK-001", "TASK-002")
        state = self.tasks.read()
        self.assertEqual(state["tasks"]["TASK-002"]["state"], "READY")
        self.assertEqual(handoff["artifacts"], state["tasks"]["TASK-001"]["outputs"])
        related = [e for e in self.tasks.logger.read() if e["event_type"] == "agent_run_started"]
        self.assertTrue(all(e["feature_id"] == "FEAT-001" and e["task_id"] == "TASK-001" and e["run_id"] == self.run for e in related))
        self.assertEqual(related[0]["agent_run_id"], work["agent_run_id"])

    def test_fail_not_run_and_budget(self):
        for result in ("FAIL", "NOT_RUN"):
            task_id = "TASK-" + result
            self.register(task_id)
            self.submit(task_id)
            self.assertEqual(self.review(task_id, result), "BLOCKED")
            with self.assertRaises(ValueError):
                self.tasks.ready(task_id)

    def test_no_visual_completion_from_specification(self):
        self.register(role="design", visual=True)
        self.submit(role="design", design_status={"specification": "COMPLETE", "mockup": "NOT_PRODUCED", "visual_review": "NOT_RUN"})
        self.assertEqual(self.review(), "BLOCKED")
        self.assertEqual(self.tasks.read()["tasks"]["TASK-001"]["design_status"]["visual_review"], "NOT_RUN")

    def test_document_only_done_keeps_visual_not_run(self):
        self.register(role="design", visual=False)
        self.submit(role="design", design_status={"specification": "COMPLETE", "mockup": "NOT_PRODUCED", "visual_review": "NOT_RUN"})
        self.assertEqual(self.review(), "DONE")
        status = self.tasks.read()["tasks"]["TASK-001"]["design_status"]
        self.assertEqual(status["visual_review"], "NOT_RUN")
        self.assertEqual(status["mockup"], "NOT_PRODUCED")

    def test_usage_binding_is_explicit_and_exclusive(self):
        self.register()
        work = self.submit()
        self.register("TASK-002")
        second = self.submit("TASK-002")
        self.tasks.logger.append("model_usage", observed={"response_id": "synthetic-response", "usage": {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2, "total_tokens": 12}}, source={"kind": "synthetic_fixture", "session_id": "synthetic-session"})
        self.tasks.bind_usage("TASK-001", work["agent_run_id"], "synthetic-session", "synthetic-response", "synthetic attribution")
        self.assertFalse(self.tasks.bind_usage("TASK-001", work["agent_run_id"], "synthetic-session", "synthetic-response", "repeat"))
        with self.assertRaises(ValueError):
            self.tasks.bind_usage("TASK-002", second["agent_run_id"], "synthetic-session", "synthetic-response", "duplicate")
        report = self.tasks.report()["tasks"]
        self.assertEqual(report["TASK-001"]["executions"][0]["model_usage"]["total_tokens"], 12)
        self.assertEqual(report["TASK-001"]["executions"][0]["model_usage"]["cached_input_tokens"], 4)
        self.assertEqual(report["TASK-002"]["executions"][0]["model_usage"]["input_tokens"], "UNKNOWN")
        self.assertEqual(self.tasks.report()["features"]["FEAT-001"]["known_subtotal"]["total_tokens"], 12)
        self.assertEqual(report["TASK-001"]["usage_summary"]["full_task_usage"], "UNKNOWN")

    def test_outbox_recovery_and_frozen_input(self):
        self.register()
        task = self.tasks.read()["tasks"]["TASK-001"]
        (self.root / "input.md").write_text("changed source; snapshot stays fixed")
        snapshot = self.root / task["inputs"][0]["snapshot"]
        self.assertEqual(snapshot.read_text(), "synthetic input")
        state = json.loads(self.tasks.path.read_text())
        self.tasks._event(state, "synthetic_recovery", task)
        self.tasks._save(state)
        self.tasks.read()
        count = len(self.tasks.logger.read())
        self.tasks.read()
        self.assertEqual(len(self.tasks.logger.read()), count)
        self.assertEqual(sum(e["event_type"] == "synthetic_recovery" for e in self.tasks.logger.read()), 1)

    def test_missing_evidence_and_policy_shortcuts_rejected(self):
        self.register()
        self.submit()
        with self.assertRaises(ValueError):
            self.tasks.begin("TASK-001", "planning", review=True)
        reviewer = self.tasks.begin("TASK-001", "verification", review=True)
        with self.assertRaises(ValueError):
            self.tasks.review("TASK-001", reviewer["agent_run_id"], [{"criterion_id": "FEAT-001-AC-001", "result": "PASS"}], "no evidence")
        self.assertEqual(self.tasks.read()["tasks"]["TASK-001"]["state"], "IN_REVIEW")


if __name__ == "__main__":
    unittest.main()
