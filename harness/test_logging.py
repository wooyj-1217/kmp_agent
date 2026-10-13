"""Tests use temporary roots and synthetic fixtures, never production logs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("harness_logger", Path(__file__).with_name("logging.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LoggingTests(unittest.TestCase):
    def test_lifecycle_and_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "old.md").write_text("before")
            log = module.Logger(root)
            run = log.start("HARNESS_BUILD", "test_role", "synthetic test")
            (root / "old.md").write_text("after")
            (root / "new.md").write_text("new")
            event = log.checkpoint(run, "synthetic result", finish=True)
            self.assertEqual({x["change"] for x in event["observed"]["changed_files"]}, {"added", "modified"})
            self.assertEqual(event["observed"]["tokens"], "UNKNOWN")
            self.assertEqual(log.read()[0]["agent_summary"]["role"], "test_role")
            self.assertIn("ended_at", event["observed"])
            self.assertNotIn("validation_result", event["observed"])
            self.assertNotIn("task_status", event["observed"])
            with self.assertRaises(ValueError):
                log.checkpoint(run, "double finish", finish=True)

    def test_import_dedup_partial_line_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            log = module.Logger(directory)
            source = Path(directory) / "fixture.jsonl"
            record = {"timestamp": "2000-01-01T00:00:00Z", "type": "token_usage_record",
                      "payload": {"response_id": "synthetic-response", "usage": {"input_tokens": 10,
                                  "cached_input_tokens": 4, "output_tokens": 2, "total_tokens": 12}}}
            source.write_text(json.dumps(record) + '\n{"type":')
            self.assertEqual(log.sync(source), 1)
            self.assertEqual(log.sync(source), 0)
            event = log.read()[0]
            self.assertEqual(event["source"]["line"], 1)
            self.assertEqual(event["source"]["kind"], "codex_session_import")
            self.assertEqual(event["work_type"], "UNKNOWN")
            self.assertEqual(event["observed"]["cost"], "UNKNOWN")
            self.assertEqual(event["observed"]["usage"]["total_tokens"], 12)
            self.assertEqual(event["observed"]["occurred_at"], record["timestamp"])
            source.write_text(json.dumps(record) + '\n' + json.dumps({"type": "event_msg", "payload": {"type": "turn_aborted"}}) + '\n')
            self.assertEqual(log.sync(source), 1)

    def test_command_failure_is_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            log = module.Logger(directory)
            run = log.start("HARNESS_IMPROVEMENT", "test_role", "synthetic failure test")
            code = log.command(run, ["rtk", "proxy", "python3", "-c", "raise SystemExit(7)"])
            self.assertEqual(code, 7)
            event = log.read()[-1]
            self.assertEqual(event["event_type"], "command_finished")
            self.assertEqual(event["observed"]["returncode"], 7)
            self.assertEqual(log.read()[-2]["observed"]["call_id"], event["observed"]["call_id"])

    def test_masking_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            log = module.Logger(directory)
            key = "sk-" + "x" * 24
            log.append("synthetic", observed={"authorization": "Bearer private-value", "input_tokens": 10},
                       summary={"text": "password=secret123 " + key + " someone@example.test"})
            stored = log.path.read_text()
            for secret in ("private-value", "secret123", key, "someone@example.test"):
                self.assertNotIn(secret, stored)
            self.assertEqual(log.read()[0]["observed"]["input_tokens"], 10)

    def test_native_identity_relocation_and_usage_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            log = module.Logger(directory)
            usage = {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2, "total_tokens": 12}
            records = [
                {"ordinal": 1, "type": "session_meta", "payload": {"session_id": "synthetic-session"}},
                {"ordinal": 2, "type": "token_usage_record", "payload": {"response_id": "synthetic-response", "usage": usage, "thread_token_usage": usage}},
                {"ordinal": 3, "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": usage, "total_token_usage": usage}}},
            ]
            source = Path(directory) / "fixture.jsonl"
            source.write_text("".join(json.dumps(r) + "\n" for r in records))
            report = log.audit(source)
            self.assertTrue(report["idempotency_pass"])
            self.assertTrue(report["increments_match_thread_cumulative"])
            self.assertEqual(report["per_response_increment_mismatches"], [])
            self.assertTrue(report["input_plus_output_matches_total"])
            self.assertTrue(report["cached_is_subset_of_input"])
            self.assertEqual(report["repeat_imported"], [0, 0])
            self.assertEqual(log.status()["reported_tokens"]["total_tokens"], 12)
            self.assertEqual(log.status()["reported_tokens"]["cached_input_tokens"], 4)
            self.assertEqual(report["responses_also_repeated_in_token_count"], 1)
            copy = Path(directory) / "copy.jsonl"
            copy.write_bytes(source.read_bytes())
            self.assertEqual(log.sync(copy), 0)
            self.assertEqual(log.read()[0]["source"]["session_id"], "synthetic-session")
            self.assertEqual(log.read()[0]["source"]["event_id"], 2)

    def test_missing_usage_and_conflicting_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            log = module.Logger(directory)
            log.append("model_usage", observed={"response_id": "missing", "usage": "UNKNOWN"})
            self.assertEqual(log.status()["known_responses_missing_usage"], 1)
            self.assertEqual(log.status()["reported_tokens"]["input_tokens"], "UNKNOWN")
            log.append("model_usage", observed={"response_id": "conflict", "usage": {"input_tokens": 10, "output_tokens": 2}})
            log.append("model_usage", observed={"response_id": "conflict", "usage": {"input_tokens": 20, "output_tokens": 3}})
            self.assertEqual(log.status()["conflicting_usage_reports"], 1)
            self.assertEqual(log.status()["known_responses_missing_usage"], 2)

    def test_legacy_masking_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            log = module.Logger(directory)
            legacy = {"schema_version": 1, "event_type": "note", "source": {"kind": "logger_runtime"},
                      "agent_summary": {"text": "password=legacy-secret"}}
            log.path.write_text(json.dumps(legacy) + "\n")
            log.migrate()
            self.assertNotIn("legacy-secret", log.path.read_text())
            self.assertEqual(log.read()[0]["redaction_version"], 1)


if __name__ == "__main__":
    unittest.main()
