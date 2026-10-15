"""Synthetic intervention joins only; never sync a real session in tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("intervention_tasks", Path(__file__).with_name("tasks.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InterventionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.md").write_text("synthetic input")
        self.log = module.logging.Logger(self.root)
        self.run = self.log.start("HARNESS_BUILD", "planning", "synthetic")
        self.tasks = module.Tasks(self.root, self.run)
        self.tasks.register("FEAT-SYNTHETIC", "TASK-SYNTHETIC", "planning", "synthetic", "test", [
            {"id": "AC-SYNTHETIC", "required": True, "text": "synthetic"}], ["input.md"])
        self.tasks.ready("TASK-SYNTHETIC")
        self.agent = self.tasks.begin("TASK-SYNTHETIC", "planning")["agent_run_id"]
        self.source = self.root / "source.jsonl"
        self.records = [
            {"ordinal": 0, "type": "session_meta", "payload": {"session_id": "synthetic-session"}},
            {"ordinal": 1, "type": "event_msg", "payload": {"type": "task_started", "turn_id": "synthetic-turn"}}]
        self.write_source()

    def write_source(self):
        self.source.write_text("".join(json.dumps(r) + "\n" for r in self.records))

    def add_message(self, message_id="synthetic-message", ordinal=2):
        self.records.append({"ordinal": ordinal, "type": "response_item", "payload": {
            "type": "message", "role": "user", "id": message_id,
            "content": [{"type": "input_text", "text": "synthetic request password=synthetic-secret"}]}})
        self.write_source()

    def declare(self, message_id="synthetic-message", classification="REQUIREMENT_CHANGE"):
        return self.tasks.intervention("TASK-SYNTHETIC", self.agent, "synthetic-session", "synthetic-turn",
                                       classification, "New condition; password=synthetic-secret",
                                       ["input.md: existing scope"], message_id)

    def linked(self):
        return [e for e in self.log.read() if e["event_type"] == "human_intervention"]

    def test_late_stop_collection_links_once_without_rewriting_pending(self):
        self.log.sync(self.source)  # Receipt hook before prompt persistence.
        result = self.declare()
        self.assertEqual(result["linked_interventions"], 0)
        pending = next(e for e in self.log.read() if e["event_type"] == "human_intervention_pending")
        self.add_message()
        self.log.sync(self.source)  # Stop hook uses exactly this existing collector.
        event = self.linked()[0]
        self.assertEqual(event["task_id"], "TASK-SYNTHETIC")
        self.assertEqual(event["run_id"], self.run)
        self.assertEqual(event["agent_run_id"], self.agent)
        self.assertEqual(event["agent_summary"]["role"], "planning")
        self.assertEqual(event["agent_summary"]["stage"], "work")
        self.assertEqual(event["agent_summary"]["task_state_at_declaration"], "IN_PROGRESS")
        self.assertEqual(event["agent_summary"]["source_message_id"], "synthetic-message")
        source = next(e for e in self.log.read() if e["event_id"] == event["agent_summary"]["source_event_id"])
        self.assertEqual(source["observed"]["message_id"], "synthetic-message")
        self.assertEqual(event["agent_summary"]["classification"], "REQUIREMENT_CHANGE")
        self.assertTrue(event["agent_summary"]["basis"])
        self.assertEqual(next(e for e in self.log.read() if e["event_id"] == pending["event_id"]), pending)
        count = len(self.log.read())
        self.assertEqual(self.log.sync(self.source), 0)
        self.declare()
        self.assertEqual(len(self.log.read()), count)
        self.assertEqual(len(self.linked()), 1)
        self.assertNotIn("synthetic-secret", self.log.path.read_text())

    def test_source_first_and_bad_classification_does_not_remove_original(self):
        self.add_message()
        self.log.sync(self.source)
        before = self.log.path.read_bytes()
        with self.assertRaises(ValueError):
            self.declare(classification="NOT_A_CLASS")
        self.assertEqual(self.log.path.read_bytes(), before)
        self.declare(classification="UNKNOWN")
        self.assertEqual(len(self.linked()), 1)

    def test_unknown_execution_and_contextless_legacy_writer_rejected(self):
        with self.assertRaises(ValueError):
            self.tasks.intervention("TASK-SYNTHETIC", "not-an-agent", "synthetic-session", "synthetic-turn",
                                    "CORRECTION", "synthetic basis", ["input.md"])
        with self.assertRaises(ValueError):
            self.log.append("human_intervention", self.run, summary={"text": "unlinked"})
        self.assertEqual(self.linked(), [])

    def test_different_turn_and_ambiguous_messages_are_never_guessed(self):
        self.declare(message_id="UNKNOWN")
        self.add_message("first", 2)
        self.add_message("second", 3)
        self.log.sync(self.source)
        self.assertEqual(self.linked(), [])
        self.assertEqual(len(self.log.intervention_status()["pending_intervention_ids"]), 1)

    def test_explicit_message_id_disambiguates_environment_message(self):
        self.add_message("environment-message", 2)
        self.add_message("synthetic-message", 3)
        self.log.sync(self.source)
        self.declare()
        self.assertEqual(len(self.linked()), 1)
        self.assertEqual(self.linked()[0]["agent_summary"]["source_message_id"], "synthetic-message")

    def test_message_reference_change_cannot_duplicate_same_request_item(self):
        self.declare(message_id="UNKNOWN")
        with self.assertRaises(ValueError):
            self.declare(message_id="synthetic-message")
        self.add_message()
        self.log.sync(self.source)
        self.assertEqual(len(self.linked()), 1)
        self.assertEqual(len([e for e in self.log.read()
                              if e["event_type"] == "human_intervention_pending"]), 1)

    def test_other_turn_and_changed_classification_do_not_relink(self):
        self.declare()
        with self.assertRaises(ValueError):
            self.declare(classification="CORRECTION")
        self.records.append({"ordinal": 2, "type": "event_msg", "payload": {
            "type": "task_started", "turn_id": "other-turn"}})
        self.add_message(ordinal=3)
        self.log.sync(self.source)
        self.assertEqual(self.linked(), [])

    def test_legacy_unlinked_event_is_preserved_and_not_retroactively_classified(self):
        legacy = {"event_id": "synthetic-legacy", "event_type": "human_intervention",
                  "source": {"kind": "logger_runtime"}, "source_key": None,
                  "agent_summary": {"text": "old free-text declaration"}}
        with self.log.path.open("a") as handle:
            handle.write(json.dumps(legacy) + "\n")
        before = self.log.path.read_bytes()
        self.declare()
        self.add_message()
        self.log.sync(self.source)
        self.assertTrue(self.log.path.read_bytes().startswith(before))
        self.assertEqual(next(e for e in self.log.read() if e["event_id"] == legacy["event_id"]), legacy)
        self.assertEqual(self.log.intervention_status()["legacy_unlinked_interventions"], 1)
        self.assertEqual(self.log.intervention_status()["linked_interventions"], 1)


if __name__ == "__main__":
    unittest.main()
