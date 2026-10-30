"""Append-only, native-evidence-checked narrowing of shared main turns."""
import copy
import hashlib
import json
from pathlib import Path
from harness.usage_context import digest
from harness.usage_provenance import read_jsonl


def record_id(value):
    return digest({k: v for k, v in value.items() if k != "id"})


def _valid(record):
    return record.get("id") == record_id(record)


def _native(evidence, session):
    path = Path(evidence["source_path"])
    size = evidence["source_bytes"]
    if type(size) is not int or size <= 0:
        raise ValueError("positive native source prefix size required")
    with path.open("rb") as f:
        content = f.read(size)
    if len(content) != size or not content.endswith(b"\n") or hashlib.sha256(content).hexdigest() != evidence["source_sha256"]:
        raise ValueError("native source prefix digest mismatch")
    rows = [json.loads(line) for line in content.splitlines()]
    from harness.logging import native_session_id
    if rows[0].get("type") != "session_meta" or native_session_id(rows[0].get("payload", {})) != session:
        raise ValueError("native session mismatch")
    boundary = evidence["boundary_line"]
    if type(boundary) is not int or not 1 <= boundary <= len(rows):
        raise ValueError("native user boundary required")
    row = rows[boundary - 1]; payload = row.get("payload", {})
    if row.get("type") != "response_item" or payload.get("type") != "message" or payload.get("role") != "user":
        raise ValueError("boundary must be native user message")
    responses = {}
    for line, row in enumerate(rows, 1):
        if row.get("type") != "token_usage_record":
            continue
        payload = row.get("payload", {}); response = payload.get("response_id")
        if not response or response == "UNKNOWN" or payload.get("thread_id", session) != session:
            raise ValueError("exact native response/session required")
        fact = (line, payload)
        if response in responses:
            raise ValueError("duplicate native response identity")
        responses[response] = fact
    return responses, boundary


def _validate(root, revision, entries, state, events):
    if not _valid(revision) or not isinstance(revision.get("reason"), str) or not revision["reason"].strip():
        raise ValueError("invalid registration revision audit")
    supersedes = revision["supersedes"]; replacements = revision["replacements"]
    if len(supersedes) != 2 or len(set(supersedes)) != 2 or len(replacements) != 2:
        raise ValueError("exact before/after registration pair required")
    by_id = {r.get("id"): r for r in entries}
    originals = [by_id[rid] for rid in supersedes]
    if any(not _valid(r) or r.get("independent") or r.get("response_ids") or not r.get("turn_id") for r in originals):
        raise ValueError("only original broad main turns may be narrowed")
    if len({(r["session_id"], r["turn_id"]) for r in originals}) != 1:
        raise ValueError("revision requires same native session/turn")
    session = originals[0]["session_id"]; turn = originals[0]["turn_id"]
    if revision['evidence'].get('session_id', session) != session or revision['evidence'].get('turn_id', turn) != turn:
        raise ValueError('native evidence declared identity mismatch')
    if len({r['execution_id'] for r in originals}) != 2:
        raise ValueError('distinct original owners required')
    source = Path(revision['evidence']['source_path']).resolve()
    if any(not r.get('source_path') or Path(r['source_path']).resolve() != source for r in originals):
        raise ValueError('registered native source mismatch')
    native, boundary = _native(revision["evidence"], session)
    runs = {run["agent_run_id"]: (task, run) for task in state["tasks"].values() for run in task["executions"]}
    facts_by_response = {}
    for event in events:
        if event.get('event_type') == 'model_usage' and event.get('source', {}).get('session_id') == session:
            facts_by_response.setdefault(event.get('observed', {}).get('response_id'), []).append(event)
    bound_owners = {}
    for _, run in runs.values():
        for binding in run.get('usage_bindings', []):
            if binding.get('session_id') == session:
                bound_owners.setdefault(binding.get('response_id'), set()).add(run['agent_run_id'])
    if {r["registration_id"] for r in replacements} != set(supersedes) or {r["side"] for r in replacements} != {"before", "after"}:
        raise ValueError("replacement pair identity mismatch")
    result = []; allocated = set()
    for replacement in replacements:
        original = by_id[replacement["registration_id"]]
        task, run = runs[original["execution_id"]]
        if task["task_id"] != original["task_id"] or run["run_id"] != original["run_id"]:
            raise ValueError("original execution mismatch")
        ids = replacement["response_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(r, str) or not r or r == "UNKNOWN" for r in ids) or len(set(ids)) != len(ids):
            raise ValueError("nonempty exact response IDs required")
        ids = set(ids)
        if allocated & ids:
            raise ValueError("replacement ownership overlap")
        allocated |= ids
        bound = {b["response_id"] for b in run.get("usage_bindings", []) if b["session_id"] == session and b["response_id"] in native}
        if not bound <= ids:
            raise ValueError("revision cannot remove existing bindings")
        for response in ids:
            if response not in native:
                raise ValueError("response absent from native evidence")
            line, payload = native[response]
            if payload.get("turn_id") != turn or (line < boundary) != (replacement["side"] == "before"):
                raise ValueError("response violates native user boundary/turn")
            if bound_owners.get(response, set()) - {original['execution_id']}:
                raise ValueError('revision cannot move existing ownership')
            facts = facts_by_response.get(response, [])
            from harness.dashboard_usage import native_identity_conflict
            if not facts or any(e.get("observed", {}).get("usage") != payload.get("usage") or e.get("observed", {}).get("turn_id") != turn or native_identity_conflict(e) or e.get('observed', {}).get('usage_semantics') != 'per_response_increment' for e in facts):
                raise ValueError("imported usage differs from native evidence")
        if replacement["side"] == "after":
            expected = {r for r, (line, p) in native.items() if line > boundary and p.get("turn_id") == turn}
            if ids != expected:
                raise ValueError("after-boundary native response allocation incomplete")
        elif ids != bound:
            raise ValueError("before-boundary allocation must preserve exact existing bindings")
        entry = copy.deepcopy(original); entry["response_ids"] = sorted(ids)
        entry["revision_id"] = revision["id"]; entry["supersedes_id"] = original["id"]
        entry["id"] = record_id(entry); result.append(entry)
    return result


def effective_registrations(root, state=None, events=None):
    root = Path(root); directory = root / ".harness/usage"
    entries = read_jsonl(directory / "sessions.jsonl")
    revisions = read_jsonl(directory / "registration-revisions.jsonl")
    if not revisions:
        return entries
    if state is None:
        state = json.loads((root / ".harness/tasks/tasks.yaml").read_text())
    if events is None:
        events = read_jsonl(root / ".harness/logs/events.jsonl")
    for revision in revisions:
        # Invalid audit must fail closed rather than restoring an obsolete broad owner.
        narrowed = _validate(root, revision, entries, state, events)
        entries = [r for r in entries if r.get("id") not in revision["supersedes"]] + narrowed
    return entries


def unresolved_limits(root, state, events, registrations, resolutions=None, limits=None):
    directory = Path(root) / ".harness/usage"
    if limits is None:
        limits = read_jsonl(directory / "attribution-limits.jsonl")
    if resolutions is None:
        resolutions = read_jsonl(directory / "attribution-resolutions.jsonl")
    turns = {}
    for event in events:
        if event.get('event_type') == 'model_usage':
            key = (event.get('source', {}).get('session_id'), event.get('observed', {}).get('response_id'))
            turns.setdefault(key, set()).add(event.get('observed', {}).get('turn_id'))
    bindings = {}
    for task in state['tasks'].values():
        for run in task['executions']:
            for binding in run.get('usage_bindings', []):
                key = (binding.get('session_id'), binding.get('response_id'))
                bindings.setdefault(key, set()).add(run['agent_run_id'])
    unresolved = set()
    for limit in limits:
        key = (limit.get("session_id"), limit.get("response_id"))
        owners = {r["execution_id"] for r in registrations if r.get("session_id") == key[0] and key[1] in r.get("response_ids", [])}
        matching = [r for r in resolutions if _valid(r) and r.get("limit_id") == record_id(limit)]
        bound = bindings.get(key, set())
        resolved = False
        for resolution in matching:
            revision = resolution.get("revision_id")
            revised = [r for r in registrations if r.get("revision_id") == revision and r.get("execution_id") == resolution.get("execution_id") and r.get("session_id") == key[0] and key[1] in r.get("response_ids", [])]
            all_owners = {r['execution_id'] for r in registrations
                          if r.get('session_id') == key[0] and
                          (key[1] in r['response_ids'] if r.get('response_ids') else
                           r.get('independent') or r.get('turn_id') in turns.get(key, set()))}
            resolved |= bool(revised and owners == bound == all_owners == {resolution.get("execution_id")} and limit.get("reason") == "multiple_explicit_contexts_for_one_response")
        if not resolved:
            unresolved.add(key)
    return unresolved
