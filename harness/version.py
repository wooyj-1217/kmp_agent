"""Runtime evidence. VERSION alone is neither a release nor capability proof."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def identity(target=None):
    def git(*args):
        result = subprocess.run(["rtk", "proxy", "git", *args], cwd=ROOT,
                                capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    version = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").exists() else "UNKNOWN"
    state = git("status", "--porcelain", "--untracked-files=normal")
    result = {"version": version, "commit": git("rev-parse", "HEAD") or "UNKNOWN",
              "dirty": state != "" if state is not None else "UNKNOWN", "mode": "development",
              "basis": "logger_or_tool_runtime; not inferred historical model execution"}
    paths = [ROOT / 'VERSION', *sorted((ROOT / 'harness').glob('*.py'))]
    result['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result['release_status'] = 'unreleased_worktree' if result['dirty'] is True else 'unconfirmed'
    if target:
        path = Path(target) / ".kmp-agent/installation.json"
        if path.exists():
            try:
                manifest = json.loads(path.read_text())
                if (Path(target) / manifest["code_path"]).resolve() == ROOT:
                    result.update(mode=manifest["mode"], requested_ref=manifest["requested_ref"],
                                  installed_commit=manifest["commit"],
                                  release_status="installed" if result["dirty"] is False else "modified_installation")
            except (OSError, ValueError, KeyError, TypeError):
                result.update(mode="UNKNOWN", installation_identity_reason="invalid_installation_metadata")
    return result
