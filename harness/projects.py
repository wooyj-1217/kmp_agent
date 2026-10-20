"""Reconcile direct harness references and verify target-side automatic collection.

Never imports sessions, submits model requests, changes trust, or copies the harness.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "<!-- kmp-agent:begin -->"
END = "<!-- kmp-agent:end -->"


def project_context(target):
    spec = importlib.util.spec_from_file_location("checked_project_context", Path(__file__).with_name("context.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.identify(target)
    result["verification_scope"] = "harness_internal" if Path(target).resolve() == ROOT else "target_project"
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(value).hexdigest()


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def git_root(path):
    result = subprocess.run(["rtk", "proxy", "git", "rev-parse", "--show-toplevel"],
                            cwd=path, text=True, capture_output=True, check=True)
    return Path(result.stdout.strip()).resolve()


def inside(root, path):
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f"managed path conflicts with a symlink: {path.name}")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.name == ".harness":
        path.parent.chmod(0o700)
    mode = path.stat().st_mode & 0o777 if path.exists() else (0o600 if path.parent.name in {".harness", ".codex"} else 0o644)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(text.encode())
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def targets(config=None):
    config = Path(config) if config else ROOT / ".harness/projects.json"
    data = read_json(config, {"targets": []})
    result = []
    for item in data["targets"]:
        item = {"path": item} if isinstance(item, str) else dict(item)
        item["path"] = str((ROOT / item["path"]).resolve())
        item.setdefault("skills", [])
        if item["path"] in [x["path"] for x in result]:
            raise ValueError("duplicate target")
        result.append(item)
    return result


def hook_spec(target=None):
    if target is not None and (Path(target) / ".kmp-agent/installation.json").exists():
        command = 'rtk proxy python3 "$(rtk proxy git rev-parse --show-toplevel)/.kmp-agent/agent.py" hook'
        return {event: {"type": "command", "command": command, "timeout": 120}
                for event in ("UserPromptSubmit", "Stop")}
    command = "rtk proxy python3 " + shlex.quote(str(ROOT / "harness/codex_sync.py"))
    source = read_json(ROOT / ".codex/hooks.json", {})
    result = {}
    for event in ("UserPromptSubmit", "Stop"):
        matches = [dict(h) for g in source.get("hooks", {}).get(event, []) for h in g.get("hooks", [])
                   if "codex_sync.py" in h.get("command", "")]
        if len(matches) > 1 or any(h.get("type") != "command" for h in matches):
            raise ValueError("ambiguous or unsupported shared collection hook")
        result[event] = matches[0] if matches else {"type": "command", "command": command, "timeout": 120}
    return result


def fingerprint(target, skills=None):
    """Version availability, not proof that every role document was read."""
    target = Path(target).resolve()
    paths = {
        "code": [ROOT / "bootstrap.py", ROOT / "VERSION"] + sorted(p for p in (ROOT / "harness").glob("*.py") if not p.name.startswith("test_")),
        "instructions": [ROOT / p for p in ("AGENTS.md", "design.md", "plan.md")] + sorted(
            p for p in (ROOT / "docs").rglob("*.md")
            if "examples" not in p.parts and p.name not in {"retrospective.md", "local-environment.md"}),
        "skills": [],
    }
    for name in skills or []:
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("skill must be a directory name")
        source = ROOT / ".agents/skills" / name
        if not (source / "SKILL.md").is_file() or not source.resolve().is_relative_to(ROOT):
            raise ValueError(f"configured shared skill unavailable: {name}")
        paths["skills"].extend(sorted(p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts))
    files = {kind: {str(p.relative_to(ROOT)): checksum(p.read_bytes()) for p in group if p.is_file()}
             for kind, group in paths.items()}
    hashes = {kind: checksum(group) for kind, group in files.items()}
    hashes["settings"] = checksum({"shared_hooks": hook_spec(target), "target_inputs": {
        str(p.relative_to(target)): checksum(p.read_bytes()) if p.exists() else None
        for p in (target / "AGENTS.md", target / ".codex/hooks.json", target / ".codex/config.toml", target / ".kmp-agent/project.json")}})
    git = subprocess.run(["rtk", "proxy", "git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True)
    return {"components": hashes, "files": files, "head": git.stdout.strip() if git.returncode == 0 else "UNKNOWN",
            "bundle_id": "draft-" + checksum(files), "harness_root": str(ROOT),
            "startup_fingerprint": checksum({k: v for k, v in hashes.items() if k != "code"})}


def plan(target, skills):
    """Only managed hook handlers, one marked AGENTS block and exact ignore entries."""
    target = Path(target).resolve()
    if git_root(target) != target or target == ROOT:
        raise ValueError("target must be a separate Git repository root")
    for p in (target / ".harness/integration.json", target / ".harness/integration-status.json",
              target / ".codex/hooks.json", target / "AGENTS.md", target / ".gitignore"):
        inside(target, p)
    previous = read_json(target / ".harness/integration.json", {})
    old_command = previous.get("command")
    spec = hook_spec(target)
    command = spec["UserPromptSubmit"]["command"]
    hook_path = target / ".codex/hooks.json"
    hooks = read_json(hook_path, {})
    tree = hooks.setdefault("hooks", {})
    for event in ("UserPromptSubmit", "Stop"):
        expected = spec[event]
        groups = tree.setdefault(event, [])
        matches = [handler for group in groups for handler in group.get("hooks", [])
                   if handler.get("command") in {expected["command"], old_command} and handler.get("command")]
        if len(matches) > 1:
            raise ValueError(f"duplicate harness hook: {event}")
        if not matches:
            if any("codex_sync.py" in handler.get("command", "") for group in groups for handler in group.get("hooks", [])):
                raise ValueError(f"unowned harness hook needs review: {event}")
            groups.append({"hooks": [expected]})
        else:
            matches[0].update(expected)
    original = hook_path.read_text() if hook_path.exists() else None
    desired = {}
    if original is None or json.loads(original) != hooks:
        desired[hook_path] = json.dumps(hooks, ensure_ascii=False, indent=2) + "\n"

    path = target / "AGENTS.md"
    text = path.read_text() if path.exists() else "# Project instructions\n"
    relative = os.path.relpath(ROOT / "AGENTS.md", target)
    block = (BEGIN + "\n" + f"공통 하네스 진입: [AGENTS.md]({relative}). 현재 역할에 필요한 지침만 읽는다.\n"
             "적용 상태: `.harness/integration-status.json`. 원문 수집은 신뢰된 훅이 수행하며 사용자에게 수동 sync를 요구하지 않는다.\n" + END)
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
            raise ValueError("invalid managed AGENTS markers")
        start, finish = text.index(BEGIN), text.index(END) + len(END)
        updated = text[:start] + block + text[finish:]
    else:
        updated = text.rstrip() + "\n\n" + block + "\n"
    if updated != text:
        desired[path] = updated

    links = []
    for name in skills:
        source = ROOT / ".agents/skills" / name
        dest = target / ".agents/skills" / name
        if not dest.parent.resolve().is_relative_to(target):
            raise ValueError("skill parent escapes target")
        if dest.is_symlink():
            if dest.resolve() != source.resolve():
                old_source = Path(previous.get("harness_root", "/nonexistent")) / ".agents/skills" / name
                if name in previous.get("skills", []) and dest.resolve() == old_source.resolve():
                    links.append((dest, source))
                else:
                    raise ValueError(f"product skill link conflict: {name}")
        elif dest.exists():
            raise ValueError(f"product skill is preserved; choose another name: {name}")
        else:
            links.append((dest, source))
    for name in set(previous.get("skills", [])) - set(skills):
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("invalid previously managed skill name")
        dest = target / ".agents/skills" / name
        old_source = Path(previous["harness_root"]) / ".agents/skills" / name
        if dest.is_symlink() and dest.resolve() == old_source.resolve():
            links.append((dest, None))  # Only retire our own link; never delete product files.
        elif dest.exists() or dest.is_symlink():
            raise ValueError(f"retired shared skill was locally replaced; preserve and review: {name}")

    ignore = target / ".gitignore"
    text = ignore.read_text() if ignore.exists() else ""
    updated = text
    installed = (target / ".kmp-agent/installation.json").exists()
    ignores = [".harness/", ".kmp-agent/releases/"] if installed else [".harness/", ".codex/hooks.json"]
    for relative in ignores + [f".agents/skills/{n}" for n in skills]:
        result = subprocess.run(["rtk", "proxy", "git", "check-ignore", "--no-index", relative],
                                cwd=target, capture_output=True)
        entry = "/" + relative
        if result.returncode != 0 and entry not in updated.splitlines():
            updated = updated.rstrip() + "\n" + entry + "\n"
    if updated != text:
        desired[ignore] = updated
    return desired, links, command


def rows(path):
    """A concurrent final incomplete line is pending, never fabricated evidence."""
    if not path.exists():
        return []
    result = []
    with path.open() as stream:
        for number, line in enumerate(stream, 1):
            try:
                result.append((number, json.loads(line)))
            except json.JSONDecodeError:
                if line.endswith("\n"):
                    raise ValueError(f"invalid complete JSONL record: {path.name}:{number}")
    return result


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def runtime(target, state, snapshot, session_id=None, message_id=None):
    log = target / ".harness/logs"
    diagnostics = rows(log / "hook-diagnostics.jsonl")
    events = rows(log / "events.jsonl")
    identity = project_context(target)
    entries = [(n, e) for n, e in diagnostics if e.get("phase") == "hook_entered"
               and (not session_id or e.get("session_id") == session_id)]
    if not entries:
        return {"result": "NOT_RUN", "state": "AWAITING_HOOK", "recovery": "Open /hooks in target; review/trust definitions, then use a fresh target session and send an ordinary request."}
    # Never fall back to an older passing session when a newer observed session fails.
    chosen_session = entries[-1][1]["session_id"]
    selected = [(n, e) for n, e in diagnostics if e.get("session_id") == chosen_session]
    selected_turn = entries[-1][1].get("turn_id")
    selected = [(n, e) for n, e in selected if e.get("turn_id") == selected_turn]
    if any(e.get("phase") == "hook_exited" and e.get("exit_code") != 0 for n, e in selected):
        return {"result": "FAIL", "state": "HOOK_FAILED", "session_id": chosen_session,
                "recovery": "Inspect target hook-diagnostics.jsonl error_type/error_detail; fix path, permissions or source, then retry an ordinary request."}
    def current_collector(entry):
        if entry.get("integration_components_basis") != "approved_manifest_cache":
            return True  # Historical diagnostics used a synchronous fingerprint.
        return (entry.get("hook_script_sha256") == checksum((ROOT / "harness/codex_sync.py").read_bytes())
                and entry.get("collector_script_sha256") == checksum((ROOT / "harness/incremental_sync.py").read_bytes()))

    current = [e for n, e in selected if e.get("phase") == "hook_entered"
               and e.get("integration_components") == snapshot["components"] and current_collector(e)]
    starts = [e for n, e in selected if e.get("phase") == "sync_started"]
    created = timestamp(starts[-1].get("session_created_at")) if starts else None
    activated = timestamp(state.get("activation_after"))
    if not current:
        previous_components = entries[-1][1].get("integration_components", {})
        if isinstance(previous_components, dict) and all(previous_components.get(k) == v for k, v in snapshot["components"].items() if k != "code"):
            return {"result": "NOT_RUN", "state": "AWAITING_REQUEST", "session_id": chosen_session,
                    "recovery": "Shared Python code changed; send the next ordinary request to exercise the new code. No settings copy or restart needed for code alone."}
    if not current or not created or not activated or created < activated:
        return {"result": "NOT_RUN", "state": "RESTART_REQUIRED", "session_id": chosen_session,
                "recovery": "Start a fresh target session after apply (old thread resume cannot prove refreshed startup inputs): rtk proxy codex --no-daemon --cd " + shlex.quote(str(target))}
    for n, end in reversed(selected):
        if end.get("phase") != "sync_finished" or end.get("hook_event_name") not in {"UserPromptSubmit", "Stop"}:
            continue
        invocation = end["invocation_id"]
        group = [e for _, e in selected if e.get("invocation_id") == invocation]
        begin = next((e for e in group if e.get("phase") == "sync_started"), {})
        exit_event = next((e for e in group if e.get("phase") == "hook_exited"), {})
        native_id = message_id or end.get("latest_collected_message_id")
        matches = [(line, e) for line, e in events if e.get("event_type") == "session_message"
                   and e.get("source", {}).get("kind") == "codex_session_import"
                   and e["source"].get("session_id") == chosen_session
                   and e.get("observed", {}).get("message_id") == native_id
                   and e["observed"].get("role") == "user"]
        expected_path = str(target / ".harness/logs/events.jsonl")
        kinds = {e.get("hook_event_name") for _, e in selected if e.get("phase") == "hook_exited" and e.get("exit_code") == 0}
        if len(matches) > 1:
            return {"result": "FAIL", "state": "VERIFICATION_FAILED", "session_id": chosen_session,
                    "cause": "duplicate source message events", "matching_events": len(matches),
                    "recovery": "Inspect deduplication/source IDs; preserve existing logs and fix the collector before retrying."}
        if begin and begin.get("events_path") != expected_path:
            return {"result": "FAIL", "state": "VERIFICATION_FAILED", "session_id": chosen_session,
                    "cause": "hook wrote to another log destination", "recovery": "Fix invoking repository routing and retry a normal request."}
        if len(matches) != 1 or exit_event.get("exit_code") != 0 or kinds != {"UserPromptSubmit", "Stop"}:
            continue
        line, event = matches[0]
        if (event.get("project_id") != identity["project_id"] or event.get("verification_scope") != "target_project"
                or any(e.get("project_id") != identity["project_id"] for e in group if e.get("phase") == "hook_entered")):
            continue
        text = "".join(c.get("text", "") for c in event["observed"].get("content", []) if isinstance(c, dict)).strip()
        lower, recorded, upper = map(timestamp, (begin.get("recorded_at"), event.get("recorded_at"), end.get("recorded_at")))
        if (not text or text.startswith(("<", "# AGENTS.md instructions")) or not lower or not recorded or not upper
                or not lower <= recorded <= upper or begin.get("events_path") != expected_path
                or not {"UserPromptSubmit", "Stop"}.issubset({e.get("hook_event_name") for e in current})):
            continue
        return {"result": "PASS", "state": "VERIFIED", "session_id": chosen_session, "message_id": native_id,
                "event_id": event["event_id"], "events_path": expected_path, "events_line": line,
                "diagnostic_line": n, "invocation_id": invocation, "matching_events": 1,
                "scope": "current harness fingerprints; actual target request imported within automatic lifecycle invocation"}
    return {"result": "NOT_RUN", "state": "AWAITING_REQUEST", "session_id": chosen_session,
            "recovery": "Finish an ordinary user request in the fresh target session; no manual sync or direct hook invocation."}


def _inspect(item, apply=False, session_id=None, message_id=None):
    target = Path(item["path"]).resolve()
    identity = project_context(target)
    try:
        protected = [target / ".codex/hooks.json", target / "AGENTS.md", target / ".gitignore"]
        before = {p: checksum(p.read_bytes()) if p.exists() else None for p in protected}
        desired, links, command = plan(target, item["skills"])
        fingerprint(target, item["skills"])  # Validate configured sources before any writes.
        changes = [str(p.relative_to(target)) for p in desired] + [str(p.relative_to(target)) for p, _ in links]
        old = read_json(target / ".harness/integration.json", {})
        if apply:
            if any((checksum(p.read_bytes()) if p.exists() else None) != version for p, version in before.items()):
                raise ValueError("concurrent project edit detected; retry without overwriting it")
            for path, text in desired.items():
                write(path, text)
            for dest, source in links:
                if source is None:
                    dest.unlink()
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.is_symlink():
                        dest.unlink()
                    dest.symlink_to(os.path.relpath(source, dest.parent), target_is_directory=True)
        snapshot = fingerprint(target, item["skills"])
        startup_changed = old.get("snapshot", {}).get("startup_fingerprint") != snapshot["startup_fingerprint"]
        state = {"harness_root": str(ROOT), "skills": item["skills"], "command": command, "snapshot": snapshot,
                 "activation_after": now() if startup_changed else old.get("activation_after"),
                 "settings_changed_at": now() if changes else old.get("settings_changed_at")}
        if apply:
            save(target / ".harness/integration.json", state)
        if changes and not apply:
            verification = {"result": "NOT_RUN", "state": "CONFIG_DRIFT", "recovery": "Run projects.py apply for this configured target; only managed fields will be reconciled."}
        elif not old and not apply:
            verification = {"result": "NOT_RUN", "state": "NOT_CONFIGURED", "recovery": "Run projects.py apply."}
        elif startup_changed and not apply:
            verification = {"result": "NOT_RUN", "state": "RESTART_REQUIRED", "recovery": "Run apply, then start a fresh target session; startup inputs changed."}
        else:
            verification = runtime(target, state, snapshot, session_id, message_id)
            if apply and startup_changed and verification["state"] == "AWAITING_HOOK":
                verification = {**verification, "state": "RESTART_REQUIRED",
                                "recovery": "Review/trust target hooks in /hooks, then start a fresh session and send an ordinary request. Installed files alone are not active verification."}
        if identity["project_id"] == "UNKNOWN":
            verification = {"result": "NOT_RUN", "state": "PROJECT_ID_UNKNOWN", "cause": identity["project_id_reason"],
                            "recovery": "Initialize project connection settings; never attribute this evidence to another project."}
        verification.update(identity)
        result = {**identity, "target": str(target), "checked_at": now(), "state": verification["state"],
                  "connection": "PASS" if apply or not changes else "NOT_RUN", "changes": changes,
                  "snapshot": snapshot, "runtime": verification,
                  "shared_skills": item["skills"] or "N/A: no shared harness skills selected",
                  "internal_tests": "NOT_RUN: independent harness test command"}
        if apply:
            save(target / ".harness/integration-status.json", result)
        return result
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        # No raw project config, tokens, prompt text or command output in the report.
        return {**identity, "target": str(target), "checked_at": now(), "state": "FAILED", "connection": "FAIL",
                "error_type": type(error).__name__, "cause": str(error) if isinstance(error, ValueError) else "Target read/write, Git or configuration operation failed",
                "recovery": "Preserved unowned settings. Check target paths/permissions and resolve reported managed-field conflicts; rerun apply, then verify a fresh ordinary request."}


def inspect(item, apply=False, session_id=None, message_id=None):
    if not apply:
        return _inspect(item, False, session_id, message_id)
    target = Path(item["path"]).resolve()
    try:
        if git_root(target) != target or target == ROOT:
            raise ValueError("target must be a separate Git repository root")
        lock_path = target / ".harness/integration.lock"
        inside(target, lock_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.parent.chmod(0o700)
        with lock_path.open("a+") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _inspect(item, True, session_id, message_id)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        return {**project_context(target), "target": str(target), "state": "FAILED", "connection": "FAIL", "error_type": type(error).__name__,
                "cause": "Target repository or integration lock unavailable",
                "recovery": "Check configured target Git root and write permissions, then retry apply."}


def reconcile(config=None, apply=False):
    results = [inspect(item, apply=apply) for item in targets(config)]
    report = {**project_context(ROOT), "checked_at": now(), "harness_root": str(ROOT), "targets": results}
    if apply:
        save(ROOT / ".harness/projects-status.json", report)
    return report


def after_hook(target, session_id):
    """Existing trusted hooks check status; never deploy or update a target."""
    target = Path(target).resolve()
    if target == ROOT:
        if (ROOT / ".harness/projects.json").exists():
            report = reconcile(apply=False)
            save(ROOT / ".harness/projects-status.json", report)
            return report
        return None
    state = read_json(target / ".harness/integration.json", {})
    if state.get("harness_root") != str(ROOT):
        return None
    result = inspect({"path": str(target), "skills": state.get("skills", [])}, session_id=session_id)
    save(target / ".harness/integration-status.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["apply", "check", "verify"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--message-id")
    args = parser.parse_args()
    if args.target:
        previous = read_json(args.target / ".harness/integration.json", {})
        report = {"targets": [inspect({"path": str(args.target), "skills": previous.get("skills", [])},
                                     apply=args.action == "apply", session_id=args.session_id, message_id=args.message_id)]}
    else:
        report = reconcile(args.config, apply=args.action == "apply")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["targets"] and all(r["state"] == "VERIFIED" for r in report["targets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
