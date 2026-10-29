"""Review returns in the existing Tasks registry; no independent workflow DB."""
import copy
import json


def is_blocking(issue):
    """Shared severity/QA policy, independent of task ownership and stage routing."""
    finding=issue.get('qa_finding') or {}
    return (issue.get('status')!='RESOLVED'
            and issue.get('severity') in {'BLOCKER','MAJOR'}
            and not (finding.get('kind')=='improvement' or finding.get('blocking') is False))


def blocking(state, task):
    folder = task.get("role_contract", task.get("delivery", {})).get("folder")
    return [i for i in state.get("issues", []) if i["feature_id"] == task["feature_id"]
            and (i.get("assigned_task_id", i["task_id"]) == task["task_id"] or (folder and i.get("folder") == folder))
            and (task["role"] != "planning" or i["owner"] == "planning") and is_blocking(i)]


def record(manager, task_id, kind, screen, ui_state, observed, expected, severity, recheck, evidence, synthetic=False, impacts=None):
    def operation(state):
        task = state["tasks"][task_id]
        if kind not in {"design", "requirements", "policy"} or severity not in {"BLOCKER", "MAJOR", "MINOR"}:
            raise ValueError("invalid issue kind/severity")
        if not all((screen, ui_state, observed, expected, recheck)):
            raise ValueError("issue needs screen/state, observation, expectation and recheck criteria")
        issues = state.setdefault("issues", [])
        issue = {"id": f"ISSUE-{len(issues)+1:03d}", "feature_id": task["feature_id"], "task_id": task_id,
            "folder": task.get("role_contract", task.get("delivery", {})).get("folder"),
            "owner": "design" if kind == "design" else "planning", "kind": kind, "screen": screen,
            "ui_state": ui_state, "observed": observed, "expected": expected, "severity": severity,
            "recheck": recheck, "evidence": manager.artifact(evidence), "synthetic": bool(synthetic),
            "impacts": impacts or [], "version": copy.deepcopy(task.get("delivery")), "status": "OPEN", "history": []}
        issues.append(issue)
        manager._event(state, "issue_returned", task, observed=issue)
        return copy.deepcopy(issue)
    return manager._mutate("issue", operation, task_id)


def route(manager, issue_id, target_id):
    def operation(state):
        issue = next(i for i in state["issues"] if i["id"] == issue_id)
        task = state["tasks"][target_id]
        if task["feature_id"] != issue["feature_id"] or task["role"] != issue["owner"] or task["state"] not in {"TODO", "BLOCKED"}:
            raise ValueError("return target must be the responsible role in TODO/BLOCKED")
        active = [r for r in task["executions"] if r["ended_at"] is None]
        if active and not (len(active) == 1 and active[0]["kind"] == "work" and manager._valid_artifact(active[0].get("checkpoint", {}))):
            raise ValueError("active work must first checkpoint before review feedback can be routed")
        task.setdefault("returned_issues", []).append(issue_id)
        issue["assigned_task_id"] = target_id
        # Retry consumes the same existing attempt budget. Carry the rejected output bytes forward.
        for ref in task["outputs"] + [issue["evidence"]]:
            if not active:
                task["inputs"] = [r for r in task["inputs"] if r["path"] != ref["path"]] + [copy.deepcopy(ref)]
        if active:
            active[0].setdefault("review_feedback", []).append(copy.deepcopy(issue))
        issue["history"].append({"event": "routed", "target_id": target_id})
        manager._event(state, "issue_routed", task, observed={"issue_id": issue_id, "owner": issue["owner"]})
    return manager._mutate("route_issue", operation, target_id)


def resolve(manager, task_id, agent_run_id, issue_id, evidence):
    def operation(state):
        task = state["tasks"][task_id]
        manager._active(task, agent_run_id, "review")
        issue = next(i for i in state["issues"] if i["id"] == issue_id)
        if task["state"] != "IN_REVIEW" or issue.get("assigned_task_id") != task_id or task["role"] != issue["owner"]:
            raise ValueError("resolution requires responsible task's active review")
        ref = manager.artifact(evidence)
        report = json.loads((manager.root / ref["snapshot"]).read_text())
        if report.get("result") != "PASS" or report.get("tested_outputs") != {a["path"]: a["sha256"] for a in task["outputs"]}:
            raise ValueError("resolution must test exact current outputs")
        if issue_id not in report.get("resolved_issues", []) or not report.get("observations"):
            raise ValueError("resolution needs issue-specific observations")
        captures = [manager.artifact(p) for p in report.get("screenshots", [])]
        if issue["kind"] == "design" and not captures:
            raise ValueError("design resolution needs actual rerender capture")
        issue.update(status="RESOLVED", resolution={"review_run_id": agent_run_id, "version": copy.deepcopy(task.get("delivery")), "evidence": ref, "captures": captures})
        issue["history"].append({"event": "resolved", "version": copy.deepcopy(task.get("delivery"))})
        manager._event(state, "issue_resolved", task, agent_run_id, observed=issue["resolution"])
    return manager._mutate("resolve_issue", operation, task_id)
