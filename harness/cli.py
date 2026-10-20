"""Project entry points for a pinned installation or explicit local development."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("action", choices=["init", "status", "update", "recover", "hook", "planning", "design", "development", "task", "command", "collection-report", "start", "finish"])
    parser.add_argument("--source")
    parser.add_argument("--ref")
    parser.add_argument("--task-id")
    parser.add_argument("--run-id", default="UNKNOWN")
    parser.add_argument("--tracking-settings", type=Path, help="One-time project modules/commands JSON, reused after init")
    parser.add_argument("--operation", choices=["register", "configure-development", "configure-stage", "configure-collection", "integration", "ready", "begin", "submit", "review", "handoff", "checkpoint", "resume", "fail", "bind-usage", "show"])
    parser.add_argument("--data", type=Path)
    parser.add_argument("--agent-run-id", default="UNKNOWN")
    parser.add_argument("--attempt-id", default="UNKNOWN")
    parser.add_argument("--command-name")
    parser.add_argument("--command-kind", default="UNKNOWN")
    parser.add_argument("--argv-json", help="Trusted rtk argv JSON; use instead of --command-name")
    parser.add_argument("--work-type", default="PRODUCT")
    parser.add_argument("--role", default="orchestrator")
    parser.add_argument("--request")
    parser.add_argument("--result")
    parser.add_argument("--worker", help="Trusted local argv encoded as JSON")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    target = args.target.resolve()
    command_exit = None
    if args.action == "hook":
        hook = bootstrap.load(ROOT / "harness/codex_sync.py", "installed_codex_hook")
        return hook.supervise()
    try:
        if args.action == "status" and (target / bootstrap.JOURNAL).exists():
            context = bootstrap.load(ROOT / "harness/context.py", "pending_project_context").identify(target)
            print(json.dumps({**context, "result": "NOT_RUN", "state": "RECOVERY_REQUIRED",
                              "recovery": "Run the project entry point recover before validating this installation."}))
            return 1
        if args.action == "update":
            if not args.ref:
                raise ValueError("Update requires an explicit --ref; no automatic latest update")
            result = bootstrap.install(target, args.source, args.ref, update=True)
        elif args.action == "recover":
            with bootstrap.acquire(target):
                result = bootstrap.recover(target)
        elif args.action == "init":
            with bootstrap.acquire(target):
                bootstrap.recover(target)
                manifest = bootstrap.read(target / bootstrap.MANIFEST)
                if not manifest:
                    raise ValueError("Run bootstrap install first")
                code = bootstrap.reference(target, manifest)
                bootstrap.validate(code, manifest["commit"] if manifest["mode"] == "installed" else None)
                context = bootstrap.load(code / "harness/context.py", "init_project_context")
                tracking = None
                if args.tracking_settings:
                    if not (code / "harness/sequential.py").exists():
                        raise ValueError("Selected release does not support sequential collection settings; explicitly update first")
                    collection = bootstrap.load(code / "harness/sequential.py", "init_collection")
                    tracking = collection.validate_settings(json.loads(args.tracking_settings.read_text()))
                result = bootstrap.configure(target, code, manifest, context.prepare(target))
                if tracking is not None:
                    result["collection_settings"] = collection.save_settings(target, tracking)
        elif args.action in {"task", "command", "collection-report", "start", "finish"}:
            manifest = bootstrap.read(target / bootstrap.MANIFEST)
            if not manifest or bootstrap.reference(target, manifest) != ROOT:
                raise ValueError("Use the project's explicitly selected .kmp-agent/agent.py")
            bootstrap.validate(ROOT, manifest["commit"] if manifest["mode"] == "installed" else None)
            from harness.tasks import Tasks
            from harness.logging import Logger, resolve_session
            logger = Logger(target)
            if args.action in {"task", "command", "start", "finish"}:
                source = resolve_session()
                if source is not None:
                    logger.sync(source)
            if args.action == "task":
                if not args.operation or (args.operation != "show" and not args.data):
                    raise ValueError("task requires --operation and --data JSON (except show)")
                tasks = Tasks(target, args.run_id)
                result = tasks.report() if args.operation == "show" else getattr(tasks, args.operation.replace("-", "_"))(**json.loads(args.data.read_text()))
            elif args.action == "collection-report":
                from harness.sequential import report
                result = report(target)
                logger.write_metadata("sequential-coverage.json", result)
            elif args.action == "start":
                if not args.request:
                    raise ValueError("start requires --request")
                result = {"run_id": logger.start(args.work_type, args.role, args.request)}
            elif args.action == "finish":
                if not args.result:
                    raise ValueError("finish requires --result")
                result = logger.checkpoint(args.run_id, args.result, finish=True)
            else:
                command_exit = logger.command(args.run_id, json.loads(args.argv_json) if args.argv_json else None,
                    args.task_id or "UNKNOWN", args.agent_run_id, args.attempt_id, args.command_kind, args.command_name)
                result = {"returncode": command_exit}
        elif args.action in {"planning", "design", "development"}:
            manifest = bootstrap.read(target / bootstrap.MANIFEST)
            if not manifest or bootstrap.reference(target, manifest) != ROOT:
                raise ValueError("Use the project's explicitly selected .kmp-agent/agent.py")
            if not args.task_id:
                raise ValueError("role execution requires --task-id")
            bootstrap.validate(ROOT, manifest["commit"] if manifest["mode"] == "installed" else None)
            roles = bootstrap.load(ROOT / "harness/roles.py", "selected_role_entry")
            result = roles.Roles(target, args.run_id).execute(args.task_id, args.action,
                json.loads(args.worker) if args.worker else None, args.timeout)
        else:
            manifest = bootstrap.read(target / bootstrap.MANIFEST)
            if not manifest:
                raise ValueError("No installed tool")
            if bootstrap.reference(target, manifest) != ROOT:
                raise ValueError("Executing code differs from the project's selected tool; use .kmp-agent/agent.py")
            runtime = bootstrap.load(ROOT / "harness/version.py", "installed_version")
            bootstrap.validate(ROOT, manifest["commit"] if manifest["mode"] == "installed" else None)
            manager = bootstrap.load(ROOT / "harness/projects.py", "installed_status_manager")
            config = bootstrap.read(target / ".kmp-agent/project.json", {"skills": []})
            connection = manager.inspect({"path": str(target), "skills": config.get("skills", [])})
            result = {**manager.project_context(target), "installation": manifest, "runtime_identity": runtime.identity(target),
                      "reference_path": str(ROOT), "logs_path": str(target / ".harness/logs/events.jsonl"),
                      "connection": connection}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == "status":
            return 0 if result["connection"]["state"] == "VERIFIED" else 1
        return command_exit if command_exit is not None else 0
    except (OSError, ValueError, SyntaxError, KeyError) as error:
        context = bootstrap.load(ROOT / "harness/context.py", "failed_tool_context").identify(target)
        print(json.dumps({**context, "result": "FAIL", "error_type": type(error).__name__,
                          "cause": str(error) if isinstance(error, ValueError) else "Tool configuration operation failed",
                          "recovery": "Use recover for an interrupted update; inspect source/ref, preserved settings and hook diagnostics."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
