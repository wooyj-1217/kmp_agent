"""Opt-in, frozen agreement/state checks; never reinterpret historical PASS.

Reviews are human/agent attestations, not an automatic stack detector or screenshot diff.
The contract must be an existing frozen task input named acceptance-contract.json.
"""
import json
from pathlib import Path


def valid(manager, ref):
    try:
        return manager._valid_artifact(ref)
    except (OSError, KeyError, TypeError):
        return False


def review_gate(manager, task, results):
    contracts = [a for a in task.get('inputs', []) if Path(a.get('path', '')).name == 'acceptance-contract.json']
    if not contracts:
        return  # Historical evidence retains its original meaning; not certified compliant.
    if len(contracts) != 1 or not valid(manager, contracts[0]):
        raise ValueError('one valid frozen acceptance contract is required')
    contract = json.loads((manager.root / contracts[0]['snapshot']).read_text())
    agreements = contract.get('agreements', [])
    states = contract.get('state_comparisons', [])
    checks = agreements + states
    if contract.get('schema_version') != 1 or not checks or len({c['id'] for c in checks}) != len(checks):
        raise ValueError('acceptance contract requires unique agreement/state checks')
    criteria = {c['id'] for c in task.get('criteria', []) if c.get('required')}
    if any(c.get('criterion_id') not in criteria for c in checks):
        raise ValueError('acceptance checks must bind required criteria')
    for c in agreements:
        if c.get('authority') not in {'USER_DECISION', 'EXPLICIT_DELEGATION'} or not c.get('expected') or not c.get('decision_basis'):
            raise ValueError('agreement requires original authority, expected target and decision basis')
        if c.get('changes_explicit_agreement') and c.get('authority') != 'USER_DECISION':
            raise ValueError('generic technical delegation cannot change explicit agreement')
        if not valid(manager, c.get('source', {})):
            raise ValueError('original agreement evidence missing')
    for c in states:
        if not all(c.get(k) for k in ('screen', 'state', 'platform', 'expected')) or not valid(manager, c.get('approved_design', {})):
            raise ValueError('state comparison requires approved design, screen/state/platform and expectation')
    expected_outputs = {a['path']: a['sha256'] for a in task.get('outputs', [])}
    for result in results:
        relevant = [c for c in checks if c['criterion_id'] == result['criterion_id']]
        if result.get('result') != 'PASS' or not relevant:
            continue
        report = json.loads((manager.root / result['evidence']['snapshot']).read_text())
        if report.get('tested_outputs') != expected_outputs or report.get('acceptance_contract_sha256') != contracts[0]['sha256']:
            raise ValueError('acceptance PASS must bind exact contract and tested outputs')
        observations = report.get('acceptance_checks', {})
        for check in relevant:
            observed = observations.get(check['id'], {})
            if observed.get('result') != 'PASS' or not observed.get('observations') or observed.get('method') not in {'AUTOMATED_TEST', 'AGENT_REVIEW', 'USER_CONFIRMATION'}:
                raise ValueError('functional PASS does not establish agreement/state comparison PASS')
            evidence = observed.get('evidence', [])
            if not evidence or not all(valid(manager, a) for a in evidence):
                raise ValueError('acceptance check requires immutable observation evidence')
            if check in states and (observed.get('screen'), observed.get('state'), observed.get('platform'), observed.get('approved_design_sha256')) != (check['screen'], check['state'], check['platform'], check['approved_design']['sha256']):
                raise ValueError('state capture must match exact screen/state/platform/design')
