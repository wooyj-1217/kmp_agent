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
    parser.add_argument("action", choices=["init", "status", "update", "recover", "hook"])
    parser.add_argument("--source")
    parser.add_argument("--ref")
    args = parser.parse_args()
    target = args.target.resolve()
    if args.action == "hook":
        hook = bootstrap.load(ROOT / "harness/codex_sync.py", "installed_codex_hook")
        return hook.main()
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
                result = bootstrap.configure(target, code, manifest, context.prepare(target))
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
        return 0
    except (OSError, ValueError, SyntaxError, KeyError) as error:
        context = bootstrap.load(ROOT / "harness/context.py", "failed_tool_context").identify(target)
        print(json.dumps({**context, "result": "FAIL", "error_type": type(error).__name__,
                          "cause": str(error) if isinstance(error, ValueError) else "Tool configuration operation failed",
                          "recovery": "Use recover for an interrupted update; inspect source/ref, preserved settings and hook diagnostics."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
