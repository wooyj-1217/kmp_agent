"""Exact, frozen verification capabilities; these never authorize product patches.

UI definitions contain actual structured tool inputs supplied by the project.
No JavaScript, shell snippets or inferred UI runtime API is interpreted here.
"""
import copy
import json
import math
import re
from pathlib import Path

from harness import development_constraints, development_tracking, execution_policy
from harness.tasks import Tasks
from harness.verification import artifact_status, context

TARGET_KEYS = {'app_id', 'tab_id', 'browser_id', 'target_id', 'window_id'}
UI_ACTIONS = {'screenshot', 'get_screenshot', 'read_screen', 'click', 'double_click',
              'type_text', 'keypress', 'scroll'}
SCRIPT_KEYS = {'code', 'script', 'javascript', 'expression', 'command', 'cmd', 'argv', 'shell'}


def _structured(value):
    if isinstance(value, dict):
        if any(not isinstance(k, str) or k.lower() in SCRIPT_KEYS for k in value):
            raise ValueError('UI capability cannot contain executable scripts or commands')
        for key, item in value.items():
            if key.lower() in {'path','output_path','file_path','filename'}:
                if not isinstance(item,str) or Path(item).is_absolute() or '..' in Path(item).parts or not item.startswith('verification/'):
                    raise ValueError('UI file output must remain under project verification/')
            _structured(item)
    elif isinstance(value, list):
        for item in value:
            _structured(item)
    elif type(value) is float and not math.isfinite(value):
        raise ValueError('UI capability requires finite JSON numbers')
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise ValueError('UI capability requires literal JSON values')


def validate(definition):
    if not isinstance(definition, dict) or set(definition) != {'version', 'target_task_id', 'tools'}:
        raise ValueError('verification capability requires version, target_task_id and tools')
    if type(definition['version']) is not int or definition['version'] != 1:
        raise ValueError('unsupported verification capability version')
    if not isinstance(definition['target_task_id'], str) or not definition['target_task_id'].strip():
        raise ValueError('verification capability requires an exact target task')
    if not isinstance(definition['tools'], list) or not definition['tools']:
        raise ValueError('verification capability requires explicit structured tool fixtures')
    for fixture in definition['tools']:
        if not isinstance(fixture, dict) or set(fixture) != {'tool_name', 'target', 'input'}:
            raise ValueError('UI fixture requires tool_name, target and input')
        name = fixture['tool_name']
        if not isinstance(name, str) or not re.fullmatch(r'mcp__[A-Za-z0-9_]+__[A-Za-z0-9_]+', name):
            raise ValueError('UI fixture requires the actual structured MCP tool name')
        if any(part in name.lower() for part in ('cua_repl', 'exec', 'shell', 'script', 'evaluate')):
            raise ValueError('executable runtime tools cannot be UI capabilities')
        if name.rsplit('__',1)[-1] not in UI_ACTIONS:
            raise ValueError('UI capability requires a supported screen/input action, never generic file or application mutation')
        target, args = fixture['target'], fixture['input']
        if not isinstance(target, dict) or not target or set(target) - TARGET_KEYS:
            raise ValueError('UI fixture requires explicit app/tab/browser/target/window IDs')
        if not isinstance(args, dict) or any(not isinstance(v, str) or not v or args.get(k) != v for k, v in target.items()):
            raise ValueError('UI input must pin every declared target ID')
        _structured(args)
    return copy.deepcopy(definition)


def configure(manager, task_id, definition):
    """Freeze a project-supplied UI fixture artifact before verification starts."""
    ref = manager.artifact(definition)
    parsed = validate(json.loads((manager.root / ref['snapshot']).read_text()))

    def operation(state):
        task = state['tasks'][task_id]
        target = state['tasks'].get(parsed['target_task_id'])
        if task['state'] not in {'TODO', 'READY'} or task.get('executions') or task.get('verification_capabilities'):
            raise ValueError('verification capabilities must be frozen once before execution')
        if task.get('work_type') != 'PRODUCT' or not target or target.get('work_type') != 'PRODUCT':
            raise ValueError('verification capabilities require PRODUCT owner and target tasks')
        if task.get('role') != 'verification' or not task.get('verification_contract'):
            raise ValueError('UI capabilities require a configured verification task')
        if not target.get('development_tracking'):
            raise ValueError('UI target requires a frozen development baseline')
        frozen = {'definition': ref, 'target_code_state': development_tracking.capture(manager, target)['state_sha256']}
        task['verification_capabilities'] = frozen
        if ref not in task['inputs']:
            task['inputs'].append(ref)
        manager._event(state, 'verification_capabilities_configured', task, observed=copy.deepcopy(frozen))
        return copy.deepcopy(frozen)
    return manager._mutate('configure_verification_capabilities', operation, task_id)


def _select(root, state, session, task_id, run_id=None):
    if not isinstance(session, str) or not session or session == 'UNKNOWN':
        raise ValueError('verification requires an exact native session')
    task = state.get('tasks', {}).get(task_id)
    if not task or task.get('work_type') != 'PRODUCT':
        raise ValueError('verification requires an explicit PRODUCT task')
    active = [r for r in task.get('executions', []) if not r.get('ended_at')]
    if len(active) != 1:
        raise ValueError('verification requires one active work or review execution; begin a verification task or review')
    run = active[0]
    expected_state = 'IN_REVIEW' if run.get('kind') == 'review' else 'IN_PROGRESS'
    if task.get('state') != expected_state or run.get('role') != 'verification':
        raise ValueError('verification capability requires an active verification role in work/review state')
    if run_id is not None and run.get('run_id') != run_id:
        raise ValueError('verification command run differs from the active verification execution')
    selected_run = run.get('run_id')
    binding = state.get('execution_policy_bindings', {}).get(selected_run, {})
    if binding.get('root_session_id') != session:
        raise ValueError('verification execution belongs to a different native session')
    if not state.get('execution_policy') or not execution_policy.membership(state, selected_run, task_id):
        raise ValueError('verification requires a bound native execution plan')
    manager = Tasks(root, selected_run)
    execution_policy.gate(manager, state, task_id, 'dispatch')
    if not run.get('actor_id'):
        raise ValueError('verification requires an explicit reviewer actor')
    if task.get('verification_contract'):
        context(manager, task)
    qa = task.get('qa_config')
    if qa:
        target_id = qa['target_task_id']
    elif task.get('verification_capabilities'):
        definition = _definition(manager, task)
        target_id = definition['target_task_id']
    elif run.get('kind') == 'review':
        target_id = task_id
    else:
        raise ValueError('verification work requires a frozen QA or UI target contract')
    target = state.get('tasks', {}).get(target_id)
    if not target or target.get('work_type') != 'PRODUCT':
        raise ValueError('verification target task is absent or not PRODUCT')
    implementers = [r for r in target.get('executions', []) if r.get('kind') == 'work' and r.get('ended_at')]
    if not implementers or not implementers[-1].get('actor_id') or implementers[-1]['actor_id'] == run['actor_id']:
        raise ValueError('verification requires a separately identified target implementer and reviewer')
    if qa:
        from harness.qa import scoped_manifest
        if scoped_manifest(manager.root, qa['manifest_scope'], qa.get('generated_paths', [])) != qa['target_manifest']:
            raise ValueError('frozen QA target changed; configure a new verification task')
    elif task.get('verification_capabilities'):
        current = development_tracking.capture(manager, target)['state_sha256']
        if current != task['verification_capabilities']['target_code_state']:
            raise ValueError('frozen UI target code changed; configure a new verification task')
    else:
        development_tracking.ensure(manager, state, task, 'begin_review', run=run)
    return manager, task, target, run


def _definition(manager, task):
    ref = task['verification_capabilities']['definition']
    if artifact_status(manager.root, ref)['state'] != 'VALID':
        raise ValueError('UI capability snapshot is missing or changed')
    path = (manager.root / ref['path']).resolve()
    from harness.logging import digest
    if not path.is_relative_to(manager.root) or not path.is_file() or digest(path.read_bytes()) != ref['sha256']:
        raise ValueError('UI capability source changed; configure a new verification task')
    return validate(json.loads((manager.root / ref['snapshot']).read_text()))


def authorize_command(root, state, session, task_id, argv, run_id=None):
    manager, task, target, run = _select(root, state, session, task_id, run_id)
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise ValueError('verification command requires structured argv')
    if task.get('qa_config'):
        approved = task['qa_config']['commands']
    else:
        constraints = development_constraints.load(manager, target)
        approved = [command for rows in (constraints or {}).get('policy', {}).get('target_commands', {}).values() for command in rows]
    if argv not in approved:
        raise ValueError('verification argv is not in the frozen approved command contract')
    # QA commands were checked against the target contract at configuration;
    # recheck it now so stale target authority cannot silently remain usable.
    constraints = development_constraints.load(manager, target)
    authoritative = [command for rows in (constraints or {}).get('policy', {}).get('target_commands', {}).values() for command in rows]
    if argv not in authoritative:
        raise ValueError('verification argv is not in authoritative target_commands')
    return manager, task


def _output_paths(root, value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'path','output_path','file_path','filename'}:
                root = Path(root).resolve()
                output = root / item
                if (not output.resolve().is_relative_to(root / 'verification')
                        or any(p.is_symlink() for p in [output,*output.parents] if root in p.parents)):
                    raise ValueError('UI output cannot follow symlinks or escape project verification/')
            _output_paths(root, item)
    elif isinstance(value,list):
        for item in value: _output_paths(root,item)


def authorize_tool(root, state, session, tool, args):
    """Authorize one exact fixture; unknown/changed targets and scripts fail closed."""
    candidates = []
    for task_id, task in state.get('tasks', {}).items():
        if not task.get('verification_capabilities'):
            continue
        active = [r for r in task.get('executions', []) if not r.get('ended_at')]
        if len(active) != 1 or state.get('execution_policy_bindings', {}).get(active[0].get('run_id'), {}).get('root_session_id') != session:
            continue
        manager = Tasks(root, 'verification-capability-inspection')
        definition = _definition(manager, task)
        # Python equality alone conflates true/1 and false/0; a frozen JSON
        # input must preserve those types as well as every key and value.
        encoded = json.dumps(args, sort_keys=True, allow_nan=False)
        if any(fixture['tool_name'] == tool and json.dumps(fixture['input'], sort_keys=True, allow_nan=False) == encoded
               for fixture in definition['tools']):
            candidates.append(task_id)
    if len(candidates) == 1:
        _output_paths(root,args)
        _select(root, state, session, candidates[0])
        return
    if candidates:
        raise ValueError('UI fixture matches multiple active verification tasks; close the unrelated execution')
    raise ValueError('UI tool/input is not an exact frozen verification fixture for this target')
