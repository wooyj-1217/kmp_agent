"""Pinned Git installer. Python stdlib + Git/rtk; no Codex/model invocation."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
MANIFEST = ".kmp-agent/installation.json"
JOURNAL = ".harness/install-transaction.json"
LAUNCHER = '''"""Stable project-owned entry point for the pinned tool."""
import base64
import json
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
journal = root / ".harness/install-transaction.json"
if sys.argv[1:2] in (["recover"], ["status"]) and journal.exists():
    previous = json.loads(journal.read_text())["snapshot"].get(".kmp-agent/installation.json")
    manifest = json.loads(base64.b64decode(previous["bytes"])) if previous else json.loads((root / ".kmp-agent/installation.json").read_text())
else:
    manifest = json.loads((root / ".kmp-agent/installation.json").read_text())
code = (root / manifest["code_path"]).resolve()
if manifest["mode"] == "installed" and not code.is_relative_to(root / ".kmp-agent/releases"):
    raise SystemExit("Invalid installation path; restore installation.json")
raise SystemExit(subprocess.call([sys.executable, str(code / "harness/cli.py"),
                                 "--target", str(root), *sys.argv[1:]], cwd=root))
'''


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args, cwd=None):
    try:
        result = subprocess.run(["rtk", "proxy", "git", *map(str, args)], cwd=cwd,
                                text=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise ValueError("Git operation timed out; check source and credentials, then retry") from None
    if result.returncode:
        raise ValueError("Git operation failed (" + args[0] + "); check source, explicit tag/commit and credentials via Git")
    return result.stdout.strip()


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else (0o600 if path.name == "install-transaction.json" else 0o644)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(path, value):
    atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def reference(target, manifest):
    relative = manifest.get("code_path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Installation code_path must be relative to its project")
    code = (target / relative).resolve()
    if manifest.get("mode") == "installed":
        expected = target / ".kmp-agent/releases" / manifest["commit"]
        if code != expected.resolve() or not code.is_relative_to((target / ".kmp-agent/releases").resolve()):
            raise ValueError("Installed code reference does not match the pinned release")
    elif manifest.get("mode") != "development":
        raise ValueError("Unknown installation mode")
    return code


def validate(code, commit=None):
    required = ["VERSION", "bootstrap.py", "AGENTS.md", "harness/cli.py", "harness/projects.py",
                "harness/codex_sync.py", "harness/logging.py", "harness/version.py", "harness/context.py"]
    for relative in required:
        path = code / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(code):
            raise ValueError("Release is missing a supported tool file: " + relative)
    version = (code / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError("Invalid VERSION")
    for path in [code / "bootstrap.py", *(code / "harness").glob("*.py")]:
        compile(path.read_text(), str(path), "exec")
    if commit and (git("rev-parse", "HEAD", cwd=code) != commit or git("status", "--porcelain", cwd=code)):
        raise ValueError("Installed release differs from its pinned Git commit")
    return version


def acquire(target):
    if Path(git("rev-parse", "--show-toplevel", cwd=target)).resolve() != target:
        raise ValueError("Target must be a Git repository root")
    for relative in (".kmp-agent", ".kmp-agent/releases", ".harness", ".codex", ".agents/skills"):
        path = target / relative
        if path.is_symlink() or not path.resolve().is_relative_to(target):
            raise ValueError("Installation directory conflicts with a symlink")
    directory = target / ".harness"
    directory.mkdir(exist_ok=True)
    directory.chmod(0o700)
    lock = (directory / "install.lock").open("a+")
    os.fchmod(lock.fileno(), 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def capture(target, skills):
    paths = [MANIFEST, ".kmp-agent/agent.py", ".kmp-agent/project.json", "AGENTS.md", ".gitignore",
             ".codex/hooks.json", ".harness/integration.json", ".harness/integration-status.json"]
    paths += [".agents/skills/" + name for name in skills]
    result = {}
    for relative in paths:
        path = target / relative
        if not path.parent.resolve().is_relative_to(target):
            raise ValueError("Managed parent path escapes the target")
        if path.is_symlink():
            if not relative.startswith(".agents/skills/"):
                raise ValueError("Managed project file is a symlink")
            result[relative] = {"link": os.readlink(path)}
        elif path.exists():
            if not path.is_file():
                raise ValueError("Managed path is a directory; preserve and resolve conflict")
            result[relative] = {"bytes": base64.b64encode(path.read_bytes()).decode(), "mode": path.stat().st_mode & 0o777}
        else:
            result[relative] = None
    return result


def signature(path):
    if path.is_symlink():
        return {"link": os.readlink(path)}
    if path.exists():
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return None


def restore(target, snapshot, expected=None):
    allowed = {MANIFEST, ".kmp-agent/agent.py", ".kmp-agent/project.json", "AGENTS.md", ".gitignore",
               ".codex/hooks.json", ".harness/integration.json", ".harness/integration-status.json"}
    conflicts = []
    for relative, value in snapshot.items():
        if relative not in allowed and not (relative.startswith(".agents/skills/") and len(Path(relative).parts) == 3):
            raise ValueError("Invalid recovery path")
        path = target / relative
        if not path.parent.resolve().is_relative_to(target):
            raise ValueError("Recovery path escapes target")
        if expected and relative in expected and signature(path) not in expected[relative]:
            conflicts.append(relative)
            continue
        if value is None:
            if path.is_file() or path.is_symlink():
                path.unlink()
        elif "link" in value:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                raise ValueError("Recovery preserves a conflicting product path")
            path.symlink_to(value["link"], target_is_directory=True)
        else:
            if path.is_symlink():
                path.unlink()
            atomic(path, base64.b64decode(value["bytes"]))
            path.chmod(value["mode"])
    if conflicts:
        raise ValueError("Recovery preserved concurrently edited files; review " + ", ".join(conflicts))


def recover(target):
    journal = read(target / JOURNAL)
    if journal:
        restore(target, journal["snapshot"], journal.get("expected"))
        (target / JOURNAL).unlink()
    context = load(ROOT / "harness/context.py", "recovery_project_context").identify(target)
    return {**context, "recovered": bool(journal), "installation": read(target / MANIFEST)}


def init(target, code):
    config = target / ".kmp-agent/project.json"
    context = load(code / "harness/context.py", "installed_project_context")
    project = context.prepare(target)
    if read(config) != project:
        save(config, project)
    manager = load(code / "harness/projects.py", "installed_project_manager")
    result = manager.inspect({"path": str(target), "skills": project.get("skills", [])}, apply=True)
    if result["connection"] != "PASS":
        raise ValueError("Init failed: " + result.get("cause", result["state"]))
    return result


def fetch(target, source, ref):
    if not source or not ref:
        raise ValueError("Explicit source and tag or full commit SHA required")
    parsed = urlsplit(source)
    if parsed.password or (parsed.scheme in {"http", "https"} and parsed.username) or parsed.query or parsed.fragment:
        raise ValueError("Use Git credentials, not secrets embedded in the source URL")
    if re.fullmatch(r"[0-9a-fA-F]{40}", ref):
        requested = ref
    else:
        tag = ref.removeprefix("refs/tags/")
        if tag.startswith("-") or git("check-ref-format", "refs/tags/" + tag) != "":
            raise ValueError("Expected an explicit tag or full commit SHA")
        requested = "refs/tags/" + tag
    releases = target / ".kmp-agent/releases"
    releases.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases))
    try:
        git("init", "--quiet", staging)
        git("-C", staging, "fetch", "--quiet", "--depth=1", "--", source, requested)
        git("-C", staging, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        commit = git("rev-parse", "HEAD", cwd=staging)
        if re.fullmatch(r"[0-9a-fA-F]{40}", ref) and commit.lower() != ref.lower():
            raise ValueError("Fetched commit does not match requested SHA")
        version = validate(staging, commit)
        dest = releases / commit
        if dest.exists():
            validate(dest, commit)
        else:
            staging.replace(dest)
        return dest, commit, version
    finally:
        if staging.exists():
            shutil.rmtree(staging)  # Only our private incomplete checkout, never a release/project log.


def install(target, source=None, ref=None, development=None, update=False):
    target = Path(target).resolve()
    with acquire(target):
        recover(target)
        previous = read(target / MANIFEST)
        if update and not previous:
            raise ValueError("No installation; use install first")
        if previous and not update:
            same = ((development and previous["mode"] == "development" and
                     (target / previous["code_path"]).resolve() == Path(development).resolve()) or
                    (not development and source == previous["source"] and ref == previous["requested_ref"]))
            if not same:
                raise ValueError("Already installed; choose an explicit update")
            code = reference(target, previous)
            if previous["mode"] == "installed" and not code.exists():
                code, commit, version = fetch(target, previous["source"], previous["commit"])
                if commit != previous["commit"] or version != previous["version"]:
                    raise ValueError("Restored checkout does not match installation metadata")
            validate(code, previous["commit"] if previous["mode"] == "installed" else None)
            context = load(code / "harness/context.py", "repeated_install_context")
            return configure(target, code, previous, context.prepare(target))
        if development:
            code = Path(development).resolve()
            version = validate(code)
            commit = git("rev-parse", "HEAD", cwd=code)
            source, ref, mode = str(code), "WORKTREE", "development"
        else:
            source = source or (previous["source"] if previous else None)
            code, commit, version = fetch(target, source, ref)
            mode = "installed"
        context = load(code / "harness/context.py", "candidate_project_context")
        config = context.prepare(target)
        manifest = {"schema_version": 1, "project_id": config["project_id"], "mode": mode, "source": source, "requested_ref": ref,
                    "commit": commit, "version": version, "code_path": os.path.relpath(code, target)}
        if previous:
            manifest["previous"] = {k: previous[k] for k in ("mode", "source", "requested_ref", "commit", "version", "code_path")}
        return configure(target, code, manifest, config)


def configure(target, code, manifest, config):
    old_state = read(target / ".harness/integration.json", {})
    skills = set(config.get("skills", [])) | set(old_state.get("skills", []))
    if any(Path(n).name != n or n in {".", ".."} for n in skills):
        raise ValueError("Invalid skill name")
    snapshot = capture(target, skills)
    expected = {relative: [signature(target / relative)] for relative in snapshot if not relative.startswith(".harness/")}
    def expect(relative, value):
        expected.setdefault(relative, []).append(value)
        save(target / JOURNAL, {"snapshot": snapshot, "expected": expected})
    expect(MANIFEST, {"sha256": hashlib.sha256((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()})
    expect(".kmp-agent/agent.py", {"sha256": hashlib.sha256(LAUNCHER.encode()).hexdigest()})
    try:
        save(target / MANIFEST, manifest)
        atomic(target / ".kmp-agent/agent.py", LAUNCHER.encode())
        manager = load(code / "harness/projects.py", "candidate_project_plan")
        desired, links, _ = manager.plan(target, config.get("skills", []))
        for path, text in desired.items():
            expect(str(path.relative_to(target)), {"sha256": hashlib.sha256(text.encode()).hexdigest()})
        for dest, source_path in links:
            expect(str(dest.relative_to(target)), {"link": os.path.relpath(source_path, dest.parent)} if source_path else None)
        expect(".kmp-agent/project.json", {"sha256": hashlib.sha256((json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()})
        save(target / ".kmp-agent/project.json", config)
        result = init(target, code)
    except Exception:
        restore(target, snapshot, expected)
        (target / JOURNAL).unlink()
        raise
    (target / JOURNAL).unlink()
    return {"project_id": manifest["project_id"], "verification_scope": "target_project",
            "installation": manifest, "connection": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "update", "recover"])
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--source")
    parser.add_argument("--ref")
    parser.add_argument("--dev-source", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "recover":
            with acquire(args.target.resolve()):
                result = recover(args.target.resolve())
        else:
            if args.action == "update" and not args.ref and not args.dev_source:
                raise ValueError("Update requires an explicit --ref")
            result = install(args.target, args.source, args.ref, args.dev_source, args.action == "update")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0  # Installation/configuration success; runtime PASS is separate.
    except (OSError, ValueError, SyntaxError, KeyError) as error:
        context = load(ROOT / "harness/context.py", "failed_install_context").identify(args.target)
        print(json.dumps({**context, "result": "FAIL", "error_type": type(error).__name__,
                          "cause": str(error) if isinstance(error, ValueError) else "Installation/configuration operation failed",
                          "recovery": "Previous release is retained. Fix source/ref/path/conflict and retry; use recover after an interrupted transaction."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
