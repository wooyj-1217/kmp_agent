"""Minimal task state machine. tasks.yaml uses the JSON subset of YAML 1.2."""
import argparse
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import uuid

spec = importlib.util.spec_from_file_location("harness_logging", Path(__file__).with_name("logging.py"))
logging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logging)
UNKNOWN = logging.UNKNOWN
STATES = {"TODO", "READY", "IN_PROGRESS", "IN_REVIEW", "DONE", "BLOCKED"}
ROLES = {"planning", "design", "development", "verification", "improvement", "orchestrator"}


class Tasks:
    def __init__(self, root, run_id):
        self.root = Path(root).resolve()
        self.run_id = run_id
        self.logger = logging.Logger(root)
        self.directory = self.root / ".harness" / "tasks"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.path = self.directory / "tasks.yaml"

    def _save(self, state):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps(logging.redact(state), ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)

    def _flush(self, state):
        for event in state["outbox"]:
            self.logger.append(**event)
        if state["outbox"]:
            state["outbox"] = []
            self._save(state)

    def _event(self, state, kind, task, agent_run_id=UNKNOWN, observed=None, summary=None):
        state["outbox"].append({"event_type": kind, "run_id": self.run_id,
            "work_type": task["work_type"], "feature_id": task["feature_id"],
            "task_id": task["task_id"], "agent_run_id": agent_run_id,
            "observed": observed or {}, "summary": summary or {},
            "source": {"kind": "task_manager", "state_file": str(self.path)},
            "source_key": "task-event:" + str(uuid.uuid4())})

    def _mutate(self, action, operation, task_id=UNKNOWN):
        with (self.directory / "state.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.path.read_text()) if self.path.exists() else {"schema_version": 1, "tasks": {}, "outbox": []}
            self._flush(state)  # Recover durable events after a previous interruption.
            original = copy.deepcopy(state)
            try:
                result = operation(state)
            except (ValueError, KeyError) as error:
                task = original["tasks"].get(task_id)
                if task:
                    self._event(original, "task_action_rejected", task,
                                observed={"action": action, "reason": str(error)})
                    self._save(original)
                    self._flush(original)
                raise
            self._save(state)
            self._flush(state)
            return result

    def read(self):
        return self._mutate("read", lambda state: copy.deepcopy(state))

    def artifact(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("artifact must be an existing file within the repository")
        data = path.read_bytes()
        sanitized = logging.redact(data.decode("utf-8")).encode("utf-8")
        checksum = logging.digest(sanitized)
        directory = self.root / ".harness" / "artifacts"
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        frozen = directory / (checksum + ".txt")
        if not frozen.exists():
            with frozen.open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(sanitized)
        git = subprocess.run(["rtk", "proxy", "git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True)
        return {"path": str(path.relative_to(self.root)), "sha256": logging.digest(data),
                "snapshot": str(frozen.relative_to(self.root)), "snapshot_sha256": checksum,
                "git_commit": git.stdout.strip() if git.returncode == 0 else UNKNOWN}

    def _valid_artifact(self, artifact):
        path = (self.root / artifact["snapshot"]).resolve()
        return path.is_relative_to(self.root) and path.is_file() and logging.digest(path.read_bytes()) == artifact["snapshot_sha256"]

    def register(self, feature_id, task_id, role, title, scope, criteria, inputs, dependencies=None, max_attempts=1,
                 work_type="HARNESS_BUILD", visual_required=False):
        def operation(state):
            if task_id in state["tasks"] or role not in ROLES or max_attempts < 1 or work_type not in logging.KINDS:
                raise ValueError("invalid or duplicate task")
            if not criteria or len({x["id"] for x in criteria}) != len(criteria) or not any(x["required"] for x in criteria):
                raise ValueError("unique criteria and at least one required criterion are needed")
            dependencies_list = dependencies or []
            if any(d not in state["tasks"] or state["tasks"][d]["feature_id"] != feature_id for d in dependencies_list):
                raise ValueError("dependencies must exist within the feature")
            refs = [self.artifact(p) for p in inputs]
            task = {"feature_id": feature_id, "task_id": task_id, "role": role, "title": title,
                    "scope": scope, "work_type": work_type, "state": "TODO", "dependencies": dependencies_list,
                    "criteria": criteria, "inputs": refs, "outputs": [], "blocked_reason": None,
                    "max_attempts": max_attempts, "executions": [], "reviews": [], "handoffs": [],
                    "design_status": {"specification": "NOT_STARTED", "mockup": "NOT_PRODUCED",
                                      "visual_review": "NOT_RUN", "visual_evidence": None},
                    "visual_required": visual_required}
            state["tasks"][task_id] = task
            self._event(state, "task_registered", task, observed={"state": "TODO", "inputs": refs},
                        summary={"role": role, "title": title, "scope": scope})
            return copy.deepcopy(task)
        return self._mutate("register", operation, task_id)

    def ready(self, task_id):
        def operation(state):
            task = state["tasks"][task_id]
            if task["state"] not in {"TODO", "BLOCKED"}:
                raise ValueError("ready requires TODO or BLOCKED")
            if any(state["tasks"][d]["state"] != "DONE" for d in task["dependencies"]):
                raise ValueError("unfinished dependency")
            if not all(self._valid_artifact(a) for a in task["inputs"]):
                raise ValueError("invalid input snapshot")
            if len([r for r in task["executions"] if r["kind"] == "work"]) >= task["max_attempts"]:
                raise ValueError("attempt budget exhausted")
            previous = task["state"]
            task.update(state="READY", blocked_reason=None)
            self._event(state, "task_state_changed", task, observed={"from": previous, "to": "READY"})
        self._mutate("ready", operation, task_id)

    def begin(self, task_id, role, review=False, execution_mode="current_agent"):
        def operation(state):
            task = state["tasks"][task_id]
            expected = "IN_REVIEW" if review else "READY"
            if task["state"] != expected or role not in ROLES or (not review and role != task["role"]):
                raise ValueError("state or role does not permit execution")
            if review and role not in {"verification", "orchestrator"}:
                raise ValueError("review role must be verification or orchestrator")
            if execution_mode not in {"current_agent", "local_check"}:
                raise ValueError("unsupported execution mode")
            attempts = [r for r in task["executions"] if r["kind"] == "work"]
            if not review and len(attempts) >= task["max_attempts"]:
                raise ValueError("attempt budget exhausted")
            if any(r["ended_at"] is None for r in task["executions"]):
                raise ValueError("an execution is already active")
            run = {"agent_run_id": str(uuid.uuid4()), "run_id": self.run_id,
                   "feature_id": task["feature_id"], "task_id": task_id, "role": role,
                   "kind": "review" if review else "work", "execution_mode": execution_mode,
                   "started_at": logging.now(), "ended_at": None, "inputs": copy.deepcopy(task["outputs"] if review else task["inputs"]),
                   "outputs": [], "usage_bindings": [], "model_usage": UNKNOWN, "cost": UNKNOWN}
            task["executions"].append(run)
            if not review:
                task["state"] = "IN_PROGRESS"
                self._event(state, "task_state_changed", task, run["agent_run_id"], observed={"from": "READY", "to": "IN_PROGRESS"})
            self._event(state, "agent_run_started", task, run["agent_run_id"], observed={"started_at": run["started_at"], "inputs": run["inputs"]},
                        summary={"role": role, "execution_mode": execution_mode, "independent_model_spawned": False})
            return copy.deepcopy(run)
        return self._mutate("begin_review" if review else "begin", operation, task_id)

    def _active(self, task, agent_run_id, kind):
        matches = [r for r in task["executions"] if r["agent_run_id"] == agent_run_id and r["kind"] == kind and r["ended_at"] is None]
        if len(matches) != 1:
            raise ValueError("execution is not active")
        return matches[0]

    def submit(self, task_id, agent_run_id, outputs, summary, design_status=None):
        def operation(state):
            task = state["tasks"][task_id]
            if task["state"] != "IN_PROGRESS" or not outputs:
                raise ValueError("submit requires work and outputs")
            run = self._active(task, agent_run_id, "work")
            refs = [self.artifact(p) for p in outputs]
            if design_status:
                if task["role"] != "design" or design_status.get("specification") not in {"IN_PROGRESS", "COMPLETE"}:
                    raise ValueError("invalid design status")
                if design_status.get("mockup") not in {"NOT_PRODUCED", "IN_PROGRESS", "COMPLETE"}:
                    raise ValueError("invalid mockup status")
                if design_status.get("visual_review") != "NOT_RUN":
                    raise ValueError("visual PASS/FAIL requires a separate visual review; not implemented")
                task["design_status"].update(design_status)
            task.update(state="IN_REVIEW", outputs=refs)
            run.update(ended_at=logging.now(), outputs=refs)
            self._event(state, "agent_run_finished", task, agent_run_id, observed={"ended_at": run["ended_at"], "outputs": refs}, summary={"result": summary})
            self._event(state, "task_state_changed", task, agent_run_id, observed={"from": "IN_PROGRESS", "to": "IN_REVIEW", "design_status": task["design_status"]})
        self._mutate("submit", operation, task_id)

    def review(self, task_id, agent_run_id, results, summary):
        def operation(state):
            task = state["tasks"][task_id]
            if task["state"] != "IN_REVIEW":
                raise ValueError("review requires IN_REVIEW")
            run = self._active(task, agent_run_id, "review")
            if {r["criterion_id"] for r in results} != {c["id"] for c in task["criteria"]} or len(results) != len(task["criteria"]):
                raise ValueError("review must cover every criterion exactly once")
            checked = []
            for result in results:
                if result["result"] not in {"PASS", "FAIL", "NOT_RUN"}:
                    raise ValueError("invalid review result")
                evidence = self.artifact(result["evidence"]) if result.get("evidence") else None
                if result["result"] == "PASS" and evidence is None:
                    raise ValueError("PASS requires evidence")
                checked.append({**result, "evidence": evidence, "tested_outputs": copy.deepcopy(task["outputs"])})
            required = {c["id"] for c in task["criteria"] if c["required"]}
            passed = all(r["result"] == "PASS" for r in checked if r["criterion_id"] in required)
            passed = passed and (not task["visual_required"] or task["design_status"]["visual_review"] == "PASS")
            passed = passed and (task["role"] != "design" or task["design_status"]["specification"] == "COMPLETE")
            task["reviews"].append({"agent_run_id": agent_run_id, "results": checked, "outputs": copy.deepcopy(task["outputs"])})
            task.update(state="DONE" if passed else "BLOCKED", blocked_reason=None if passed else "Required review failed or NOT_RUN, or required visual review incomplete")
            run.update(ended_at=logging.now(), outputs=[r["evidence"] for r in checked if r["evidence"]])
            self._event(state, "task_reviewed", task, agent_run_id, observed={"results": checked, "design_status": task["design_status"]}, summary={"reviewer_role": run["role"], "result": summary})
            self._event(state, "agent_run_finished", task, agent_run_id, observed={"ended_at": run["ended_at"], "outputs": run["outputs"]})
            self._event(state, "task_state_changed", task, agent_run_id, observed={"from": "IN_REVIEW", "to": task["state"], "reason": task["blocked_reason"]})
            return task["state"]
        return self._mutate("review", operation, task_id)

    def handoff(self, source_id, target_id):
        def operation(state):
            source, target = state["tasks"][source_id], state["tasks"][target_id]
            if source["state"] != "DONE" or target["state"] != "TODO" or source_id not in target["dependencies"]:
                raise ValueError("handoff requires reviewed source and dependent TODO target")
            if source["feature_id"] != target["feature_id"]:
                raise ValueError("feature mismatch")
            if any(state["tasks"][d]["state"] != "DONE" for d in target["dependencies"]):
                raise ValueError("unfinished target dependency")
            if not all(self._valid_artifact(a) for a in source["outputs"] + target["inputs"]):
                raise ValueError("invalid handoff snapshot")
            target["inputs"].extend(copy.deepcopy(source["outputs"]))
            record = {"from_task_id": source_id, "to_task_id": target_id, "artifacts": copy.deepcopy(source["outputs"]),
                      "criteria_ids": [c["id"] for c in source["criteria"]], "version_policy": "content_snapshot_for_harness_trial; product_handoff_requires_git_commit"}
            source["handoffs"].append(record)
            target["handoffs"].append(record)
            target["state"] = "READY"
            self._event(state, "task_handoff", target, observed=record)
            self._event(state, "task_state_changed", target, observed={"from": "TODO", "to": "READY"})
            return copy.deepcopy(record)
        return self._mutate("handoff", operation, source_id)

    def bind_usage(self, task_id, agent_run_id, session_id, response_id, reason):
        def operation(state):
            task = state["tasks"][task_id]
            matches = [r for r in task["executions"] if r["agent_run_id"] == agent_run_id]
            if len(matches) != 1:
                raise ValueError("unknown agent_run_id")
            run = matches[0]
            binding = {"session_id": session_id, "response_id": response_id}
            for other in state["tasks"].values():
                for execution in other["executions"]:
                    if binding in execution["usage_bindings"]:
                        if execution["agent_run_id"] == agent_run_id:
                            return False
                        raise ValueError("response already attributed to another execution")
            events = [e for e in self.logger.read() if e["event_type"] == "model_usage"
                      and e["source"].get("session_id") == session_id and e["observed"].get("response_id") == response_id]
            if not events:
                raise ValueError("response usage must be imported before attribution")
            run["usage_bindings"].append(binding)
            self._event(state, "usage_attributed", task, agent_run_id,
                        observed={**binding, "source_event_ids": [e["event_id"] for e in events]},
                        summary={"attribution": "agent_declared", "reason": reason})
            return True
        return self._mutate("bind_usage", operation, task_id)

    def report(self):
        state = self.read()
        events = self.logger.read()
        report = copy.deepcopy(state)
        report["features"] = {}
        for task in report["tasks"].values():
            for run in task["executions"]:
                selected = {}
                for b in run["usage_bindings"]:
                    values = [e["observed"].get("usage", UNKNOWN) for e in events if e["event_type"] == "model_usage"
                              and e["source"].get("session_id") == b["session_id"] and e["observed"].get("response_id") == b["response_id"]]
                    selected[(b["session_id"], b["response_id"])] = values[0] if values and all(v == values[0] for v in values) else UNKNOWN
                fields = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
                run["model_usage"] = {k: sum(v[k] for v in selected.values()) if selected and all(isinstance(v, dict) and isinstance(v.get(k), int) for v in selected.values()) else UNKNOWN for k in fields}
                run["attributed_responses"] = len(selected)
                run["usage_coverage"] = "explicit_bindings_only; unbound_calls_unknown"
            fields = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
            task["usage_summary"] = {"known_subtotal": {k: sum(r["model_usage"][k] for r in task["executions"] if isinstance(r["model_usage"][k], int))
                                                        if any(isinstance(r["model_usage"][k], int) for r in task["executions"]) else UNKNOWN for k in fields},
                                     "full_task_usage": UNKNOWN, "cost": UNKNOWN,
                                     "executions_without_usage_binding": sum(not r["usage_bindings"] for r in task["executions"])}
            feature = report["features"].setdefault(task["feature_id"], {"task_ids": [], "known_subtotal": {k: UNKNOWN for k in fields}, "full_feature_usage": UNKNOWN, "cost": UNKNOWN})
            feature["task_ids"].append(task["task_id"])
            for k in fields:
                value = task["usage_summary"]["known_subtotal"][k]
                if isinstance(value, int):
                    feature["known_subtotal"][k] = (feature["known_subtotal"][k] if isinstance(feature["known_subtotal"][k], int) else 0) + value
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=logging.ROOT)
    parser.add_argument("--run-id", default=UNKNOWN)
    parser.add_argument("action", choices=["register", "ready", "begin", "submit", "review", "handoff", "bind-usage", "show"])
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    tasks = Tasks(args.root, args.run_id)
    if args.action == "show":
        result = tasks.report()
    else:
        data = json.loads(args.data.read_text())
        result = getattr(tasks, args.action.replace("-", "_"))(**data)
    print(json.dumps(logging.redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
