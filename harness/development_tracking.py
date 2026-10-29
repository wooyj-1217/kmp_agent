"""Target-repository development evidence in the existing task registry. No code restore."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    result = subprocess.run(["rtk", "proxy", "git", *args], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError("target Git inspection failed: " + " ".join(args[:2]))
    return result.stdout


def capture(manager, task):
    config = task["development_tracking"]
    root = manager.root
    if Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
        raise ValueError("task root must be the target Git repository root")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    names = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
    names += git(root, "ls-tree", "-r", "--name-only", "-z", head).decode().split("\0")
    paths = config["code_paths"]
    files = {}
    for name in sorted(set(names) - {""}):
        if name.startswith((".harness/", ".git/", ".kmp-agent/")):
            continue
        if paths and not any(name == p or name.startswith(p + "/") for p in paths):
            continue
        path = root / name
        if path.is_symlink():
            raise ValueError("symlink code state unsupported; cannot certify validation")
        files[name] = digest(path.read_bytes()) if path.is_file() else None
    changed = {}
    for name, checksum in files.items():
        result = subprocess.run(["rtk", "proxy", "git", "show", head + ":" + name], cwd=root, capture_output=True)
        committed = digest(result.stdout) if result.returncode == 0 else None
        if committed != checksum:
            changed[name] = {"head_sha256": committed, "working_sha256": checksum}
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all").decode()
    status = [line for line in status.splitlines() if not line[3:].startswith((".harness/", ".kmp-agent/"))]
    index = [entry for entry in git(root, "ls-files", "--stage", "-z").decode().split("\0")
             if entry and entry.split("\t", 1)[-1] in files]
    if any(entry.startswith("160000 ") for entry in index):
        raise ValueError("submodule code state requires explicit separate target task")
    modes = {name: (root / name).stat().st_mode & 0o777 for name in files if (root / name).is_file()}
    identity = {"head": head, "files": files, "index": index, "modes": modes}
    if git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("target HEAD changed during capture")
    for name, checksum in files.items():
        path = root / name
        if (digest(path.read_bytes()) if path.is_file() else None) != checksum:
            raise ValueError("target files changed during capture")
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "repository_root": str(root), "head": head, "dirty": bool(status),
            "scope": paths or ("FULL_REPOSITORY" if config.get("scope_policy") == "full_repository" else "UNKNOWN_FULL_REPOSITORY"), "files": files, "index": index, "modes": modes, "changed_files": changed,
            "content_in_head": not changed, "state_kind": "WORKING_TREE" if status else "COMMITTED",
            "state_sha256": digest(json.dumps(identity, sort_keys=True).encode()),
            "code_restore_supported": False}


def baseline(task):
    return copy.deepcopy({"references": task["development_tracking"]["baselines"],
                          "inputs": task["inputs"], "role_contract": task.get("role_contract"),
                          "stage_contract": task.get("stage_contract")})


def dependency_gate(state, task):
    for tid in task["dependencies"]:
        source = state["tasks"][tid]
        latest = source["reviews"][-1]["agent_run_id"] if source["reviews"] else None
        if execution_scope(source) == "code_implementation" and (not source.get("development_tracking") or not source["reviews"] or not source["reviews"][-1].get("development_evidence")):
            raise ValueError("dependency development tracking missing; requires recheck")
        if source.get("validation_status", {}).get(latest, {}).get("state") == "RECHECK_REQUIRED":
            raise ValueError("dependency validation requires recheck")


def validate_baseline(manager, state, task):
    config = task.get("development_tracking")
    if not config:
        return
    refs = config["baselines"]
    for ref in refs.values():
        if not manager._valid_artifact(ref) or ref not in task["inputs"]:
            raise ValueError("development baseline missing from frozen task inputs")
    role = task.get("role_contract", {})
    if role.get("planning_version") or role.get("design_version"):
        from harness.deliverables import find_version
        book = state["deliverables"][role["folder"]]
        for kind in ("planning", "design"):
            identifier = role.get(kind + "_version")
            if identifier:
                version = find_version(book, identifier)
                if kind not in refs or not any(a["path"] == refs[kind]["path"] and a["sha256"] == refs[kind]["sha256"] for a in version["artifacts"]):
                    raise ValueError("execution baseline differs from selected P/D")
                if book.get("validation_status", {}).get(identifier, {}).get("state") == "RECHECK_REQUIRED":
                    raise ValueError("P/D baseline requires revalidation")
    stage = task.get("stage_contract", {}).get("stage")
    if stage in {"client_integration", "server_implementation", "integration_verification"}:
        from harness.project_contract import load
        data = load(manager, task)
        required = data["server_mode"].get("value") != "none"
        if required != config["api_required"]:
            raise ValueError("API requirement changed; configure development baseline again")
        if required:
            for kind, key in (("api", "api_contract"), ("policy", "policy_responsibility")):
                document = next((r for r in task["stage_contract"]["documents"] if r["path"] == data[key]["value"]), None)
                if document != refs.get(kind):
                    raise ValueError("API/policy baseline differs from frozen stage inputs")


def check_peers(state, task):
    config = task.get("development_tracking")
    if not config or not config.get("api_required"):
        return
    own = config["baselines"]["api"]["sha256"]
    for other in state["tasks"].values():
        peer = other.get("development_tracking")
        latest = other["reviews"][-1]["agent_run_id"] if other["reviews"] else None
        if other["state"] == "DONE" and other.get("validation_status", {}).get(latest, {}).get("state") == "RECHECK_REQUIRED":
            continue  # Historical invalidated implementations do not define the new active baseline.
        if other["feature_id"] == task["feature_id"] and peer and peer.get("api_required"):
            if not {"api", "policy"}.issubset(peer.get("baselines", {})):
                raise ValueError("peer development tracking missing API/policy baselines")
            if own != peer["baselines"]["api"]["sha256"] or config["baselines"]["policy"]["sha256"] != peer["baselines"]["policy"]["sha256"]:
                raise ValueError("client/server API baseline mismatch in feature")


def refresh(manager, state):
    for task in state["tasks"].values():
        if not task.get("development_tracking"):
            for review in task["reviews"]:
                if review.get("development_evidence"):
                    key = review["agent_run_id"]
                    previous = task.setdefault("validation_status", {}).get(key, {})
                    if previous.get("state") != "RECHECK_REQUIRED":
                        status = {"state": "RECHECK_REQUIRED", "reasons": ["development tracking configuration missing"]}
                        task["validation_status"][key] = status
                        manager._event(state, "development_validation_invalidated", task, key, observed=status)
            continue
        for review in task["reviews"]:
            proof = review.get("development_evidence")
            if not proof:
                continue
            reasons = []
            try:
                current = capture(manager, task)
                if current["state_sha256"] != proof["code_state"]["state_sha256"]:
                    reasons.append("code state changed or impact unknown")
                if baseline(task) != proof["baseline"]:
                    reasons.append("input baseline changed")
                for ref in proof["baseline"]["inputs"]:
                    path = manager.root / ref["path"]
                    if not path.is_file() or digest(path.read_bytes()) != ref["sha256"]:
                        reasons.append("input working copy changed")
                validate_baseline(manager, state, task)
                check_peers(state, task)
            except (ValueError, OSError, KeyError, TypeError):
                reasons.append("current code/contract impact cannot be established")
            key = review["agent_run_id"]
            if not task["development_tracking"].get("code_paths") and task["development_tracking"].get("scope_policy") != "full_repository":
                reasons.append("impact scope unknown")
            previous = task.setdefault("validation_status", {}).get(key, {})
            if reasons and previous.get("state") != "RECHECK_REQUIRED":
                status = {"state": "RECHECK_REQUIRED", "reasons": sorted(set(reasons))}
                task["validation_status"][key] = status
                manager._event(state, "development_validation_invalidated", task, key, observed=status)


def configure(manager, task_id, baselines, code_paths=None, api_required=False, service_version=None, change_id=None):
    def operation(state):
        return _configure(manager, state, task_id, baselines, code_paths, api_required, service_version, change_id)
    return manager._mutate("configure_development", operation, task_id)


def _configure(manager, state, task_id, baselines, code_paths=None, api_required=False,
               service_version=None, change_id=None, automatic=False):
    task = state["tasks"][task_id]
    allowed = {"TODO", "BLOCKED", "READY"} if automatic else {"TODO", "BLOCKED"}
    if task["state"] not in allowed or any(r["ended_at"] is None for r in task["executions"]):
        raise ValueError("development baseline requires inactive TODO/BLOCKED task")
    if not baselines or set(baselines) - {"planning", "design", "api", "policy"}:
        raise ValueError("explicit applicable planning/design/api/policy baselines required")
    if api_required and not {"api", "policy"}.issubset(baselines):
        raise ValueError("API work requires API and policy baselines")
    paths = code_paths or []
    for p in paths:
        if not p or Path(p).is_absolute() or ".." in Path(p).parts or p.startswith((".git", ".harness")):
            raise ValueError("code_paths must be target-relative code scopes")
    stage = task.get("stage_contract", {}).get("stage")
    required_api = api_required
    if stage in {"client_integration", "server_implementation", "integration_verification"}:
        from harness.project_contract import load
        data = load(manager, task)
        required_api = data["server_mode"].get("value") != "none"
    if required_api and not {"api", "policy"}.issubset(baselines):
        raise ValueError("integration requires API and policy baselines")
    refs = {}
    for kind, value in baselines.items():
        if isinstance(value, dict):
            if value not in task["inputs"] or not manager._valid_artifact(value):
                raise ValueError("auto baseline must be a valid frozen task input")
            refs[kind] = copy.deepcopy(value)
        else:
            refs[kind] = manager.artifact(value)
    if required_api and task.get("stage_contract"):
        from harness.project_contract import load
        settings = load(manager, task)
        for key, field in (("api", "api_contract"), ("policy", "policy_responsibility")):
            expected = next((r for r in task["stage_contract"]["documents"] if r["path"] == settings[field]["value"]), None)
            if expected != refs[key]:
                raise ValueError("development baseline differs from frozen stage contract")
    role = task.get("role_contract", {})
    if role.get("planning_version") or role.get("design_version"):
        from harness.deliverables import find_version
        book = state["deliverables"][role["folder"]]
        for kind in ("planning", "design"):
            version_id = role.get(kind + "_version")
            if version_id:
                version = find_version(book, version_id)
                if kind not in refs or not any(a["sha256"] == refs[kind]["sha256"] and a["path"] == refs[kind]["path"] for a in version["artifacts"]):
                    raise ValueError("baseline must match selected P/D version")
    previous = copy.deepcopy(task.get("development_tracking"))
    if previous and previous["baselines"] != refs and not change_id:
        raise ValueError("baseline change requires existing CR")
    if change_id:
        changes = [c for b in state.get("deliverables", {}).values() for c in b["changes"] if c["id"] == change_id]
        if len(changes) != 1 or not changes[0].get("development_change"):
            raise ValueError("unambiguous CR with development change evidence required")
        change = changes[0]["development_change"]
        if change["after_baselines"] != refs or (previous and change["before_baselines"] != previous["baselines"]):
            raise ValueError("CR before/after baselines do not match")
        if task_id not in changes[0]["impacts"]["tasks"] and "UNKNOWN" not in changes[0]["impacts"]["tasks"]:
            raise ValueError("CR must include affected task")
    task["development_tracking"] = {"baselines": refs, "code_paths": paths,
        "api_required": bool(required_api), "service_version": service_version, "change_id": change_id,
        "repository_root": str(manager.root), "automatic": automatic,
        "scope_policy": "full_repository" if automatic else ("declared_paths" if paths else "unknown"),
        "checkpoint_semantics": "execution_resume_only", "code_restore_supported": False}
    task["execution_scope"] = "code_implementation"
    old_paths = {r["path"] for r in previous["baselines"].values()} if previous else set()
    task["inputs"] = [r for r in task["inputs"] if r["path"] not in old_paths]
    for ref in refs.values():
        task["inputs"] = [r for r in task["inputs"] if r["path"] != ref["path"]] + [ref]
    capture(manager, task)
    manager._event(state, "development_baseline_configured", task,
                   observed={"before": previous, "after": task["development_tracking"]})


def submitted_in_head(manager, head, refs):
    for ref in refs:
        result = subprocess.run(["rtk", "proxy", "git", "show", head + ":" + ref["path"]],
                                cwd=manager.root, capture_output=True)
        if result.returncode or digest(result.stdout) != ref["sha256"]:
            return False
    return True


SCOPES = {"code_implementation", "documentation", "input_interpretation_only"}


def execution_scope(task):
    """Structured task intent; never infer code work from a free-text title."""
    declared = task.get("execution_scope")
    if task.get("development_tracking") or task.get("stage_contract"):
        if task.get("role_contract", {}).get("scope") == "input_interpretation_only":
            raise ValueError("code stage/tracking conflicts with interpretation-only entry point")
        if declared in {"documentation", "input_interpretation_only"}:
            raise ValueError("code stage/tracking conflicts with non-code execution_scope")
        return "code_implementation"
    if task.get("role_contract", {}).get("scope") == "input_interpretation_only":
        if declared == "code_implementation":
            raise ValueError("implementation conflicts with interpretation-only role entry point")
        return "input_interpretation_only"
    return declared or ("code_implementation" if task["role"] == "development" else "documentation")


def document_outputs(task, paths, design_status=None):
    design_status = design_status or task.get("design_status", {})
    # Development documentation is an explicit exemption, not a route to submit source/configuration.
    if (task["role"] == "development" or task.get("execution_scope") in {"documentation", "input_interpretation_only"}) and execution_scope(task) != "code_implementation":
        allowed = {".md", ".txt", ".rst", ".adoc", ".pdf", ".docx"}
        # An explicitly submitted mockup is a design artifact, not product implementation.
        # The separate visual review remains NOT_RUN; this never grants quality PASS.
        if task["role"] == "design" and (design_status or {}).get("mockup") == "COMPLETE" and (design_status or {}).get("visual_review") == "NOT_RUN":
            allowed |= {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp"}
        if any(Path(p).suffix.lower() not in allowed for p in paths):
            raise ValueError("non-code task cannot submit source/configuration; create a code_implementation task")


def _infer_baselines(manager, state, task):
    """Only unambiguous existing frozen references; never re-read changed working docs."""
    refs, missing = {}, []
    role = task.get("role_contract", {})
    from harness.deliverables import find_version
    for kind, filename in (("planning", "requirements.md"), ("design", "design.md")):
        identifier = role.get(kind + "_version")
        if identifier:
            book = state.get("deliverables", {}).get(role.get("folder"), {})
            version = find_version(book, identifier)
            candidates = [r for r in version["artifacts"] if Path(r["path"]).name == filename and r in task["inputs"]]
        else:
            candidates = [r for r in task["inputs"] if Path(r["path"]).name == filename]
        unique = {json.dumps(r, sort_keys=True): r for r in candidates}
        if len(unique) == 1:
            refs[kind] = next(iter(unique.values()))
        elif identifier or len(unique) > 1:
            missing.append(kind + " (unambiguous frozen task input)")
    if not any(k in refs for k in ("planning", "design")):
        missing.append("planning/design baseline (typed P/D or canonical requirements.md/design.md input)")
    if not task.get("stage_contract"):
        missing.append("stage_contract (UI/API applicability) or explicit configure-development")
    else:
        from harness.project_contract import load
        data = load(manager, task)
        stage = task["stage_contract"]["stage"]
        if stage != "ui" and data["server_mode"].get("value") != "none":
            for kind, field in (("api", "api_contract"), ("policy", "policy_responsibility")):
                candidates = [r for r in task["stage_contract"]["documents"] if r["path"] == data[field].get("value") and r in task["inputs"]]
                unique = {json.dumps(r, sort_keys=True): r for r in candidates}
                if len(unique) != 1:
                    missing.append(kind + " (frozen stage document)")
                else:
                    refs[kind] = next(iter(unique.values()))
    return refs, missing


def ensure(manager, state, task, phase, run=None):
    """Fail closed at every lifecycle boundary. Past start evidence is never reconstructed."""
    if execution_scope(task) != "code_implementation":
        if any(r.get("code_state_start") or r.get("execution_scope") == "code_implementation" for r in task["executions"]):
            raise ValueError("code execution cannot be downgraded to a non-code exemption")
        document_outputs(task, [r["path"] for r in task["outputs"]])
        return
    if task.get("target_repository", str(manager.root)) != str(manager.root):
        raise ValueError("development tracking missing/invalid: target_repository does not match task manager root")
    config = task.get("development_tracking")
    if not config:
        if phase not in {"ready", "begin", "handoff_target"} or task["executions"]:
            raise ValueError("development_tracking missing: cannot reconstruct code start; create a tracked code task")
        refs, missing = _infer_baselines(manager, state, task)
        try:
            top = Path(git(manager.root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
            if top != manager.root:
                missing.append("target_repository (must be Git root)")
            git(manager.root, "rev-parse", "HEAD")
        except ValueError:
            missing.append("target_repository Git root and existing HEAD")
        if missing:
            raise ValueError("development tracking missing: " + "; ".join(missing))
        _configure(manager, state, task["task_id"], refs, automatic=True)
        config = task["development_tracking"]
    missing = [k for k in ("baselines", "code_paths", "api_required") if k not in config]
    if not config.get("baselines"):
        missing.append("nonempty baselines")
    if config.get("api_required") and not {"api", "policy"}.issubset(config.get("baselines", {})):
        missing.append("API/policy baselines")
    if missing:
        raise ValueError("development tracking missing: " + ", ".join(missing))
    if config.get("repository_root", str(manager.root)) != str(manager.root):
        raise ValueError("development tracking target repository mismatch")
    validate_baseline(manager, state, task)
    check_peers(state, task)
    if run is not None:
        if not run.get("baseline") or not run.get("code_state_start"):
            raise ValueError("development tracking missing: execution baseline/code_state_start")
        if run["code_state_start"]["repository_root"] != str(manager.root):
            raise ValueError("execution target repository mismatch")
        if run["baseline"] != baseline(task):
            raise ValueError("execution input baseline changed")
    if phase in {"begin_review", "review", "handoff_source"}:
        submitted = [r for r in task["executions"] if r["kind"] == "work" and r.get("outputs") == task["outputs"] and r.get("ended_at")]
        if not submitted:
            raise ValueError("development tracking missing: submitted work execution")
        work = submitted[-1]
        if not work.get("code_state_start") or not work.get("code_state_result") or not work.get("baseline") or not task.get("submission_code_state"):
            raise ValueError("development tracking missing: work start/submission evidence")
        if work["baseline"] != baseline(task) or work["code_state_result"] != task["submission_code_state"]:
            raise ValueError("development submission baseline/code state mismatch")
    if phase == "handoff_source":
        review = task["reviews"][-1] if task["reviews"] else {}
        key = review.get("agent_run_id")
        validity = task.get("validation_status", {}).get(key, {}).get("state")
        if validity == "RECHECK_REQUIRED":
            raise ValueError("development validation requires recheck before handoff")
        if not review.get("development_evidence") or validity != "CURRENT":
            raise ValueError("development tracking missing/current validation unavailable for handoff")
