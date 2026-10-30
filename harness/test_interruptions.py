"""Only interruption recovery, provenance, timing and repeat-sync regression checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("interruptions", Path(__file__).with_name("interruptions.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InterruptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.recovery = module.Interruptions(self.root)
        self.log = self.recovery.logger
        self.run = "synthetic-run"
        self.log.append("run_started", self.run, "HARNESS_BUILD", observed={"started_at": "2000-01-01T00:00:00Z"})
        self.log.append("run_finished", self.run, "HARNESS_BUILD", observed={"ended_at": "2000-01-01T00:02:00Z"})
        self.source = self.root / "source.jsonl"
        self.records = [
            {"type": "session_meta", "ordinal": 1, "payload": {"session_id": "synthetic-session"}},
            {"type": "event_msg", "ordinal": 2, "timestamp": "2000-01-01T00:00:30Z",
             "payload": {"type": "task_complete", "turn_id": "error-turn", "error": {"codex_error_info": "server_overloaded"}}},
            {"type": "event_msg", "ordinal": 3, "timestamp": "2000-01-01T00:01:00Z",
             "payload": {"type": "task_started", "turn_id": "resume-turn"}},
        ]
        self.source.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        directory = self.root / ".harness" / "tasks"
        directory.mkdir()
        self.state_path = directory / "tasks.yaml"
        self.state_path.write_text(json.dumps({"tasks": {"TASK-001": {"task_id": "TASK-001", "state": "DONE", "executions": [
            {"agent_run_id": "synthetic-role", "run_id": self.run, "role": "planning", "kind": "work",
             "started_at": "2000-01-01T00:00:00Z", "ended_at": "2000-01-01T00:00:20Z"}]}}}))

    def recover(self, source=None):
        return self.recovery.recover(self.run, "user-assertion", source or self.source, "error-turn", "resume-turn")

    def test_source_recovery_repeat_sync_and_skip_completed(self):
        before_state = self.state_path.read_bytes()
        self.recovery.user_report(self.run, "user-assertion", "User confirms interruption and resume", {"message_id": "synthetic-user"})
        first = self.recover()
        recovered = [e for e in self.log.read() if e["source"]["kind"] == "codex_session_recovery"]
        self.assertEqual(recovered[0]["observed"]["source_error"]["codex_error_info"], "server_overloaded")
        self.assertEqual(recovered[0]["source"]["record_ordinal"], 2)
        self.assertEqual(recovered[1]["source"]["record_ordinal"], 3)
        self.assertTrue(all(e["run_id"] == self.run for e in recovered))
        self.assertTrue(all("continuation_mapping" in e["agent_summary"] for e in recovered))
        count = len(self.log.read())
        time = self.recovery.timing(self.run)
        self.assertEqual(time["confirmed_wait_seconds"], 30)
        self.assertEqual(time["overall_elapsed_seconds"], 120)
        self.assertEqual(time["phase_elapsed_union_seconds"], 20)
        self.assertEqual(time["remaining_unclassified_seconds"], 70)
        second = self.recover()
        self.assertEqual(second["recovered_events"], 0)
        self.assertEqual(len(self.log.read()), count)
        self.assertEqual(self.recovery.timing(self.run)["confirmed_wait_seconds"], 30)
        copy = self.root / "relocated.jsonl"
        copy.write_bytes(self.source.read_bytes())
        self.assertEqual(self.recover(copy)["recovered_events"], 0)
        self.assertEqual(self.state_path.read_bytes(), before_state)
        self.assertEqual(first["resume_plan"]["completed_tasks_to_skip"], [])
        self.assertIn('TASK-001', first['resume_plan']['revalidation_required'])
        self.assertEqual(first["resume_plan"]["unfinished_tasks"], [])

    def test_user_claim_without_source_stays_unknown_and_masked(self):
        self.recovery.user_report(self.run, "user-assertion", "capacity error password=synthetic-secret", {"message_id": "synthetic-user"}, "model capacity")
        empty = self.root / "empty.jsonl"
        empty.write_text(json.dumps(self.records[0]) + "\n")
        result = self.recover(empty)
        self.assertFalse(result["interruption_source_found"])
        self.assertEqual(self.recovery.timing(self.run)["confirmed_wait_seconds"], "UNKNOWN")
        self.assertEqual(self.recovery.timing(self.run)["confirmed_wait_lower_bound_seconds"], 0)
        events = [e for e in self.log.read() if e["event_type"] in {"run_interrupted", "run_resumed"}]
        self.assertTrue(all(e["observed"]["occurred_at"] == "UNKNOWN" for e in events))
        self.assertTrue(all(e["observed"]["cause"] == "UNKNOWN" for e in events))
        self.assertEqual(events[0]["user_statement"]["cause"], "model capacity")
        self.assertNotIn("synthetic-secret", self.log.path.read_text())
        count = len(self.log.read())
        self.recovery.user_report(self.run, "user-assertion", "same assertion", {"message_id": "synthetic-user"})
        self.assertEqual(len(self.log.read()), count)

    def test_missing_resumption_does_not_use_last_stage_end(self):
        partial = self.root / "partial.jsonl"
        partial.write_text("".join(json.dumps(r) + "\n" for r in self.records[:2]))
        self.recover(partial)
        report = self.recovery.timing(self.run)
        self.assertEqual(report["confirmed_wait_seconds"], "UNKNOWN")
        self.assertEqual(report["remaining_unclassified_seconds"], 100)

    def test_resume_without_error_does_not_invent_pause(self):
        self.recovery.user_report(self.run, "user-assertion", "User confirms capacity interruption", {"message_id": "synthetic-user"})
        missing = self.root / "missing-error.jsonl"
        missing.write_text("".join(json.dumps(r) + "\n" for r in [self.records[0], self.records[2]]))
        result = self.recover(missing)
        self.assertFalse(result["interruption_source_found"])
        self.assertTrue(result["resumption_source_found"])
        self.assertEqual(self.recovery.timing(self.run)["confirmed_wait_seconds"], "UNKNOWN")

    def test_overlap_union_does_not_double_count(self):
        self.recover()
        state = json.loads(self.state_path.read_text())
        state["tasks"]["TASK-001"]["executions"][0]["ended_at"] = "2000-01-01T00:01:30Z"
        self.state_path.write_text(json.dumps(state))
        report = self.recovery.timing(self.run)
        self.assertEqual(report["phase_elapsed_union_seconds"], 90)
        self.assertEqual(report["phase_wait_overlap_seconds"], 30)
        self.assertEqual(report["remaining_unclassified_seconds"], 30)

    def test_reverse_resumption_rejected(self):
        self.records[2]["timestamp"] = "2000-01-01T00:00:10Z"
        self.source.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        with self.assertRaises(ValueError):
            self.recover()


if __name__ == "__main__":
    unittest.main()
