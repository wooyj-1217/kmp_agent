"""Minimal task state machine. tasks.yaml uses the JSON subset of YAML 1.2."""
import argparse
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        self.context = self.logger.execution_context(run_id)
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
        if len(state["outbox"]) > 1 and all(e["event_type"] == "usage_attributed" for e in state["outbox"]):
            self.logger.append_many(state["outbox"])
        else:
            for event in state["outbox"]:
                self.logger.append(**event)
        if state["outbox"]:
            state["outbox"] = []
            self._save(state)

    def _event(self, state, kind, task, agent_run_id=UNKNOWN, observed=None, summary=None):
        observed = copy.deepcopy(observed or {})
        if kind in {"agent_run_started", "agent_run_finished", "agent_run_failed"}:
            run = next((r for r in task["executions"] if r["agent_run_id"] == agent_run_id), {})
            if run.get("collection"):
                observed.update(attempt_id=run["attempt_id"], collection=copy.deepcopy(run["collection"]))
            if run.get('usage_context'):
                observed['usage_context'] = copy.deepcopy(run['usage_context'])
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
            from harness.development_tracking import refresh
            refresh(self, state)
            from harness.decisions import refresh_waits
            refresh_waits(self, state)
            original = copy.deepcopy(state)
            try:
                from harness.execution_policy import gate
                if task_id in state['tasks']:
                    gate(self, state, task_id, action)
                result = operation(state)
            except (ValueError, KeyError) as error:
                task = original["tasks"].get(task_id)
                if task:
                    self._event(original, "task_action_rejected", task,
                                observed={"action": action, "reason": str(error)})
                    self._save(original)
                    self._flush(original)
                raise
            refresh(self, state)
            refresh_waits(self, state)
            self._save(state)
            self._flush(state)
            return result

    def read(self):
        return self._mutate("read", lambda state: copy.deepcopy(state))

    def configure_execution_policy(self, root_session_path, root_session_id, **configuration):
        from harness.execution_policy import configure
        return configure(self, root_session_path, root_session_id, **configuration)

    def configure_task_plan(self, task_id, work_plan, reason):
        from harness.execution_policy import configure_plan
        return configure_plan(self, task_id, work_plan, reason)

    def bind_execution_session(self, root_session_path, root_session_id):
        from harness.execution_policy import bind_session
        return bind_session(self, root_session_path, root_session_id)

    def open_question(self, question_id, question, affected_task_ids, options=None, **configuration):
        from harness.decisions import open_question
        return open_question(self, question_id, question, affected_task_ids, options, **configuration)

    def answer_question(self, question_id, **configuration):
        from harness.decisions import answer_question
        return answer_question(self, question_id, **configuration)

    def question_status(self):
        return copy.deepcopy(self.read().get('required_questions', {}))

    def require_dispatch(self, task_id):
        return self._mutate('dispatch', lambda state: None, task_id)

    def configure_completion(self, task_id, context_paths, usage_required=True, context_required=True, exception_reason=None):
        from harness.completion import configure
        return configure(self, task_id, context_paths, usage_required, context_required, exception_reason)

    def record_context_maintenance(self, task_id, work_execution_id, report_path):
        from harness.completion import record
        return record(self, task_id, work_execution_id, report_path)

    def configure_development(self, task_id, baselines, code_paths=None, api_required=False, service_version=None, change_id=None):
        from harness.development_tracking import configure
        return configure(self, task_id, baselines, code_paths, api_required, service_version, change_id)

    def refresh_validation(self):
        return self.read()

    def configure_qa(self, task_id, **configuration):
        from harness.qa import QA
        return QA(self.root,self.run_id).configure(task_id,**configuration)

    def configure_runtime_limits(self, **limits):
        from harness.runtime_limits import configure
        return configure(self,**limits)

    def configure_delegation(self, parent_task_id, **configuration):
        from harness.delegation import Development
        return Development(self.root,self.run_id).configure(parent_task_id,**configuration)

    def configure_collection(self, task_id, **declarations):
        from harness.sequential import configure
        return configure(self, task_id, **declarations)

    def integration(self, task_id, agent_run_id, **observation):
        from harness.sequential import integration
        return integration(self, task_id, agent_run_id, **observation)

    def collection_report(self):
        from harness.sequential import report
        return report(self.root)

    def artifact(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError("artifact must be an existing file within the repository")
        data = path.read_bytes()
        try:
            sanitized = logging.redact(data.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            sanitized = data  # Local binary evidence (e.g. browser PNG), never decoded into logs.
        checksum = logging.digest(sanitized)
        directory = self.root / ".harness" / "artifacts"
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        frozen = directory / (checksum + ".txt")
        with (directory / 'snapshot.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not frozen.exists():
                with frozen.open("xb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(sanitized)
        git = subprocess.run(["rtk", "proxy", "git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True)
        return {"path": str(path.relative_to(self.root)), "sha256": logging.digest(data),
                "snapshot": str(frozen.relative_to(self.root)), "snapshot_sha256": checksum,
                "git_commit": git.stdout.strip() if git.returncode == 0 else UNKNOWN}

    def _valid_artifact(self, artifact):
        if not artifact or "snapshot" not in artifact or "snapshot_sha256" not in artifact:
            return False
        path = (self.root / artifact["snapshot"]).resolve()
        return path.is_relative_to(self.root) and path.is_file() and logging.digest(path.read_bytes()) == artifact["snapshot_sha256"]

    def register(self, feature_id, task_id, role, title, scope, criteria, inputs, dependencies=None, max_attempts=1,
                 work_type="HARNESS_BUILD", visual_required=False, execution_scope=None, pipeline_stage=None):
        return self._mutate("register", lambda state:self._register_state(state, feature_id, task_id, role, title, scope, criteria, inputs, dependencies, max_attempts, work_type, visual_required, execution_scope, pipeline_stage), task_id)

    def _register_state(self, state, feature_id, task_id, role, title, scope, criteria, inputs, dependencies=None, max_attempts=1,
                 work_type="HARNESS_BUILD", visual_required=False, execution_scope=None, pipeline_stage=None):
        if task_id in state["tasks"] or role not in ROLES or max_attempts < 1 or work_type not in logging.KINDS:
            raise ValueError("invalid or duplicate task")
        if pipeline_stage is not None and pipeline_stage not in {'planning','design','development','verification','report'}:
            raise ValueError('pipeline_stage must name a development pipeline stage, not work/review or a role')
        if not criteria or len({x["id"] for x in criteria}) != len(criteria) or not any(x["required"] for x in criteria):
            raise ValueError("unique criteria and at least one required criterion are needed")
        dependencies_list = dependencies or []
        if any(d not in state["tasks"] or state["tasks"][d]["feature_id"] != feature_id for d in dependencies_list):
            raise ValueError("dependencies must exist within the feature")
        from harness.development_tracking import SCOPES
        if execution_scope is not None and execution_scope not in SCOPES:
            raise ValueError("execution_scope must be code_implementation/documentation/input_interpretation_only")
        from harness.completion import inherited_contract
        completion = inherited_contract(self, work_type)
        refs = [self.artifact(p) for p in inputs]
        task = {"feature_id": feature_id, "task_id": task_id, "role": role, "title": title,
                "project_id": self.context["project_id"], "verification_scope": self.context["verification_scope"],
                "scope": scope, "execution_scope": execution_scope, "target_repository": str(self.root),
                "work_type": work_type, "state": "TODO", "dependencies": dependencies_list,
                "criteria": criteria, "inputs": refs, "outputs": [], "blocked_reason": None,
                "max_attempts": max_attempts, "executions": [], "reviews": [], "handoffs": [],
                "design_status": {"specification": "NOT_STARTED", "mockup": "NOT_PRODUCED",
                                  "visual_review": "NOT_RUN", "visual_evidence": None},
                "visual_required": visual_required}
        state["tasks"][task_id] = task
        from harness.execution_policy import inherit
        inherit(state, task, self.run_id)
        if pipeline_stage is not None:
            task['pipeline_stage']=pipeline_stage
        self._event(state, "task_registered", task, observed={"state": "TODO", "inputs": refs},
                    summary={"role": role, "title": title, "scope": scope})
        if completion is not None:
            task['completion_contract'] = completion
            self._event(state, 'completion_configured', task, observed=copy.deepcopy(completion))
        return copy.deepcopy(task)

    def register_execution_plan(self, **configuration):
        from harness.execution_plan import register
        return register(self, **configuration)

    def revise_execution_plan(self, **configuration):
        from harness.execution_plan import revise
        return revise(self, **configuration)

    def configure_stage(self, task_id, stage, settings):
        from harness.project_contract import STAGES, DOCUMENTS, validate
        def operation(state):
            task = state["tasks"][task_id]
            if stage not in STAGES or task["state"] not in {"TODO", "BLOCKED"} or any(r["ended_at"] is None for r in task["executions"]):
                raise ValueError("stage configuration requires inactive TODO/BLOCKED task and supported stage")
            ref = self.artifact(settings)
            data = validate(json.loads((self.root / ref["snapshot"]).read_text()))
            documents = [self.artifact(data[k]["value"]) for k in sorted(DOCUMENTS)
                         if data[k]["status"] in {"CONFIRMED", "PROPOSED"}]
            old = task.get("stage_contract", {})
            replaced = {a["path"] for a in [old["settings"]] + old["documents"]} if old else set()
            task["inputs"] = [a for a in task["inputs"] if a["path"] not in replaced]
            for item in [ref] + documents:
                if item not in task["inputs"]:
                    task["inputs"].append(item)
            task["stage_contract"] = {"stage": stage, "settings": ref, "documents": documents,
                                      "api_mode": data["api_contract"].get("mode", "NOT_APPLICABLE")}
            self._event(state, "task_stage_configured", task, observed={"before": old, "after": task["stage_contract"]})
        self._mutate("configure_stage", operation, task_id)

    def ready(self, task_id):
        def operation(state):
            task = state["tasks"][task_id]
            if task.get('applicability',{}).get('status')=='EXCLUDED':
                raise ValueError('excluded Todo is not complete or executable; record an applicability decision first')
            from harness.stage_readiness import gate as readiness_gate
            reason=readiness_gate(self,state,task)
            if reason:raise ValueError(reason)
            if task["state"] not in {"TODO", "BLOCKED"}:
                raise ValueError("ready requires TODO or BLOCKED")
            if any(r["ended_at"] is None for r in task["executions"]):
                raise ValueError("active checkpoint must be resumed or failed first")
            if any(state["tasks"][d]["state"] != "DONE" for d in task["dependencies"]):
                raise ValueError("unfinished dependency")
            if not all(self._valid_artifact(a) for a in task["inputs"]):
                raise ValueError("invalid input snapshot")
            from harness.project_contract import gate
            gate(self, task)
            if len([r for r in task["executions"] if r["kind"] == "work"]) >= task["max_attempts"]:
                raise ValueError("attempt budget exhausted")
            from harness.development_tracking import check_peers, validate_baseline, dependency_gate
            dependency_gate(state, task)
            from harness.development_tracking import ensure
            ensure(self, state, task, "ready")
            validate_baseline(self, state, task)
            check_peers(state, task)
            previous = task["state"]
            task.update(state="READY", blocked_reason=None)
            self._event(state, "task_state_changed", task, observed={"from": previous, "to": "READY"})
        self._mutate("ready", operation, task_id)

    def configure_usage_context(self, task_id, **context):
        """Explicit purpose/owner/repeat metadata; no task/QA status changes."""
        from harness.usage_context import validate
        def operation(state):
            task = state['tasks'][task_id]
            if any(not r.get('ended_at') for r in task['executions']):
                raise ValueError('finish/checkpoint the old role segment before changing its context')
            value = validate(context, task['role'])
            task['usage_context_configuration'] = value
            self._event(state, 'usage_context_configured', task, observed=value)
            return copy.deepcopy(value)
        return self._mutate('configure_usage_context', operation, task_id)

    def begin(self, task_id, role, review=False, execution_mode="current_agent", usage_context=None, agent_run_id=None):
        def operation(state):
            task = state["tasks"][task_id]
            from harness.stage_readiness import gate as readiness_gate
            reason=readiness_gate(self,state,task,[] if review else None)
            if reason:raise ValueError(reason)
            expected = "IN_REVIEW" if review else "READY"
            if task["state"] != expected or role not in ROLES or (not review and role != task["role"]):
                raise ValueError("state or role does not permit execution")
            if review and role not in {"verification", "orchestrator"}:
                raise ValueError("review role must be verification or orchestrator")
            if execution_mode not in {"current_agent", "local_check", "independent_process"}:
                raise ValueError("unsupported execution mode")
            attempts = [r for r in task["executions"] if r["kind"] == "work"]
            if not review and len(attempts) >= task["max_attempts"]:
                raise ValueError("attempt budget exhausted")
            if any(r["ended_at"] is None for r in task["executions"]):
                raise ValueError("an execution is already active")
            if not review:
                from harness.project_contract import gate
                gate(self, task)
                from harness.development_tracking import dependency_gate
                dependency_gate(state, task)
            from harness.development_tracking import ensure, execution_scope
            ensure(self, state, task, "begin_review" if review else "begin")
            reserved_id=agent_run_id or str(uuid.uuid4())
            if not isinstance(reserved_id,str) or str(uuid.UUID(reserved_id))!=reserved_id or any(r['agent_run_id']==reserved_id for t in state['tasks'].values() for r in t.get('executions',[])):
                raise ValueError('execution ID must be a new canonical UUID')
            run = {"agent_run_id": reserved_id, "run_id": self.run_id,
                   "execution_context": copy.deepcopy(self.context),
                   "feature_id": task["feature_id"], "task_id": task_id, "role": role,
                   "kind": "review" if review else "work", "execution_mode": execution_mode,
                   "execution_scope": execution_scope(task),
                   "started_at": logging.now(), "ended_at": None, "inputs": copy.deepcopy(task["outputs"] if review else task["inputs"]),
                   "outputs": [], "usage_bindings": [], "model_usage": UNKNOWN, "cost": UNKNOWN}
            if task.get('pipeline_stage'):
                run['pipeline_stage']=task['pipeline_stage']
            if task.get("development_tracking"):
                from harness.development_tracking import baseline, capture, check_peers
                from harness.development_tracking import validate_baseline
                validate_baseline(self, state, task)
                check_peers(state, task)
                run["baseline"] = baseline(task)
                run["code_state_start"] = capture(self, task)
            from harness.sequential import begin
            begin(self, task, run)
            for field in ('parent_task_id','development_area','coordination_plan_id'):
                if field in task:run[field]=task[field]
            from harness.usage_context import frozen
            # Copy the context before emitting start; later task edits never relabel it.
            run['usage_context'] = frozen(state, task, run, usage_context)
            task["executions"].append(run)
            if task.get('execution_contract'):
                run['execution_contract'] = copy.deepcopy(task['execution_contract'])
                run['execution_contract'].update(state['execution_policy_bindings'][self.run_id])
                run['execution_contract']['run_id'] = self.run_id
            if not review:
                task["state"] = "IN_PROGRESS"
                self._event(state, "task_state_changed", task, run["agent_run_id"], observed={"from": "READY", "to": "IN_PROGRESS"})
            self._event(state, "agent_run_started", task, run["agent_run_id"], observed={"started_at": run["started_at"], "inputs": run["inputs"], "baseline": run.get("baseline"), "code_state": run.get("code_state_start")},
                        summary={"role": role, "execution_mode": execution_mode, "independent_model_spawned": False})
            return copy.deepcopy(run)
        return self._mutate("begin_review" if review else "begin", operation, task_id)

    def checkpoint(self, task_id, agent_run_id, reason, checkpoint, wait_type=UNKNOWN, wait_target=UNKNOWN):
        """Pause active work without consuming another attempt or inventing a state."""
        def operation(state):
            task = state["tasks"][task_id]
            run = self._active(task, agent_run_id, "work")
            if task["state"] != "IN_PROGRESS" or not reason:
                raise ValueError("checkpoint requires active work and reason")
            ref = self.artifact(checkpoint)
            run["checkpoint"] = ref
            run["checkpoint_capabilities"] = {"execution_resume": True, "code_restore": False}
            from harness.sequential import wait_start
            wait_start(self, state, task, run, reason, wait_type, wait_target)
            task.update(state="BLOCKED", blocked_reason=reason)
            self._event(state, "role_checkpoint", task, agent_run_id,
                        observed={"checkpoint": ref, "reason": reason, "from": "IN_PROGRESS", "to": "BLOCKED"})
        return self._mutate("checkpoint", operation, task_id)

    def resume(self, task_id, agent_run_id, decision):
        def operation(state):
            task = state["tasks"][task_id]
            matching = [r for r in task['executions'] if r['agent_run_id'] == agent_run_id and not r.get('ended_at')]
            kind = matching[0]['kind'] if len(matching) == 1 else 'work'
            run = self._active(task, agent_run_id, kind)
            if kind != 'work' and not run.get('required_question_wait'):
                raise ValueError('only question-checkpointed reviews can be resumed')
            if task["state"] != "BLOCKED" or not self._valid_artifact(run.get("checkpoint", {})):
                raise ValueError("resume requires a valid checkpoint")
            from harness.development_tracking import ensure
            ensure(self, state, task, "resume", run)
            ref = self.artifact(decision)
            run.setdefault("decisions", []).append(ref)
            from harness.sequential import wait_end
            wait_end(self, state, task, run, "RELEASED")
            restored_state = 'IN_REVIEW' if kind == 'review' else 'IN_PROGRESS'
            task.update(state=restored_state, blocked_reason=None)
            self._event(state, "role_resumed", task, agent_run_id,
                        observed={"decision": ref, "checkpoint": run["checkpoint"], "from": "BLOCKED", "to": restored_state})
        return self._mutate("resume", operation, task_id)

    def fail(self, task_id, agent_run_id, reason, failure_category="UNKNOWN", failure_evidence=None, next_action=None, requires_human=None, decision_question=None, cancel_question_wait=False):
        if failure_category not in {"PRODUCT_DEFECT","HARNESS_DEFECT","ENVIRONMENT","UNKNOWN"} or (requires_human is not None and not isinstance(requires_human,bool)):
            raise ValueError("invalid explicit failure classification")
        if (failure_category!="UNKNOWN" or requires_human is True) and not failure_evidence:
            raise ValueError("classified failure/human decision requires evidence")
        if requires_human is True and not decision_question:
            raise ValueError("human decision needs an explicit question")
        context={"category":failure_category,"evidence":self.artifact(failure_evidence) if failure_evidence else None,"next_action":next_action,"requires_human":requires_human,"question":decision_question}
        def operation(state):
            task = state["tasks"][task_id]
            run = self._active(task, agent_run_id, "work")
            from harness.execution_policy import pending
            if pending(state, task_id) and run.get('required_question_wait') and not cancel_question_wait:
                self._event(state, 'required_question_worker_stopped', task, agent_run_id,
                            observed={'reason': reason, 'checkpoint': run.get('checkpoint'), 'state': 'WAITING_REQUIRED_ANSWER'})
                return
            if task["state"] not in {"IN_PROGRESS", "BLOCKED"} or not reason:
                raise ValueError("failure requires active work and cause")
            previous = task["state"]
            run.update(ended_at=logging.now(), failure=reason, failure_context=context)
            from harness.sequential import finish, wait_end
            wait_end(self, state, task, run, "CANCELLED")
            finish(self, task, run)
            task.update(state="BLOCKED", blocked_reason=reason)
            self._event(state, "agent_run_failed", task, agent_run_id,
                        observed={"reason": reason, "failure_context": context, "ended_at": run["ended_at"], "from": previous, "to": "BLOCKED"})
        return self._mutate("fail", operation, task_id)

    def _active(self, task, agent_run_id, kind):
        matches = [r for r in task["executions"] if r["agent_run_id"] == agent_run_id and r["kind"] == kind and r["ended_at"] is None]
        if len(matches) != 1:
            raise ValueError("execution is not active")
        return matches[0]

    def submit(self, task_id, agent_run_id, outputs, summary, design_status=None, delivery=None):
        def operation(state):
            task = state["tasks"][task_id]
            if task["state"] != "IN_PROGRESS" or not outputs:
                raise ValueError("submit requires work and outputs")
            run = self._active(task, agent_run_id, "work")
            from harness.development_tracking import ensure, document_outputs
            ensure(self, state, task, "submit", run)
            document_outputs(task, outputs, design_status)
            refs = [self.artifact(p) for p in outputs]
            if task.get("development_tracking"):
                from harness.development_tracking import capture, baseline, check_peers
                from harness.development_tracking import validate_baseline
                validate_baseline(self, state, task)
                check_peers(state, task)
                if baseline(task) != run["baseline"]:
                    raise ValueError("execution input baseline changed")
                paths = task["development_tracking"]["code_paths"]
                if paths and any(not any(r["path"] == p or r["path"].startswith(p + "/") for p in paths) for r in refs):
                    raise ValueError("submitted outputs must be covered by code_paths")
                task["submission_code_state"] = capture(self, task)
                if any(task["submission_code_state"]["files"].get(r["path"]) != r["sha256"] for r in refs):
                    raise ValueError("submitted files changed while capturing code state")
                run["code_state_result"] = copy.deepcopy(task["submission_code_state"])
                from harness.development_tracking import submitted_in_head
                run["submitted_content_in_head"] = submitted_in_head(self, task["submission_code_state"]["head"], refs)
            if delivery is not None:
                from harness.deliverables import archive
                task["delivery"] = archive(self, state, task, refs, delivery)
            if task["role"] == "design":
                task["design_status"] = {"specification": "NOT_STARTED", "mockup": "NOT_PRODUCED", "visual_review": "NOT_RUN", "visual_evidence": None}
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
            from harness.sequential import finish
            finish(self, task, run)
            self._event(state, "agent_run_finished", task, agent_run_id, observed={"ended_at": run["ended_at"], "outputs": refs, "code_state": run.get("code_state_result"), "submitted_content_in_head": run.get("submitted_content_in_head")}, summary={"result": summary})
            self._event(state, "task_state_changed", task, agent_run_id, observed={"from": "IN_PROGRESS", "to": "IN_REVIEW", "design_status": task["design_status"]})
        self._mutate("submit", operation, task_id)

    def review(self, task_id, agent_run_id, results, summary, design_checks=None):
        def operation(state):
            task = state["tasks"][task_id]
            from harness.stage_readiness import STAGES
            for result in results:
                if 'return_stage' in result and (result['result']!='FAIL' or result['return_stage'] not in STAGES or task['feature_id'] not in state.get('stage_workflows',{}) or not result.get('reason')):
                    raise ValueError('typed return requires FAIL, registered target stage, reason and evidence')
            if task["state"] != "IN_REVIEW":
                raise ValueError("review requires IN_REVIEW")
            run = self._active(task, agent_run_id, "review")
            from harness.development_tracking import ensure
            ensure(self, state, task, "review", run)
            if design_checks is not None:
                if task["role"] != "design" or set(design_checks) != {"structure", "interaction", "visual"}:
                    raise ValueError("design review requires separate structure, interaction and visual results")
                accepted = {}
                for name, check in design_checks.items():
                    if check.get("result") not in {"PASS", "FAIL", "NOT_RUN"}:
                        raise ValueError("invalid design check result")
                    evidence = self.artifact(check["evidence"]) if check.get("evidence") else None
                    if check["result"] != "NOT_RUN" and (not evidence or not check.get("environment") or not check.get("coverage")):
                        raise ValueError("executed design checks require evidence, environment and coverage")
                    captures = []
                    if evidence and check["result"] != "NOT_RUN":
                        report = json.loads((self.root / evidence["snapshot"]).read_text())
                        expected = {a["path"]: a["sha256"] for a in task["outputs"]}
                        if report.get("tested_outputs") != expected or report.get("kind") != name or report.get("result") != check["result"]:
                            raise ValueError("review evidence must match exact submitted output hashes and check kind/result")
                        targets = task.get("role_contract", {}).get("design_targets", [])
                        for target in targets:
                            result = report.get("target_results", {}).get(target, {})
                            if result.get("result") not in {"PASS", "FAIL", "NOT_RUN"} or (check["result"] == "PASS" and result["result"] != "PASS") or not result.get("coverage"):
                                raise ValueError("review must cover each configured target separately")
                            if name == "visual" and not result.get("screenshots"):
                                raise ValueError("each target needs its own visual capture evidence")
                            if name == "visual" and not set(result["screenshots"]).issubset(set(report.get("screenshots", []))):
                                raise ValueError("target capture references must be in archived review captures")
                        if name == "visual":
                            captures = [self.artifact(p) for p in report.get("screenshots", [])]
                            if not captures:
                                raise ValueError("visual review requires actual screenshot files")
                    accepted[name] = {**check, "evidence": evidence, "captures": captures, "tested_outputs": copy.deepcopy(task["outputs"])}
                task["design_status"].update(checks=accepted, visual_review=accepted["visual"]["result"],
                                             visual_evidence=accepted["visual"]["evidence"])
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
            if passed:
                from harness.completion import gate as completion_gate
                completion_gate(self, state, task)
            passed = passed and (not task["visual_required"] or task["design_status"]["visual_review"] == "PASS")
            passed = passed and (task["role"] != "design" or task["design_status"]["specification"] == "COMPLETE")
            from harness.project_contract import review_gate
            review_gate(self, task, checked)
            from harness.stage_readiness import gate as readiness_gate,review_basis
            reason=readiness_gate(self,state,task,checked)
            if reason:raise ValueError(reason)
            from harness.findings import blocking
            passed = passed and not blocking(state, task)
            if task.get("role_contract", {}).get("scope") == "input_interpretation_only":
                receipt = task.get("input_confirmation", {}).get("receipt", {})
                passed = passed and {r["path"]: r["sha256"] for r in receipt.get("artifacts", [])} == {r["path"]: r["sha256"] for r in task["inputs"]}
                passed = passed and bool(receipt.get("interpretation"))
            if task["visual_required"]:
                passed = passed and task["design_status"]["mockup"] == "COMPLETE"
                passed = passed and all(task["design_status"].get("checks", {}).get(k, {}).get("result") == "PASS"
                                        for k in ("structure", "interaction", "visual"))
            record = {"agent_run_id": agent_run_id, "results": checked, "outputs": copy.deepcopy(task["outputs"])}
            basis=review_basis(self,state,task)
            if basis is not None:
                from harness.stage_readiness import contract_hash
                config=next(c for c in state['stage_workflows'][task['feature_id']]['stages'].values() if c['task_id']==task_id)
                record.update(stage_readiness_basis=basis,stage_readiness_contract_sha256=contract_hash(task,config))
            if task.get("development_tracking"):
                from harness.development_tracking import capture, baseline, check_peers
                from harness.development_tracking import validate_baseline
                validate_baseline(self, state, task)
                check_peers(state, task)
                code = capture(self, task)
                if code["state_sha256"] != run["code_state_start"]["state_sha256"]:
                    raise ValueError("code changed during verification; begin a new verification")
                if any(not (self.root / r["path"]).is_file() or logging.digest((self.root / r["path"]).read_bytes()) != r["sha256"] for r in task["outputs"]):
                    raise ValueError("submitted output changed before verification")
                for result in checked:
                    if result["result"] == "PASS":
                        report = json.loads((self.root / result["evidence"]["snapshot"]).read_text())
                        if report.get("code_state_sha256") != code["state_sha256"] or report.get("baseline") != baseline(task):
                            raise ValueError("PASS evidence requires exact code state and baseline")
                record["development_evidence"] = {"code_state": code, "baseline": baseline(task)}
                task.setdefault("validation_status", {})[agent_run_id] = {"state": "CURRENT" if passed else "NOT_PASSED"}
            task["reviews"].append(record)
            task.update(state="DONE" if passed else "BLOCKED", blocked_reason=None if passed else "Required review failed or NOT_RUN, or required visual review incomplete")
            if task.get("delivery"):
                from harness.deliverables import reviewed
                reviewed(state, task, passed)
            if passed and task.get("input_confirmation"):
                task["input_confirmation"].update(state="INTERPRETATION_REVIEWED", review_run_id=agent_run_id)
            run.update(ended_at=logging.now(), outputs=[r["evidence"] for r in checked if r["evidence"]])
            if record.get("development_evidence"):
                run["code_state_result"] = copy.deepcopy(record["development_evidence"]["code_state"])
            from harness.sequential import finish
            finish(self, task, run)
            self._event(state, "task_reviewed", task, agent_run_id, observed={"results": checked, "design_status": task["design_status"], "development_evidence": record.get("development_evidence")}, summary={"reviewer_role": run["role"], "result": summary})
            self._event(state, "agent_run_finished", task, agent_run_id, observed={"ended_at": run["ended_at"], "outputs": run["outputs"]})
            self._event(state, "task_state_changed", task, agent_run_id, observed={"from": "IN_REVIEW", "to": task["state"], "reason": task["blocked_reason"]})
            return task["state"]
        outcome=self._mutate("review", operation, task_id)
        grouped={}
        for result in results:
            if result.get('return_stage'):grouped.setdefault(result['return_stage'],[]).append(result)
        current=self.read()
        flow=current.get('stage_workflows',{}).get(current['tasks'][task_id]['feature_id'],{})
        own=next((n for n,c in flow.get('stages',{}).items() if c['task_id']==task_id),None)
        if outcome=='BLOCKED' and own and not grouped:
            required={c['id'] for c in current['tasks'][task_id]['criteria'] if c['required']}
            rejected=[r for r in results if r['criterion_id'] in required and r['result']!='PASS']
            if rejected:
                grouped[own]=[{**r,'reason':'required criterion '+r['result']} for r in rejected]
        for stage,items in grouped.items():
            proof=items[0].get('evidence')
            if not proof:
                # Failure may legitimately lack evidence. Preserve the recorded review,
                # never manufacture PASS evidence or lose the already committed return.
                path=self.path.parent/'review-returns'/(agent_run_id+'.json');path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps({'review_run_id':agent_run_id,'task_id':task_id,'result':'NOT_PASSED','return_stage':stage,'criteria':items},ensure_ascii=False,indent=2))
                proof=str(path.relative_to(self.root))
            self.return_to_stage(self.read()['tasks'][task_id]['feature_id'],stage,
                '; '.join(r['criterion_id']+': '+r['reason'] for r in items),proof,task_id,agent_run_id)
        return outcome

    def handoff(self, source_id, target_id):
        def operation(state):
            from harness.development_tracking import refresh
            refresh(self, state)
            source, target = state["tasks"][source_id], state["tasks"][target_id]
            from harness.execution_policy import gate as execution_gate
            execution_gate(self, state, target_id, 'ready')
            from harness.development_tracking import ensure
            ensure(self, state, source, "handoff_source")
            latest_review = source["reviews"][-1]["agent_run_id"] if source["reviews"] else None
            if source.get("validation_status", {}).get(latest_review, {}).get("state") == "RECHECK_REQUIRED":
                raise ValueError("development validation requires recheck before handoff")
            if source["state"] != "DONE" or target["state"] != "TODO" or source_id not in target["dependencies"]:
                raise ValueError("handoff requires reviewed source and dependent TODO target")
            if source["feature_id"] != target["feature_id"]:
                raise ValueError("feature mismatch")
            from harness.findings import blocking
            if blocking(state, source):
                raise ValueError("unresolved blocking findings prevent handoff")
            if any(state["tasks"][d]["state"] != "DONE" for d in target["dependencies"]):
                raise ValueError("unfinished target dependency")
            if target["role"] == "development" and source["role"] == "design" and not source["visual_required"]:
                raise ValueError("document-only design cannot hand off final UI to development")
            if not all(self._valid_artifact(a) for a in source["outputs"] + target["inputs"]):
                raise ValueError("invalid handoff snapshot")
            from harness.project_contract import gate
            gate(self, target)
            target["inputs"].extend(copy.deepcopy(source["outputs"]))
            supplementary = []
            if target["role"] == "development" and source.get("delivery"):
                from harness.deliverables import registry, find_version
                book = registry(state, source["delivery"]["folder"])
                supplementary.extend(find_version(book, source["delivery"]["planning_version"])["artifacts"])
                supplementary.extend(c["evidence"] for c in source["design_status"].get("checks", {}).values() if c.get("evidence"))
                for ref in supplementary:
                    if not self._valid_artifact(ref):
                        raise ValueError("invalid transitive handoff input")
                    if ref not in target["inputs"]:
                        target["inputs"].append(copy.deepcopy(ref))
            ensure(self, state, target, "handoff_target")
            record = {"from_task_id": source_id, "to_task_id": target_id, "artifacts": copy.deepcopy(source["outputs"]),
                      "criteria_ids": [c["id"] for c in source["criteria"]], "version_policy": "content_snapshot_for_harness_trial; product_handoff_requires_git_commit"}
            record["sequential_collection"] = {"source_declarations": copy.deepcopy(source.get("collection", {})),
                "target_declarations": copy.deepcopy(target.get("collection", {})),
                "check": "Inspect collection-report; undeclared dependencies/resources/waits/integration are UNKNOWN, not zero. Never infer REQUIRED edges from execution order."}
            if source.get("delivery"):
                record["delivery"] = copy.deepcopy(source["delivery"])
                from harness.deliverables import find_version, registry
                book = registry(state, source["delivery"]["folder"])
                version = find_version(book, source["delivery"]["version"])
                if version["status"] != "APPROVED":
                    raise ValueError("handoff requires currently approved deliverable")
                if target["role"] == "development" and book.get("validation_status", {}).get(version["id"], {}).get("state") == "RECHECK_REQUIRED":
                    raise ValueError("changed deliverable requires revalidation before development handoff")
                version["milestones"].append({"handoff_to": target_id})
                record["supplementary_artifacts"] = copy.deepcopy(supplementary)
            source["handoffs"].append(record)
            target["handoffs"].append(record)
            target["state"] = "READY"
            self._event(state, "task_handoff", target, observed=record)
            self._event(state, "task_state_changed", target, observed={"from": "TODO", "to": "READY"})
            return copy.deepcopy(record)
        return self._mutate("handoff", operation, source_id)

    def issue(self, **data):
        from harness.findings import record
        return record(self, **data)

    def configure_stage_workflow(self,feature_id,stages):
        from harness.stage_readiness import configure
        return configure(self,feature_id,stages)

    def bind_stage_inputs(self,task_id,inputs,reason):
        from harness.stage_readiness import bind_inputs
        return bind_inputs(self,task_id,inputs,reason)

    def return_to_stage(self,feature_id,stage,reason,evidence,source_task_id=None,source_review_id=None):
        from harness.stage_readiness import return_to_stage
        return return_to_stage(self,feature_id,stage,reason,evidence,source_task_id,source_review_id)

    def route_issue(self, **data):
        from harness.findings import route
        return route(self, **data)

    def resolve_issue(self, **data):
        from harness.findings import resolve
        return resolve(self, **data)

    def intervention(self, task_id, agent_run_id, session_id, turn_id, classification, basis, evidence,
                     message_id=UNKNOWN, request_item="1"):
        task = self.read()["tasks"][task_id]
        matches = [e for e in task["executions"] if e["agent_run_id"] == agent_run_id]
        if len(matches) != 1:
            raise ValueError("explicit existing agent_run_id required")
        execution = matches[0]
        context = {"feature_id": task["feature_id"], "task_id": task_id,
                   "agent_run_id": agent_run_id, "run_id": execution["run_id"],
                   "role": execution["role"], "stage": execution["kind"], "work_type": task["work_type"],
                   "task_state": task["state"], "design_status": copy.deepcopy(task.get("design_status", UNKNOWN))}
        return self.logger.record_intervention(context, session_id, turn_id, classification, basis,
                                               evidence, message_id, request_item)

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

    def bind_usage_batch(self, task_id, agent_run_id, bindings, reason):
        """Validate one owner's entire batch before appending any attribution."""
        if not isinstance(bindings, list) or any(not isinstance(binding, dict) for binding in bindings):
            raise ValueError('bindings list required')
        requested = []
        seen = set()
        for binding in bindings:
            key = (binding.get('session_id'), binding.get('response_id'))
            if any(not isinstance(value, str) or not value or value == UNKNOWN for value in key):
                raise ValueError('explicit session_id and response_id required')
            if key not in seen:
                requested.append(key)
                seen.add(key)

        def operation(state):
            task = state['tasks'][task_id]
            matches = [r for r in task['executions'] if r['agent_run_id'] == agent_run_id]
            if len(matches) != 1:
                raise ValueError('unknown agent_run_id')
            run = matches[0]
            owners = {}
            for other in state['tasks'].values():
                for execution in other['executions']:
                    for binding in execution['usage_bindings']:
                        key = (binding['session_id'], binding['response_id'])
                        owners.setdefault(key, set()).add(execution['agent_run_id'])
            pending = []
            for key in requested:
                existing = owners.get(key, set())
                if existing - {agent_run_id}:
                    raise ValueError('response already attributed to another execution')
                if not existing:
                    pending.append(key)
            if not pending:
                return 0
            wanted = set(pending)
            source_ids = {}
            for event in self.logger.read():
                if event['event_type'] != 'model_usage':
                    continue
                key = (event['source'].get('session_id'), event['observed'].get('response_id'))
                if key in wanted:
                    source_ids.setdefault(key, []).append(event['event_id'])
            if any(key not in source_ids for key in pending):
                raise ValueError('response usage must be imported before attribution')
            for session_id, response_id in pending:
                binding = {'session_id':session_id, 'response_id':response_id}
                run['usage_bindings'].append(binding)
                self._event(state, 'usage_attributed', task, agent_run_id,
                            observed={**binding, 'source_event_ids':source_ids[(session_id,response_id)]},
                            summary={'attribution':'agent_declared', 'reason':reason})
            return len(pending)
        return self._mutate('bind_usage_batch', operation, task_id)

    def report(self):
        state = self.read()
        events = self.logger.read()
        report = copy.deepcopy(state)
        report["execution_context"] = copy.deepcopy(self.context)
        report["features"] = {}
        for task in report["tasks"].values():
            from harness.execution_policy import status as execution_status
            task['execution_gate'] = execution_status(state, task, self.run_id)
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
    parser.add_argument("action", choices=["bind-execution-session", "configure-execution-policy", "configure-task-plan", "open-question", "answer-question", "question-status", "register", "configure-completion", "record-context-maintenance", "configure-development", "refresh-validation", "configure-stage", "configure-stage-workflow", "bind-stage-inputs", "return-to-stage", "configure-delegation", "configure-runtime-limits", "configure-qa", "configure-collection", "collection-report", "integration", "ready", "begin", "submit", "review", "handoff", "checkpoint", "resume", "fail", "issue", "route-issue", "resolve-issue", "intervention", "bind-usage", "show"])
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    tasks = Tasks(args.root, args.run_id)
    if args.action == 'question-status':
        result = tasks.question_status()
    elif args.action == "collection-report":
        result = tasks.collection_report()
    elif args.action in {"show", "refresh-validation"}:
        result = tasks.report()
    else:
        data = json.loads(args.data.read_text())
        result = getattr(tasks, args.action.replace("-", "_"))(**data)
    print(json.dumps(logging.redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
