"""Sequential, explicit planning/design process entry points backed by Tasks."""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.tasks import Tasks, logging
from harness.deliverables import archive, change, folder_key, restore

CODE = Path(__file__).resolve().parents[1]
PROTOCOL = {
    "status": "submitted | waiting | failed",
    "files": [{"path": "requirements.md OR design.md / prototype/...", "content": "complete UTF-8 file"}],
    "summary": "short result or failure cause",
    "questions": [{"question": "decision needed", "recommended": "option and impact", "alternative": "option and impact"}],
    "completed": ["completed steps to preserve when resumed"],
    "reuse": ["optional unchanged file paths from frozen task inputs; do not regenerate their contents"],
    "target_artifacts": {"<configured target>": {"entry": "prototype/<actual>.html", "screens": ["SCREEN-ID"], "requirements": ["REQ-ID"]}},
    "input_receipt": {"planning_version": "<exact delivery P>", "design_version": "<exact delivery D>",
                      "artifacts": [{"path": "<EVERY task input reference path>", "sha256": "<exact reference sha256>"}],
                      "acceptance_ids": ["<actual ACs read>"], "interpretation": "<meaning and limits read from originals>"},
    "returns": [{"kind": "design|requirements|policy", "screen": "<affected>", "ui_state": "<affected>",
                 "observed": "<input gap/conflict>", "expected": "<required>", "severity": "MAJOR", "recheck": "<criterion>"}],
}


class Roles:
    def __init__(self, root, run_id):
        self.tasks = Tasks(root, run_id)
        self.root = self.tasks.root

    def setup(self, task_id, folder, planning_version=None, change_id=None, design_version=None, design_targets=None):
        folder = folder_key(self.tasks, folder)
        def operation(state):
            task = state["tasks"][task_id]
            if task["role"] not in {"planning", "design", "development"} or task["state"] != "TODO" or task.get("role_contract"):
                raise ValueError("setup requires an unconfigured TODO planning/design task")
            task["role_contract"] = {"folder": folder, "planning_version": planning_version, "change_id": change_id}
            if task["role"] == "development":
                task["role_contract"].update(design_version=design_version, scope="input_interpretation_only")
            if design_targets:
                task["role_contract"]["design_targets"] = design_targets
            self.tasks._event(state, "role_configured", task, observed=task["role_contract"])
        return self.tasks._mutate("role_setup", operation, task_id)

    def rebase(self, task_id, inputs, planning_version=None, design_version=None, change_id=None, design_targets=None):
        def operation(state):
            task = state["tasks"][task_id]
            if task["state"] not in {"TODO", "BLOCKED"} or any(r["ended_at"] is None for r in task["executions"]):
                raise ValueError("rebase requires inactive TODO/BLOCKED work")
            before = copy.deepcopy(task["role_contract"])
            for key, value in {"planning_version": planning_version, "design_version": design_version, "change_id": change_id, "design_targets": design_targets}.items():
                if value is not None:
                    task["role_contract"][key] = value
            for path in inputs:
                ref = self.tasks.artifact(path)
                task["inputs"] = [r for r in task["inputs"] if r["path"] != ref["path"]] + [ref]
            self.tasks._event(state, "role_rebased", task, observed={"before": before, "after": task["role_contract"], "inputs": task["inputs"]})
        return self.tasks._mutate("role_rebase", operation, task_id)

    def prepare(self, task_id, role):
        task = self.tasks.read()["tasks"][task_id]
        if task["role"] != role or not task.get("role_contract"):
            raise ValueError("role mismatch or missing setup")
        if task["state"] == "DONE":
            return {"skipped": True, "task_id": task_id, "delivery": task.get("delivery")}
        if role == "development":
            from harness.deliverables import find_version
            from harness.findings import blocking
            state = self.tasks.read()
            book = state["deliverables"][task["role_contract"]["folder"]]
            p = find_version(book, task["role_contract"]["planning_version"])
            d = find_version(book, task["role_contract"]["design_version"])
            needed = {(r["snapshot"], r["snapshot_sha256"]) for r in p["artifacts"] + d["artifacts"]}
            available = {(r["snapshot"], r["snapshot_sha256"]) for r in task["inputs"]}
            if p["status"] != "APPROVED" or d["status"] != "APPROVED" or d["planning_version"] != p["id"] or not needed.issubset(available) or blocking(state, task):
                raise ValueError("development interpretation requires approved matching P/D, their exact inputs and no blockers")
            if book.get("validation_status", {}).get(d["id"], {}).get("state") == "RECHECK_REQUIRED":
                raise ValueError("design validation requires recheck before development")
        if task["state"] in {"IN_PROGRESS", "BLOCKED"}:
            active = [r for r in task["executions"] if r["ended_at"] is None and r["kind"] == "work"]
            if active:
                def guard(state):
                    from harness.development_tracking import ensure
                    current = state["tasks"][task_id]
                    run = self.tasks._active(current, active[0]["agent_run_id"], "work")
                    ensure(self.tasks, state, current, "resume", run)
                self.tasks._mutate("role_continue_guard", guard, task_id)
                return self.context(task_id, active[0]["agent_run_id"])
        if task["state"] in {"TODO", "BLOCKED"}:
            self.tasks.ready(task_id)
        run = self.tasks.begin(task_id, role, execution_mode="independent_process")
        return self.context(task_id, run["agent_run_id"])

    def context(self, task_id, agent_run_id):
        task = self.tasks.read()["tasks"][task_id]
        run = next(r for r in task["executions"] if r["agent_run_id"] == agent_run_id)
        directory = self.root / ".harness" / "roles" / agent_run_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        packet_path = directory / "context.json"
        if packet_path.exists():
            packet = json.loads(packet_path.read_text())
        else:
            template = {"planning": "requirements", "design": "design", "development": "development-plan"}[task["role"]]
            definition_paths = [f"docs/roles/{task['role']}.md", f"docs/templates/{template}.md",
                                "docs/operations.md", "docs/role-execution.md"]
            if task["role"] == "development":
                definition_paths.append("docs/product-architecture.md")
            definitions = [{"path": p, "sha256": logging.digest((CODE / p).read_bytes()), "content": (CODE / p).read_text()} for p in definition_paths]
            sources = []
            for ref in run["inputs"]:
                if not self.tasks._valid_artifact(ref):
                    raise ValueError("corrupt input snapshot")
                try:
                    content = (self.root / ref["snapshot"]).read_text()
                except UnicodeDecodeError:
                    content = None
                sources.append({"reference": ref, "content": content})
            state = self.tasks.read()
            feature_folder = self.root / task["role_contract"]["folder"]
            working = [feature_folder / {"planning": "requirements.md", "design": "design.md", "development": "development-plan.md"}[task["role"]]]
            if task["role"] == "design" and (feature_folder / "prototype").is_dir():
                working.extend(p for p in (feature_folder / "prototype").rglob("*") if p.is_file())
            packet = {"task_id": task_id, "agent_run_id": agent_run_id, "role": task["role"], "scope": task["scope"],
                "working_copies": [self.tasks.artifact(str(p.relative_to(self.root))) for p in working if p.is_file()],
                "workflow": {"feature_id": task["feature_id"], "dependencies": task["dependencies"],
                    "next_tasks": [{"task_id": t["task_id"], "role": t["role"], "state": t["state"]} for t in state["tasks"].values() if task_id in t["dependencies"]],
                    "note": "This is the registry observed at context preparation. Missing external PR/decision info is UNKNOWN, not proof of absence."},
                "baselines": [{k: v.get(k) for k in ("id", "role", "status", "planning_version", "task_id", "artifacts")}
                              for v in state.get("deliverables", {}).get(task["role_contract"]["folder"], {}).get("versions", [])],
                "returned_issues": [i for i in state.get("issues", []) if i.get("assigned_task_id") == task_id and i["status"] != "RESOLVED"],
                "criteria": task["criteria"], "delivery": task["role_contract"], "definitions": definitions,
                "stage_contract": task.get("stage_contract"),
                "inputs": sources, "protocol": PROTOCOL,
                "instruction": "Use only supplied frozen sources and explicit decisions. No previous conversation is available. "
                "Return JSON matching protocol. Never edit source files or another role's decisions. "
                "Inspect existing sources before asking questions; assumptions stay INFERRED/UNKNOWN. "
                "Only unresolved material decisions require waiting; do not mark unexecuted validation PASS. "
                "Planning publishes requirements.md; design publishes design.md and prototype/ including tokens.css, components.html, system.md and actual HTML. "
                "For unchanged files already in frozen inputs, list their feature-relative paths in reuse instead of repeating content. "
                "Development is input interpretation ONLY: publish development-plan.md, read every supplied P/D/token/component/prototype/AC/architecture input, "
                "and return input_receipt with planning_version, design_version, artifacts [{path,sha256}] for EVERY task input, acceptance_ids and interpretation. "
                "Map REQs to KMP/Clean Architecture modules, shared/platform ownership and test plan. Do not implement or build an app. "
                "Return missing/conflicting mandatory information to planning/design with a waiting response; preserve intentional UNKNOWNs outside this trial. Keep literal user sources and approved requirements distinct from agent-derived specifications. Map each derived item to original IDs and record omissions, changed values/behavior, exclusions and actual approval. A derived document is never authority by filename. Require independent requirements QA before implementation; scoped harness trials cannot establish product PASS. "
                "Returned issue fixes must address their recheck criteria; never self-resolve issues. "
                "For configured design_targets, return target_artifacts {target:{entry:feature-relative HTML path,screens:[],requirements:[]}} for every target. "
                "App HTML is a native-style simulation, not native execution. Responsive web needs distinct mobile and desktop composition/interaction. "
                "Do not claim browser checks: a separate reviewer executes and records them."}
        packet["sequential_collection"] = {"attempt_id": run.get("attempt_id", "UNKNOWN"),
            "declarations": run.get("collection", {}),
            "instructions": "Declare REQUIRED vs ORDER_ONLY dependency reasons and shared modules/resources via configure-collection; during execution provide the active agent_run_id. Late declarations are timestamped separately and never rewrite the frozen start identity. Use UNKNOWN for unobservable facts. Use the command wrapper with task/agent_run/attempt IDs and command kind or a configured command name. On waiting use checkpoint wait_type/wait_target; resume closes the wait. Record actual integration/conflict/rework with evidence and an existing CR when applicable. Execution order is not a required dependency; file observation is not authorship. At handoff inspect collection-report and identify missing evidence. Settings do not observe commands run outside the wrapper."}
        packet['usage_context'] = copy.deepcopy(run.get('usage_context'))
        packet["decisions"] = [{"reference": r, "content": (self.root / r["snapshot"]).read_text()} for r in run.get("decisions", [])]
        packet["returned_issues"] = [i for i in self.tasks.read().get("issues", []) if i.get("assigned_task_id") == task_id and i["status"] != "RESOLVED"]
        packet["checkpoint"] = ({"reference": run["checkpoint"], "content": (self.root / run["checkpoint"]["snapshot"]).read_text()}
                                 if run.get("checkpoint") else None)
        from harness.human_progress import for_task, message
        packet['human_progress']=for_task(self.root,task_id,self.tasks.run_id)
        packet['human_progress_message']=message(packet['human_progress'],start=True)
        packet['progress_instructions']='CMD: project > phase > current task, then the native checklist at major transitions. Dashboard: project-wide agent flow from the same source, not the same display scope. Register the whole execution Todo before starting; no platform guessing. Use the native checklist at major transitions, not every command. Mark [x] only for verified completion, [ ] otherwise; bold active items with 진행 중. Keep retries inside the same task. Refresh through harness.human_progress; never invent statuses or persist a separate checklist. Explain what each check establishes before/after commands; classify failures only from evidence. Do not present request acceptance as live process observation.'
        self.write(packet_path, packet)
        def operation(state):
            current = self.tasks._active(state["tasks"][task_id], agent_run_id, "work")
            current["role_context"] = self.tasks.artifact(str(packet_path.relative_to(self.root)))
        self.tasks._mutate("role_context", operation, task_id)
        return {"task_id": task_id, "agent_run_id": agent_run_id, "context": str(packet_path.relative_to(self.root))}

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = json.dumps(logging.redact(value), ensure_ascii=False, indent=2)
        with path.open("w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data + "\n")

    def process_event(self, task_id, aid, observed):
        def operation(state):
            task = state["tasks"][task_id]
            self.tasks._event(state, "role_process", task, aid, observed=observed)
        self.tasks._mutate("role_process", operation, task_id)

    def collect_codex(self, task_id, aid, stdout):
        """CLI finish collection via existing sync and native response IDs, never time slicing."""
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        threads = {e["thread_id"] for e in events if e.get("type") == "thread.started"}
        safe = [e for e in events if e.get("type") in {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}]
        result = {"cli_events": safe, "usage": "UNKNOWN"}
        if len(threads) == 1:
            thread = next(iter(threads))
            home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
            paths = list((home / "sessions").rglob(f"*{thread}.jsonl"))
            if len(paths) == 1:
                self.tasks.logger.sync(paths[0], self.tasks.run_id)
                usage = [e for e in self.tasks.logger.read() if e["event_type"] == "model_usage" and e["source"].get("session_id") == thread]
                responses = {e["observed"].get("response_id") for e in usage} - {None, "UNKNOWN"}
                for response in responses:
                    self.tasks.bind_usage(task_id, aid, thread, response, "native thread.started from this exact role process; CLI finish sync")
                result.update(session_id=thread, attributed_responses=len(responses), usage="explicit_native_responses" if responses else "UNKNOWN")
        return result

    def accept(self, task_id, agent_run_id, response):
        self.tasks._mutate('accept', lambda state: None, task_id)
        task = self.tasks.read()["tasks"][task_id]
        self.tasks._active(task, agent_run_id, "work")
        if task["state"] != "IN_PROGRESS":
            raise ValueError("resume checkpoint with explicit decision before accepting work")
        if response.get("status") not in {"submitted", "waiting", "failed"} or not response.get("summary"):
            raise ValueError("invalid worker response")
        directory = self.root / ".harness/roles" / agent_run_id
        result_path = directory / f"response-{len(list(directory.glob('response-*.json'))) + 1:03d}.json"
        self.write(result_path, response)
        if response["status"] == "failed":
            return self.tasks.fail(task_id, agent_run_id, response["summary"])
        files = copy.deepcopy(response.get("files", []))
        base = Path(task["role_contract"]["folder"])
        for path in response.get("reuse", []):
            relative = Path(path)
            source = relative if relative.is_relative_to(base) else base / relative
            matches = [a for a in task["inputs"] if a["path"] == str(source)]
            if len(matches) != 1 or not self.tasks._valid_artifact(matches[0]):
                raise ValueError("reuse requires exactly one frozen task input")
            files.append({"path": str(source), "content": (self.root / matches[0]["snapshot"]).read_text()})
        for item in files:
            p = Path(item["path"])
            base = Path(task["role_contract"]["folder"])
            if not p.is_absolute() and p.is_relative_to(base):
                item["path"] = str(p.relative_to(base))
        paths = [f["path"] for f in files]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate output path")
        # Validate the entire batch before touching canonical work files.
        for item in files:
            p = Path(item["path"])
            if p.is_absolute() or ".." in p.parts or not isinstance(item.get("content"), str):
                raise ValueError("invalid worker file")
            allowed = (p == Path("requirements.md") if task["role"] == "planning" else
                       p == Path("development-plan.md") if task["role"] == "development" else p == Path("design.md") or p.is_relative_to("prototype"))
            if not allowed:
                raise ValueError("role output ownership violation")
        if response["status"] == "waiting":
            if response.get("returns"):
                for issue in response["returns"]:
                    self.tasks.issue(task_id=task_id, evidence=str(result_path.relative_to(self.root)), **issue)
            elif not response.get("questions") or any(not all(q.get(k) for k in ("question", "recommended", "alternative")) for q in response["questions"]):
                raise ValueError("waiting requires options and impacts")
            # Reviewable partial files stay in this execution's draft; active canonical files stay unchanged.
            for item in files:
                preview = directory / result_path.stem / item["path"]
                preview.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                preview.write_text(logging.redact(item["content"]))
            return self.tasks.checkpoint(task_id, agent_run_id, response["summary"], str(result_path.relative_to(self.root)))
        required = ({"requirements.md"} if task["role"] == "planning" else {"development-plan.md"} if task["role"] == "development" else {"design.md", "prototype/index.html", "prototype/tokens.css", "prototype/components.html", "prototype/system.md"})
        if not required.issubset(set(paths)):
            raise ValueError("missing required actual deliverable files")
        if task["role"] == "design":
            from harness.design_assets import validate
            self.write(directory / (result_path.stem + "-source-check.json"), validate(files))
            targets = task["role_contract"].get("design_targets", [])
            if targets:
                actual_targets = response.get("target_artifacts", {})
                if set(actual_targets) != set(targets) or any(v.get("entry") not in paths or not v.get("screens") or not v.get("requirements") for v in actual_targets.values()):
                    raise ValueError("every configured target needs actual HTML, screen and requirement mapping")
                import re
                active_paths = {v["entry"] for v in actual_targets.values()} | {"prototype/index.html", "prototype/components.html"}
                for item in files:
                    if item["path"] in active_paths:
                        visible_source = re.sub(r"<!--.*?-->|<script\b[^>]*>.*?</script>", "", item["content"], flags=re.S | re.I)
                        if re.search(r"NOT_RUN|하네스\s*검증|검증\s*(?:PASS|FAIL|상태)", visible_source):
                            raise ValueError("active product prototype must not embed harness verification status")
        folder = self.root / task["role_contract"]["folder"]
        execution = next(r for r in task["executions"] if r["agent_run_id"] == agent_run_id)
        context = json.loads((self.root / execution["role_context"]["snapshot"]).read_text())
        expected = {r["path"]: r["sha256"] for r in context.get("working_copies", task["inputs"])}
        for item in files:
            dest = folder / item["path"]
            if not dest.resolve().is_relative_to(folder.resolve()):
                raise ValueError("output escapes feature folder")
            relative = str(dest.relative_to(self.root))
            current = logging.digest(dest.read_bytes()) if dest.is_file() else None
            if current != expected.get(relative):
                raise ValueError("working copy changed since context preparation; preserve it and explicitly rebase")
        preview_refs = []
        for item in files:
            staged = directory / result_path.stem / item["path"]
            staged.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            staged.write_text(logging.redact(item["content"]))
            ref = self.tasks.artifact(str(staged.relative_to(self.root)))
            ref["path"] = str((folder / item["path"]).relative_to(self.root))
            preview_refs.append(ref)
        # Check ownership, P baseline and CR before changing even a single working file.
        preview = self.tasks.read()
        if task["role"] != "development":
            archive(self.tasks, preview, preview["tasks"][task_id], preview_refs, task["role_contract"])
        else:
            receipt = response.get("input_receipt", {})
            actual = {r["path"]: r["sha256"] for r in task["inputs"]}
            confirmed = {r["path"]: r["sha256"] for r in receipt.get("artifacts", [])}
            if receipt.get("planning_version") != task["role_contract"]["planning_version"] or receipt.get("design_version") != task["role_contract"]["design_version"] or actual != confirmed or not receipt.get("acceptance_ids") or not receipt.get("interpretation"):
                raise ValueError("development must explicitly confirm every frozen input, exact P/D and AC interpretation")
        # The old reviewed bytes already live in immutable Tasks artifact snapshots.
        outputs = []
        for item in files:
            dest = folder / item["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(logging.redact(item["content"]))
            outputs.append(str(dest.relative_to(self.root)))
        status = {"specification": "COMPLETE", "mockup": "COMPLETE", "visual_review": "NOT_RUN"} if task["role"] == "design" else None
        self.tasks.submit(task_id, agent_run_id, outputs, response["summary"], status, task["role_contract"] if task["role"] != "development" else None)
        if task["role"] == "design" and response.get("target_artifacts"):
            def targets_saved(state):
                state["tasks"][task_id]["target_artifacts"] = response["target_artifacts"]
            self.tasks._mutate("design_targets", targets_saved, task_id)
        if task["role"] == "development":
            def confirmed(state):
                state["tasks"][task_id]["input_confirmation"] = {"state": "CONFIRMED_BY_AGENT", "agent_run_id": agent_run_id,
                    "receipt": response["input_receipt"], "response": self.tasks.artifact(str(result_path.relative_to(self.root)))}
                self.tasks._event(state, "development_inputs_confirmed", state["tasks"][task_id], agent_run_id,
                                  observed={"scope": "input_interpretation_only", "receipt": response["input_receipt"]})
            self.tasks._mutate("confirm_inputs", confirmed, task_id)
        return self.tasks.read()["tasks"][task_id].get("delivery", {"scope": "input_interpretation_only"})

    def execute(self, task_id, role, worker=None, timeout=300):
        self.tasks.require_dispatch(task_id)
        task=self.tasks.read()['tasks'][task_id]
        if task.get('qa_config'):
            if role!='verification' or worker is not None:raise ValueError('QA uses verification role and its configured adapter')
            from harness.qa import QA
            qa=QA(self.root,self.tasks.run_id)
            if task['qa_config'].get('repair_task_id'):
                from harness.qa_repair import execute_with_owner
                return execute_with_owner(qa,task_id)
            return qa.execute(task_id)
        if task.get('development_delegation'):
            if role!='development' or worker is not None:
                raise ValueError('configured delegation requires development and native configured adapter')
            from harness.delegation import Development
            return Development(self.root,self.tasks.run_id).execute(task_id)
        if worker is None and task.get('state')!='DONE':
            from harness.execution_plan import require
            require(self.tasks,task_id)
        prepared = self.prepare(task_id, role)
        if prepared.get("skipped"):
            return prepared
        aid = prepared["agent_run_id"]
        directory = self.root / prepared["context"]
        directory = directory.parent
        # Serial execution only. The lock also protects explicit retry/resume calls.
        with (directory / "dispatch.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            task = self.tasks.read()["tasks"][task_id]
            if task["state"] != "IN_PROGRESS":
                return {**prepared, "state": task["state"], "reason": task["blocked_reason"]}
            index = len(list(directory.glob("dispatch-*.json"))) + 1
            result = directory / f"last-{index}.json"
            import uuid
            call_id = str(uuid.uuid4())
            command = worker or ["codex", "exec", "--ignore-user-config", "--sandbox", "read-only", "--skip-git-repo-check", "--json", "-o", str(result), "-"]
            prompt = (self.root / prepared["context"]).read_text()
            try:
                from harness.runtime_limits import model_slot
                with model_slot(self.tasks,task_id,aid,timeout):
                    self.tasks.require_dispatch(task_id)
                    child = subprocess.Popen(command, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, text=True, start_new_session=True)
                    self.write(directory / f"dispatch-{index:03d}.json", {"pid": child.pid, "command": command,
                        "adapter": "custom_process" if worker else "codex_exec", "started_at": logging.now(), "usage": "UNKNOWN",
                        "implementation_sha256": {p: logging.digest((CODE / p).read_bytes()) for p in
                            ["harness/roles.py", "harness/tasks.py", "harness/deliverables.py", "harness/design_assets.py"]}})
                    self.process_event(task_id, aid, {"call_id": call_id, "pid": child.pid, "adapter": "custom_process" if worker else "codex_exec", "spawned": True,
                        'process_state': 'role_process_started', 'started_at': logging.now(),
                        'independent_model_spawned': worker is None})
                    try:
                        from harness.delegation_runtime import _communicate_stream, _drain
                        from harness.usage_collection import WorkerStream
                        stream = WorkerStream(self.tasks, task_id, aid, call_id)
                        stdout, stderr = _communicate_stream(child, prompt, timeout, stream)
                    except BaseException as interrupted:
                        try:
                            os.killpg(child.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        try:
                            partial_stdout, partial_stderr = _drain(child, timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            partial_stdout, partial_stderr = _drain(child, timeout=5)
                        try:
                            partial = {"stdout": partial_stdout} if worker else self.collect_codex(task_id, aid, partial_stdout)
                        except (OSError, ValueError):
                            partial = {"usage": "UNKNOWN", "collection": "partial CLI stream could not be imported"}
                        self.write(directory / f"process-{index:03d}.json", {"returncode": child.returncode, **partial,
                            "stderr": partial_stderr, "interrupted": type(interrupted).__name__, "finished_at": logging.now()})
                        raise
                    finally:
                        for pipe in (child.stdin, child.stdout, child.stderr):
                            if pipe is not None:
                                pipe.close()
                    collected = {"stdout": stdout} if worker else self.collect_codex(task_id, aid, stdout)
                    self.process_event(task_id, aid, {'call_id': call_id, 'process_state': 'role_process_finished',
                        'thread_ids': sorted(stream.threads), 'exit_code': child.returncode})
                    stream.tick()
                    self.write(directory / f"process-{index:03d}.json", {"returncode": child.returncode, **collected, "stderr": stderr,
                        "finished_at": logging.now(), "independent_process_observed": True})
                    if child.returncode:
                        raise ValueError(f"worker exit {child.returncode}; see process-{index:03d}.json")
                    response = json.loads(stdout if worker else result.read_text())
                    return self.accept(task_id, aid, response)
            except (OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                self.tasks.fail(task_id, aid, f"{type(error).__name__}: {error}")
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=CODE)
    parser.add_argument("--run-id", default="UNKNOWN")
    parser.add_argument("action", choices=["setup", "rebase", "planning", "design", "development", "prepare", "accept", "change", "restore"])
    parser.add_argument("--data", type=Path, help="JSON named method arguments")
    parser.add_argument("--task-id")
    parser.add_argument("--worker", help="Explicit trusted local command as JSON argv; no shell interpolation")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    roles = Roles(args.root, args.run_id)
    if args.action in {"planning", "design", "development"}:
        result = roles.execute(args.task_id, args.action, json.loads(args.worker) if args.worker else None, args.timeout)
    else:
        data = json.loads(args.data.read_text())
        result = change(roles.tasks, **data) if args.action == "change" else restore(roles.tasks, **data) if args.action == "restore" else getattr(roles, args.action)(**data)
    print(json.dumps(logging.redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
