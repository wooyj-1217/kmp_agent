"""Sequential evidence collection, not a scheduler or parallelization analyzer."""
import copy
import fcntl
import json
import os
from pathlib import Path
import uuid
from datetime import datetime

from harness import logging as log

UNKNOWN = log.UNKNOWN
KINDS = {"development", "build", "test", "integration", "other", UNKNOWN}
SETTINGS = ".harness/settings/sequential.json"


def validate_settings(data):
    if not isinstance(data, dict) or set(data) - {"schema_version", "modules", "commands"} or data.get("schema_version") != 1:
        raise ValueError("collection settings require schema_version 1, modules and commands")
    modules, commands = data.get("modules", {}), data.get("commands", {})
    if not isinstance(modules, dict) or not isinstance(commands, dict):
        raise ValueError("modules and commands must be objects")
    def relative(value):
        return isinstance(value, str) and bool(value) and not Path(value).is_absolute() and ".." not in Path(value).parts
    for name, paths in modules.items():
        if not name or not isinstance(paths, list) or not paths or not all(relative(p) for p in paths):
            raise ValueError("module paths must be nonempty project-relative paths")
    for name, command in commands.items():
        if not name or not isinstance(command, dict) or set(command) - {"kind", "argv", "cwd"}:
            raise ValueError("invalid named command")
        argv = command.get("argv")
        if command.get("kind") not in KINDS or not isinstance(argv, list) or not argv or argv[0] != "rtk" or not all(isinstance(a, str) for a in argv):
            raise ValueError("named command needs kind and trusted rtk argv")
        if not relative(command.get("cwd", ".")):
            raise ValueError("command cwd must be project-relative")
    return copy.deepcopy(data)


def settings(root):
    path = Path(root) / SETTINGS
    return validate_settings(json.loads(path.read_text())) if path.exists() else None


def save_settings(root, data):
    data = validate_settings(data)
    path = Path(root) / SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (path.parent / "sequential.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        temporary = path.with_name(".sequential-" + str(uuid.uuid4()))
        try:
            with temporary.open("x") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"path": SETTINGS, "sha256": log.digest(path.read_bytes()), "automatic_execution": False}


def read_state(root):
    directory = Path(root) / ".harness/tasks"
    if not directory.exists():
        return {"tasks": {}}
    with (directory / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        path = directory / "tasks.yaml"
        return json.loads(path.read_text()) if path.exists() else {"tasks": {}}


def configure(manager, task_id, dependency_relations=None, shared_modules=None, shared_resources=None,
              feature_version=None, baseline_id=None, agent_run_id=None):
    """Declarations never inferred from event order, filenames or elapsed time."""
    def operation(state):
        task = state["tasks"][task_id]
        active = [r for r in task["executions"] if r["ended_at"] is None]
        if active and (len(active) != 1 or active[0]["agent_run_id"] != agent_run_id):
            raise ValueError("declarations during execution require the explicit active agent_run_id")
        if active and (feature_version is not None or baseline_id is not None):
            raise ValueError("set feature/baseline identity before execution; frozen identity cannot be changed")
        old = copy.deepcopy(task.get("collection", {}))
        data = copy.deepcopy(old)
        if dependency_relations is not None:
            if not isinstance(dependency_relations, list):
                raise ValueError("dependency_relations must be an explicit list")
            ids = []
            for edge in dependency_relations:
                if not isinstance(edge, dict) or set(edge) != {"task_id", "kind", "reason"}:
                    raise ValueError("dependency relation needs task_id, kind and reason")
                target = state["tasks"].get(edge["task_id"])
                if not target or target["task_id"] == task_id or target["feature_id"] != task["feature_id"] or edge["kind"] not in {"REQUIRED", "ORDER_ONLY"} or not isinstance(edge["reason"], str) or not edge["reason"].strip():
                    raise ValueError("invalid dependency declaration")
                ids.append(edge["task_id"])
            if len(ids) != len(set(ids)) or {e["task_id"] for e in dependency_relations if e["kind"] == "REQUIRED"} != set(task["dependencies"]):
                raise ValueError("REQUIRED edges must match existing dependencies; ORDER_ONLY does not gate execution")
            data["dependency_relations"] = copy.deepcopy(dependency_relations)
        for key, value in (("shared_modules", shared_modules), ("shared_resources", shared_resources)):
            if value is not None:
                if value != UNKNOWN and (not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value)):
                    raise ValueError(key + " must be an explicit list or UNKNOWN")
                data[key] = copy.deepcopy(value)
        for key, value in (("feature_version", feature_version), ("baseline_id", baseline_id)):
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(key + " must be a nonempty identifier or UNKNOWN")
                data[key] = value
        data["source"] = "role_declared"
        data["declared_at"] = log.now()
        task["collection"] = data
        if active and (task.get('verification_contract') or any(t.get('verification_contract') and any(not r.get('ended_at') for r in t['executions']) for t in state['tasks'].values())):
            from harness.execution_ownership import gate
            gate(manager, state, task, active[0]['kind'] == 'review')
        if active:
            active[0].setdefault("collection_declarations", []).append(copy.deepcopy(data))
        manager._event(state, "task_collection_configured", task, agent_run_id or UNKNOWN, observed={"before": old, "after": data})
        return copy.deepcopy(data)
    return manager._mutate("configure_collection", operation, task_id)


def begin(manager, task, run):
    run["attempt_id"] = run["agent_run_id"]  # Existing unique execution attempt; resume keeps it.
    run["attempt_number"] = 1 + sum(r["kind"] == run["kind"] for r in task["executions"])
    collection = copy.deepcopy(task.get("collection", {}))
    config = None
    if (manager.root / SETTINGS).exists():
        collection["settings"] = manager.artifact(SETTINGS)
        config = validate_settings(json.loads((manager.root / collection["settings"]["snapshot"]).read_text()))
    bundle = {"inputs": run["inputs"], "baseline": run.get("baseline"), "stage_contract": task.get("stage_contract")}
    collection["input_bundle_id"] = "sha256:" + log.digest(json.dumps(bundle, sort_keys=True).encode())
    collection["harness"] = copy.deepcopy(manager.logger.harness)
    collection["files_start"] = copy.deepcopy(run["code_state_start"]["files"]) if run.get("code_state_start") else log.snapshot(manager.root)
    collection["file_scope"] = "development_code_state" if run.get("code_state_start") else "logger_snapshot_exclusions"
    collection["module_map"] = copy.deepcopy(config.get("modules", {})) if config is not None else UNKNOWN
    run["collection"] = collection


def finish(manager, task, run):
    if "collection" not in run:  # Never backfill a historical start.
        return
    data = run["collection"]
    after = copy.deepcopy(run["code_state_result"]["files"]) if run.get("code_state_result") else None
    # A tracked run must retain its start scope even on failure/review paths.
    if data["file_scope"] == "development_code_state" and not run.get("code_state_result"):
        from harness.development_tracking import capture
        try:
            after = capture(manager, task)["files"]
        except (OSError, ValueError) as error:
            data.update(files_end=UNKNOWN, changed_files=UNKNOWN, modification_actor=UNKNOWN,
                        observed_modules=UNKNOWN, collection_error=type(error).__name__)
            return
    if after is None:
        after = log.snapshot(manager.root)
    data.update(files_end=after, changed_files=log.changes(data["files_start"], after),
                modification_actor=UNKNOWN, attribution_basis="boundary observation; not exclusive ownership")
    mapping = data["module_map"]
    data["observed_modules"] = ({p["path"]: [name for name, prefixes in mapping.items()
        if any(prefix == "." or p["path"] == prefix.rstrip("/") or p["path"].startswith(prefix.rstrip("/") + "/") for prefix in prefixes)]
        or UNKNOWN for p in data["changed_files"]} if isinstance(mapping, dict) else UNKNOWN)


def wait_start(manager, state, task, run, reason, kind, target):
    if kind not in {"DEPENDENCY", "RESOURCE", "DECISION", "EXTERNAL", "OTHER", UNKNOWN} or not isinstance(target, str) or not target:
        raise ValueError("invalid wait type/target; use UNKNOWN when unavailable")
    record = {"id": str(uuid.uuid4()), "type": kind, "target": target, "reason": reason,
              "started_at": log.now(), "ended_at": None, "source": "role_declared"}
    run.setdefault("waits", []).append(record)
    manager._event(state, "task_wait_started", task, run["agent_run_id"], observed=copy.deepcopy(record))


def wait_end(manager, state, task, run, outcome):
    for wait in run.get("waits", []):
        if wait["ended_at"] is None:
            wait.update(ended_at=log.now(), outcome=outcome)
            wait["wall_elapsed_seconds"] = wall_elapsed(wait["started_at"], wait["ended_at"])
            manager._event(state, "task_wait_finished", task, run["agent_run_id"], observed=copy.deepcopy(wait))


def integration(manager, task_id, agent_run_id, kind, reason, evidence, cr=None,
                before_commit=UNKNOWN, after_commit=UNKNOWN, conflict_files=None):
    def operation(state):
        task = state["tasks"][task_id]
        runs = [r for r in task["executions"] if r["agent_run_id"] == agent_run_id]
        if len(runs) != 1 or kind not in {"INTEGRATION", "CONFLICT", "REWORK"} or not isinstance(reason, str) or not reason.strip():
            raise ValueError("existing execution, event kind and reason required")
        if cr is not None:
            if not isinstance(cr, dict) or set(cr) != {"folder", "id"}:
                raise ValueError("CR link requires folder and id")
            book = state.get("deliverables", {}).get(cr["folder"], {})
            changes = [c for c in book.get("changes", []) if c["id"] == cr["id"]]
            if len(changes) != 1 or task_id not in changes[0]["impacts"]["tasks"]:
                raise ValueError("CR must exist and include this task in impacts")
        for commit in (before_commit, after_commit):
            if not isinstance(commit, str) or not commit.strip():
                raise ValueError("commit identifiers must be explicit strings or UNKNOWN")
        if conflict_files is not None and (not isinstance(conflict_files, list) or not all(isinstance(p, str) for p in conflict_files)):
            raise ValueError("conflict_files must be explicit paths or omitted for UNKNOWN")
        record = {"id": str(uuid.uuid4()), "kind": kind, "reason": reason, "evidence": manager.artifact(evidence),
                  "cr": copy.deepcopy(cr) if cr else UNKNOWN, "before_commit": before_commit, "after_commit": after_commit,
                  "conflict_files": conflict_files if conflict_files is not None else UNKNOWN,
                  "recorded_at": log.now(), "source": "role_declared"}
        runs[0].setdefault("integration_events", []).append(record)
        if cr is not None:
            changes[0].setdefault("integration_observations", []).append({"id": record["id"], "task_id": task_id, "agent_run_id": agent_run_id})
        manager._event(state, "integration_observation", task, agent_run_id, observed=record)
        return copy.deepcopy(record)
    return manager._mutate("integration", operation, task_id)


def command_context(root, run_id, task_id, agent_run_id, attempt_id):
    supplied = [v != UNKNOWN for v in (task_id, agent_run_id, attempt_id)]
    if not any(supplied):
        return {"task_id": UNKNOWN, "agent_run_id": UNKNOWN, "feature_id": UNKNOWN}, {"attempt_id": UNKNOWN, "link_status": "MISSING"}
    if not all(supplied):
        raise ValueError("command link needs task_id, agent_run_id and attempt_id together")
    task = read_state(root)["tasks"].get(task_id)
    runs = [r for r in task["executions"] if r["agent_run_id"] == agent_run_id] if task else []
    if len(runs) != 1 or runs[0].get("attempt_id") != attempt_id or runs[0]["run_id"] != run_id or runs[0]["ended_at"] is not None or task["state"] == "BLOCKED":
        raise ValueError("command IDs must identify an active, unblocked execution attempt in this run")
    return {"task_id": task_id, "agent_run_id": agent_run_id, "feature_id": task["feature_id"]}, {
        "attempt_id": attempt_id, "link_status": "COLLECTED", "input_bundle_id": runs[0].get("collection", {}).get("input_bundle_id", UNKNOWN)}


def report(root):
    """Read-only coverage; no state refresh, historical enrichment or scheduling verdict."""
    state = read_state(root)
    events = log.Logger(root).read()
    def cell(value=UNKNOWN, evidence=None, missing=False):
        return {"status": "MISSING" if missing else "UNKNOWN" if value == UNKNOWN else "COLLECTED",
                "value": value, "evidence": evidence or []}
    commands = []
    starts = [e for e in events if e.get("event_type") == "command_started"]
    for start in starts:
        obs = start.get("observed", {})
        ends = [e for e in events if e.get("event_type") == "command_finished" and e.get("run_id") == start.get("run_id") and e.get("observed", {}).get("call_id") == obs.get("call_id")]
        end = ends[0] if len(ends) == 1 else None
        result = end.get("observed", {}) if end else {}
        evidence = [start.get("event_id", UNKNOWN)] + ([end.get("event_id", UNKNOWN)] if end else [])
        related_task = state["tasks"].get(start.get("task_id"), {})
        related_runs = [r for r in related_task.get("executions", []) if r["agent_run_id"] == start.get("agent_run_id")]
        linked = (len(related_runs) == 1 and obs.get("attempt_id", UNKNOWN) != UNKNOWN
                  and related_runs[0].get("attempt_id") == obs["attempt_id"] and related_runs[0]["run_id"] == start.get("run_id"))
        commands.append({"call_id": obs.get("call_id", UNKNOWN), "run_id": start.get("run_id", UNKNOWN),
            "task_id": start.get("task_id", UNKNOWN), "agent_run_id": start.get("agent_run_id", UNKNOWN),
            "link": cell(obs.get("attempt_id", UNKNOWN), evidence, missing=not linked),
            "input_bundle_id": cell(obs.get("input_bundle_id", UNKNOWN), evidence),
            "configuration": cell({key: obs.get(key, UNKNOWN) for key in ("command_name", "command_settings_sha256", "cwd", "argv_sha256")}, evidence),
            "kind": cell(obs.get("command_kind", UNKNOWN), evidence, missing="command_kind" not in obs),
            "started_at": cell(obs.get("started_at", UNKNOWN), evidence),
            "ended_at": cell(result.get("ended_at", UNKNOWN), evidence, missing=end is None),
            "elapsed_seconds": cell(result.get("elapsed_seconds", UNKNOWN), evidence, missing="elapsed_seconds" not in result),
            "returncode": cell(result.get("returncode", UNKNOWN), evidence, missing=end is None),
            "error_type": result.get("error_type", UNKNOWN)})
    tasks = {}
    for tid, task in state["tasks"].items():
        source = [".harness/tasks/tasks.yaml#" + tid]
        declared = task.get("collection", {})
        item = {"dependencies": cell(declared.get("dependency_relations", UNKNOWN), source, missing="dependency_relations" not in declared),
                "legacy_dependencies": task.get("dependencies", []), "inputs": cell(task.get("inputs", UNKNOWN), source),
                "shared_modules": cell(declared.get("shared_modules", UNKNOWN), source, missing="shared_modules" not in declared),
                "shared_resources": cell(declared.get("shared_resources", UNKNOWN), source, missing="shared_resources" not in declared),
                "executions": []}
        for run in task["executions"]:
            data = run.get("collection", {})
            refs = source + ["agent_run:" + run["agent_run_id"]]
            item["executions"].append({"agent_run_id": run["agent_run_id"],
                "attempt_id": cell(run.get("attempt_id", UNKNOWN), refs, missing="attempt_id" not in run),
                "feature_version": cell(data.get("feature_version", UNKNOWN), refs),
                "baseline_id": cell(data.get("baseline_id", data.get("input_bundle_id", UNKNOWN)), refs),
                "input_bundle_id": cell(data.get("input_bundle_id", UNKNOWN), refs),
                "frozen_declarations": {key: cell(data.get(key, UNKNOWN), refs, missing=key not in data)
                    for key in ("dependency_relations", "shared_modules", "shared_resources")},
                "later_declarations": cell(run.get("collection_declarations", UNKNOWN), refs),
                "started_at": cell(run.get("started_at", UNKNOWN), refs),
                "ended_at": cell(run.get("ended_at") or UNKNOWN, refs, missing=not run.get("ended_at")),
                "wall_elapsed_seconds": cell(wall_elapsed(run.get("started_at"), run.get("ended_at")), refs),
                "harness": cell(data.get("harness", UNKNOWN), refs, missing="harness" not in data),
                "settings": cell(data.get("settings", UNKNOWN), refs, missing="settings" not in data),
                "files": cell(data.get("changed_files", UNKNOWN), refs, missing="changed_files" not in data),
                "file_scope": data.get("file_scope", UNKNOWN), "modification_actor": data.get("modification_actor", UNKNOWN),
                "observed_modules": cell(data.get("observed_modules", UNKNOWN), refs),
                "waits": cell(run.get("waits", UNKNOWN), refs),
                "integration": cell(run.get("integration_events", UNKNOWN), refs),
                "usage_bindings": cell(run.get("usage_bindings") or UNKNOWN, refs),
                "verification": cell([r for r in task.get("reviews", []) if r["agent_run_id"] == run["agent_run_id"]] or UNKNOWN, refs),
                "validation_status": task.get("validation_status", {}),
                "commands": cell([c["call_id"] for c in commands if c["link"]["status"] == "COLLECTED" and c["task_id"] == tid and c["agent_run_id"] == run["agent_run_id"]] or UNKNOWN, refs, missing=not any(c["link"]["status"] == "COLLECTED" and c["task_id"] == tid and c["agent_run_id"] == run["agent_run_id"] for c in commands))})
        tasks[tid] = item
    result = {"schema_version": 1, "observed_at": log.now(), "tasks": tasks, "commands": commands,
              "commands_without_links": sum(c["link"]["status"] == "MISSING" for c in commands),
              "command_finishes_without_start": [e.get("event_id", UNKNOWN) for e in events
                  if e.get("event_type") == "command_finished" and not any(s.get("run_id") == e.get("run_id") and s.get("observed", {}).get("call_id") == e.get("observed", {}).get("call_id") for s in starts)],
              "commands_outside_wrapper": UNKNOWN, "parallelization_verdict": "NOT_EVALUATED",
              "expected_time_savings": UNKNOWN,
              "rules": ["Execution order is not a mandatory dependency", "No wait, conflict or rework record does not mean zero", "Boundary file differences do not identify the modification actor", "No historical values are backfilled"]}
    return log.redact(result)


def wall_elapsed(start, end):
    try:
        elapsed = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
        return elapsed if elapsed >= 0 else UNKNOWN
    except (ValueError, TypeError):
        return UNKNOWN
