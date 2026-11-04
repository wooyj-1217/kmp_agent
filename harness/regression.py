"""Project-local regression catalog orchestration, never official certification."""
import argparse
import copy
import json
import math
from pathlib import Path
import uuid

from harness import verification_runner as runner


PLATFORMS = {'common', 'android', 'ios', 'web', 'server'}
SUITES = {'smoke', 'full'}
AUTHORITY = 'UNTRUSTED_REGRESSION_OBSERVATION'


def _json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def _relative(root, value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be a project-relative path')
    relative = Path(value)
    if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != value:
        raise ValueError(label + ' must be a normalized project-relative path')
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(label + ' escapes project root')
    return resolved


def load_catalog(root, catalog_path):
    """Load and validate the entire catalog, including unselected definitions."""
    root = Path(root).resolve()
    path = _relative(root, str(catalog_path), 'catalog')
    catalog = _json(path)
    if not isinstance(catalog, dict) or type(catalog.get('schema_version')) is not int or catalog['schema_version'] != 1:
        raise ValueError('catalog schema_version must be 1')
    if not isinstance(catalog.get('scenarios'), list) or not catalog['scenarios']:
        raise ValueError('catalog scenarios must be a nonempty list')
    ids, bindings, definitions = set(), set(), {}
    for scenario in catalog['scenarios']:
        if not isinstance(scenario, dict):
            raise ValueError('scenario must be an object')
        for key in ('id', 'criterion_id', 'platform', 'tool', 'scope', 'definition', 'check_id', 'owner'):
            if not isinstance(scenario.get(key), str) or not scenario[key].strip():
                raise ValueError('scenario ' + key + ' required')
        if scenario['id'] in ids:
            raise ValueError('duplicate scenario id: ' + scenario['id'])
        ids.add(scenario['id'])
        if scenario['platform'] not in PLATFORMS:
            raise ValueError('unknown scenario platform: ' + scenario['platform'])
        suites = scenario.get('suites')
        if not isinstance(suites, list) or not suites or not all(isinstance(suite, str) for suite in suites) or len(set(suites)) != len(suites) or not set(suites).issubset(SUITES):
            raise ValueError('scenario suites must be distinct smoke/full names')
        if scenario.get('required') is not True:
            raise ValueError('catalog scenarios must explicitly be required')
        definition_path = _relative(root, scenario['definition'], 'definition')
        relative = str(definition_path.relative_to(root))
        binding = (relative, scenario['check_id'])
        if binding in bindings:
            raise ValueError('duplicate definition/check binding: ' + repr(binding))
        bindings.add(binding)
        if relative not in definitions:
            definition = _json(definition_path)
            try:
                runner.validate_definition(definition)
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                raise ValueError('invalid verification definition: ' + str(error)) from error
            definitions[relative] = {'definition': definition, 'file_sha256': runner.digest(definition_path.read_bytes()),
                                     'definition_sha256': runner.digest(runner.canonical(definition))}
        checks = definitions[relative]['definition']['checks']
        check = next((check for check in checks if check['id'] == scenario['check_id']), None)
        if check is None:
            raise ValueError('unknown check binding: ' + scenario['check_id'])
        if check['platform'] != scenario['platform'] or check['criterion_id'] != scenario['criterion_id']:
            raise ValueError('scenario platform/criterion does not match definition check')
        if check['required'] is not True:
            raise ValueError('catalog required check must be required in original definition')
    return {'catalog': catalog, 'catalog_path': str(path.relative_to(root)),
            'catalog_file_sha256': runner.digest(path.read_bytes()),
            'catalog_sha256': runner.digest(runner.canonical(catalog)), 'definitions': definitions}


def _filters(values, allowed, label):
    if values is None:
        return None
    if not isinstance(values, (list, tuple)) or not values or not all(isinstance(value, str) for value in values) or len(set(values)) != len(values):
        raise ValueError(label + ' filters must be distinct nonempty names')
    if set(values) - allowed:
        raise ValueError('unknown ' + label + ': ' + ', '.join(sorted(set(values) - allowed)))
    return set(values)


def _output_path(root, output):
    value = Path(output)
    if value.is_absolute():
        try:
            value = value.relative_to(root)
        except ValueError:
            raise ValueError('output must be inside project verification/') from None
    target = _relative(root, value.as_posix(), 'output')
    relative = value.parts
    if len(relative) < 2 or relative[0] != 'verification':
        raise ValueError('output must be a new directory inside project verification/')
    current = root
    for part in relative:
        current /= part
        if current.is_symlink():
            raise ValueError('output path must not contain symlinks')
    if target.exists():
        raise ValueError('output already exists; regression receipts cannot be overwritten')
    return target


def plan(root, catalog_path, suite='smoke', platforms=None, scenarios=None, output=None):
    """Read-only selection and provenance. Optional output is only a planned path."""
    root = Path(root).resolve()
    loaded = load_catalog(root, catalog_path)
    if suite not in SUITES:
        raise ValueError('unknown suite: ' + str(suite))
    platform_filter = _filters(platforms, PLATFORMS, 'platform')
    scenario_filter = _filters(scenarios, {row['id'] for row in loaded['catalog']['scenarios']}, 'scenario')
    selected = [row for row in loaded['catalog']['scenarios'] if suite in row['suites'] and
                (platform_filter is None or row['platform'] in platform_filter) and
                (scenario_filter is None or row['id'] in scenario_filter)]
    if not selected:
        raise ValueError('selection contains zero scenarios')
    if scenario_filter is not None and scenario_filter != {row['id'] for row in selected}:
        raise ValueError('requested scenario excluded by suite/platform filters')
    if platform_filter is not None and platform_filter != {row['platform'] for row in selected}:
        raise ValueError('requested platform has zero selected scenarios')
    groups = []
    selected_commands = set()
    for path, source in loaded['definitions'].items():
        bound = [row for row in selected if str((root/row['definition']).resolve().relative_to(root)) == path]
        if not bound:
            continue
        ids = {row['check_id'] for row in bound}
        compiled = copy.deepcopy(source['definition'])
        compiled['checks'] = [check for check in compiled['checks'] if check['id'] in ids]
        commands = [tuple(check['command']) for check in compiled['checks']]
        if len(commands) != len(set(commands)) or selected_commands.intersection(commands):
            raise ValueError('selected checks share a command; split the approved commands to avoid duplicate execution')
        selected_commands.update(commands)
        groups.append({'definition_path': path, 'original_plan_version': source['definition']['plan_version'],
                       'original_definition_sha256': source['definition_sha256'],
                       'original_definition_file_sha256': source['file_sha256'],
                       'selected_definition_sha256': runner.digest(runner.canonical(compiled)),
                       'selected_definition': compiled, 'scenarios': copy.deepcopy(bound),
                       'excluded_check_ids': [check['id'] for check in source['definition']['checks'] if check['id'] not in ids]})
    result = {key: loaded[key] for key in ('catalog_path', 'catalog_sha256', 'catalog_file_sha256')}
    result.update(schema_version=1, authority=AUTHORITY, official=False, full_completion=False,
                  selection={'suite': suite, 'platforms': sorted({row['platform'] for row in selected}),
                             'scenario_ids': [row['id'] for row in selected]}, groups=groups)
    if output is not None:
        result['planned_output'] = str(_output_path(root, output).relative_to(root))
    return result


def _write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def run(root, catalog_path, output, suite='smoke', platforms=None, scenarios=None, timeout=300):
    """Execute only selected checks. No official approval or full-product claim."""
    root = Path(root).resolve()
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be positive')
    selected = plan(root, catalog_path, suite, platforms, scenarios, output)
    target = _output_path(root, output)
    target.mkdir(parents=True, exist_ok=False)
    # The generated receipt tree is observation data, not submitted source.
    (target/'.gitignore').write_text('*\n')
    _write(target/'plan.json', selected)
    summary = {key: selected[key] for key in ('schema_version', 'authority', 'official', 'full_completion', 'catalog_path',
               'catalog_sha256', 'catalog_file_sha256', 'selection')}
    summary.update(run_id=uuid.uuid4().hex, groups=[], scenarios=[], platforms={})
    baseline = runner.source_state(root)
    summary['source_baseline'] = baseline
    for number, group in enumerate(selected['groups'], 1):
        location = target/('group-' + str(number))
        location.mkdir()
        _write(location/'selected-definition.json', group['selected_definition'])
        failure = None
        try:
            receipt = runner.run_verification(group['selected_definition'], root, timeout=timeout)
        except Exception as error:
            failure = str(error)
            receipt = {'authority': 'UNTRUSTED_OBSERVATION', 'checks': [], 'error': failure}
        _write(location/'receipt.json', receipt)
        details = {key: group[key] for key in ('definition_path', 'original_plan_version', 'original_definition_sha256',
                   'original_definition_file_sha256', 'selected_definition_sha256', 'excluded_check_ids')}
        details.update(receipt_path=str((location/'receipt.json').relative_to(root)),
                       receipt_sha256=runner.digest((location/'receipt.json').read_bytes()),
                       source=receipt.get('source'), source_after=receipt.get('source_after'))
        summary['groups'].append(details)
        observations = receipt.get('checks', [])
        expected_ids = {row['check_id'] for row in group['scenarios']}
        valid_rows = isinstance(observations, list) and all(isinstance(row, dict) and row.get('id') in expected_ids for row in observations)
        valid_rows = valid_rows and len({row['id'] for row in observations}) == len(observations)
        identity_valid = (receipt.get('definition_sha256') == group['selected_definition_sha256'] and
                            receipt.get('plan_version') == group['original_plan_version'] and
                            isinstance(receipt.get('source'), dict) and receipt['source'].get('manifest_sha256') is not None and
                            isinstance(receipt.get('source_after'), dict))
        source_stable = identity_valid and receipt['source'].get('manifest_sha256') == receipt['source_after'].get('manifest_sha256') and receipt['source'].get('commit') == receipt['source_after'].get('commit')
        provenance_valid = identity_valid and source_stable
        details['provenance_valid'] = provenance_valid
        for scenario in group['scenarios']:
            matches = [row for row in observations if isinstance(row, dict) and row.get('id') == scenario['check_id']] if isinstance(observations, list) else []
            row = copy.deepcopy(matches[0]) if len(matches) == 1 and valid_rows else None
            reason = 'RUNNER_ERROR' if failure else 'RUNNER_RESULT_INVALID' if not valid_rows else 'RUNNER_RESULT_MISSING'
            if row is None:
                row = {'id': scenario['check_id'], 'result': 'NOT_RUN', 'status': 'NOT_RUN', 'reason': reason}
            expected = next(check for check in group['selected_definition']['checks'] if check['id'] == scenario['check_id'])
            binding_valid = all(row.get(key) == expected[key] for key in ('criterion_id', 'platform', 'kind', 'command', 'required', 'expected')) if matches else False
            result = row.get('result', row.get('status', 'NOT_RUN'))
            indexed_reason = row.get('reason')
            status_matches = row.get('status', result) == result
            if matches and valid_rows and (not identity_valid or (result == 'OBSERVED_PASS' and not source_stable) or not binding_valid or not status_matches or result not in {'OBSERVED_PASS', 'FAIL', 'NOT_RUN'}):
                result, indexed_reason = 'NOT_RUN', 'RUNNER_PROVENANCE_MISMATCH'
            indexed = {**copy.deepcopy(scenario), 'definition_path': group['definition_path'],
                       'original_plan_version': group['original_plan_version'],
                       'original_definition_sha256': group['original_definition_sha256'],
                       'result': result, 'reason': indexed_reason,
                       'source': receipt.get('source'), 'observation': row,
                       'receipt_path': details['receipt_path'], 'receipt_sha256': details['receipt_sha256']}
            summary['scenarios'].append(indexed)
    # Definitions may themselves be ignored files. Recheck them independently of
    # the code manifest before reporting the selected regression observations.
    inputs_changed = []
    def current_hash(path):
        try:
            return runner.digest(path.read_bytes())
        except OSError:
            return None
    if current_hash(root/selected['catalog_path']) != selected['catalog_file_sha256']:
        inputs_changed.append(selected['catalog_path'])
    for group in selected['groups']:
        if current_hash(root/group['definition_path']) != group['original_definition_file_sha256']:
            inputs_changed.append(group['definition_path'])
    summary['changed_regression_inputs'] = inputs_changed
    if inputs_changed:
        for row in summary['scenarios']:
            if row['result'] == 'OBSERVED_PASS':
                row.update(result='NOT_RUN', reason='REGRESSION_INPUT_CHANGED_DURING_EXECUTION')
    final_source = runner.source_state(root)
    summary['source_final'] = final_source
    def source_identity(source):
        if not isinstance(source, dict) or not source.get('commit') or not source.get('manifest_sha256'):
            return None
        return source['commit'], source['manifest_sha256']
    baseline_identity = source_identity(baseline)
    mismatched_groups = [group['definition_path'] for group in summary['groups']
        if baseline_identity is None or source_identity(group['source']) != baseline_identity or
        source_identity(group['source_after']) != baseline_identity]
    summary['source_consistent'] = (baseline_identity is not None and not mismatched_groups and
                                    source_identity(final_source) == baseline_identity)
    summary['source_mismatched_groups'] = mismatched_groups
    if not summary['source_consistent']:
        reason = 'SOURCE_IDENTITY_UNAVAILABLE' if baseline_identity is None else 'SOURCE_CHANGED_DURING_REGRESSION'
        for row in summary['scenarios']:
            if row['result'] == 'OBSERVED_PASS':
                row.update(result='NOT_RUN', reason=reason)
    for platform in selected['selection']['platforms']:
        rows = [row for row in summary['scenarios'] if row['platform'] == platform]
        statuses = [row['result'] for row in rows]
        summary['platforms'][platform] = {'result': 'OBSERVED_PASS' if all(status == 'OBSERVED_PASS' for status in statuses)
            else 'FAIL' if 'FAIL' in statuses else 'NOT_RUN', 'scenario_ids': [row['id'] for row in rows]}
    summary['selection_result'] = 'OBSERVED_PASS' if all(row['result'] == 'OBSERVED_PASS' for row in summary['scenarios']) else 'FAIL' if any(row['result'] == 'FAIL' for row in summary['scenarios']) else 'NOT_RUN'
    summary['result'] = summary['selection_result']
    _write(target/'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'run'])
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--suite', choices=sorted(SUITES), default='smoke')
    parser.add_argument('--platform', action='append')
    parser.add_argument('--scenario', action='append')
    parser.add_argument('--output')
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args(argv)
    if args.action == 'run' and not args.output:
        parser.error('run requires --output verification/<new-run-directory>')
    try:
        result = plan(args.root, args.catalog, args.suite, args.platform, args.scenario, args.output) if args.action == 'list' else run(
            args.root, args.catalog, args.output, args.suite, args.platform, args.scenario, args.timeout)
    except (ValueError, OSError, TypeError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if args.action == 'list' or result['selection_result'] == 'OBSERVED_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
