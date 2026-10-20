"""Local, stdlib-only JSONL logger. No model or external service calls."""
import argparse
import importlib.util
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

UNKNOWN = "UNKNOWN"
KINDS = ("HARNESS_BUILD", "HARNESS_IMPROVEMENT", "PRODUCT")
INTERVENTION_CLASSES = {"REQUIREMENT_CHANGE", "CORRECTION", "STATUS_OR_EXPLANATION", UNKNOWN}
ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEY = re.compile(r"^(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|passwd|client[_-]?secret|secret|cookie|set-cookie)$", re.I)


def redact(value):
    """Conservative pattern masking, not a guarantee of arbitrary PII detection."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SENSITIVE_KEY.fullmatch(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]", value, flags=re.S)
    value = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value, flags=re.I)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b|\bAKIA[A-Z0-9]{16}\b", "[REDACTED_KEY]", value)
    value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED_TOKEN]", value)
    value = re.sub(r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)\s*[:=]\s*[\"']?[^\s,;\"'<>]+", r"\1=[REDACTED]", value)
    value = re.sub(r"(?<!\w)(\w+://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    value = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", value)
    return value


def source_identity(record, session_id):
    payload = record.get("payload", {})
    ids = {k: payload[k] for k in ("id", "event_id", "session_id", "thread_id", "turn_id", "root_turn_id", "response_id", "call_id") if k in payload}
    item = payload.get("item", {})
    if isinstance(item, dict) and "id" in item:
        ids["item_id"] = item["id"]
    ordinal = record.get("ordinal", UNKNOWN)
    # Native session ordinal survives file relocation and repeated lines.
    native = str(ordinal) if ordinal != UNKNOWN else digest(json.dumps(record, sort_keys=True).encode())
    return {"session_id": session_id, "event_id": record.get("event_id", payload.get("event_id", ordinal)), "record_ordinal": ordinal,
            "native_ids": ids, "identity_kind": "session_ordinal" if ordinal != UNKNOWN else "record_content_hash",
            "key": digest((session_id + ":" + native).encode())}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[:2] == (".kmp-agent", "releases"):
            continue
        if any(p in (".git", ".harness", "__pycache__") for p in relative.parts):
            continue
        if path.is_symlink() or not path.is_file() or path.name == ".DS_Store":
            continue
        result[str(relative)] = digest(path.read_bytes())
    return result


def changes(before, after):
    return [{"path": p, "before_sha256": before.get(p), "after_sha256": after.get(p),
             "change": "added" if p not in before else "deleted" if p not in after else "modified"}
            for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]


class Logger:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / ".harness" / "logs"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.path = self.directory / "events.jsonl"
        spec = importlib.util.spec_from_file_location("harness_runtime_version", Path(__file__).with_name("version.py"))
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        self.harness = runtime.identity(self.root)
        spec = importlib.util.spec_from_file_location("harness_execution_context", Path(__file__).with_name("context.py"))
        context = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(context)
        self.context = context.identify(self.root)

    def read(self):
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            return [json.loads(line) for line in handle if line.strip()]

    def execution_context(self, run_id):
        start = next((e for e in self.read() if e.get("event_type") == "run_started" and e.get("run_id") == run_id), {})
        return dict(start.get("execution_context", self.context))

    def append(self, event_type, run_id=UNKNOWN, work_type=UNKNOWN, observed=None,
               summary=None, source=None, source_key=None, feature_id=UNKNOWN,
               task_id=UNKNOWN, agent_run_id=UNKNOWN, user_statement=None):
        # One lock protects deduplication, sequence allocation and durable append.
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            existing = [json.loads(line) for line in handle if line.strip()]
            if event_type == "human_intervention":
                details = summary or {}
                required = ("source_session_id", "source_message_id", "source_event_id", "basis", "role", "stage")
                if (any(not details.get(k) or details[k] == UNKNOWN for k in required)
                        or any(v in (None, "", UNKNOWN) for v in (feature_id, task_id, run_id, agent_run_id))
                        or details.get("classification") not in INTERVENTION_CLASSES):
                    raise ValueError("human_intervention requires linked source, execution context, classification and basis")
                message = next((e for e in existing if e["event_id"] == details["source_event_id"]), None)
                if (not message or message["event_type"] != "session_message"
                        or message["observed"].get("role") != "user"
                        or message["source"].get("session_id") != details["source_session_id"]
                        or message["observed"].get("message_id") != details["source_message_id"]):
                    raise ValueError("intervention source must be an imported user message")
            if source_key and any(e.get("source_key") == source_key for e in existing):
                return None
            start = next((e for e in existing if e.get("event_type") == "run_started" and e.get("run_id") == run_id), {})
            context = start.get("execution_context", self.context)
            event = {
                "schema_version": 2, "redaction_version": 1, "event_id": str(uuid.uuid4()),
                "sequence": len(existing) + 1, "recorded_at": now(),
                "event_type": event_type, "work_type": work_type,
                "run_id": run_id, "feature_id": feature_id, "task_id": task_id,
                "agent_run_id": agent_run_id,
                "harness": self.harness,
                "project_id": context["project_id"], "verification_scope": context["verification_scope"],
                "execution_context": context,
                "observed": observed or {}, "agent_summary": summary or {},
                "source": source or {"kind": "logger_runtime"},
                "source_key": source_key,
            }
            if user_statement is not None:
                event["user_statement"] = user_statement
            event = redact(event)
            handle.seek(0, 2)
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o600)
            return event

    def record_intervention(self, context, session_id, turn_id, classification, basis, evidence,
                            message_id=UNKNOWN, request_item="1"):
        if (classification not in INTERVENTION_CLASSES or not basis.strip() or not evidence
                or any(not v or v == UNKNOWN for v in (session_id, turn_id, request_item))):
            raise ValueError("explicit source session/turn, classification, basis and evidence required")
        # Context comes from Tasks.intervention, never from the latest message/time guess.
        for key in ("feature_id", "task_id", "run_id", "agent_run_id", "role", "stage", "work_type"):
            if not context.get(key) or context[key] == UNKNOWN:
                raise ValueError("explicit task execution context required")
        summary = redact({"source_session_id": session_id, "source_turn_id": turn_id,
                          "source_message_id": message_id, "request_item": request_item,
                          "classification": classification, "basis": basis, "evidence": evidence,
                          "role": context["role"], "stage": context["stage"],
                          "task_state_at_declaration": context.get("task_state", UNKNOWN),
                          "design_status_at_declaration": context.get("design_status", UNKNOWN),
                          "classification_source": "agent_declared"})
        identity = [session_id, turn_id, request_item, context["task_id"], context["agent_run_id"]]
        key = "intervention-pending:" + digest(json.dumps(identity).encode())
        previous = next((e for e in self.read() if e.get("source_key") == key), None)
        if previous and previous["agent_summary"] != summary:
            raise ValueError("existing declaration differs; do not overwrite its classification or basis")
        event = self.append("human_intervention_pending", context["run_id"], context["work_type"],
                            feature_id=context["feature_id"], task_id=context["task_id"],
                            agent_run_id=context["agent_run_id"], summary=summary,
                            source={"kind": "agent_declared_intervention"}, source_key=key)
        pending = event or next(e for e in self.read() if e.get("source_key") == key)
        self.resolve_interventions()
        return {"pending_event_id": pending["event_id"], **self.intervention_status()}

    def resolve_interventions(self):
        # Only new pending declarations participate; historical free-text events stay untouched.
        events = self.read()
        linked = {e.get("agent_summary", {}).get("pending_event_id") for e in events
                  if e["event_type"] == "human_intervention"}
        resolved = 0
        for pending in events:
            if pending["event_type"] != "human_intervention_pending" or pending["event_id"] in linked:
                continue
            details = pending["agent_summary"]
            candidates = [e for e in events if e["event_type"] == "session_message"
                          and e["observed"].get("role") == "user"
                          and e["source"].get("session_id") == details["source_session_id"]
                          and e["observed"].get("session_turn_id") == details["source_turn_id"]
                          and e["observed"].get("message_id") not in (None, "", UNKNOWN)
                          and (details["source_message_id"] == UNKNOWN
                               or e["observed"].get("message_id") == details["source_message_id"])]
            if len(candidates) != 1:
                continue  # Missing or ambiguous is pending, never "latest message".
            source = candidates[0]
            final = {**details, "pending_event_id": pending["event_id"],
                     "source_message_id": source["observed"]["message_id"],
                     "source_event_id": source["event_id"], "request_source": source["source"]}
            result = self.append("human_intervention", pending["run_id"], pending["work_type"],
                                 feature_id=pending["feature_id"], task_id=pending["task_id"],
                                 agent_run_id=pending["agent_run_id"], summary=final,
                                 observed={"source_message_id": final["source_message_id"],
                                           "source_event_id": source["event_id"],
                                           "source_session_id": details["source_session_id"],
                                           "source_turn_id": details["source_turn_id"],
                                           "occurred_at": source["observed"].get("occurred_at", UNKNOWN)},
                                 source={"kind": "intervention_linker"},
                                 source_key="intervention-linked:" + pending["event_id"])
            resolved += result is not None
        return resolved

    def intervention_status(self):
        events = self.read()
        pending = [e["event_id"] for e in events if e["event_type"] == "human_intervention_pending"]
        linked = {e.get("agent_summary", {}).get("pending_event_id") for e in events
                  if e["event_type"] == "human_intervention" and e["source"].get("kind") == "intervention_linker"}
        return {"linked_interventions": len(linked),
                "pending_intervention_ids": [p for p in pending if p not in linked],
                "legacy_unlinked_interventions": sum(e["event_type"] == "human_intervention"
                                                     and e["source"].get("kind") != "intervention_linker" for e in events)}

    def migrate(self):
        """Redact existing local logs and add identities verified against source lines."""
        if not self.path.exists():
            return 0
        with self.path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            events = [json.loads(line) for line in handle if line.strip()]
            cache = {}
            for event in events:
                event["redaction_version"] = 1
                source = event.get("source", {})
                if source.get("kind") != "codex_session_import":
                    continue
                path = source.get("path")
                if path not in cache:
                    p = Path(path)
                    records = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
                    meta = next((r["payload"] for r in records if r.get("type") == "session_meta"), {})
                    cache[path] = (records, meta.get("session_id", meta.get("id", UNKNOWN)))
                records, session = cache[path]
                record = records[source["line"] - 1]
                identity = source_identity(record, session)
                source.update({k: v for k, v in identity.items() if k != "key"})
                event["source_key"] = identity["key"]
                if event["event_type"] == "model_usage":
                    payload = record["payload"]
                    event["observed"]["usage_semantics"] = "per_response_increment"
                    event["observed"]["turn_token_usage"] = payload.get("turn_token_usage", UNKNOWN)
                    event["observed"]["thread_token_usage"] = payload.get("thread_token_usage", UNKNOWN)
            sanitized = [redact(event) for event in events]
            handle.seek(0)
            handle.write("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in sanitized))
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o600)
        return len(events)

    def start(self, work_type, role, request):
        if work_type not in KINDS:
            raise ValueError("invalid work_type")
        run_id = str(uuid.uuid4())
        proc = subprocess.run(["rtk", "proxy", "git", "rev-parse", "HEAD"],
                              cwd=self.root, capture_output=True, text=True)
        self.append("run_started", run_id, work_type,
                    observed={"started_at": now(), "files": snapshot(self.root),
                              "git_commit": proc.stdout.strip() if proc.returncode == 0 else UNKNOWN,
                              "python": sys.version.split()[0], "platform": sys.platform,
                              "logger_sha256": digest(Path(__file__).read_bytes()),
                              "session_id": os.getenv("CODEX_THREAD_ID", UNKNOWN),
                              "tokens": UNKNOWN, "cost": UNKNOWN},
                    summary={"role": role, "request_summary": request,
                             "work_type_source": "agent_declared"})
        return run_id

    def run(self, run_id):
        found = [e for e in self.read() if e["run_id"] == run_id and e["event_type"] == "run_started"]
        if not found:
            raise ValueError("unknown run_id")
        return found[0]

    def checkpoint(self, run_id, result, finish=False):
        start = self.run(run_id)
        if any(e["run_id"] == run_id and e["event_type"] == "run_finished" for e in self.read()):
            raise ValueError("run already finished")
        observed = {"changed_files": changes(start["observed"]["files"], snapshot(self.root)),
                    "tokens": UNKNOWN, "cost": UNKNOWN}
        if finish:
            observed["ended_at"] = now()
        return self.append("run_finished" if finish else "checkpoint", run_id,
                           start["work_type"], observed=observed, summary={"result": result})

    def command(self, run_id, command=None, task_id=UNKNOWN, agent_run_id=UNKNOWN,
                attempt_id=UNKNOWN, command_kind=UNKNOWN, command_name=None):
        start = self.run(run_id)
        if any(e["run_id"] == run_id and e["event_type"] == "run_finished" for e in self.read()):
            raise ValueError("run already finished")
        sys.path.insert(0, str(ROOT))
        from harness.sequential import command_context, validate_settings, KINDS
        context, binding = command_context(self.root, run_id, task_id, agent_run_id, attempt_id)
        cwd = self.root
        if command_name is not None:
            config_path = self.root / ".harness/settings/sequential.json"
            config_bytes = config_path.read_bytes() if config_path.exists() else None
            config = validate_settings(json.loads(config_bytes)) if config_bytes is not None else None
            if command or config is None or command_name not in config.get("commands", {}):
                raise ValueError("choose an existing named command without explicit argv")
            selected = config["commands"][command_name]
            if command_kind != UNKNOWN and command_kind != selected["kind"]:
                raise ValueError("command kind conflicts with named configuration")
            command, command_kind = selected["argv"], selected["kind"]
            cwd = (self.root / selected.get("cwd", ".")).resolve()
            binding["command_settings_sha256"] = digest(config_bytes)
        if command_kind not in KINDS:
            raise ValueError("unsupported command kind")
        if not cwd.is_relative_to(self.root) or not cwd.is_dir():
            raise ValueError("command cwd must exist inside target project")
        if not command or command[0] != "rtk":
            raise ValueError("wrapped commands must start with rtk")
        before = snapshot(self.root)
        call_id = str(uuid.uuid4())
        metadata = {**binding, "call_id": call_id, "command_kind": command_kind,
                    "command_name": command_name or UNKNOWN, "cwd": str(cwd.relative_to(self.root))}
        self.append("command_started", run_id, start["work_type"],
                    **context, observed={**metadata, "started_at": now(),
                              "argv_sha256": digest(json.dumps(command).encode())})
        timer = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True)
        except (OSError, KeyboardInterrupt) as error:
            self.append("command_finished", run_id, start["work_type"],
                        **context, observed={**metadata, "ended_at": now(), "elapsed_seconds": time.monotonic() - timer, "error_type": type(error).__name__,
                                  "returncode": UNKNOWN, "changed_files": changes(before, snapshot(self.root))})
            raise
        self.append("command_finished", run_id, start["work_type"],
                    **context, observed={**metadata, "ended_at": now(), "elapsed_seconds": time.monotonic() - timer, "returncode": proc.returncode,
                              "stdout_sha256": digest(proc.stdout), "stderr_sha256": digest(proc.stderr),
                              "changed_files": changes(before, snapshot(self.root))})
        sys.stdout.buffer.write(proc.stdout)
        sys.stderr.buffer.write(proc.stderr)
        return proc.returncode

    def sync(self, session_path, run_id=UNKNOWN, content=None):
        """Compatible full-source sync; batch writes, then explicit legacy linking.

        The hook adapter is not a Logger and follows the conversion body below.
        This keeps its incremental parsing and existing source identities unchanged.
        """
        if isinstance(self, Logger):
            spec = importlib.util.spec_from_file_location("legacy_batch_sync", Path(__file__).with_name("incremental_sync.py"))
            batch = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(batch)
            adapter = batch.Collector(self, 0, 0)
            metadata = {}
            adapter.write_metadata = metadata.__setitem__
            started = time.monotonic()
            Logger.sync(adapter, session_path, run_id, content=content)
            stats = {"mode": "legacy_full"}
            imported = batch.append_batch(self, adapter.events, stats)
            metadata = dict(metadata["last-sync.json"], imported=imported)
            self.write_metadata("last-sync.json", metadata)
            self.resolve_interventions()
            self.last_collection = {**stats, "elapsed_seconds": time.monotonic()-started}
            return imported
        path = Path(session_path).resolve()
        imported = 0
        turn_id = UNKNOWN
        model = UNKNOWN
        data = path.read_bytes() if content is None else content
        records = []
        for number, line in enumerate(data.decode("utf-8").splitlines(keepends=True), 1):
            try:
                records.append((number, line, json.loads(line)))
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break
                raise
        meta = next((r["payload"] for _, _, r in records if r.get("type") == "session_meta"), {})
        session = meta.get("session_id", meta.get("id", UNKNOWN))
        # Partial final lines are skipped and retried on the next sync.
        if records:
            for number, line, record in records:
                payload = record.get("payload", {})
                kind = record.get("type")
                subtype = payload.get("type")
                if kind == "event_msg" and subtype == "task_started":
                    turn_id = payload.get("turn_id", UNKNOWN)
                if kind == "turn_context":
                    model = payload.get("model", UNKNOWN)
                observed = {"occurred_at": record.get("timestamp", UNKNOWN),
                            "session_turn_id": turn_id}
                event_type = None
                if kind == "token_usage_record":
                    event_type = "model_usage"
                    observed.update({k: payload.get(k, UNKNOWN) for k in
                                     ("thread_id", "turn_id", "response_id", "usage")})
                    observed.update({"cost": UNKNOWN, "duration_ms": UNKNOWN, "model": model})
                    observed.update({"usage_semantics": "per_response_increment",
                                     "turn_token_usage": payload.get("turn_token_usage", UNKNOWN),
                                     "thread_token_usage": payload.get("thread_token_usage", UNKNOWN)})
                elif kind == "event_msg" and subtype == "token_count":
                    event_type = "usage_snapshot"
                    observed["info"] = payload.get("info", UNKNOWN)
                    observed["aggregation"] = "excluded_snapshot"
                elif kind == "event_msg" and subtype in ("task_started", "task_complete", "turn_aborted"):
                    event_type = "session_" + subtype
                    observed.update({k: payload.get(k, UNKNOWN) for k in
                                     ("turn_id", "started_at", "completed_at", "duration_ms", "reason", "error")})
                elif kind == "response_item" and subtype == "message" and payload.get("role") in ("user", "assistant"):
                    # Store user requests and final results only, never hidden reasoning.
                    if payload.get("role") == "user" or payload.get("phase") == "final_answer":
                        event_type = "session_message"
                        observed.update({"role": payload.get("role"), "content": payload.get("content", []),
                                         "message_id": payload.get("id", UNKNOWN)})
                elif kind == "response_item" and subtype in ("function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"):
                    event_type = "session_tool_event"
                    observed.update({"item_type": subtype, "call_id": payload.get("call_id", UNKNOWN),
                                     "tool_name": payload.get("name", UNKNOWN),
                                     "status": payload.get("status", UNKNOWN),
                                     "payload_sha256": digest(json.dumps(payload, sort_keys=True).encode())})
                elif kind == "event_msg" and subtype == "item_completed":
                    event_type = "session_item_timing"
                    item = payload.get("item", {})
                    observed.update({k: payload.get(k, UNKNOWN) for k in
                                     ("turn_id", "started_at_ms", "completed_at_ms")})
                    observed["item_id"] = item.get("id", UNKNOWN) if isinstance(item, dict) else UNKNOWN
                if event_type:
                    identity = source_identity(record, session)
                    key = identity.pop("key")
                    event = self.append(event_type, run_id, observed=observed,
                                        source={"kind": "codex_session_import", "path": str(path),
                                                "line": number, "record_type": kind,
                                                **identity,
                                                "historical_classification": UNKNOWN}, source_key=key)
                    imported += event is not None
        self.write_metadata("last-sync.json", {"completed_at": now(), "source_path": str(path),
                            "source_session_id": session, "snapshot_sha256": digest(data),
                            "snapshot_bytes": len(data), "complete_records": len(records),
                            "last_source_timestamp": records[-1][2].get("timestamp", UNKNOWN) if records else UNKNOWN,
                            "imported": imported})
        self.resolve_interventions()
        return imported

    def write_metadata(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)

    def status(self):
        events = self.read()
        groups = {}
        for event in events:
            key = (event.get("project_id", UNKNOWN), event.get("verification_scope", UNKNOWN))
            groups[key] = groups.get(key, 0) + 1
        usage = {}
        duplicate_reports = 0
        conflicts = 0
        for event in events:
            if event["event_type"] != "model_usage":
                continue
            obs = event["observed"]
            response = obs.get("response_id", UNKNOWN)
            if response == UNKNOWN:
                continue
            key = (event["source"].get("session_id", UNKNOWN), response)
            if key in usage:
                duplicate_reports += 1
                conflicts += usage[key] != obs.get("usage", UNKNOWN)
                # Never overwrite one response with an inconsistent report silently.
                if usage[key] != obs.get("usage", UNKNOWN):
                    usage[key] = UNKNOWN
            else:
                usage[key] = obs.get("usage", UNKNOWN)
        fields = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
        values = list(usage.values())
        totals = {k: (sum(v[k] for v in values if isinstance(v, dict) and isinstance(v.get(k), int))
                      if any(isinstance(v, dict) and isinstance(v.get(k), int) for v in values) else UNKNOWN) for k in fields}
        missing = {k: sum(not isinstance(v, dict) or not isinstance(v.get(k), int) for v in values) for k in fields}
        sync_path = self.directory / "last-sync.json"
        return {**self.context, "path": str(self.path), "events": len(events),
                "event_identity_groups": [{"project_id": k[0], "verification_scope": k[1], "events": count} for k, count in groups.items()],
                "legacy_events_without_project_id": sum("project_id" not in e for e in events),
                "collection_started_at": events[0]["recorded_at"] if events else UNKNOWN,
                "model_responses": len(usage), "reported_tokens": totals, "usage_missing_fields": missing,
                "known_responses_missing_usage": sum(not isinstance(v, dict) or any(not isinstance(v.get(k), int) for k in ("input_tokens", "output_tokens")) for v in values),
                "unobserved_model_calls": UNKNOWN, "duplicate_usage_reports": duplicate_reports,
                "conflicting_usage_reports": conflicts,
                "usage_events_missing_response_id": sum(e["event_type"] == "model_usage" and e["observed"].get("response_id", UNKNOWN) == UNKNOWN for e in events),
                "cost": UNKNOWN, "usage_scope": "unique imported model response IDs; not user turns or full current-run usage",
                "interventions": self.intervention_status(),
                "last_sync": json.loads(sync_path.read_text()) if sync_path.exists() else UNKNOWN}

    def audit(self, session_path):
        path = Path(session_path).resolve()
        content = path.read_bytes()  # Freeze in memory; never persist a raw copy.
        warmup = self.sync(path, content=content)
        before = self.status()
        first = self.sync(path, content=content)
        middle = self.status()
        second = self.sync(path, content=content)
        after = self.status()
        checked = ("events", "model_responses", "reported_tokens", "usage_missing_fields")
        stable = all(before[k] == middle[k] == after[k] for k in checked)
        records = []
        for line in content.decode("utf-8").splitlines(keepends=True):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break
                raise
        reports = [r for r in records if r.get("type") == "token_usage_record"]
        snapshots = [r["payload"].get("info", {}) for r in records
                     if r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "token_count"]
        unique = {}
        running = {}
        increment_mismatches = []
        for r in reports:
            payload = r["payload"]
            key = payload.get("response_id", UNKNOWN)
            if key != UNKNOWN and key not in unique:
                value = payload.get("usage", UNKNOWN)
                unique[key] = value
                cumulative = payload.get("thread_token_usage", {})
                for field in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens"):
                    if isinstance(value, dict) and isinstance(value.get(field), int):
                        running[field] = running.get(field, 0) + value[field]
                        if cumulative and running[field] != cumulative.get(field):
                            increment_mismatches.append({"response_id": key, "field": field})
        sums = {k: (sum(v[k] for v in unique.values() if isinstance(v, dict) and isinstance(v.get(k), int))
                    if any(isinstance(v, dict) and isinstance(v.get(k), int) for v in unique.values()) else UNKNOWN)
                for k in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")}
        last = reports[-1]["payload"].get("thread_token_usage", {}) if reports else {}
        report = {
            "verified_at": now(), "snapshot": after["last_sync"],
            "warmup_imported": warmup, "repeat_imported": [first, second],
            "events_across_repeats": [before["events"], middle["events"], after["events"]],
            "tokens_across_repeats": [before["reported_tokens"], middle["reported_tokens"], after["reported_tokens"]],
            "idempotency_pass": stable and first == second == 0,
            "source_first_timestamp": records[0].get("timestamp", UNKNOWN) if records else UNKNOWN,
            "source_usage_records": len(reports), "source_unique_response_ids": len(unique),
            "source_user_turns": len({r["payload"].get("turn_id") for r in records
                                     if r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "task_started"}),
            "first_44_responses_distinct_turns": len({r["payload"].get("turn_id") for r in reports[:44]}) if len(reports) >= 44 else UNKNOWN,
            "source_duplicate_response_reports": sum(r["payload"].get("response_id", UNKNOWN) != UNKNOWN for r in reports) - len(unique),
            "source_token_count_snapshots": len(snapshots),
            "responses_also_repeated_in_token_count": sum(any(s.get("last_token_usage") == r["payload"].get("usage")
                and s.get("total_token_usage") == r["payload"].get("thread_token_usage") for s in snapshots) for r in reports),
            "sum_unique_usage": sums, "last_thread_token_usage": last,
            "increments_match_thread_cumulative": bool(reports) and all(sums[k] == last.get(k) for k in sums),
            "per_response_increment_mismatches": increment_mismatches,
            "input_plus_output_matches_total": all(isinstance(v, dict) and all(isinstance(v.get(k), int) for k in ("input_tokens", "output_tokens", "total_tokens"))
                                                   and v["input_tokens"] + v["output_tokens"] == v["total_tokens"] for v in unique.values()),
            "cached_is_subset_of_input": all(isinstance(v, dict) and isinstance(v.get("cached_input_tokens"), int) and isinstance(v.get("input_tokens"), int)
                                             and 0 <= v["cached_input_tokens"] <= v["input_tokens"] for v in unique.values()),
            "status": after,
        }
        self.write_metadata("audit.json", report)
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--session-path", type=Path, help="session source for lifecycle sync")
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start")
    start.add_argument("--work-type", choices=KINDS, required=True)
    start.add_argument("--role", required=True)
    start.add_argument("--request", required=True)
    for name in ("checkpoint", "finish"):
        p = sub.add_parser(name)
        p.add_argument("run_id")
        p.add_argument("--result", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("session_path", type=Path)
    audit = sub.add_parser("audit")
    audit.add_argument("session_path", type=Path)
    sub.add_parser("migrate")
    event = sub.add_parser("event")
    event.add_argument("run_id")
    event.add_argument("--type", required=True)
    event.add_argument("--summary", required=True)
    command = sub.add_parser("command")
    command.add_argument("run_id")
    command.add_argument("--task-id", default=UNKNOWN)
    command.add_argument("--agent-run-id", default=UNKNOWN)
    command.add_argument("--attempt-id", default=UNKNOWN)
    command.add_argument("--command-kind", default=UNKNOWN)
    command.add_argument("--command-name")
    command.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    args = parser.parse_args()
    logger = Logger(args.root)
    if args.action in {"start", "checkpoint", "finish", "event", "command"}:
        # Persist source messages before interpreting a request or reporting completion.
        source = resolve_session(args.session_path)
        if source is not None:
            logger.sync(source)
        else:
            print("Source sync unavailable: no session id/path (offline execution).", file=sys.stderr)
    if args.action == "start":
        print(logger.start(args.work_type, args.role, args.request))
    elif args.action in ("checkpoint", "finish"):
        print(json.dumps(logger.checkpoint(args.run_id, args.result, args.action == "finish"), ensure_ascii=False))
    elif args.action == "sync":
        print(json.dumps({"imported": logger.sync(args.session_path), "path": str(logger.path)}))
    elif args.action == "audit":
        print(json.dumps(logger.audit(args.session_path), ensure_ascii=False))
    elif args.action == "migrate":
        print(json.dumps({"migrated": logger.migrate()}))
    elif args.action == "event":
        start = logger.run(args.run_id)
        logger.append(args.type, args.run_id, start["work_type"], summary={"text": args.summary})
    elif args.action == "command":
        sys.exit(logger.command(args.run_id, args.argv, args.task_id, args.agent_run_id,
                                args.attempt_id, args.command_kind, args.command_name))
    else:
        print(json.dumps(logger.status(), ensure_ascii=False))


def resolve_session(explicit=None, session_id=None):
    session_id = session_id or os.getenv("CODEX_THREAD_ID")
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError("session source does not exist")
    elif session_id:
        home = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
        matches = list((home / "sessions").rglob("*" + session_id + "*.jsonl"))
        if len(matches) != 1:
            raise ValueError("session source missing or ambiguous; use --session-path")
        path = matches[0].resolve()
    else:
        return None
    # Never silently import a different conversation into the task log.
    with path.open() as handle:
        first = json.loads(next(handle))
    meta = first.get("payload", {}) if first.get("type") == "session_meta" else {}
    actual_id = meta.get("session_id", meta.get("id"))
    if not actual_id or (session_id and actual_id != session_id):
        raise ValueError("session source identity mismatch")
    return path


if __name__ == "__main__":
    main()
