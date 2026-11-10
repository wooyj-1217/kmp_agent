"""Authoritative implementation choices, using the existing lineage and artifacts.

Product-specific patterns check declared structure, not arbitrary code semantics.
Source labels alone do not establish authenticity; independent source QA remains.
"""
import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re

KEY = 'development_constraints'
SETTINGS = {'implementation_targets', 'ui_technology', 'database', 'server_mode', 'code_ownership'}
SKIP = {'.git', '.harness', '.kmp-agent', '.agents', '.codex', '.gradle', 'build', 'node_modules', 'dist'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _path(value, pattern=False):
    if not isinstance(value, str) or not value or value in {'.', '/'} or '\\' in value:
        raise ValueError('development constraint requires project-relative paths')
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or any(x in SKIP for x in path.parts):
        raise ValueError('unsafe development constraint path: ' + value)
    if not pattern and any(c in value for c in '*?['):
        raise ValueError('literal development constraint path required')
    return value.rstrip('/')


def validate(policy):
    required = {'settings', 'ui_sharing', 'ui_owners', 'platform_entrypoints', 'target_commands', 'source_rules'}
    if not isinstance(policy, dict) or set(policy) != required:
        raise ValueError('development constraints require settings, UI ownership, entrypoints, target commands and source rules')
    settings = policy['settings']
    if not isinstance(settings, dict) or set(settings) != SETTINGS:
        raise ValueError('development constraints require all architectural settings')
    targets = settings['implementation_targets']
    if not isinstance(targets, list) or not targets or any(not isinstance(t, str) or not t.strip() for t in targets) or len(set(targets)) != len(targets):
        raise ValueError('development constraints require unique implementation targets')
    database = settings['database']
    if database is not None and (not isinstance(database, dict) or not {'engine', 'location', 'role'} <= set(database) or not all(isinstance(database[k], str) and database[k].strip() for k in ('engine', 'location', 'role'))):
        raise ValueError('database decision requires engine, location and role (or explicit null)')
    if policy['ui_sharing'] not in {'shared', 'platform_specific', 'none'} or not isinstance(policy['ui_owners'], dict):
        raise ValueError('explicit UI sharing and ownership required')
    for path, owner in policy['ui_owners'].items():
        _path(path)
        if owner not in {'kmp', 'android', 'ios', 'web', 'server'}:
            raise ValueError('unsupported UI owner area')
        if policy['ui_sharing'] == 'shared' and owner != 'kmp':
            raise ValueError('shared UI must belong to common client area, not platform UI')
    if policy['ui_sharing'] != 'none' and not policy['ui_owners']:
        raise ValueError('UI decision requires owned UI paths')
    entries = policy['platform_entrypoints']
    if not isinstance(entries, dict) or set(entries) != set(targets):
        raise ValueError('entrypoints must cover every approved target')
    for paths in entries.values():
        if not isinstance(paths, list) or not paths:
            raise ValueError('each target requires explicit entrypoint files')
        for path in paths: _path(path)
    commands = policy['target_commands']
    if not isinstance(commands, dict) or set(commands) != set(targets):
        raise ValueError('verification commands must cover every approved target')
    for rows in commands.values():
        if not isinstance(rows, list) or not rows:
            raise ValueError('each target requires commands; unavailable is not PASS')
        for argv in rows:
            if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x.strip() for x in argv):
                raise ValueError('target commands must be explicit argument arrays')
    if not isinstance(policy['source_rules'], list) or not policy['source_rules']:
        raise ValueError('product architecture requires explicit source rules')
    for rule in policy['source_rules']:
        if not isinstance(rule, dict) or set(rule) != {'glob', 'required_patterns', 'forbidden_patterns'}:
            raise ValueError('source rule requires glob, required_patterns and forbidden_patterns')
        _path(rule['glob'], pattern=True)
        patterns = []
        for key in ('required_patterns', 'forbidden_patterns'):
            if not isinstance(rule[key], list) or any(not isinstance(p, str) or not p for p in rule[key]):
                raise ValueError('source patterns must be nonempty regex strings')
            patterns.extend(rule[key])
        if not patterns: raise ValueError('source rule cannot be empty')
        for pattern in patterns:
            try: re.compile(pattern)
            except re.error as exc: raise ValueError('invalid architecture source pattern') from exc
    return copy.deepcopy(policy)


def _authoritative(manager, archive=True, product=False):
    from harness.requirement_lineage import load as lineage_load, compare, NAME
    lineage = lineage_load(manager.root)
    if product and lineage['scope'] != 'PRODUCT':
        raise ValueError('product implementation cannot use trial development decisions')
    comparison = compare(manager.root)
    if not comparison['structurally_ready']:
        raise ValueError('development decisions need approved, complete requirement lineage')
    if product and not comparison['authorization_ready']:
        raise ValueError('product technology decisions require current native human authorization; derived labels or general plan approval are insufficient')
    rows = [r for r in lineage['requirements'] if KEY in r['expected']]
    if len(rows) != 1:
        raise ValueError('exactly one authoritative requirement must define development_constraints')
    row = rows[0]
    policy = validate(row['expected'][KEY])
    result = {'policy': policy, 'sha256': _digest(policy), 'requirement_id': row['id']}
    if archive:
        result.update(lineage=manager.artifact(NAME), sources=[manager.artifact(s['path']) for s in lineage['sources']])
    return result


def _required(task):
    from harness.development_tracking import execution_scope
    return task.get('work_type') == 'PRODUCT' and execution_scope(task) == 'code_implementation'


def _settings(manager, task, policy):
    contract = task.get('stage_contract')
    if not contract:
        raise ValueError('product implementation requires configured stage and authoritative development constraints')
    ref = contract['settings']
    if not manager._valid_artifact(ref): raise ValueError('project settings snapshot missing or corrupt')
    data = json.loads((manager.root / ref['snapshot']).read_text())
    for key, expected in policy['settings'].items():
        item = data[key]
        value = None if item['status'] == 'NOT_APPLICABLE' else item['value']
        if item['status'] not in {'CONFIRMED', 'NOT_APPLICABLE'} or value != expected:
            raise ValueError('project setting differs from authoritative development decision: ' + key)


def bind(manager, task):
    from harness.requirement_lineage import NAME
    if not (manager.root / NAME).is_file():
        if _required(task): raise ValueError('product implementation requires authoritative development constraints')
        return None
    raw = json.loads((manager.root / NAME).read_text())
    declared = any(KEY in r.get('expected', {}) for r in raw.get('requirements', []))
    if not _required(task) and not declared: return None
    frozen = _authoritative(manager, product=_required(task))
    _settings(manager, task, frozen['policy'])
    task['stage_contract'][KEY] = frozen
    for ref in [frozen['lineage']] + frozen['sources']:
        if ref not in task['inputs']: task['inputs'].append(copy.deepcopy(ref))
    return frozen


def load(manager, task):
    frozen = task.get('stage_contract', {}).get(KEY)
    if not frozen:
        if _required(task): raise ValueError('product implementation requires frozen authoritative development constraints')
        return None
    for ref in [frozen['lineage']] + frozen['sources']:
        path = manager.root / ref['path']
        if not manager._valid_artifact(ref) or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
            raise ValueError('development decision source changed, missing or corrupt')
        if ref not in task.get('inputs', []): raise ValueError('development decision source not frozen in task inputs')
    current = _authoritative(manager, archive=False, product=_required(task))
    if any(current[key] != frozen.get(key) for key in current):
        raise ValueError('authoritative development decision changed; reconfigure and re-review')
    _settings(manager, task, frozen['policy'])
    return copy.deepcopy(frozen)


gate = load
packet = load


def check_plan(manager, parent, architecture, children, integration_commands):
    frozen = load(manager, parent)
    if not frozen: return
    policy = frozen['policy']
    if architecture.get('ui_owners', {}) != policy['ui_owners']:
        raise ValueError('UI ownership plan differs from authoritative sharing decision')
    if any(argv not in integration_commands for rows in policy['target_commands'].values() for argv in rows):
        raise ValueError('integration plan omits approved target verification commands')


def _files(root):
    for folder, directories, names in os.walk(root, followlinks=False):
        directories[:] = [d for d in directories if d not in SKIP]
        for name in names:
            path = Path(folder) / name
            yield path.relative_to(root).as_posix(), path


def check_code(manager, task, root=None, complete=True):
    frozen = load(manager, task)
    if not frozen: return
    root = Path(root or manager.root).resolve()
    files = list(_files(root)); policy = frozen['policy']
    tracked = task.get('development_tracking', {}).get('code_paths', [])
    captured = None
    if complete and task.get('development_tracking'):
        from harness.development_tracking import capture
        captured = capture(manager, task)['files']
    def covered(name):
        if complete and tracked and not any(name == p or name.startswith(p + '/') for p in tracked):
            raise ValueError('architecture source outside tracked code scope: ' + name)
        if captured is not None and name not in captured:
            raise ValueError('architecture source missing from code fingerprint: ' + name)
    for rule in policy['source_rules']:
        matches = [(name, path) for name, path in files if fnmatch.fnmatchcase(name, rule['glob'])]
        if complete and rule['required_patterns'] and not matches:
            raise ValueError('required architecture source missing: ' + rule['glob'])
        for name, path in matches:
            covered(name)
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('unsafe architecture source: ' + name)
            try: text = path.read_text()
            except (OSError, UnicodeError) as exc: raise ValueError('architecture source unreadable: ' + name) from exc
            if any(re.search(pattern, text) for pattern in rule['forbidden_patterns']):
                raise ValueError('forbidden architecture pattern: ' + name)
            if complete and any(not re.search(pattern, text) for pattern in rule['required_patterns']):
                raise ValueError('required architecture pattern missing: ' + name)
    if complete:
        for paths in policy['platform_entrypoints'].values():
            for name in paths:
                covered(name)
                path = root / name
                if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
                    raise ValueError('approved platform entrypoint missing: ' + name)
        for name in policy['ui_owners']:
            for file_name, _ in files:
                if file_name == name or file_name.startswith(name + '/'):
                    covered(file_name)
            if not any(p == name or p.startswith(name + '/') for p, _ in files):
                raise ValueError('approved shared/platform UI source missing: ' + name)


def review_gate(manager, task, evidence):
    frozen = load(manager, task)
    if not frozen: return
    complete = not task.get('parent_task_id')
    check_code(manager, task, complete=complete)
    if not complete: return  # Area checks never certify the whole product.
    if evidence.get('constraints_sha256') != frozen['sha256']:
        raise ValueError('review must bind authoritative development constraints digest')
    rows = evidence.get('constraint_target_results', [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or len(rows) != len(frozen['policy']['target_commands']):
        raise ValueError('exact approved target execution results required')
    works = [run for run in task.get('executions', []) if run.get('kind') == 'work' and run.get('ended_at') and run.get('outputs') == task.get('outputs')]
    execution_id = evidence.get('constraint_review_run_id')
    if not works or execution_id != works[-1]['agent_run_id']:
        raise ValueError('target command evidence must bind the submitted work execution')
    events = manager.logger.read()
    from harness.development_tracking import capture
    code_state = capture(manager, task)['state_sha256']
    for target, commands in frozen['policy']['target_commands'].items():
        match = next((row for row in rows if row.get('target') == target), None)
        if not match or match.get('result') != 'PASS':
            raise ValueError('all approved target results required; unavailable is NOT_RUN/BLOCKED')
        for argv in commands:
            proof = next((r for r in match.get('commands', []) if r.get('argv') == argv and r.get('exit_code') == 0), None)
            if not proof:
                raise ValueError('target command execution evidence missing or mismatched')
            matching = [event for event in events if event.get('task_id') == task['task_id'] and event.get('agent_run_id') == execution_id and event.get('observed', {}).get('call_id') == proof.get('call_id')]
            starts = [e for e in matching if e['event_type'] == 'command_started']
            ends = [e for e in matching if e['event_type'] == 'command_finished']
            if len(starts) != 1 or len(ends) != 1 or starts[0]['sequence'] >= ends[0]['sequence'] or starts[0]['run_id'] != works[-1]['run_id'] or ends[0]['run_id'] != works[-1]['run_id']:
                raise ValueError('target command needs exact native start/finish events')
            if any(event['observed'].get('cwd') != '.' or event['observed'].get('code_state_sha256') != code_state
                   for event in (starts[0], ends[0])):
                raise ValueError('target command must verify submitted code in project root')
            expected_hash = hashlib.sha256(json.dumps(argv).encode()).hexdigest()
            observed = ends[0]['observed']
            if starts[0]['observed'].get('argv_sha256') != expected_hash or observed.get('returncode') != 0 or any(not proof.get(key) or proof[key] != observed.get(key) for key in ('stdout_sha256', 'stderr_sha256')):
                raise ValueError('target command log differs from claimed execution')
