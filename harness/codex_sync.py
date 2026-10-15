"""Codex lifecycle hook: collect source records only; never classify requests."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import os
import hashlib
import fcntl
import time
import uuid
from datetime import datetime, timezone

harness_logging = None
projects = None
DIAGNOSTIC_PATH = None  # Selected from the invoking repository, not the script location.


def repository_root(cwd):
    git = subprocess.run(["rtk", "proxy", "git", "rev-parse", "--show-toplevel"],
                         cwd=cwd, capture_output=True, text=True, check=True)
    return Path(git.stdout.strip()).resolve()


def load_logger():
    global harness_logging
    if harness_logging is None:
        spec = importlib.util.spec_from_file_location("harness_logger", Path(__file__).with_name("logging.py"))
        harness_logging = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(harness_logging)
    return harness_logging


def load_projects():
    global projects
    if projects is None:
        spec = importlib.util.spec_from_file_location("harness_projects", Path(__file__).with_name("projects.py"))
        projects = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(projects)
    return projects


def diagnostic(invocation_id, phase, **fields):
    if DIAGNOSTIC_PATH is None:
        raise ValueError("hook diagnostic repository unavailable")
    DIAGNOSTIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_PATH.parent.chmod(0o700)
    record = {"invocation_id": invocation_id, "phase": phase,
              "recorded_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), **fields}
    if harness_logging is not None:
        record = harness_logging.redact(record)
    # Metadata only: no prompt, credentials, tool arguments, or transcript body.
    with DIAGNOSTIC_PATH.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        os.fchmod(handle.fileno(), 0o600)
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def source_probe(path, prompt=None):
    users = []
    last_timestamp = None
    session_created_at = "UNKNOWN"
    with path.open(encoding="utf-8") as handle:
        for line, raw in enumerate(handle, 1):
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            last_timestamp = row.get("timestamp", last_timestamp)
            payload = row.get("payload", {})
            if row.get("type") == "session_meta":
                session_created_at = payload.get("timestamp", row.get("timestamp", "UNKNOWN"))
            if row.get("type") == "response_item" and payload.get("role") == "user":
                text = "".join(x.get("text", "") for x in payload.get("content", []) if isinstance(x, dict))
                users.append({"message_id": payload.get("id"), "line": line,
                              "timestamp": row.get("timestamp"),
                              "prompt_matches": text == prompt if prompt is not None else None})
    return {"source_bytes": path.stat().st_size, "source_last_timestamp": last_timestamp,
            "session_created_at": session_created_at,
            "source_user_count": len(users), "source_latest_user": users[-1] if users else None,
            "source_contains_hook_prompt": any(x["prompt_matches"] for x in users) if prompt is not None else None}


def handle(payload, trace=None):
    logger_module = load_logger()
    if payload.get("hook_event_name") not in {"UserPromptSubmit", "Stop"}:
        raise ValueError("unsupported lifecycle event")
    cwd = Path(payload["cwd"]).resolve()
    root = repository_root(cwd)
    source = logger_module.resolve_session(payload.get("transcript_path"), payload["session_id"])
    if source is None:
        raise ValueError("hook transcript unavailable")
    logger = logger_module.Logger(root)
    if trace:
        trace("sync_started", repository_root=str(root),
              harness=logger.harness,
              events_path=str(root / ".harness/logs/events.jsonl"),
              harness_root=str(Path(__file__).resolve().parents[1]),
              resolved_source_path=str(source), **source_probe(source, payload.get("prompt")))
    imported = logger.sync(source)
    if trace:
        events = logger.read()
        latest = [x for x in events if x["event_type"] == "session_message"
                  and x["source"].get("session_id") == payload["session_id"]
                  and x["observed"].get("role") == "user"]
        trace("sync_finished", imported_events=imported, intervention_links=logger.intervention_status(),
              collected_user_count=len(latest),
              latest_collected_message_id=latest[-1]["observed"].get("message_id") if latest else None,
              **source_probe(source, payload.get("prompt")))
    return imported


def main():
    global DIAGNOSTIC_PATH
    invocation_id = str(uuid.uuid4())
    started = time.monotonic()
    context = {"hook_event_name": "UNKNOWN", "session_id": "UNKNOWN", "turn_id": "UNKNOWN",
               "project_id": "UNKNOWN", "project_id_reason": "execution_context_not_resolved_yet",
               "verification_scope": "UNKNOWN"}
    trace = lambda phase, **fields: diagnostic(invocation_id, phase, **context, **fields)
    try:
        process_root = repository_root(Path.cwd())
        if DIAGNOSTIC_PATH is None:
            DIAGNOSTIC_PATH = process_root / ".harness/logs/hook-diagnostics.jsonl"
        trace("process_entered")
        payload = json.load(sys.stdin)
        context.update({k: payload.get(k, "UNKNOWN") for k in ("hook_event_name", "session_id", "turn_id")})
        if repository_root(Path(payload["cwd"]).resolve()) != process_root:
            raise ValueError("hook process and payload repository differ")
        manager = None
        components, integration_error = "UNKNOWN", None
        try:
            manager = load_projects()
            context.update(manager.project_context(process_root))
            state = manager.read_json(process_root / ".harness/integration.json", {})
            components = manager.fingerprint(process_root, state.get("skills", []))["components"]
        except Exception as error:
            integration_error = type(error).__name__
        trace("hook_entered", cwd=payload.get("cwd"), transcript_path=payload.get("transcript_path"),
              integration_components=components, integration_error=integration_error,
              hook_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        handle(payload, trace=trace)
    except Exception as error:
        try:
            trace("hook_exited", exit_code=1, error_type=type(error).__name__,
                  error_detail=harness_logging.redact(str(error)) if harness_logging is not None else None,
                  subprocess_exit_code=getattr(error, "returncode", None),
                  elapsed_seconds=time.monotonic() - started)
        except (OSError, ValueError):
            pass
        # No prompt or source content in diagnostics; no false success.
        print(json.dumps({"systemMessage": "Harness source sync failed: " + type(error).__name__}))
        return 1
    trace("hook_exited", exit_code=0, error_type=None, elapsed_seconds=time.monotonic() - started)
    try:
        if manager is None:
            raise ValueError("integration manager unavailable")
        manager.after_hook(process_root, payload["session_id"])
    except Exception as error:
        # Propagation failures must not erase successful raw source collection.
        trace("integration_check_failed", error_type=type(error).__name__)
        print(json.dumps({"systemMessage": "Harness target verification failed: " + type(error).__name__}))
        return 1
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
