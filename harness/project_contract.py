"""Stage-scoped checks over frozen project inputs; not a stack selector or runner."""
import json

STATUSES = {"CONFIRMED", "PROPOSED", "UNDECIDED", "NOT_APPLICABLE"}
BASE = {"implementation_targets", "ui_technology", "support_scope", "code_ownership"}
SERVER = {"server_technology", "database", "migration_plan"}
API = {"api_contract", "policy_responsibility"}
FIELDS = BASE | SERVER | API | {"server_mode", "runbook", "integration_acceptance"}
STAGES = {"ui", "client_integration", "server_implementation", "integration_verification"}
DOCUMENTS = {"api_contract", "policy_responsibility", "migration_plan", "runbook", "integration_acceptance"}


def validate(data):
    if set(data) != FIELDS:
        raise ValueError("project settings must declare all decision fields")
    for name, item in data.items():
        if not isinstance(item, dict) or item.get("status") not in STATUSES or not item.get("reason"):
            raise ValueError(f"invalid decision status/reason: {name}")
        if item["status"] in {"CONFIRMED", "PROPOSED"} and not item.get("value"):
            raise ValueError(f"decision value required: {name}")
    targets = data["implementation_targets"]
    if targets["status"] in {"CONFIRMED", "PROPOSED"} and (not isinstance(targets["value"], list) or
            any(not isinstance(x, str) or not x for x in targets["value"]) or len(set(targets["value"])) != len(targets["value"])):
        raise ValueError("implementation_targets must be a nonempty unique string list")
    if data["api_contract"]["status"] in {"CONFIRMED", "PROPOSED"} and data["api_contract"].get("mode") not in {"real", "temporary", "mock"}:
        raise ValueError("api_contract requires real/temporary/mock mode")
    mode = data["server_mode"]
    if mode["status"] in {"CONFIRMED", "PROPOSED"} and mode["value"] not in {"none", "existing", "new"}:
        raise ValueError("server_mode must be none/existing/new")
    if mode["status"] == "CONFIRMED" and mode["value"] == "none":
        if any(data[k]["status"] != "NOT_APPLICABLE" for k in SERVER | API):
            raise ValueError("server none requires server/DB/API fields NOT_APPLICABLE with reasons")
    return data


def load(manager, task):
    contract = task.get("stage_contract")
    if not contract:
        return None
    if not all(manager._valid_artifact(ref) for ref in [contract["settings"]] + contract["documents"]):
        raise ValueError("invalid project input snapshot")
    return validate(json.loads((manager.root / contract["settings"]["snapshot"]).read_text()))


def gate(manager, task):
    data = load(manager, task)
    if data is None:  # Historic/planning/interpretation tasks keep their original contract.
        return
    stage = task["stage_contract"]["stage"]
    required = set(BASE) if stage in {"ui", "integration_verification"} else {"code_ownership"}
    if stage == "client_integration":
        required.add("implementation_targets")
    if stage != "ui":
        required.add("server_mode")
        mode = data["server_mode"]
        if mode["status"] != "CONFIRMED":
            raise ValueError("stage missing confirmed decisions: server_mode")
        mode = mode["value"]
        if stage in {"client_integration", "server_implementation"} and (mode == "none" or stage == "server_implementation" and mode != "new"):
            raise ValueError("stage NOT_APPLICABLE for selected server mode")
        if mode != "none":
            required |= API
        if mode == "new" and stage in {"server_implementation", "integration_verification"}:
            required |= SERVER
        if stage == "integration_verification":
            required |= {"runbook", "integration_acceptance"}
    missing = sorted(k for k in required if data[k]["status"] != "CONFIRMED")
    if missing:
        raise ValueError("stage missing confirmed decisions: " + ", ".join(missing))
    if stage != "ui" and data["server_mode"]["value"] != "none":
        api = data["api_contract"]
        if api.get("mode") != "real":
            raise ValueError("temporary/mock API cannot authorize real integration or server implementation")


def review_gate(manager, task, results):
    """Review JSON is an attestation linked to exact outputs, not automatic E2E execution."""
    from harness.acceptance_contract import review_gate as acceptance_review
    acceptance_review(manager, task, results)
    if task.get("stage_contract", {}).get("stage") != "integration_verification":
        return
    gate(manager, task)
    data = load(manager, task)
    targets = data["implementation_targets"]["value"]
    expected = {a["path"]: a["sha256"] for a in task["outputs"]}
    required = {c["id"] for c in task["criteria"] if c["required"]}
    for item in results:
        if item["result"] != "PASS" or item["criterion_id"] not in required:
            continue
        report = json.loads((manager.root / item["evidence"]["snapshot"]).read_text())
        if report.get("mode") != "real" or report.get("result") != "PASS" or report.get("tested_outputs") != expected:
            raise ValueError("integration PASS requires real-mode evidence matching submitted outputs")
        if set(report.get("target_results", {})) != set(targets) or any(v != "PASS" for v in report["target_results"].values()):
            raise ValueError("integration PASS requires every implementation target")
        if report.get("end_to_end") != "PASS" or not report.get("environment") or not report.get("observations"):
            raise ValueError("integration PASS requires end-to-end observations and environment")
