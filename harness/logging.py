"""Local, stdlib-only JSONL logger. No model or external service calls."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import uuid

UNKNOWN = "UNKNOWN"
KINDS = ("HARNESS_BUILD", "HARNESS_IMPROVEMENT", "PRODUCT")
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
    value = re.sub(r"(\w+://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", value)
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

    def read(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def append(self, event_type, run_id=UNKNOWN, work_type=UNKNOWN, observed=None,
               summary=None, source=None, source_key=None, feature_id=UNKNOWN,
               task_id=UNKNOWN, agent_run_id=UNKNOWN, user_statement=None):
        # One lock protects deduplication, sequence allocation and durable append.
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            existing = [json.loads(line) for line in handle if line.strip()]
            if source_key and any(e.get("source_key") == source_key for e in existing):
                return None
            event = {
                "schema_version": 2, "redaction_version": 1, "event_id": str(uuid.uuid4()),
                "sequence": len(existing) + 1, "recorded_at": now(),
                "event_type": event_type, "work_type": work_type,
                "run_id": run_id, "feature_id": feature_id, "task_id": task_id,
                "agent_run_id": agent_run_id,
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

    def command(self, run_id, command):
        start = self.run(run_id)
        if any(e["run_id"] == run_id and e["event_type"] == "run_finished" for e in self.read()):
            raise ValueError("run already finished")
        if not command or command[0] != "rtk":
            raise ValueError("wrapped commands must start with rtk")
        before = snapshot(self.root)
        call_id = str(uuid.uuid4())
        self.append("command_started", run_id, start["work_type"],
                    observed={"call_id": call_id, "started_at": now(),
                              "argv_sha256": digest(json.dumps(command).encode())})
        try:
            proc = subprocess.run(command, cwd=self.root, capture_output=True)
        except OSError as error:
            self.append("command_finished", run_id, start["work_type"],
                        observed={"call_id": call_id, "ended_at": now(), "error_type": type(error).__name__,
                                  "returncode": UNKNOWN, "changed_files": changes(before, snapshot(self.root))})
            raise
        self.append("command_finished", run_id, start["work_type"],
                    observed={"call_id": call_id, "ended_at": now(), "returncode": proc.returncode,
                              "stdout_sha256": digest(proc.stdout), "stderr_sha256": digest(proc.stderr),
                              "changed_files": changes(before, snapshot(self.root))})
        sys.stdout.buffer.write(proc.stdout)
        sys.stderr.buffer.write(proc.stderr)
        return proc.returncode

    def sync(self, session_path, run_id=UNKNOWN, content=None):
        """Import only observed records; never infer historical work types/roles."""
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
        return imported

    def write_metadata(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n")
        path.chmod(0o600)

    def status(self):
        events = self.read()
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
        return {"path": str(self.path), "events": len(events),
                "collection_started_at": events[0]["recorded_at"] if events else UNKNOWN,
                "model_responses": len(usage), "reported_tokens": totals, "usage_missing_fields": missing,
                "known_responses_missing_usage": sum(not isinstance(v, dict) or any(not isinstance(v.get(k), int) for k in ("input_tokens", "output_tokens")) for v in values),
                "unobserved_model_calls": UNKNOWN, "duplicate_usage_reports": duplicate_reports,
                "conflicting_usage_reports": conflicts,
                "usage_events_missing_response_id": sum(e["event_type"] == "model_usage" and e["observed"].get("response_id", UNKNOWN) == UNKNOWN for e in events),
                "cost": UNKNOWN, "usage_scope": "unique imported model response IDs; not user turns or full current-run usage",
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
    command.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    args = parser.parse_args()
    logger = Logger(args.root)
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
        sys.exit(logger.command(args.run_id, args.argv))
    else:
        print(json.dumps(logger.status(), ensure_ascii=False))


if __name__ == "__main__":
    main()
