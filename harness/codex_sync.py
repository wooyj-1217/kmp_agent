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
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("diagnostic lock budget exceeded")
                time.sleep(.01)
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
    spec = importlib.util.spec_from_file_location("harness_incremental", Path(__file__).with_name("incremental_sync.py"))
    incremental = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(incremental)
    # Metadata lookup reads the first record only, never scans the session.
    with source.open(encoding="utf-8") as f:
        first = json.loads(f.readline())
    if trace:
        trace("sync_started", repository_root=str(root), harness=logger.harness,
              events_path=str(logger.path), harness_root=str(Path(__file__).resolve().parents[1]),
              resolved_source_path=str(source), source_bytes=source.stat().st_size,
              session_created_at=first.get("payload", {}).get("timestamp", first.get("timestamp", "UNKNOWN")))
    imported = incremental.collect(logger, source, mode="hook", trace=trace)
    if trace:
        trace("sync_finished", imported_events=imported, **{k:v for k,v in logger.last_collection.items() if k != "imported_events"})
    return imported


def main(supervised=False):
    global DIAGNOSTIC_PATH
    invocation_id = os.environ.get("KMP_HOOK_INVOCATION_ID") or str(uuid.uuid4())
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
        context.update(load_projects().project_context(process_root))
        # Reuse approved manifest metadata; no runtime tree scan or reconciliation.
        state_path = process_root / ".harness/integration.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        cached_components = state.get("snapshot", {}).get("components", "DEFERRED")
        # Project verification/fingerprinting is an explicit maintenance command.
        trace("hook_entered", cwd=payload.get("cwd"), transcript_path=payload.get("transcript_path"),
              integration_components=cached_components, integration_components_basis="approved_manifest_cache", integration_error=None,
              hook_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              collector_script_sha256=hashlib.sha256(Path(__file__).with_name("incremental_sync.py").read_bytes()).hexdigest())
        handle(payload, trace=trace)
    except Exception as error:
        try:
            trace("collector_failed" if supervised else "hook_exited", exit_code=1, error_type=type(error).__name__,
                  error_detail=harness_logging.redact(str(error)) if harness_logging is not None else None,
                  subprocess_exit_code=getattr(error, "returncode", None),
                  elapsed_seconds=time.monotonic() - started)
        except (OSError, ValueError):
            pass
        # No prompt or source content in diagnostics; no false success.
        print(json.dumps({"systemMessage": "Harness source sync failed: " + type(error).__name__}))
        return 1
    # Flush the response before the final marker. Missing marker remains UNKNOWN;
    # the external hook runner's process status is still the final exit authority.
    print("{}", flush=True)
    trace("collector_ready" if supervised else "hook_exited", exit_code=0, error_type=None, completion_scope="collector_and_response",
          elapsed_seconds=time.monotonic() - started)
    return 0


def supervise():
    """Observe collector subprocess exit; leave interrupted wrapper runs UNKNOWN."""
    global DIAGNOSTIC_PATH
    root = repository_root(Path.cwd())
    DIAGNOSTIC_PATH = root / ".harness/logs/hook-diagnostics.jsonl"
    invocation = str(uuid.uuid4())
    started = time.monotonic()
    raw = sys.stdin.read()
    payload = json.loads(raw)
    context = {k: payload.get(k,"UNKNOWN") for k in ("hook_event_name","session_id","turn_id")}
    context.update(load_projects().project_context(root))
    env = dict(os.environ, KMP_HOOK_INVOCATION_ID=invocation)
    try:
        child = subprocess.run([sys.executable,"-B",str(Path(__file__).resolve()),"--worker"],
                               input=raw, text=True, capture_output=True, env=env, timeout=110)
        code = child.returncode
        if code == 0 and child.stdout.strip() != "{}":
            code = 1  # A clean process exit without the completion response is not success.
        print(child.stdout.strip() or json.dumps({"systemMessage":"Harness collector returned no response"}),flush=True)
        diagnostic(invocation,"hook_exited",**context,exit_code=code,
                   completion_scope="observed_collector_process_exit",
                   elapsed_seconds=time.monotonic()-started)
        return code
    except subprocess.TimeoutExpired:
        diagnostic(invocation,"hook_exited",**context,exit_code=1,error_type="CollectorTimeout",
                   completion_scope="collector_timeout_reaped",elapsed_seconds=time.monotonic()-started)
        print(json.dumps({"systemMessage":"Harness collection exceeded internal budget; retry pending"}),flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(supervised=True) if sys.argv[1:] == ["--worker"] else supervise())
