"""Narrow self-update contract for an already trusted, pinned installation.

Only the existing source and an explicit tag/full commit are used. This is
installation management, independent of product readiness or completion.
"""
import json
from pathlib import Path
import re

import bootstrap

ROOT = Path(__file__).resolve().parents[1]
CONTROL_DIRECTORIES = ('.kmp-agent', '.kmp-agent/releases', '.harness', '.codex', '.agents', '.agents/skills')
CONTROL_FILES = (bootstrap.MANIFEST, '.kmp-agent/agent.py', '.kmp-agent/project.json',
                 '.harness/project.json', bootstrap.JOURNAL, '.harness/integration.json',
                 '.harness/integration-status.json', '.harness/install.lock', '.harness/integration.lock',
                 '.codex/hooks.json', 'AGENTS.md', '.gitignore')
LOCK_FILES = {'.harness/install.lock', '.harness/integration.lock'}


def control_paths(root):
    """Reject installer aliases/special files before any open, chmod or mkdir."""
    for relative in CONTROL_DIRECTORIES:
        path = root/relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.exists() and not path.is_dir():
            raise ValueError('managed update control directory must not be a symlink or special file: '+relative)
    for relative in CONTROL_FILES:
        path = root/relative
        if path.is_symlink() or path.exists() and not path.is_file():
            raise ValueError('managed update control path must be a regular file: '+relative)
        if relative in LOCK_FILES and path.exists() and path.stat().st_nlink != 1:
            raise ValueError('managed update control lock must not have aliases: '+relative)


def read_manifest(root):
    root = Path(root).resolve()
    path = root / bootstrap.MANIFEST
    parent = root/'.kmp-agent'
    if parent.is_symlink() or not parent.is_dir() or path.is_symlink() or not path.is_file():
        raise ValueError('managed update requires a regular installation manifest')
    try:
        with path.open('rb') as source:
            payload = source.read(64_001)
        if len(payload) > 64_000:
            raise ValueError('managed update installation manifest exceeds size limit')
        value = json.loads(payload)
    except RecursionError as error:
        raise ValueError('managed update installation manifest is too deeply nested') from error
    if not isinstance(value, dict):
        raise ValueError('managed update requires an installation manifest object')
    return value


def authorize(root, arguments, *, runtime=ROOT):
    """Validate the canonical project entrypoint update before any installer write."""
    root = Path(root).resolve()
    if (not isinstance(arguments, list) or len(arguments) != 3
            or arguments[:2] != ['update', '--ref']
            or not isinstance(arguments[2], str) or not arguments[2]):
        raise ValueError('managed update supports only update --ref <explicit tag or full commit>; '
                         'source, target and other options require the user terminal bootstrap')
    control_paths(root)
    ref = arguments[2]
    if ref.startswith('-') or '\x00' in ref:
        raise ValueError('managed update requires an explicit tag or full commit')
    if not re.fullmatch(r'[0-9a-fA-F]{40}', ref):
        tag = ref.removeprefix('refs/tags/')
        # Match the installer's tag interpretation; never interpret a branch.
        if not tag or tag.startswith('-'):
            raise ValueError('managed update requires an explicit tag or full commit')
        bootstrap.git('check-ref-format', 'refs/tags/' + tag)
    if (root / bootstrap.JOURNAL).exists():
        raise ValueError('managed update requires recovery first; use the user terminal bootstrap recover')
    manifest = read_manifest(root)
    if manifest.get('mode') != 'installed':
        raise ValueError('managed update requires an installed release, not development mode')
    commit = manifest.get('commit')
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('managed update requires the pinned full installation commit')
    source = manifest.get('source')
    if not isinstance(source, str) or not source.strip() or '\x00' in source:
        raise ValueError('managed update requires the existing installation source')
    pinned = root / '.kmp-agent/releases' / commit
    if manifest.get('code_path') != str(pinned.relative_to(root)):
        raise ValueError('managed update requires the canonical pinned installation path')
    code = bootstrap.reference(root, manifest)
    launcher = root / '.kmp-agent/agent.py'
    for path in (root/'.kmp-agent', root/'.kmp-agent/releases', pinned, pinned/'harness', launcher):
        if path.is_symlink():
            raise ValueError('managed update installation paths cannot be symlinks')
    if not launcher.is_file() or launcher.read_bytes() != bootstrap.LAUNCHER.encode():
        raise ValueError('managed update requires the unchanged official project launcher')
    if code != Path(runtime).resolve():
        raise ValueError('managed update must run the currently selected installed runtime')
    try:
        version = bootstrap.validate(code, commit)
    except (SyntaxError, RecursionError) as error:
        raise ValueError('managed update runtime validation failed; use a clean pinned release') from error
    if version != manifest.get('version'):
        raise ValueError('managed update version differs from its installation manifest')
    return {'source': source, 'ref': ref}


def execute_cli(root, argv, *, runtime=ROOT):
    """The launcher supplies one canonical target before forwarding user argv."""
    root = Path(root).resolve()
    if not isinstance(argv, list) or argv[:3] != ['--target', str(root), 'update']:
        raise ValueError('managed update requires the official project entrypoint arguments')
    selected = authorize(root, argv[2:], runtime=runtime)
    try:
        return bootstrap.install(root, selected['source'], selected['ref'], update=True)
    except (SyntaxError, RecursionError) as error:
        raise ValueError('managed update installation failed; inspect recovery state in the user terminal') from error
