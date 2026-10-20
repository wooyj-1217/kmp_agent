"""P/D/CR identifiers in the existing task registry; no second status database."""
import copy
import json
from pathlib import Path


def folder_key(manager, folder):
    path = (manager.root / folder).resolve()
    if path == manager.root or not path.is_relative_to(manager.root) or ".harness" in path.relative_to(manager.root).parts:
        raise ValueError("feature folder must be a dedicated repository subdirectory")
    return str(path.relative_to(manager.root))


def registry(state, folder):
    return state.setdefault("deliverables", {}).setdefault(folder, {"versions": [], "changes": []})


def find_version(book, version):
    matches = [v for v in book["versions"] if v["id"] == version]
    if len(matches) != 1:
        raise ValueError("unknown deliverable version")
    return matches[0]


def archive(manager, state, task, refs, delivery):
    folder = folder_key(manager, delivery["folder"])
    role = task["role"]
    if role not in {"planning", "design"}:
        raise ValueError("only planning and design have P/D versions")
    base = Path(folder)
    allowed = lambda p: p == base / ("requirements.md" if role == "planning" else "design.md") or (role == "design" and p.is_relative_to(base / "prototype"))
    if not all(allowed(Path(a["path"])) for a in refs):
        raise ValueError("role cannot publish another role's files")
    expected = str(base / ("requirements.md" if role == "planning" else "design.md"))
    if expected not in [a["path"] for a in refs]:
        raise ValueError("canonical role document missing")
    if role == "design" and not any(Path(a["path"]).is_relative_to(base / "prototype") and a["path"].endswith(".html") for a in refs):
        raise ValueError("design submission requires actual prototype")
    book = registry(state, folder)
    if book.get("feature_id", task["feature_id"]) != task["feature_id"]:
        raise ValueError("feature folder already belongs to another feature")
    book["feature_id"] = task["feature_id"]
    planning = delivery.get("planning_version")
    if role == "design":
        source = find_version(book, planning)
        if source["role"] != "planning" or source["status"] != "APPROVED":
            raise ValueError("design must reference an approved planning version")
        source_hashes = {(a["snapshot"], a["snapshot_sha256"]) for a in source["artifacts"]}
        if not source_hashes.issubset({(a["snapshot"], a["snapshot_sha256"]) for a in task["inputs"]}):
            raise ValueError("planning baseline must be handed off as frozen task inputs")
    change = delivery.get("change_id")
    if change and change not in [c["id"] for c in book["changes"]]:
        raise ValueError("unknown change request")
    signature = json.dumps([planning, sorted((a["path"], a["sha256"]) for a in refs)], ensure_ascii=False)
    previous = [v for v in book["versions"] if v["role"] == role]
    if previous and previous[-1]["signature"] == signature:
        return {"folder": folder, "version": previous[-1]["id"], "planning_version": planning, "change_id": change}
    prefix = "P" if role == "planning" else "D"
    identifier = f"{prefix}-{1 + max([int(v['id'][2:]) for v in book['versions'] if v['role'] == role] or [0]):03d}"
    # An overlay points to old immutable review records; neither old evidence nor artifacts are rewritten.
    validity = book.setdefault("validation_status", {})
    affected = [v for v in book["versions"] if v["role"] == role or (role == "planning" and v["role"] == "design")]
    for old in affected:
        validity[old["id"]] = {"state": "RECHECK_REQUIRED", "trigger_version": identifier,
            "change_id": change, "impacts": next((c["impacts"] for c in book["changes"] if c["id"] == change), "explicit new submission")}
    validity[identifier] = {"state": "NOT_RUN", "change_id": change}
    book["versions"].append({"id": identifier, "role": role, "task_id": task["task_id"],
        "signature": signature, "planning_version": planning, "change_id": change,
        "artifacts": copy.deepcopy(refs), "status": "IN_REVIEW", "review_history": [], "milestones": ["REVIEW_REQUESTED"]})
    return {"folder": folder, "version": identifier, "planning_version": planning, "change_id": change}


def reviewed(state, task, passed):
    delivery = task["delivery"]
    book = registry(state, delivery["folder"])
    version = find_version(book, delivery["version"])
    version["review_history"].append({"task_id": task["task_id"], "result": "PASS" if passed else "BLOCKED"})
    # A failed identical resubmission must not erase the last approval.
    if passed:
        book.setdefault("validation_status", {})[version["id"]] = {"state": "CURRENT", "task_id": task["task_id"]}
        for other in book["versions"]:
            if other["role"] == version["role"] and other["status"] == "APPROVED" and other is not version:
                other["status"] = "SUPERSEDED"
        version["status"] = "APPROVED"
        if "APPROVED" not in version["milestones"]:
            version["milestones"].append("APPROVED")
    elif version["status"] != "APPROVED":
        version["status"] = "BLOCKED"
    if delivery.get("change_id"):
        change = next(c for c in book["changes"] if c["id"] == delivery["change_id"])
        change.setdefault("after", {})[version["role"]] = version["id"]
        change.setdefault("validation", []).append({"task_id": task["task_id"], "version": version["id"], "result": "PASS" if passed else "BLOCKED"})


def change(manager, folder, request, reason, before, impacts, evidence,
           intervention_ids=None, before_baselines=None, after_baselines=None,
           compatibility=None, compatibility_basis=None, service_version=None):
    """An explicit request, not automatic detection or approval of product policy."""
    folder = folder_key(manager, folder)
    def operation(state):
        if not request or not reason or set(impacts) != {"requirements", "screens", "checks", "tasks"} or not all(isinstance(v, list) for v in impacts.values()):
            raise ValueError("request, reason and explicit impact lists required")
        book = registry(state, folder)
        for version in before:
            find_version(book, version)
        identifier = f"CR-{len(book['changes']) + 1:03d}"
        record = {"id": identifier, "request": request, "reason": reason, "before": before,
                  "impacts": impacts, "evidence": manager.artifact(evidence), "after": {}, "validation": []}
        if any(v is not None for v in (before_baselines, after_baselines, intervention_ids, compatibility, compatibility_basis, service_version)):
            if not isinstance(before_baselines, dict) or not isinstance(after_baselines, dict) or not after_baselines:
                raise ValueError("development CR requires explicit before/after baseline maps")
            if compatibility not in {"COMPATIBLE", "BREAKING", "UNKNOWN", "NOT_APPLICABLE"} or not isinstance(compatibility_basis, str) or not compatibility_basis.strip():
                raise ValueError("explicit compatibility judgment and basis required; hashes do not decide compatibility")
            ids = intervention_ids or []
            events = {e["event_id"]: e for e in manager.logger.read()}
            if any(i not in events or events[i]["event_type"] not in {"human_intervention", "human_intervention_pending"} for i in ids):
                raise ValueError("intervention ID must reference existing intervention evidence")
            if not impacts["tasks"] or any(t not in state["tasks"] and t != "UNKNOWN" for t in impacts["tasks"]):
                raise ValueError("development CR requires affected existing tasks")
            if not impacts["checks"]:
                raise ValueError("development CR requires affected checks or UNKNOWN")
            def freeze(refs):
                if set(refs) - {"planning", "design", "api", "policy"}:
                    raise ValueError("invalid baseline kind")
                result = {}
                for k, v in refs.items():
                    if isinstance(v, dict):
                        if not manager._valid_artifact(v) or not v.get("sha256"):
                            raise ValueError("invalid frozen baseline reference")
                        result[k] = copy.deepcopy(v)
                    else:
                        result[k] = manager.artifact(v)
                return result
            record["development_change"] = {"intervention_ids": ids,
                "before_baselines": freeze(before_baselines), "after_baselines": freeze(after_baselines),
                "compatibility": compatibility, "compatibility_basis": compatibility_basis,
                "compatibility_source": "agent_declared", "service_version": service_version}
            affected = list(state["tasks"]) if "UNKNOWN" in impacts["tasks"] else impacts["tasks"]
            if not affected:
                raise ValueError("development CR needs at least one affected task")
            for tid in affected:
                target = state["tasks"][tid]
                for review in target["reviews"]:
                    target.setdefault("validation_status", {})[review["agent_run_id"]] = {
                        "state": "RECHECK_REQUIRED", "reasons": ["CR impact requires revalidation"], "change_id": identifier}
        book["changes"].append(record)
        if record.get("development_change"):
            manager._event(state, "development_change_registered", state["tasks"][affected[0]], observed=record)
        return copy.deepcopy(record)
    return manager._mutate("change", operation)


def restore(manager, folder, version):
    """Rebuild a reviewed bundle without replacing canonical working files."""
    folder = folder_key(manager, folder)
    record = find_version(registry(manager.read(), folder), version)
    target = manager.root / ".harness/baselines" / folder / version
    for ref in record["artifacts"]:
        if not manager._valid_artifact(ref):
            raise ValueError("corrupt baseline snapshot")
        destination = target / Path(ref["path"]).relative_to(folder)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = (manager.root / ref["snapshot"]).read_bytes()
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError("restored baseline was modified; refusing overwrite")
        if not destination.exists():
            with destination.open("xb") as stream:
                stream.write(data)
    return str(target.relative_to(manager.root))
