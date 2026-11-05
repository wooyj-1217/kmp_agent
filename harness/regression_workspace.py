"""Select project-local regression catalogs without granting completion authority."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
from . import regression


def plan(workspace_root, workspace, suite='smoke', platforms=None, scenarios=None):
    for values in (platforms, scenarios):
        if values is not None and (not values or any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) != len(values)):
            raise ValueError('invalid or duplicate selection filter')
    base = Path(workspace_root).resolve()
    config_path = Path(workspace).resolve()
    config = regression._json(config_path)
    if not isinstance(config, dict) or type(config.get('schema_version')) is not int or config['schema_version'] != 1 or not isinstance(config.get('projects'), list) or not config['projects']:
        raise ValueError('invalid workspace schema')
    required = config.get('required_platforms')
    if not isinstance(required, list) or not required or any(p not in regression.PLATFORMS for p in required) or len(set(required)) != len(required):
        raise ValueError('invalid required_platforms')
    projects, entries, ids, roots = [], [], set(), set()
    for item in config['projects']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
            raise ValueError('invalid project id')
        root = regression._relative(base, item['root'], 'project root')
        if not root.is_dir() or item['id'] in ids or root in roots:
            raise ValueError('missing or duplicate project')
        ids.add(item['id']); roots.add(root)
        loaded = regression.load_catalog(root, item['catalog'])
        rows = loaded['catalog']['scenarios']
        projects.append((item, root, rows))
        entries.extend(rows)
    scenario_ids = [row['id'] for row in entries]
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError('duplicate workspace scenario id')
    if platforms and set(platforms) - {row['platform'] for row in entries}:
        raise ValueError('unknown workspace platform')
    if scenarios and set(scenarios) - set(scenario_ids):
        raise ValueError('unknown workspace scenario')
    selected = []
    for item, root, rows in projects:
        matched = [row['id'] for row in rows if suite in row['suites']
                   and (not platforms or row['platform'] in platforms)
                   and (not scenarios or row['id'] in scenarios)]
        if matched:
            selection = regression.plan(root, item['catalog'], suite=suite, scenarios=matched)
            selected.append({'id': item['id'], 'root': str(root), 'catalog': item['catalog'], 'plan': selection})
    selected_ids = {row['id'] for _, _, rows in projects for row in rows
                    if suite in row['suites'] and (not platforms or row['platform'] in platforms)
                    and (not scenarios or row['id'] in scenarios)}
    coverage = {row['platform'] for row in entries if row['id'] in selected_ids}
    expected = set(platforms or ([] if scenarios else config.get('required_platforms', [])))
    if not selected or expected - coverage or (scenarios and set(scenarios) - selected_ids):
        raise ValueError('selection omits requested scenarios or required platforms')
    return {'schema_version': 1, 'official': False, 'full_completion': False,
            'authority': 'UNTRUSTED_REGRESSION_OBSERVATION', 'suite': suite,
            'workspace': str(config_path), 'workspace_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
            'coverage': sorted(coverage), 'scenario_ids': sorted(selected_ids), 'projects': selected}


def run(workspace_root, workspace, suite='smoke', platforms=None, scenarios=None, timeout=1800):
    selection = plan(workspace_root, workspace, suite, platforms, scenarios)
    sources = {p['id']: regression.runner.source_state(Path(p['root'])) for p in selection['projects']}
    identifier = uuid.uuid4().hex
    output = Path(__file__).resolve().parents[1] / 'verification/regression-workspaces' / identifier
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for project in selection['projects']:
        root = Path(project['root'])
        destination = root / 'verification/regression' / identifier
        ids = project['plan']['selection']['scenario_ids']
        try:
            current = regression.plan(root, project['catalog'], suite=suite, scenarios=ids)
            if current != project['plan']:
                raise ValueError('project selection changed since workspace plan')
            observation = regression.run(root, project['catalog'], destination, suite=suite,
                                         scenarios=ids, timeout=timeout)
            if regression.plan(root, project['catalog'], suite=suite, scenarios=ids) != project['plan']:
                raise ValueError('project selection changed during workspace run')
            path = destination / 'summary.json'
            results.append({'project': project['id'], 'result': observation['selection_result'],
                            'summary': str(path), 'summary_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        except Exception as error:
            results.append({'project': project['id'], 'result': 'FAIL', 'error': str(error)})
    try:
        unchanged = hashlib.sha256(Path(workspace).read_bytes()).hexdigest() == selection['workspace_sha256']
    except OSError:
        unchanged = False
    try:
        plans_consistent = all(regression.plan(Path(p['root']), p['catalog'], suite=suite, scenarios=p['plan']['selection']['scenario_ids']) == p['plan'] for p in selection['projects'])
    except (OSError, ValueError, KeyError, TypeError):
        plans_consistent = False
    source_consistent = all(regression.runner.source_state(Path(p['root'])) == sources[p['id']] for p in selection['projects'])
    selection.update(results=results, workspace_unchanged=unchanged, plans_consistent=plans_consistent, source_consistent=source_consistent, sources=sources,
                     selection_result='OBSERVED_PASS' if unchanged and plans_consistent and source_consistent and all(row['result'] == 'OBSERVED_PASS' for row in results) else 'FAIL')
    path = output / 'summary.json'
    path.write_text(json.dumps(selection, indent=2) + '\n')
    selection['summary'] = str(path)
    return selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'run'])
    parser.add_argument('--workspace-root', default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument('--workspace', default=str(Path(__file__).resolve().parents[1] / 'regression/workspace.json'))
    parser.add_argument('--suite', choices=['smoke', 'full'], default='smoke')
    parser.add_argument('--platform', action='append')
    parser.add_argument('--scenario', action='append')
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    try:
        function = run if args.action == 'run' else plan
        kwargs = {'timeout': args.timeout} if args.action == 'run' else {}
        result = function(args.workspace_root, args.workspace, args.suite, args.platform, args.scenario, **kwargs)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 1 if args.action == 'run' and result['selection_result'] != 'OBSERVED_PASS' else 0


if __name__ == '__main__':
    raise SystemExit(main())
