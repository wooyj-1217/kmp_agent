"""Synthetic target integration tests; no real sync, model calls or trust edits."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

spec = importlib.util.spec_from_file_location("projects_tested", Path(__file__).with_name("projects.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.harness = self.base / "harness-repo"
        self.target = self.base / "product"
        for root in (self.harness, self.target):
            root.mkdir()
            subprocess.run(["rtk", "proxy", "git", "init", "--quiet", str(root)], check=True)
        (self.harness / "harness").mkdir()
        (self.harness / "harness/codex_sync.py").write_text("# synthetic implementation\n")
        (self.harness / "AGENTS.md").write_text("shared synthetic rules\n")
        (self.target / "AGENTS.md").write_text("# Product\nKeep product policy.\n")
        module.save(self.target / ".kmp-agent/project.json", {"project_id": "synthetic-product", "project_path": "..", "skills": []})
        (self.target / ".codex").mkdir()
        (self.target / ".codex/config.toml").write_text('model = "product-model"\n')
        module.save(self.target / ".codex/hooks.json", {
            "description": "product-owned", "hooks": {"Stop": [{"matcher": "keep", "hooks": [
                {"type": "command", "command": "product-owned-command", "timeout": 7}]}]}})
        previous = module.ROOT
        module.ROOT = self.harness
        self.addCleanup(setattr, module, "ROOT", previous)
        self.item = {"path": str(self.target), "skills": []}

    def apply(self):
        return module.inspect(self.item, apply=True)

    def fixture(self, message_count=1, recorded_inside=True, created_after=True):
        state = module.read_json(self.target / ".harness/integration.json")
        created = datetime.fromisoformat(state["activation_after"]) + timedelta(seconds=1 if created_after else -10)
        start = created + timedelta(seconds=1)
        end = start + timedelta(seconds=1)
        components = module.fingerprint(self.target)["components"]
        rows = []
        for kind, invocation in (("UserPromptSubmit", "receipt"), ("Stop", "stop")):
            for phase in ("hook_entered", "sync_started", "sync_finished", "hook_exited"):
                row = {"phase": phase, "hook_event_name": kind, "session_id": "synthetic-session",
                       "project_id": "synthetic-product", "verification_scope": "target_project",
                       "turn_id": "synthetic-turn", "invocation_id": invocation,
                       "recorded_at": (end if phase in ("sync_finished", "hook_exited") else start).isoformat(),
                       "integration_components": components, "exit_code": 0,
                       "session_created_at": created.isoformat(),
                       "events_path": str(self.target / ".harness/logs/events.jsonl"),
                       "latest_collected_message_id": "synthetic-message"}
                rows.append(row)
        log = self.target / ".harness/logs"
        log.mkdir(exist_ok=True)
        (log / "hook-diagnostics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        event = {"event_id": "synthetic-event", "event_type": "session_message",
                 "project_id": "synthetic-product", "verification_scope": "target_project",
                 "recorded_at": (start + timedelta(seconds=0.5) if recorded_inside else start - timedelta(seconds=20)).isoformat(),
                 "source": {"kind": "codex_session_import", "session_id": "synthetic-session"},
                 "observed": {"role": "user", "message_id": "synthetic-message", "content": [{"text": "synthetic request"}]}}
        (log / "events.jsonl").write_text((json.dumps(event) + "\n") * message_count)

    def test_apply_preserves_product_config_and_is_idempotent(self):
        config = (self.target / ".codex/config.toml").read_bytes()
        first = self.apply()
        self.assertEqual(first["connection"], "PASS")
        self.assertEqual(first["runtime"]["result"], "NOT_RUN")
        hooks = module.read_json(self.target / ".codex/hooks.json")
        self.assertEqual(hooks["description"], "product-owned")
        self.assertEqual(hooks["hooks"]["Stop"][0]["hooks"][0]["command"], "product-owned-command")
        self.assertEqual((self.target / ".codex/config.toml").read_bytes(), config)
        self.assertIn("Keep product policy.", (self.target / "AGENTS.md").read_text())
        protected = {p: p.read_bytes() for p in (self.target / "AGENTS.md", self.target / ".codex/hooks.json", self.target / ".gitignore")}
        state = module.read_json(self.target / ".harness/integration.json")
        second = self.apply()
        self.assertEqual(second["changes"], [])
        self.assertEqual(module.read_json(self.target / ".harness/integration.json")["activation_after"], state["activation_after"])
        self.assertTrue(all(p.read_bytes() == data for p, data in protected.items()))

    def test_synthetic_runtime_proof_separate_from_connection(self):
        self.apply()
        self.fixture()
        result = module.inspect(self.item)
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["internal_tests"], "NOT_RUN: independent harness test command")
        self.assertEqual(result["runtime"]["matching_events"], 1)

    def test_old_session_cannot_pass_after_apply(self):
        self.apply()
        self.fixture(created_after=False)
        self.assertEqual(module.inspect(self.item)["state"], "RESTART_REQUIRED")

    def test_duplicate_message_or_manual_import_is_not_automatic_pass(self):
        self.apply()
        self.fixture(message_count=2)
        self.assertEqual(module.inspect(self.item)["runtime"]["result"], "FAIL")
        self.fixture(recorded_inside=False)
        self.assertEqual(module.inspect(self.item)["runtime"]["result"], "NOT_RUN")

    def test_newer_failed_session_does_not_fall_back_to_older_pass(self):
        self.apply()
        self.fixture()
        path = self.target / ".harness/logs/hook-diagnostics.jsonl"
        with path.open("a") as handle:
            for phase in ("hook_entered", "hook_exited"):
                handle.write(json.dumps({"phase": phase, "session_id": "newer-synthetic", "turn_id": "new",
                                         "hook_event_name": "Stop", "exit_code": 1}) + "\n")
        self.assertEqual(module.inspect(self.item)["state"], "HOOK_FAILED")
        self.assertEqual(module.inspect(self.item, session_id="synthetic-session")["state"], "VERIFIED")

    def test_receipt_collection_also_counts_but_both_hooks_must_finish(self):
        self.apply()
        self.fixture()
        path = self.target / ".harness/logs/hook-diagnostics.jsonl"
        records = [json.loads(s) for s in path.read_text().splitlines()]
        for record in records:
            if record["hook_event_name"] == "Stop":
                record["recorded_at"] = (datetime.fromisoformat(record["recorded_at"]) + timedelta(seconds=10)).isoformat()
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        result = module.inspect(self.item)
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["runtime"]["invocation_id"], "receipt")

    def test_retiring_a_shared_skill_removes_only_our_link(self):
        source = self.harness / ".agents/skills/shared"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("synthetic shared skill\n")
        self.item["skills"] = ["shared"]
        self.apply()
        dest = self.target / ".agents/skills/shared"
        self.item["skills"] = []
        self.apply()
        self.assertFalse(dest.is_symlink())
        self.assertTrue((source / "SKILL.md").exists())

    def test_instruction_change_requires_apply_and_restart_but_code_only_does_not(self):
        self.apply()
        self.fixture()
        implementation = self.harness / "harness/codex_sync.py"
        implementation.write_text("# new synthetic code\n")
        self.assertEqual(module.inspect(self.item)["state"], "AWAITING_REQUEST")
        self.apply()
        self.assertEqual(module.inspect(self.item)["state"], "AWAITING_REQUEST")
        (self.harness / "AGENTS.md").write_text("new startup rules\n")
        self.assertEqual(module.inspect(self.item)["state"], "RESTART_REQUIRED")
        self.apply()
        self.assertEqual(module.inspect(self.item)["state"], "RESTART_REQUIRED")

    def test_only_selected_shared_skills_are_linked_and_owned_skills_preserved(self):
        source = self.harness / ".agents/skills/shared"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("synthetic skill\n")
        self.item["skills"] = ["shared"]
        self.assertEqual(self.apply()["connection"], "PASS")
        dest = self.target / ".agents/skills/shared"
        self.assertTrue(dest.is_symlink())
        self.assertEqual(dest.resolve(), source)
        self.assertEqual(self.apply()["changes"], [])
        dest.unlink()
        dest.mkdir()
        (dest / "SKILL.md").write_text("product-owned skill\n")
        self.assertEqual(self.apply()["state"], "FAILED")
        self.assertEqual((dest / "SKILL.md").read_text(), "product-owned skill\n")

    def test_hook_changes_update_only_managed_handlers(self):
        self.apply()
        path = self.harness / ".codex/hooks.json"
        spec = module.hook_spec()
        spec["Stop"]["timeout"] = 99
        module.save(path, {"hooks": {k: [{"hooks": [v]}] for k, v in spec.items()}})
        result = self.apply()
        self.assertIn(".codex/hooks.json", result["changes"])
        hooks = module.read_json(self.target / ".codex/hooks.json")
        self.assertEqual(hooks["hooks"]["Stop"][0]["hooks"][0]["command"], "product-owned-command")
        self.assertEqual(hooks["hooks"]["Stop"][1]["hooks"][0]["timeout"], 99)

    def test_conflicts_and_missing_skill_do_not_overwrite_existing_inputs(self):
        path = self.target / "AGENTS.md"
        path.write_text("keep\n" + module.BEGIN + "\nbroken marker\n")
        before = path.read_bytes()
        self.assertEqual(self.apply()["state"], "FAILED")
        self.assertEqual(path.read_bytes(), before)
        path.write_text("keep\n")
        self.item["skills"] = ["missing"]
        self.assertEqual(self.apply()["state"], "FAILED")
        self.assertEqual(path.read_text(), "keep\n")

    def test_product_hook_refreshes_status_without_sync_or_config_changes(self):
        self.apply()
        self.fixture()
        path = self.target / ".harness/logs/events.jsonl"
        before = path.read_bytes()
        self.assertEqual(module.after_hook(self.target, "synthetic-session")["state"], "VERIFIED")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(module.read_json(self.target / ".harness/integration-status.json")["state"], "VERIFIED")

    def test_harness_hook_checks_without_pushing_changes_to_registered_targets(self):
        module.save(self.harness / ".harness/projects.json", {"targets": [{"path": "../product", "skills": []}]})
        result = module.after_hook(self.harness, "synthetic-harness-session")
        self.assertEqual(result["targets"][0]["connection"], "NOT_RUN")
        self.assertFalse((self.target / ".harness/integration.json").exists())
        self.assertTrue((self.harness / ".harness/projects-status.json").exists())

    def test_partial_diagnostic_line_is_pending_not_evidence(self):
        self.apply()
        self.fixture()
        path = self.target / ".harness/logs/hook-diagnostics.jsonl"
        with path.open("a") as handle:
            handle.write('{"phase":')
        self.assertEqual(module.inspect(self.item)["state"], "VERIFIED")

    def test_wrong_project_evidence_is_never_accepted(self):
        self.apply()
        self.fixture()
        path = self.target / ".harness/logs/events.jsonl"
        event = json.loads(path.read_text())
        event["project_id"] = "another-project"
        path.write_text(json.dumps(event) + "\n")
        self.assertEqual(module.inspect(self.item)["runtime"]["result"], "NOT_RUN")

    def test_unknown_project_path_has_reason_and_preserves_logs(self):
        self.apply()
        self.fixture()
        path = self.target / ".harness/logs/events.jsonl"
        original = path.read_bytes()
        module.save(self.target / ".kmp-agent/project.json", {"project_id": "synthetic-product", "project_path": "../wrong"})
        result = module.inspect(self.item)
        self.assertEqual(result["state"], "PROJECT_ID_UNKNOWN")
        self.assertEqual(result["project_id"], "UNKNOWN")
        self.assertEqual(result["project_id_reason"], "project_connection_path_mismatch")
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
