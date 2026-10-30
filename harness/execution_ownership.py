"""Fail-closed ownership admission inside the existing Tasks state lock.

No separate leases, registry, or OS-wide locks: only executions in this task
ledger are protected. External processes and other project ledgers are outside
this boundary. An unfinished checkpoint continues to own its resources.
"""
from pathlib import Path


def _resources(collection):
    value = collection.get("shared_resources") if isinstance(collection, dict) else None
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() or x.strip() == "UNKNOWN" for x in value):
        return None
    return set(x.strip() for x in value)


def _held(task, run):
    # Changing a live declaration cannot silently relinquish its earlier claims.
    declarations = [run.get("collection", {}), task.get("collection", {})]
    declarations.extend(run.get("collection_declarations", []))
    resources = set()
    for declaration in declarations:
        claims = _resources(declaration)
        if claims is None:
            return None
        resources.update(claims)
    return resources


def _repository(manager, task):
    return str(Path(task.get("target_repository", str(manager.root))).resolve())


def _writer(task, review=False, run=None):
    if review or run is not None and run.get("kind") == "review":
        return False
    from harness.development_tracking import execution_scope
    return (run or {}).get("execution_scope", execution_scope(task)) == "code_implementation"


def gate(manager, state, task, review=False):
    """Call from begin/resume while Tasks._mutate owns state.lock.

    Exact shared-resource strings identify devices, ports, data paths, branches
    and workspaces. [] explicitly declares no external shared resources; missing
    or UNKNOWN declarations cannot establish safe parallel execution.
    """
    claims = _resources(task.get("collection", {}))
    own_active = [r for r in task.get("executions", []) if r.get("ended_at") is None]
    for run in own_active:
        held = _held(task, run)
        if held is None:
            claims = None
        elif claims is not None:
            claims.update(held)
    for peer in state.get("tasks", {}).values():
        if peer.get("task_id") == task.get("task_id"):
            continue
        for run in peer.get("executions", []):
            if run.get("ended_at") is not None:
                continue
            if _writer(task, review) and _writer(peer, run=run) and _repository(manager, task) == _repository(manager, peer):
                raise ValueError("execution ownership conflict: same repository workspace writer: " + peer["task_id"])
            occupied = _held(peer, run)
            if claims is None or occupied is None:
                raise ValueError("execution ownership unknown: declare shared_resources before parallel execution: " + peer["task_id"])
            collision = claims & occupied
            if collision:
                raise ValueError("execution ownership conflict: " + ", ".join(sorted(collision)) + " owned by " + peer["task_id"])
