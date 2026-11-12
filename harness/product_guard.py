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
              'get_goal', 'clock__curr_time', 'interrupt_agent'}
SERENA_READ = {'initial_instructions', 'get_current_config', 'get_symbols_overview',
               'find_symbol', 'find_referencing_symbols', 'search_for_pattern',
               'list_dir', 'find_file', 'read_file', 'list_memories', 'read_memory'}
GIT_READ = {'status', 'diff', 'show', 'log', 'ls-files', 'ls-tree', 'cat-file',
            'rev-parse', 'ls-remote', 'check-ignore', 'merge-base'}
MANAGEMENT = {'task', 'start', 'planning', 'design', 'development', 'verification',
              'qa', 'usage-register', 'usage-poll', 'collection-report', 'status'}
HELP_ACTIONS = MANAGEMENT | {'init','update','recover','hook','guard','finish','command'}
CONTENT_READ_TOOLS = {'mcp__headroom__headroom_retrieve', 'mcp__headroom.headroom_retrieve'}
# Native hook names can concatenate namespace and method. Accept only observed,
# exact aliases; stripping punctuation from arbitrary names would widen authority.
COLLABORATION_ACTIONS = {'spawn_agent', 'send_message', 'wait_agent',
                         'followup_task', 'list_agents', 'interrupt_agent'}
TOOL_ALIASES = {'collaboration'+action: action for action in COLLABORATION_ACTIONS}
WEB_READ_TOOLS = {'web.run', 'web__run', 'webrun'}


def installed(root):
    path = Path(root) / '.kmp-agent/installation.json'
    # Invalid selection metadata must not silently turn off an installed guard.
    return path.exists() or path.is_symlink()


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
    if not runs:
        raise ValueError('native session has no bound execution plan; use task --operation bind-execution-session')
    candidates = []
    rejected = []
    for task in _members(state, runs):
        if task_id is not None and task['task_id'] != task_id:
            continue
        if task.get('state') != 'IN_PROGRESS' or development_tracking.execution_scope(task) != 'code_implementation':
            rejected.append(task['task_id']+': state='+str(task.get('state'))+', scope='+development_tracking.execution_scope(task)+'; use task ready/begin after configuring development')
            continue
        works = [r for r in task.get('executions', []) if r.get('kind') == 'work' and not r.get('ended_at') and r.get('run_id') in runs]
        if len(works) != 1:
            rejected.append(task['task_id']+': expected one open work execution in the bound run; use task begin or resume')
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
        raise ValueError('expected one planned PRODUCT implementation; '+('; '.join(rejected) if not candidates else 'ambiguous active tasks: '+', '.join(t['task_id'] for _, t in candidates)+'; select --task-id for commands')+('; requested task is absent from bound plan; use register-execution-plan' if task_id and not any(t['task_id']==task_id for t in _members(state,runs)) else ''))
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
    # Metadata preparation has its own named namespace, never arbitrary docs JSON.
    if all(name.startswith('docs/guard-inputs/') and name.endswith('.json')
           and content is not None for name, content in changes.items()):
        code_paths = [p for t in state.get('tasks',{}).values() for p in t.get('development_tracking',{}).get('code_paths',[])]
        if any(name == p or name.startswith(p+'/') for name in changes for p in code_paths):
            raise ValueError('metadata preparation overlaps registered implementation code paths')
        for content in changes.values():
            if not isinstance(json.loads(content), dict):
                raise ValueError('guard-inputs must contain a JSON object')
        return
    if document_patch(root, state, session, changes):
        return
    manager, task = active(root, state, session)
    paths = task['development_tracking']['code_paths']
    for name, content in changes.items():
        if not paths or not any(name == p or name.startswith(p+'/') for p in paths):
            raise ValueError('patch is outside the active implementation code paths')
        if content is None:
            continue  # Required files/patterns are checked on submit and product certification.
        policy = development_constraints.load(manager, task)['policy']
        for rule in policy['source_rules']:
            if fnmatch.fnmatch(name, rule['glob']):
                if any(re.search(pattern,content) for pattern in rule['forbidden_patterns']):
                    raise ValueError('patch violates an authoritative technology source rule')


def _argv(command):
    if not isinstance(command, str):
        raise ValueError('shell command must be a string')
    # Inspect shell syntax before removing quotes. Single quotes are entirely
    # literal; double quotes still expand substitutions. No shell evaluation.
    quote, escaped = None, False
    for char in command:
        if char in '\n\r':
            raise ValueError('multiline shell commands require an approved managed command')
        if escaped:
            escaped = False
            continue
        if quote == "'":
            if char == "'": quote = None
            continue
        if char == '\\':
            escaped = True
            continue
        if quote == '"':
            if char == '"': quote = None
            elif char in '$`':
                raise ValueError('shell substitution requires an approved managed command')
            continue
        if char in "'\"": quote = char
        elif char in ';&|<>`$(){}':
            raise ValueError('compound/dynamic shell commands require an approved managed command; run one simple command per exec_command for reads')
    argv = shlex.split(command)
    if argv[:2] == ['rtk','proxy']: argv = argv[2:]
    elif argv[:1] == ['rtk']: argv = argv[1:]
    if not argv: raise ValueError('empty tool command')
    return argv


def _save_or_share(args):
    if not args: return False
    if args[0] == 'add':
        for arg in args[1:]:
            if arg == '--': break
            if arg.startswith('-') and arg not in {'-A','--all','-u','--update','-f','--force','-N','--intent-to-add','-v','--verbose','-n','--dry-run'}:
                raise ValueError('unsupported staging option; use git add [--all|--update] -- <paths>')
        return True
    if args[0] == 'commit':
        i, message = 1, False
        while i < len(args):
            arg = args[i]
            if arg == '--': break
            if arg in {'-m','--message','-F','--file'}:
                if i+1 >= len(args): raise ValueError('commit message argument required')
                message = True
                i += 2
                continue
            if arg.startswith(('--message=', '--file=')):
                message = True
            elif arg.startswith('-') and arg not in {'-a','--all','-q','--quiet','-v','--verbose','--allow-empty','--allow-empty-message','-s','--signoff'}:
                raise ValueError('unsupported commit option; save with git commit -m <message> or -F <file>; hook bypass/rewrite is forbidden')
            i += 1
        if not message:
            raise ValueError('work saving requires explicit git commit -m <message> or -F <file>')
        return True
    if args[0] != 'push': return False
    # A push shares a named development branch; tags, deletes, force/mirror,
    # configured default refspecs and protected deployment refs stay denied.
    if args.count('--no-follow-tags') != 1:
        raise ValueError('work sharing requires git push --no-follow-tags [-u] <remote> <branch>; prevent configured automatic tag publication')
    values = [a for a in args[1:] if a not in {'-u', '--set-upstream', '--no-follow-tags'}]
    if len(values) != 2 or not re.fullmatch(r'[A-Za-z0-9_.-]+', values[0]) or values[0].startswith('-'):
        raise ValueError('share with git push [-u] <remote-name> <branch>:refs/heads/<branch>')
    ref = values[1]
    if ref.count(':') > 1:
        raise ValueError('one explicit development branch required')
    source, destination = ref.split(':') if ':' in ref else (ref, ref)
    if destination.startswith('refs/') and not destination.startswith('refs/heads/'):
        raise ValueError('work sharing supports refs/heads only, never tags or other namespaces')
    destination = destination.removeprefix('refs/heads/')
    if (source != 'HEAD' and not re.fullmatch(r'(?:refs/heads/)?[A-Za-z0-9_][A-Za-z0-9_./-]*', source)
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', destination)
            or ref == 'HEAD' or '..' in ref or '@{' in ref
            or source.startswith(('refs/tags/', '-'))
            or any(p.lower() in {'main','master','release','releases','production','prod','deploy','deployment','staging'} for p in destination.split('/'))):
        raise ValueError('push supports development branches only; release/protected refs require an external approved publication path')
    return True


def _sed_read(argv):
    # No -e/-f, writes, e-command or substitutions. Only numeric line viewing.
    return (len(argv) >= 4 and argv[1] == '-n'
            and re.fullmatch(r'\d+(?:,\d+|,\$)?p', argv[2]) is not None
            and all(not p.startswith('-') for p in argv[3:]))


def configure_documents(manager, task_id, paths, reason):
    if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)) or not isinstance(reason,str) or not reason.strip():
        raise ValueError('explicit unique document paths and reason required')
    names = [relative(manager.root, path) for path in paths]
    def operation(state):
        task = state['tasks'][task_id]
        def document(name):
            metadata = (name.endswith('.md') or name in {'requirement-lineage.json', 'project-settings.json'}
                        or name.startswith('docs/') and name.endswith('.json'))
            design = (task.get('role') == 'design' and task.get('execution_scope') == 'documentation'
                      and name.startswith(('docs/', 'prototype/')) and name.endswith(('.html', '.css')))
            return metadata or design
        if any(not document(name) for name in names):
            raise ValueError('document scope requires document/metadata paths; design documentation may freeze exact docs/ or prototype/ HTML/CSS paths; product source requires an implementation contract')
        if task.get('state') not in {'TODO','READY'} or task.get('executions') or task.get('document_scope'):
            raise ValueError('document scope must be frozen once before execution')
        task['document_scope'] = {'paths':names, 'reason':reason}
        manager._event(state,'document_scope_configured',task,observed=task['document_scope'])
        return task['document_scope']
    return manager._mutate('configure_documents',operation,task_id)


def document_patch(root, state, session, changes):
    runs = _runs(state, session)
    matches = [t for t in _members(state,runs)
               if t.get('state') == 'IN_PROGRESS' and t.get('execution_scope') == 'documentation'
               and set(changes).issubset(t.get('document_scope',{}).get('paths',[]))
               and len([r for r in t.get('executions',[]) if r.get('kind')=='work' and not r.get('ended_at') and r.get('run_id') in runs]) == 1]
    if len(matches) != 1: return False
    task = matches[0]
    execution_policy.gate(Tasks(root,next(r['run_id'] for r in task['executions'] if not r.get('ended_at'))),state,task['task_id'],'dispatch')
    # A Markdown/JSON file inside any implementation scope remains product code.
    code_paths = [p for t in state.get('tasks',{}).values() for p in t.get('development_tracking',{}).get('code_paths',[])]
    if any(name == p or name.startswith(p+'/') for name in changes for p in code_paths):
        raise ValueError('document patch overlaps registered implementation code paths')
    return True


def _content_read(args):
    # This service restores previously stored tool output, not project files.
    if (not isinstance(args,dict) or set(args) != {'hash'}
            or not isinstance(args['hash'],str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',args['hash'])):
        raise ValueError('headroom_retrieve requires exactly one literal hash string')


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


def _managed_update_command(root, argv):
    if len(argv) < 3 or argv[0] not in {'python', 'python3'} or argv[2] != 'update':
        return False
    root = Path(root).resolve()
    script = Path(argv[1])
    script = script if script.is_absolute() else root / script
    expected = root / '.kmp-agent/agent.py'
    if script.resolve() != expected.resolve():
        return False
    if script.absolute() != expected:
        raise ValueError('managed update cannot use an alias for the official project launcher')
    from harness.managed_update import authorize
    authorize(root, argv[2:], runtime=Path(__file__).resolve().parents[1])
    return True


def _help_command(root, argv):
    if not (argv[2:] in (['--help'], ['-h'])
            or argv[2] in HELP_ACTIONS and argv[3:] in (['--help'], ['-h'])):
        return False
    root = Path(root).resolve()
    expected = root / '.kmp-agent/agent.py'
    script = Path(argv[1])
    script = script if script.is_absolute() else root / script
    from bootstrap import LAUNCHER
    if (script.absolute() != expected or expected.is_symlink() or expected.parent.is_symlink()
            or not expected.is_file() or expected.read_bytes() != LAUNCHER.encode()):
        raise ValueError('help requires the unchanged official project launcher without aliases; inspect control files with read tools')
    return True


def _shell(root, state, session, command):
    argv = _argv(command)
    if _managed_update_command(root, argv):
        return
    program = Path(argv[0]).name
    if argv[0] != program:
        raise ValueError('executable paths cannot impersonate read-only command names')
    if program in {'pwd','ls','cat','head','tail','wc'}:
        return
    if argv in (['printenv', 'CODEX_THREAD_ID'], ['ps', '-axo', 'pid,args']):
        return  # Exact session diagnostics, never a general environment dump.
    if program == 'sed' and _sed_read(argv):
        return
    if program == 'rg' and not any(x.startswith(('--pre','--hostname-bin')) for x in argv[1:]):
        return
    if program == 'git':
        args = argv[1:]
        # Permit only this fixed configuration, never arbitrary -c/alias overrides.
        safe_status = args[:4] == ['--no-pager', '--no-optional-locks', '-c', 'core.fsmonitor=false']
        if safe_status:
            args = args[4:]
        target = Path(root).resolve()
        if args[:1] == ['-C']:
            if len(args) < 3:
                raise ValueError('explicit Git target and command required')
            target = (Path(root)/args[1]).resolve()
            args = args[2:]
        if target != Path(root).resolve():
            # External repository configuration may execute fsmonitor, diff or
            # textconv programs. Support a narrow status handoff, not executors.
            if safe_status and args and args[0] == 'status' and all(
                    a in {'--short', '--branch', '--porcelain', '--porcelain=v1',
                          '--porcelain=v2', '-s', '-b'} for a in args[1:]):
                return
            raise ValueError('external Git supports status observation only: git --no-pager --no-optional-locks '
                             '-c core.fsmonitor=false -C <root> status --short --branch; '
                             'mutations require a separate session rooted in that repository')
        if args in (['remote','-v'], ['remote','--verbose'], ['remote']):
            return
        if _git_read(args):
            return
        if _save_or_share(args):
            return
    if program in {'python','python3'} and len(argv) > 2 and (Path(root)/argv[1]).resolve() == (Path(root)/'.kmp-agent/agent.py').resolve():
        if any(x == '--target' or x.startswith('--target=') for x in argv[2:]):
            raise ValueError('selected project entrypoint cannot override its target')
        if any(x == '--worker' or x.startswith('--worker=') for x in argv[2:]):
            raise ValueError('installed role execution cannot inject an arbitrary worker')
        action = argv[2]
        if _help_command(root,argv):
            return  # argparse help is diagnostic, independent of product state.
        state = state if state is not None else _state(root)
        if action in MANAGEMENT:
            if action in {'planning','design','development','verification','qa'}:
                task = state.get('tasks',{}).get(_option(argv,'--task-id'),{})
                if task.get('work_type') != 'PRODUCT':
                    raise ValueError('installed role execution requires an explicit PRODUCT task')
            return  # The selected entrypoint's own lifecycle gates still apply.
        if action == 'finish':
            run = _option(argv,'--run-id')
            if run not in _runs(state,session): raise ValueError('finish belongs to a different native session')
            reason = _option(argv,'--end-reason') if '--end-reason' in argv else 'completed'
            if reason == 'completed': complete(root,state,{run})
            elif reason not in {'blocked','handoff','user_stopped','paused'}: raise ValueError('unsupported run end reason')
            return
        if action == 'command':
            run, task_id = _option(argv,'--run-id'), _option(argv,'--task-id')
            if run not in _runs(state,session):
                raise ValueError('command belongs to a different native session; bind-execution-session for the actual run')
            if '--argv-json' not in argv:
                raise ValueError('guarded product command requires explicit approved argv')
            authorize_command(root,state,task_id,json.loads(_option(argv,'--argv-json')),run_id=run)
            return
    raise ValueError('unclassified executable tool path; use approved task commands instead of direct execution')


def authorize_command(root, state, task_id, argv, run_id=None):
    """Also called inside Logger.command, so a wrapper cannot smuggle arbitrary code."""
    if not installed(root): return
    task = state.get('tasks',{}).get(task_id)
    if not task or task.get('work_type') != 'PRODUCT':
        raise ValueError('installed product command requires an explicit PRODUCT task')
    opened = [r for r in task.get('executions',[]) if not r.get('ended_at')]
    if len(opened) == 1 and (opened[0].get('kind') == 'review' or task.get('role') == 'verification'):
        from harness.verification_capabilities import authorize_command as verify_command
        session = state.get('execution_policy_bindings',{}).get(opened[0]['run_id'],{}).get('root_session_id')
        verify_command(root,state,session,task_id,argv,run_id=run_id)
        return
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


END_REASONS = {'completed','blocked','handoff','user_stopped','paused'}


def finish(root, run_id, end_reason='completed'):
    if end_reason not in END_REASONS:
        raise ValueError('unsupported run end reason')
    if installed(root) and end_reason == 'completed':
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
        # A harness repair must remain possible when the product ledger is
        # blocked or malformed. Only this separately verified management
        # capability may bypass reading product state; no product work is allowed.
        if event == 'PreToolUse' and payload.get('tool_name') in {'Bash', 'exec_command', 'functions.exec_command'}:
            args = payload.get('tool_input', {})
            if isinstance(args, dict):
                if 'cmd' in args and 'command' in args:
                    raise ValueError('guarded shell tools cannot supply both cmd and command')
                if args.get('shell') is not None:
                    raise ValueError('guarded tools require the default shell; explicit shell overrides are unsupported')
            command = args.get('command', args.get('cmd')) if isinstance(args, dict) else args
            workdir = args.get('workdir', str(root)) if isinstance(args, dict) else str(root)
            argv = _argv(command)
            if Path(workdir).resolve() == root and _managed_update_command(root, argv):
                return {}
        # Ending a conversational turn never certifies product completion.
        if event == 'Stop':
            return {}
        session = payload.get('session_id')
        state = None
        if event == 'PreToolUse':
            tool, args = payload.get('tool_name',''), payload.get('tool_input',{})
            tool = TOOL_ALIASES.get(tool, tool)
            if tool.startswith('collaboration.') and tool.split('.',1)[1] in READ_TOOLS:
                tool = tool.split('.',1)[1]
            if tool.startswith('functions.') and tool.split('.',1)[1] in READ_TOOLS | {'exec_command','apply_patch'}:
                tool = tool.split('.',1)[1]
            if tool in CONTENT_READ_TOOLS:
                _content_read(args)
                return {}
            if tool in {'mcp__cua_repl__js', 'mcp__cua_repl.js'}:
                from harness.cua_guard import observation
                observation(args)
                return {}
            if tool == 'mcp__codex_tui__list_threads':
                return {}  # Discovery only; thread creation does not switch cwd.
            if tool in READ_TOOLS or tool in WEB_READ_TOOLS or tool.startswith('mcp__serena__') and tool.rsplit('__',1)[-1] in SERENA_READ:
                return {}
            command = args.get('command',args.get('cmd')) if isinstance(args,dict) else args
            if tool in {'apply_patch','Edit','Write'}:
                _patch(root,_state(root),session,command)
            elif tool in {'Bash','exec_command'}:
                workdir = args.get('workdir',str(root)) if isinstance(args,dict) else str(root)
                if Path(workdir).resolve() != root: raise ValueError('command workdir must be the project root')
                _shell(root,None,session,command)
            else:
                from harness.verification_capabilities import UI_ACTIONS, authorize_tool
                if tool.startswith('mcp__') and tool.rsplit('__',1)[-1] in UI_ACTIONS:
                    authorize_tool(root,_state(root),session,tool,args)
                else:
                    raise ValueError('unsupported tool capability '+repr(tool)+'; use supported read tools or the official project entrypoint --help; no product mutation authorized')
        else:
            raise ValueError('unsupported product guard event')
        return {}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
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
