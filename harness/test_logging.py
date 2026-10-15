"""Tests use temporary roots and synthetic fixtures, never production logs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import os
import sys
import contextlib
import io
import subprocess

spec = importlib.util.spec_from_file_location("harness_logger", Path(__file__).with_name("logging.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@contextlib.contextmanager
def replace_attribute(obj, name, value):
    previous = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, previous)


@contextlib.contextmanager
def patch_environment(values):
    previous = os.environ.copy()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


class LoggingTests(unittest.TestCase):
    def test_cli_collects_before_classification_failure_and_at_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            records = [
                {"type": "session_meta", "payload": {"id": "synthetic-session"}},
                {"ordinal": 1, "type": "response_item", "payload": {
                    "type": "message", "role": "user", "id": "synthetic-message",
                    "content": [{"type": "input_text", "text": "synthetic request password=secret123"}]}}
            ]
            source.write_text("".join(json.dumps(x) + "\n" for x in records))
            log = module.Logger(root)
            run = log.start("HARNESS_BUILD", "test", "synthetic")
            original_append = module.Logger.append

            def fail_classification(instance, event_type, *args, **kwargs):
                if event_type == "human_intervention":
                    raise ValueError("synthetic classifier failure")
                return original_append(instance, event_type, *args, **kwargs)

            common = ["logging.py", "--root", str(root), "--session-path", str(source)]
            with patch_environment({"CODEX_THREAD_ID": "synthetic-session"}), \
                    replace_attribute(sys, "argv", common + ["event", run, "--type", "human_intervention", "--summary", "synthetic"]), \
                    replace_attribute(module.Logger, "append", fail_classification), \
                    self.assertRaises(ValueError):
                module.main()
            messages = [x for x in log.read() if x["event_type"] == "session_message"]
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["observed"]["message_id"], "synthetic-message")
            self.assertNotIn("secret123", log.path.read_text())
            records.append({"ordinal": 2, "type": "response_item", "payload": {
                "type": "message", "role": "user", "id": "synthetic-second", "content": []}})
            source.write_text("".join(json.dumps(x) + "\n" for x in records))
            with patch_environment({"CODEX_THREAD_ID": "synthetic-session"}), \
                    replace_attribute(sys, "argv", common + ["finish", run, "--result", "synthetic"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                module.main()
            self.assertEqual(len([x for x in log.read() if x["event_type"] == "session_message"]), 2)
            self.assertEqual(log.sync(source), 0)

    def test_session_discovery_rejects_mismatch_and_missing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            source.write_text(json.dumps({"type": "session_meta", "payload": {"id": "synthetic"}}) + "\n")
            with self.assertRaises(ValueError):
                module.resolve_session(source, "different")
            with patch_environment({"CODEX_HOME": directory}):
                with self.assertRaises(ValueError):
                    module.resolve_session(session_id="missing")

    def test_hook_collects_source_without_classification_and_deduplicates(self):
        hook_spec = importlib.util.spec_from_file_location("codex_sync_hook", Path(__file__).with_name("codex_sync.py"))
        hook = importlib.util.module_from_spec(hook_spec)
        hook_spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jsonl"
            source.write_text(json.dumps({"type": "session_meta", "payload": {"id": "synthetic"}}) + "\n" +
                              json.dumps({"ordinal": 1, "type": "response_item", "payload": {
                                  "type": "message", "role": "user", "id": "synthetic-message", "content": []}}) + "\n")
            log = module.Logger(directory)
            payload = {"hook_event_name": "UserPromptSubmit", "cwd": str(Path(__file__).resolve().parents[1]),
                       "transcript_path": str(source), "session_id": "synthetic"}
            with replace_attribute(hook.load_logger(), "Logger", lambda root: log):
                self.assertEqual(hook.handle(payload), 1)
                payload["hook_event_name"] = "Stop"
                self.assertEqual(hook.handle(payload), 0)
                payload["session_id"] = "wrong-session"
                with self.assertRaises(ValueError):
                    hook.handle(payload)
            self.assertEqual([x["event_type"] for x in log.read()], ["session_message"])

    def test_hook_diagnostic_entry_exit_and_error_without_real_sync(self):
        hook_spec = importlib.util.spec_from_file_location("diagnostic_hook", Path(__file__).with_name("codex_sync.py"))
        hook = importlib.util.module_from_spec(hook_spec)
        hook_spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.jsonl"
            payload = {"hook_event_name": "UserPromptSubmit", "session_id": "synthetic", "turn_id": "synthetic-turn",
                       "cwd": directory, "transcript_path": "missing", "prompt": "private prompt"}

            def failure(payload, trace=None):
                raise ValueError("synthetic failure")

            with replace_attribute(hook, "DIAGNOSTIC_PATH", path), \
                    replace_attribute(sys, "stdin", io.StringIO(json.dumps(payload))), \
                    replace_attribute(hook, "repository_root", lambda cwd: Path(directory)), \
                    replace_attribute(hook, "handle", failure), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(hook.main(), 1)
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual([x["phase"] for x in rows], ["process_entered", "hook_entered", "hook_exited"])
            self.assertEqual(rows[-1]["exit_code"], 1)
            self.assertEqual(rows[-1]["error_type"], "ValueError")
            self.assertEqual(rows[1]["hook_event_name"], "UserPromptSubmit")
            self.assertNotIn("private prompt", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_shared_hook_collects_in_product_repo_and_routes_diagnostics(self):
        hook_spec = importlib.util.spec_from_file_location("product_hook", Path(__file__).with_name("codex_sync.py"))
        hook = importlib.util.module_from_spec(hook_spec)
        hook_spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            subprocess.run(["rtk", "proxy", "git", "init", "--quiet", str(root)], check=True)
            nested = root / "docs"
            nested.mkdir()
            source = root / "synthetic-source.jsonl"
            source.write_text(json.dumps({"type": "session_meta", "payload": {"id": "product-synthetic"}}) + "\n")
            payload = {"hook_event_name": "UserPromptSubmit", "session_id": "product-synthetic",
                       "turn_id": "synthetic-turn", "cwd": str(nested), "transcript_path": str(source)}
            previous = Path.cwd()
            try:
                os.chdir(nested)
                with replace_attribute(sys, "stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(hook.main(), 0)
                with source.open("a") as handle:
                    handle.write(json.dumps({"type": "response_item", "payload": {"type": "message",
                                 "role": "user", "id": "product-message", "content": []}}) + "\n")
                payload["hook_event_name"] = "Stop"
                for _ in range(2):
                    with replace_attribute(sys, "stdin", io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(hook.main(), 0)
            finally:
                os.chdir(previous)
            events = [json.loads(s) for s in (root / ".harness/logs/events.jsonl").read_text().splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["source"]["session_id"], "product-synthetic")
            self.assertEqual(events[0]["observed"]["message_id"], "product-message")
            rows = [json.loads(s) for s in (root / ".harness/logs/hook-diagnostics.jsonl").read_text().splitlines()]
            self.assertEqual(len([r for r in rows if r["phase"] == "process_entered"]), 3)
            starts = [r for r in rows if r["phase"] == "sync_started"]
            self.assertTrue(all(r["events_path"] == str(root / ".harness/logs/events.jsonl") for r in starts))
            self.assertTrue(all(r["exit_code"] == 0 for r in rows if r["phase"] == "hook_exited"))
            self.assertFalse((nested / ".harness").exists())

    def test_source_probe_detects_prompt_not_yet_written(self):
        hook_spec = importlib.util.spec_from_file_location("probe_hook", Path(__file__).with_name("codex_sync.py"))
        hook = importlib.util.module_from_spec(hook_spec)
        hook_spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.jsonl"
            row = {"type": "response_item", "payload": {"role": "user", "id": "synthetic", "content": [{"text": "old"}]}}
            path.write_text(json.dumps(row) + "\n")
            self.assertFalse(hook.source_probe(path, "next")["source_contains_hook_prompt"])
            row["payload"]["content"] = [{"text": "next"}]
            with path.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            result = hook.source_probe(path, "next")
            self.assertTrue(result["source_contains_hook_prompt"])
            self.assertNotIn("next", json.dumps(result))

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
