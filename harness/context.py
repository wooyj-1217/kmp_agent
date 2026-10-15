"""Stable project identity from project-owned connection settings, never guesses."""
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN = "UNKNOWN"


def object_at(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Project identity metadata must be a JSON object")
    return data


def prepare(root):
    root = Path(root).resolve()
    path = root / ".kmp-agent/project.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Project connection settings must be a JSON object")
    legacy_path = root / ".harness/project.json"
    legacy = object_at(legacy_path).get("project_id") if legacy_path.exists() else None
    existing = data.get("project_id")
    manifest_path = root / ".kmp-agent/installation.json"
    installed = object_at(manifest_path).get("project_id") if manifest_path.exists() else None
    values = [v for v in (existing, legacy, installed) if v is not None]
    if any(not isinstance(v, str) or not v.strip() or v.upper() == UNKNOWN for v in values):
        raise ValueError("Invalid existing project ID")
    if len(set(values)) > 1:
        raise ValueError("Conflicting existing project IDs; do not assign one by inference")
    identity = existing or legacy or installed or str(uuid.uuid4())
    if not isinstance(identity, str) or not identity.strip() or identity.upper() == UNKNOWN:
        raise ValueError("Invalid existing project ID")
    relative = data.get("project_path", "..")
    if not isinstance(relative, str) or Path(relative).is_absolute() or (path.parent / relative).resolve() != root:
        raise ValueError("Project connection path does not identify this target")
    skills = data.get("skills", [])
    if not isinstance(skills, list) or any(not isinstance(n, str) or Path(n).name != n or n in {".", ".."} for n in skills):
        raise ValueError("skills must be a list of shared skill names")
    return {**data, "project_id": identity, "project_path": relative, "skills": data.get("skills", [])}


def identify(root):
    root = Path(root).resolve()
    result = {"project_id": UNKNOWN, "project_id_reason": "project_connection_settings_missing",
              "verification_scope": "harness_internal" if root == ROOT else "target_project",
              "identity_source": None}
    path = root / ".kmp-agent/project.json"
    if not path.exists():
        path = root / ".harness/project.json"
    if not path.exists():
        return result
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("project_connection_settings_not_an_object")
        identity = data.get("project_id")
        if not isinstance(identity, str) or not identity.strip() or identity.upper() == UNKNOWN:
            raise ValueError("project_id_missing_or_invalid")
        relative = data.get("project_path")
        if relative is None or Path(relative).is_absolute() or (path.parent / relative).resolve() != root:
            raise ValueError("project_connection_path_mismatch")
        manifest = root / ".kmp-agent/installation.json"
        if manifest.exists():
            installed = object_at(manifest)
            if installed.get("project_id", identity) != identity:
                raise ValueError("installation_project_id_mismatch")
        legacy = root / ".harness/project.json"
        if legacy.exists() and legacy != path:
            legacy_id = object_at(legacy).get("project_id")
            if legacy_id and legacy_id != identity:
                raise ValueError("conflicting_existing_project_ids")
        result.update(project_id=identity, project_id_reason=None, identity_source=str(path.relative_to(root)))
    except (OSError, ValueError, TypeError, KeyError) as error:
        result["project_id_reason"] = str(error) if type(error) is ValueError else "invalid_project_connection_settings"
    return result
