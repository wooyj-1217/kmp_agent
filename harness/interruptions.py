"""Evidence-only interruption recovery. Never schedules or reruns task stages."""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("harness_logger", Path(__file__).with_name("logging.py"))
logging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logging)
UNKNOWN = logging.UNKNOWN


def parse_time(value):
    if not isinstance(value, str) or value == UNKNOWN:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.timestamp() if result.tzinfo else None
    except ValueError:
        return None


def merge(intervals):
    result = []
    for begin, end in sorted(intervals):
        if end <= begin:
            continue
        if result and begin <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([begin, end])
    return result


def duration(intervals):
    return sum(end - begin for begin, end in merge(intervals))


class Interruptions:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.logger = logging.Logger(root)

    def interruption_id(self, run_id, assertion_id):
        return logging.digest((run_id + ":" + assertion_id).encode())

    def user_report(self, run_id, assertion_id, statement, source, cause=UNKNOWN):
        run = self.logger.run(run_id)
        interruption_id = self.interruption_id(run_id, assertion_id)
        count = 0
        for event_type in ("run_interrupted", "run_resumed"):
            event = self.logger.append(event_type, run_id, run["work_type"],
                observed={"interruption_id": interruption_id, "occurred_at": UNKNOWN,
                          "cause": UNKNOWN, "continuation_of_run_id": run_id},
                user_statement={"text": statement, "claims_interrupted_and_resumed": True,
                                "cause": cause,
                                "exact_interruption_time": UNKNOWN, "exact_resumption_time": UNKNOWN},
                source={"kind": "user_statement", "evidence": source},
                source_key=f"interruption-user:{interruption_id}:{event_type}")
            count += event is not None
        return count

    def recover(self, run_id, assertion_id, session_path, interrupted_turn_id, resumed_turn_id, content=None):
        run = self.logger.run(run_id)
        path = Path(session_path).resolve()
        data = path.read_bytes() if content is None else content
        self.logger.sync(path, content=data)
        records = []
        for number, line in enumerate(data.decode("utf-8").splitlines(keepends=True), 1):
            try:
                records.append((number, json.loads(line)))
            except json.JSONDecodeError:
                if not line.endswith("\n"):
                    break
                raise
        meta = next((r["payload"] for _, r in records if r.get("type") == "session_meta"), {})
        session_id = meta.get("session_id", meta.get("id", UNKNOWN))
        errors = [(n, r) for n, r in records if r.get("type") == "event_msg"
                  and r.get("payload", {}).get("turn_id") == interrupted_turn_id
                  and (r["payload"].get("type") == "turn_aborted"
                       or (r["payload"].get("type") == "task_complete" and r["payload"].get("error")))]
        starts = [(n, r) for n, r in records if r.get("type") == "event_msg"
                  and r.get("payload", {}).get("type") == "task_started"
                  and r["payload"].get("turn_id") == resumed_turn_id]
        if len(errors) > 1 or len(starts) > 1:
            raise ValueError("ambiguous interruption or resumption; explicit source resolution required")
        if errors and starts:
            begin, end = parse_time(errors[0][1].get("timestamp")), parse_time(starts[0][1].get("timestamp"))
            if begin is not None and end is not None and end < begin:
                raise ValueError("resumption precedes interruption")
        interruption_id = self.interruption_id(run_id, assertion_id)
        imported = 0
        for event_type, evidence in (("run_interrupted", errors), ("run_resumed", starts)):
            if not evidence:
                # Missing source facts stay UNKNOWN in user_report; no invented event time.
                continue
            number, record = evidence[0]
            identity = logging.source_identity(record, session_id)
            native_key = identity.pop("key")
            payload = record["payload"]
            occurred_at = record.get("timestamp", UNKNOWN)
            cause = payload.get("error") or payload.get("reason") or UNKNOWN
            event = self.logger.append(event_type, run_id, run["work_type"],
                observed={"interruption_id": interruption_id, "occurred_at": occurred_at,
                          "time_semantics": "source_record_timestamp", "cause": cause,
                          "turn_id": payload.get("turn_id", UNKNOWN), "source_error": payload.get("error", UNKNOWN),
                          "continuation_of_run_id": run_id},
                summary={"continuation_mapping": "explicit agent mapping; distinct source turns are not automatically equated",
                         "assertion_id": assertion_id},
                source={"kind": "codex_session_recovery", "path": str(path), "line": number, **identity},
                source_key=f"interruption-source:{run_id}:{native_key}:{event_type}")
            imported += event is not None
        return {"recovered_events": imported, "interruption_id": interruption_id,
                "interruption_source_found": bool(errors), "resumption_source_found": bool(starts),
                "continuation_of_run_id": run_id, "resume_plan": self.resume_plan(run_id)}

    def resume_plan(self, run_id):
        self.logger.run(run_id)
        path = self.root / ".harness" / "tasks" / "tasks.yaml"
        state = json.loads(path.read_text()) if path.exists() else {"tasks": {}}
        registered = {e["task_id"] for e in self.logger.read()
                      if e["run_id"] == run_id and e["event_type"] == "task_registered"}
        tasks = [t for t in state["tasks"].values()
                 if t["task_id"] in registered or any(r.get("run_id") == run_id for r in t.get("executions", []))]
        return {"continuation_of_run_id": run_id, "snapshot_observed_at": logging.now(),
                "completed_tasks_to_skip": [t["task_id"] for t in tasks if t["state"] == "DONE"],
                "unfinished_tasks": [{"task_id": t["task_id"], "state": t["state"]} for t in tasks if t["state"] != "DONE"],
                "automatic_execution": False, "task_state_modified": False}

    def timing(self, run_id, scope_start=None):
        run = self.logger.run(run_id)
        events = self.logger.read()
        ends = [e for e in events if e["event_type"] == "run_finished" and e["run_id"] == run_id]
        end_text = ends[-1]["observed"].get("ended_at", UNKNOWN) if ends else UNKNOWN
        start_text = scope_start or run["observed"].get("started_at", UNKNOWN)
        start, end = parse_time(start_text), parse_time(end_text)
        if start is None or end is None or end < start:
            return {"run_id": run_id, "overall_elapsed_seconds": UNKNOWN, "reason": "missing or invalid scope bounds"}
        groups = {}
        for event in events:
            if event["run_id"] != run_id or event["event_type"] not in {"run_interrupted", "run_resumed"}:
                continue
            observed = event["observed"]
            identity = observed["interruption_id"]
            entry = groups.setdefault(identity, {"has_user_statement": False, "pause": set(), "resume": set()})
            entry["has_user_statement"] |= bool(event.get("user_statement"))
            timestamp = parse_time(observed.get("occurred_at"))
            if event["source"]["kind"] == "codex_session_recovery" and timestamp is not None:
                entry["pause" if event["event_type"] == "run_interrupted" else "resume"].add(timestamp)
        waits, unresolved = [], []
        for identity, entry in groups.items():
            if len(entry["pause"]) == len(entry["resume"]) == 1:
                begin, finish = next(iter(entry["pause"])), next(iter(entry["resume"]))
                if finish >= begin:
                    waits.append([max(start, begin), min(end, finish)])
                else:
                    unresolved.append(identity)
            else:
                unresolved.append(identity)
        path = self.root / ".harness" / "tasks" / "tasks.yaml"
        state = json.loads(path.read_text()) if path.exists() else {"tasks": {}}
        phases, phase_intervals = [], []
        for task in state["tasks"].values():
            for execution in task.get("executions", []):
                if execution.get("run_id") != run_id:
                    continue
                begin, finish = parse_time(execution.get("started_at")), parse_time(execution.get("ended_at"))
                elapsed = finish - begin if begin is not None and finish is not None and finish >= begin else UNKNOWN
                phases.append({"task_id": task["task_id"], "agent_run_id": execution["agent_run_id"],
                               "role": execution["role"], "kind": execution["kind"], "elapsed_seconds": elapsed})
                if isinstance(elapsed, (int, float)):
                    phase_intervals.append([max(start, begin), min(end, finish)])
        wait = duration(waits)
        phases_total = duration(phase_intervals)
        covered = duration(waits + phase_intervals)
        return {"run_id": run_id, "scope_start": start_text, "scope_end": end_text,
                "overall_elapsed_seconds": end - start,
                "confirmed_wait_seconds": wait if waits or not unresolved else UNKNOWN,
                "confirmed_wait_lower_bound_seconds": wait, "unresolved_interruptions": unresolved,
                "confirmed_wait_intervals": merge(waits), "phases": phases,
                "phase_elapsed_union_seconds": phases_total,
                "phase_wait_overlap_seconds": wait + phases_total - covered,
                "remaining_unclassified_seconds": max(0, end - start - covered),
                "remaining_time_is_not_proven_work_time": True, "resume_plan": self.resume_plan(run_id)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=logging.ROOT)
    sub = parser.add_subparsers(dest="action", required=True)
    user = sub.add_parser("user-report")
    user.add_argument("run_id")
    user.add_argument("--assertion-id", required=True)
    user.add_argument("--statement", required=True)
    user.add_argument("--source", required=True)
    user.add_argument("--cause", default=UNKNOWN)
    recover = sub.add_parser("recover")
    recover.add_argument("run_id")
    recover.add_argument("--assertion-id", required=True)
    recover.add_argument("--session-path", type=Path, required=True)
    recover.add_argument("--interrupted-turn-id", required=True)
    recover.add_argument("--resumed-turn-id", required=True)
    timing = sub.add_parser("timing")
    timing.add_argument("run_id")
    timing.add_argument("--scope-start")
    args = parser.parse_args()
    interruptions = Interruptions(args.root)
    if args.action == "user-report":
        result = interruptions.user_report(args.run_id, args.assertion_id, args.statement, {"reference": args.source}, args.cause)
    elif args.action == "recover":
        result = interruptions.recover(args.run_id, args.assertion_id, args.session_path, args.interrupted_turn_id, args.resumed_turn_id)
    else:
        result = interruptions.timing(args.run_id, args.scope_start)
    print(json.dumps(logging.redact(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
