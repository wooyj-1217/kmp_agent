"""Installed-target guardrails. Reuse Tasks/contracts; never authorize from prose.

This is not an OS sandbox: only supported, enabled, trusted Codex tool hooks run it.
Unknown executable paths are denied, not heuristically treated as read-only.
"""
import fnmatch
import json
from pathlib import Path
import re
import shlex
import sys

from harness.tasks import Tasks
from harness import development_constraints, development_tracking, execution_policy

CONTROL = {'.git', '.kmp-agent', '.harness', '.codex', '.agents', '.githooks'}
READ_TOOLS = {'read_file', 'list_dir', 'search', 'view_image', 'update_plan',
              'request_user_input', 'request_user_input_async', 'wait', 'wait_agent',
              'spawn_agent', 'Agent', 'send_message', 'followup_task', 'list_agents',
              'exec', 'get_goal', 'clock__curr_time'}
SERENA_READ = {'initial_instructions', 'get_current_config', 'get_symbols_overview',
               'find_symbol', 'find_referencing_symbols', 'search_for_pattern',
               'list_dir', 'find_file', 'read_file', 'list_memories', 'read_memory'}
GIT_READ = {'status', 'diff', 'show', 'log', 'ls-files', 'ls-tree', 'cat-file',
            'rev-parse', 'ls-remote', 'check-ignore', 'merge-base'}
MANAGEMENT = {'task', 'start', 'planning', 'design', 'development', 'verification',
              'qa', 'usage-register', 'usage-poll', 'collection-report', 'status'}


def installed(root):
    return (Path(root) / '.kmp-agent/installation.json').is_file()


def _state(root):
    path = Path(root) / '.harness/tasks/tasks.yaml'
    state = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(state, dict) or not isinstance(state.get('tasks', {}), dict):
        raise ValueError('invalid native task ledger')
    return state


def _runs(state, session_id):
    if not isinstance(session_id, str) or not session_id or session_id == 'UNKNOWN':
        raise ValueError('exact native session required')
    return {run for run, binding in state.get('execution_policy_bindings', {}).items()
            if binding.get('root_session_id') == session_id}


def _members(state, runs):
    ids = {tid for run in runs for tid in state.get('execution_plans', {}).get(run, {}).get('task_ids', [])}
    # Include real delegated children; a new unplanned task cannot authorize a write.
    for task in state.get('tasks', {}).values():
        if any(execution_policy.membership(state, run, task['task_id']) for run in runs):
            ids.add(task['task_id'])
    return [state['tasks'][tid] for tid in sorted(ids) if state['tasks'][tid].get('work_type') == 'PRODUCT']


def active(root, state, session_id, task_id=None):
    runs = _runs(state, session_id)
    candidates = []
    for task in _members(state, runs):
        if task_id is not None and task['task_id'] != task_id:
            continue
        if task.get('state') != 'IN_PROGRESS' or development_tracking.execution_scope(task) != 'code_implementation':
            continue
        works = [r for r in task.get('executions', []) if r.get('kind') == 'work' and not r.get('ended_at') and r.get('run_id') in runs]
        if len(works) != 1:
            continue
        manager = Tasks(root, works[0]['run_id'])
        if not state.get('execution_policy'):
            raise ValueError('product tool execution requires a native execution policy')
        execution_policy.gate(manager, state, task['task_id'], 'dispatch')
        from harness.stage_readiness import gate as stage_gate
        from harness.project_contract import gate as project_gate
        reason = stage_gate(manager, state, task)
        if reason:
            raise ValueError(reason)
        project_gate(manager, task)
        if not task.get('development_tracking'):
            raise ValueError('product code tracking is required before tool execution')
        development_tracking.ensure(manager, state, task, 'dispatch', run=works[0])
        candidates.append((manager, task))
    if len(candidates) != 1:
        raise ValueError('exactly one active, planned PRODUCT implementation with frozen technology constraints is required')
    return candidates[0]


def complete(root, state, runs):
    tasks = _members(state, runs)
    if not tasks:
        raise ValueError('product publication requires a bound native execution plan')
    if any(t.get('state') != 'DONE' for t in tasks):
        raise ValueError('product tasks are not officially DONE; TODO or partial tests cannot authorize publication')
    checked = False
    for task in tasks:
        if development_tracking.execution_scope(task) != 'code_implementation':
            continue
        checked = True
        works = [r for r in task.get('executions', []) if r.get('kind') == 'work' and r.get('ended_at')]
        if not works:
            raise ValueError('completed product has no ended implementation execution')
        manager = Tasks(root, works[-1]['run_id'])
        development_constraints.check_code(manager, task)
        development_tracking.refresh(manager, state)
        reviews = task.get('reviews', [])
        if not reviews or task.get('validation_status', {}).get(reviews[-1]['agent_run_id'], {}).get('state') != 'CURRENT':
            raise ValueError('product validation is absent, stale or invalid')
        from harness.completion import gate as completion_gate
        completion_gate(manager, state, task)
    if not checked:
        raise ValueError('a documentation-only plan cannot certify a product implementation')


def relative(root, name):
    root = Path(root).resolve()
    path = Path(name)
    path = path if path.is_absolute() else root / path
    # Resolving must not silently authorize a symlink to a different code scope.
    if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
        raise ValueError('symlink mutation is not an approved product code path')
    path = path.resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('tool mutation escapes the target project')
    name = str(path.relative_to(root))
    if Path(name).parts[0] in CONTROL or name == 'AGENTS.md':
        raise ValueError('control files must not be changed by raw product tools')
    return name


def patch_files(root, patch):
    """Preview the supported apply_patch grammar without writing a single byte."""
    if not isinstance(patch, str) or not patch.startswith('*** Begin Patch\n') or not patch.rstrip().endswith('*** End Patch'):
        raise ValueError('supported apply_patch input required')
    lines = patch.splitlines()
    i, changes = 1, {}
    while i < len(lines) and lines[i] != '*** End Patch':
        header = lines[i]
        if not any(header.startswith('*** '+kind+' File: ') for kind in ('Add','Update','Delete')):
            raise ValueError('unsupported patch file header')
        kind, raw = header[4:].split(' File: ', 1)
        name = relative(root, raw)
        if name in changes:
            raise ValueError('duplicate patch path')
        i += 1
        if kind == 'Delete':
            changes[name] = None
            continue
        if kind == 'Add':
            content = []
            while i < len(lines) and not lines[i].startswith('*** '):
                if not lines[i].startswith('+'):
                    raise ValueError('unsupported added-file line')
                content.append(lines[i][1:]); i += 1
            changes[name] = '\n'.join(content) + '\n'
            continue
        original = (Path(root) / name).read_text().splitlines()
        destination = name
        if i < len(lines) and lines[i].startswith('*** Move to: '):
            destination = relative(root, lines[i][13:]); i += 1
        cursor, output = 0, []
        while i < len(lines) and (not lines[i].startswith('*** ') or lines[i] == '*** End of File'):
            if lines[i] == '*** End of File':
                i += 1; break
            if lines[i].startswith('@@'):
                anchor = lines[i][2:].strip()
                if anchor:
                    found = next((n for n in range(cursor,len(original)) if original[n].strip() == anchor), None)
                    if found is None: raise ValueError('patch anchor is not in current source')
                    output.extend(original[cursor:found+1]); cursor = found+1
                i += 1
            old, new = [], []
            while i < len(lines) and not lines[i].startswith(('@@', '*** ')):
                line = lines[i]
                if not line or line[0] not in ' +-': raise ValueError('unsupported update line')
                if line[0] in ' -': old.append(line[1:])
                if line[0] in ' +': new.append(line[1:])
                i += 1
            found = next((n for n in range(cursor,len(original)+1) if original[n:n+len(old)] == old), None)
            if found is None: raise ValueError('patch does not match current source')
            output.extend(original[cursor:found]); output.extend(new); cursor = found+len(old)
        output.extend(original[cursor:])
        if destination != name:
            changes[name] = None
            if destination in changes: raise ValueError('duplicate move destination')
        changes[destination] = '\n'.join(output) + '\n'
    if not changes:
        raise ValueError('empty mutation patch')
    return changes


def _patch(root, state, session, patch):
    changes = patch_files(root, patch)
    # Planning documents and the existing lineage input may be prepared before code.
    setup = all(name.endswith('.md') or name == 'requirement-lineage.json'
                or name.startswith('docs/') and name.endswith('.json') for name in changes)
    if setup:
        return
    manager, task = active(root, state, session)
    paths = task['development_tracking']['code_paths']
    for name, content in changes.items():
        if not paths or not any(name == p or name.startswith(p+'/') for p in paths):
            raise ValueError('patch is outside the active implementation code paths')
        if content is None:
            continue  # Required files/patterns are checked on submit/commit/publication.
        policy = development_constraints.load(manager, task)['policy']
        for rule in policy['source_rules']:
            if fnmatch.fnmatch(name, rule['glob']):
                if any(re.search(pattern,content) for pattern in rule['forbidden_patterns']):
                    raise ValueError('patch violates an authoritative technology source rule')


def _argv(command):
    if not isinstance(command, str) or any(c in command for c in '\n\r;&|<>`$'):
        raise ValueError('compound/dynamic shell commands require an approved managed command')
    argv = shlex.split(command)
    if argv[:2] == ['rtk','proxy']: argv = argv[2:]
    elif argv[:1] == ['rtk']: argv = argv[1:]
    if not argv: raise ValueError('empty tool command')
    return argv


def _option(argv, name):
    if argv.count(name) != 1 or argv.index(name)+1 >= len(argv):
        raise ValueError('explicit '+name+' required')
    return argv[argv.index(name)+1]


def _git_read(args):
    if not args or args[0] not in GIT_READ:
        return False
    if args[0] == 'ls-remote':
        for arg in args[1:]:
            if re.match(r'^[A-Za-z0-9+.-]+::', arg):
                return False  # Explicit remote-helper command/transport.
            scheme = re.match(r'^([A-Za-z0-9+.-]+)://', arg)
            if scheme and scheme[1] not in {'git', 'file', 'http', 'https', 'ssh'}:
                return False
    # Git accepts abbreviated long options. Merely matching --output or
    # --upload-pack verbatim leaves --out/--upload and -u executable escapes.
    dangerous = ('--output', '--ext-diff', '--textconv', '--filters', '--upload-pack')
    for arg in args[1:]:
        if arg == '--':
            break  # Remaining arguments are paths, not options.
        option = arg.split('=', 1)[0]
        if option.startswith('--') and len(option) > 2 and any(
                full.startswith(option) or option.startswith(full) for full in dangerous):
            return False
        if args[0] == 'ls-remote' and arg.startswith('-') and not arg.startswith('--') and 'u' in arg[1:]:
            return False
    return True


def _shell(root, state, session, command):
    argv = _argv(command)
    program = Path(argv[0]).name
    if argv[0] != program:
        raise ValueError('executable paths cannot impersonate read-only command names')
    if program in {'pwd','ls','cat','head','tail','wc'}:
        return
    if program == 'rg' and not any(x.startswith(('--pre','--hostname-bin')) for x in argv[1:]):
        return
    if program == 'git':
        args = argv[1:]
        if args[:1] == ['-C']:
            if len(args) < 3 or (Path(root)/args[1]).resolve() != Path(root).resolve():
                raise ValueError('Git mutation must target this project root')
            args = args[2:]
        if _git_read(args):
            return
        if args and args[0] == 'add':
            active(root,state,session); return
        if args and args[0] == 'commit':
            manager, task = active(root,state,session)
            development_constraints.check_code(manager,task); return
        if args and args[0] == 'push':
            complete(root,state,_runs(state,session)); return
    if program in {'python','python3'} and len(argv) > 2 and (Path(root)/argv[1]).resolve() == (Path(root)/'.kmp-agent/agent.py').resolve():
        if any(x == '--target' or x.startswith('--target=') for x in argv[2:]):
            raise ValueError('selected project entrypoint cannot override its target')
        if any(x == '--worker' or x.startswith('--worker=') for x in argv[2:]):
            raise ValueError('installed role execution cannot inject an arbitrary worker')
        action = argv[2]
        if action in MANAGEMENT:
            if action in {'planning','design','development','verification','qa'}:
                task = state.get('tasks',{}).get(_option(argv,'--task-id'),{})
                if task.get('work_type') != 'PRODUCT':
                    raise ValueError('installed role execution requires an explicit PRODUCT task')
            return  # The selected entrypoint's own lifecycle gates still apply.
        if action == 'finish':
            run = _option(argv,'--run-id')
            if run not in _runs(state,session): raise ValueError('finish belongs to a different native session')
            complete(root,state,{run}); return
        if action == 'command':
            run, task_id = _option(argv,'--run-id'), _option(argv,'--task-id')
            manager, task = active(root,state,session,task_id=task_id)
            if manager.run_id != run or task['task_id'] != task_id:
                raise ValueError('command belongs to a different active task/run')
            if '--argv-json' not in argv:
                raise ValueError('guarded product command requires explicit approved argv')
            authorize_command(root,state,task_id,json.loads(_option(argv,'--argv-json')))
            return
    raise ValueError('unclassified executable tool path; use approved task commands instead of direct execution')


def authorize_command(root, state, task_id, argv, run_id=None):
    """Also called inside Logger.command, so a wrapper cannot smuggle arbitrary code."""
    if not installed(root): return
    task = state.get('tasks',{}).get(task_id)
    if not task or task.get('work_type') != 'PRODUCT':
        raise ValueError('installed product command requires an explicit PRODUCT task')
    works = [r for r in task.get('executions',[]) if r.get('kind') == 'work' and not r.get('ended_at')]
    if task.get('state') != 'IN_PROGRESS' or len(works) != 1:
        raise ValueError('installed product command requires one active implementation execution')
    run = works[0]['run_id']
    if run_id is not None and run_id != run:
        raise ValueError('installed product command run differs from active execution')
    session = state.get('execution_policy_bindings',{}).get(run,{}).get('root_session_id')
    _, selected = active(root,state,session,task_id=task_id)
    if selected['task_id'] != task_id:
        raise ValueError('installed command task differs from native active execution')
    policy = development_constraints.load(Tasks(root,'guard'),task)['policy']
    approved = [command for commands in policy['target_commands'].values() for command in commands]
    if argv not in approved:
        raise ValueError('command argv is not in authoritative target_commands')


def finish(root, run_id):
    if installed(root):
        complete(root,_state(root),{run_id})


def configured_adapter(manager, task, commands, executable):
    """Validate configured subprocess surfaces before setup and again before launch."""
    if not installed(manager.root): return
    if executable != 'codex':
        raise ValueError('installed adapters require native codex; arbitrary executables are forbidden')
    if not commands: return  # Read-only document review needs no implementation contract.
    if task.get('work_type') != 'PRODUCT':
        raise ValueError('installed adapter commands require a PRODUCT technology contract')
    constraints=development_constraints.load(manager,task)
    if not constraints:
        raise ValueError('installed adapter commands require frozen technology constraints')
    approved=[command for rows in constraints['policy']['target_commands'].values() for command in rows]
    if any(command not in approved for command in commands):
        raise ValueError('installed adapter commands must be included in authoritative target_commands')


def evaluate(root, payload):
    root = Path(root).resolve()
    if not installed(root): return {}
    event = payload.get('hook_event_name')
    try:
        if Path(payload.get('cwd','')).resolve() != root:
            raise ValueError('hook cwd differs from target project root')
        state = _state(root)
        session = payload.get('session_id')
        if event == 'Stop':
            runs = _runs(state,session)
            tasks = _members(state,runs)
            if not tasks: return {}
            unfinished = [t for t in tasks if t.get('state') != 'DONE']
            from harness.decisions import _contract_current
            def waiting(task):
                for qid in execution_policy.pending(state,task['task_id']):
                    question = state['required_questions'][qid]
                    if (question.get('status') == 'OPEN' and question.get('run_id') in runs
                            and question.get('decision_contract') and question.get('checkpoint')
                            and _contract_current(state,question,root)):
                        return True
                return False
            if unfinished and all(waiting(t) for t in unfinished):
                return {}  # Only current, bound required questions permit a waiting turn.
            complete(root,state,runs)
        elif event == 'PreToolUse':
            tool, args = payload.get('tool_name',''), payload.get('tool_input',{})
            if tool in READ_TOOLS or tool.startswith('mcp__serena__') and tool.rsplit('__',1)[-1] in SERENA_READ:
                return {}
            command = args.get('command',args.get('cmd')) if isinstance(args,dict) else args
            if tool in {'apply_patch','Edit','Write'}:
                _patch(root,state,session,command)
            elif tool in {'Bash','exec_command'}:
                workdir = args.get('workdir',str(root)) if isinstance(args,dict) else str(root)
                if Path(workdir).resolve() != root: raise ValueError('command workdir must be the project root')
                _shell(root,state,session,command)
            else:
                raise ValueError('unknown local tool capability; product mutation is not implicitly authorized')
        else:
            raise ValueError('unsupported product guard event')
        return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        # Explicit supported denial is essential: hook errors alone may fail open.
        reason = 'Product contract guard: '+str(error)
        if event == 'PreToolUse':
            return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':reason}}
        return {'decision':'block','reason':reason}


def main(root):
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload,dict): raise ValueError('hook object required')
    except (ValueError, OSError):
        print(json.dumps({'decision':'block','reason':'Invalid product guard payload'}))
        return 2
    print(json.dumps(evaluate(root,payload),ensure_ascii=False))
    return 0
