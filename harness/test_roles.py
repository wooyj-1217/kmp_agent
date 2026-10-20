import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.roles import Roles, CODE
from harness.deliverables import change, restore
from harness.design_assets import validate


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.md").write_text("Synthetic example; not product approval")
        self.roles = Roles(self.root, "synthetic-run")
        self.tasks = self.roles.tasks

    def register(self, tid="P1", role="planning", deps=None, planning=None, cr=None, attempts=2):
        self.tasks.register("F", tid, role, "synthetic", "fixture test", [{"id": "C", "required": True, "text": "content checked by reviewer"}], ["input.md"], deps, attempts, visual_required=role == "design")
        self.roles.setup(tid, "feature", planning, cr)

    def execute(self, tid, role):
        return self.roles.execute(tid, role, [sys.executable, str(CODE / "harness/role_example_worker.py")])

    def review(self, tid, design=False, result="PASS", stale=False):
        task = self.tasks.read()["tasks"][tid]
        (self.root / "evidence.md").write_text("Synthetic semantic review fixture")
        checks = None
        if design:
            checks = {}
            (self.root / "capture.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-fixture-NOT-real-browser")
            for kind in ("structure", "interaction", "visual"):
                report = {"kind": kind, "result": result, "tested_outputs": {} if stale else {a["path"]: a["sha256"] for a in task["outputs"]}, "screenshots": ["capture.png"]}
                (self.root / f"{kind}.json").write_text(json.dumps(report))
                checks[kind] = {"result": result, "evidence": f"{kind}.json", "environment": "synthetic fixture", "coverage": ["synthetic matrix"]}
        run = self.tasks.begin(tid, "verification", review=True)
        return self.tasks.review(tid, run["agent_run_id"], [{"criterion_id": "C", "result": result, "evidence": "evidence.md"}], "synthetic check", checks)

    def planning_done(self):
        self.register()
        self.execute("P1", "planning")
        self.assertEqual(self.review("P1"), "DONE")

    def test_real_process_context_handoff_versions_change_restore(self):
        self.planning_done()
        old_p = copy.deepcopy(self.tasks.read()["deliverables"]["feature"]["versions"][0])
        self.register("D1", "design", ["P1"], "P-001")
        self.tasks.handoff("P1", "D1")
        self.execute("D1", "design")
        drun = self.tasks.read()["tasks"]["D1"]["executions"][0]
        packet = json.loads((self.root / drun["role_context"]["snapshot"]).read_text())
        self.assertEqual(packet["role"], "design")
        self.assertNotIn("docs/roles/planning.md", [d["path"] for d in packet["definitions"]])
        self.assertEqual(packet["workflow"]["dependencies"], ["P1"])
        self.assertEqual(packet["baselines"][0]["status"], "APPROVED")
        self.assertEqual(self.review("D1", True), "DONE")
        before = (self.root / "feature/prototype/tokens.css").read_bytes()
        restored = self.root / restore(self.tasks, "feature", "D-001")
        old_html = (restored / "prototype/index.html").read_bytes()
        cr = change(self.tasks, "feature", "new copy", "explicit test", ["P-001", "D-001"], {"requirements": ["REQ-002"], "screens": ["SCREEN-001"], "checks": ["saved"], "tasks": ["P2", "D2"]}, "input.md")
        self.register("P2", cr=cr["id"])
        self.execute("P2", "planning")
        self.review("P2")
        self.register("D2", "design", ["P2"], "P-002", cr["id"])
        self.tasks.handoff("P2", "D2")
        self.execute("D2", "design")
        self.review("D2", True)
        book = self.tasks.read()["deliverables"]["feature"]
        self.assertEqual([v["id"] for v in book["versions"]], ["P-001", "D-001", "P-002", "D-002"])
        self.assertEqual(book["changes"][0]["after"], {"planning": "P-002", "design": "D-002"})
        self.assertEqual(old_p["artifacts"], book["versions"][0]["artifacts"])
        self.assertEqual(before, (self.root / "feature/prototype/tokens.css").read_bytes())
        self.assertEqual(old_html, (restored / "prototype/index.html").read_bytes())
        self.assertNotEqual(old_html, (self.root / "feature/prototype/index.html").read_bytes())
        self.assertTrue(self.roles.execute("D1", "design")["skipped"])

    def test_wait_resume_keeps_run_decisions_and_completed_work(self):
        self.register()
        ctx = self.roles.prepare("P1", "planning")
        response = {"status": "waiting", "summary": "choose scope", "files": [], "completed": ["existing sources read"],
                    "questions": [{"question": "scope?", "recommended": "A: minimal scope", "alternative": "B: larger scope"}]}
        self.roles.accept("P1", ctx["agent_run_id"], response)
        with self.assertRaises(ValueError):
            self.tasks.ready("P1")
        (self.root / "decision.md").write_text("Synthetic choice A, not a user approval")
        self.tasks.resume("P1", ctx["agent_run_id"], "decision.md")
        self.execute("P1", "planning")
        task = self.tasks.read()["tasks"]["P1"]
        self.assertEqual(len(task["executions"]), 1)
        packet = json.loads((self.root / ctx["context"]).read_text())
        self.assertEqual(json.loads(packet["checkpoint"]["content"])["completed"], ["existing sources read"])
        self.assertIn("Synthetic choice", packet["decisions"][0]["content"])

    def test_failure_budget_and_output_ownership(self):
        self.register(attempts=1)
        ctx = self.roles.prepare("P1", "planning")
        with self.assertRaises(ValueError):
            self.roles.accept("P1", ctx["agent_run_id"], {"status": "submitted", "summary": "wrong role", "files": [{"path": "design.md", "content": "bad"}]})
        self.assertFalse((self.root / "feature/design.md").exists())
        self.tasks.fail("P1", ctx["agent_run_id"], "explicit failure")
        with self.assertRaises(ValueError):
            self.roles.prepare("P1", "planning")

    def test_stale_review_and_not_run_cannot_pass(self):
        self.planning_done()
        self.register("D1", "design", ["P1"], "P-001")
        self.tasks.handoff("P1", "D1")
        self.execute("D1", "design")
        with self.assertRaises(ValueError):
            self.review("D1", True, stale=True)
        self.assertEqual(self.tasks.read()["tasks"]["D1"]["state"], "IN_REVIEW")

    def test_identical_submission_does_not_increment_version(self):
        self.planning_done()
        self.tasks.register("F", "P2", "planning", "reuse", "synthetic", [{"id": "C", "required": True, "text": "review"}], ["feature/requirements.md"])
        self.roles.setup("P2", "feature")
        ctx = self.roles.prepare("P2", "planning")
        self.roles.accept("P2", ctx["agent_run_id"], {"status": "submitted", "summary": "reuse frozen bytes", "files": [], "reuse": ["feature/requirements.md"]})
        self.assertEqual(len(self.tasks.read()["deliverables"]["feature"]["versions"]), 1)

    def test_canonical_worker_paths_are_normalized_without_wider_access(self):
        self.register()
        ctx = self.roles.prepare("P1", "planning")
        self.roles.accept("P1", ctx["agent_run_id"], {"status": "submitted", "summary": "canonical path", "files": [{"path": "feature/requirements.md", "content": "synthetic"}]})
        self.assertEqual((self.root / "feature/requirements.md").read_text(), "synthetic")

    def test_reverting_older_content_does_not_reuse_superseded_number(self):
        self.planning_done()
        original = (self.root / "feature/requirements.md").read_text()
        for tid, text in [("P2", "changed synthetic requirements"), ("P3", original)]:
            self.register(tid)
            ctx = self.roles.prepare(tid, "planning")
            self.roles.accept(tid, ctx["agent_run_id"], {"status": "submitted", "summary": "revision fixture", "files": [{"path": "requirements.md", "content": text}]})
            self.review(tid)
        self.assertEqual([v["id"] for v in self.tasks.read()["deliverables"]["feature"]["versions"]], ["P-001", "P-002", "P-003"])

    def test_user_working_edit_during_execution_is_preserved(self):
        self.register()
        (self.root / "feature").mkdir()
        path = self.root / "feature/requirements.md"
        path.write_text("initial working draft")
        ctx = self.roles.prepare("P1", "planning")
        path.write_text("user edit during agent execution")
        with self.assertRaises(ValueError):
            self.roles.accept("P1", ctx["agent_run_id"], {"status": "submitted", "summary": "stale result", "files": [{"path": "requirements.md", "content": "agent replacement"}]})
        self.assertEqual(path.read_text(), "user edit during agent execution")

    def test_wrong_planning_baseline_and_missing_files_rejected(self):
        self.planning_done()
        self.register("D1", "design", planning="P-001")
        with self.assertRaises(ValueError):
            self.execute("D1", "design")
        self.assertNotIn("delivery", self.tasks.read()["tasks"]["D1"])
        self.assertFalse((self.root / "feature/design.md").exists())

    def test_asset_closure_and_shared_tokens(self):
        files = [{"path": "prototype/tokens.css", "content": ":root{--ink:#123}body{color:var(--ink)}"},
                 {"path": "prototype/index.html", "content": '<link rel="stylesheet" href="tokens.css">'},
                 {"path": "prototype/components.html", "content": '<link rel="stylesheet" href="tokens.css">'},
                 {"path": "prototype/system.md", "content": "synthetic rules"}]
        validate(files)
        missing = copy.deepcopy(files)
        missing[1]["content"] += '<script src="missing.js"></script>'
        with self.assertRaises(ValueError):
            validate(missing)
        external = copy.deepcopy(files)
        external[0]["content"] += 'body{background:url(https://example.invalid/a.png)}'
        with self.assertRaises(ValueError):
            validate(external)
        unknown = copy.deepcopy(files)
        unknown[0]["content"] += 'p{color:var(--undefined)}'
        with self.assertRaises(ValueError):
            validate(unknown)

    def test_not_run_blocks_design_and_timeout_records_failure(self):
        self.planning_done()
        self.register("D1", "design", ["P1"], "P-001")
        self.tasks.handoff("P1", "D1")
        self.execute("D1", "design")
        self.assertEqual(self.review("D1", True, result="NOT_RUN"), "BLOCKED")
        self.register("TIMEOUT", attempts=1)
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            self.roles.execute("TIMEOUT", "planning", [sys.executable, "-c", "import time; time.sleep(5)"], timeout=.05)
        self.assertIn("TimeoutExpired", self.tasks.read()["tasks"]["TIMEOUT"]["blocked_reason"])


if __name__ == "__main__":
    unittest.main()
