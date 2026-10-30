"""Project-owned verification instructions; validation never executes or certifies them."""
import argparse
import copy
import json
from pathlib import PurePosixPath, Path

PLATFORMS = ('android', 'ios', 'web', 'server')
DOCTOR_CHECKS = ('build', 'process', 'device', 'port', 'authentication', 'environment')


def _object(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(where + ' requires exactly: ' + ', '.join(keys))


def _text(value, where):
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in {'TODO', 'UNKNOWN', 'TBD'}:
        raise ValueError(where + ' requires a concrete instruction or explicit non-applicability reason')


def _texts(value, where):
    if not isinstance(value, list) or not value:
        raise ValueError(where + ' requires nonempty instructions')
    for item in value:
        _text(item, where)


def _path(value, where):
    _text(value, where)
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or value != path.as_posix() or str(path) == '.':
        raise ValueError(where + ' must be a normalized project-relative path')
    return path


def validate(data):
    """Validate an instruction artifact, returning a copy. This is not execution PASS.

    A caller freezes the returned document with the existing Tasks.artifact API.
    Runtime results must separately bind its SHA, platform, criteria and evidence.
    """
    _object(data, ('schema_version', 'owner', 'platforms'), 'procedure')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('unsupported verification procedure schema')
    _text(data['owner'], 'owner')
    _object(data['platforms'], PLATFORMS, 'platforms')
    for platform, config in data['platforms'].items():
        _object(config, ('required', 'reason', 'procedure'), platform)
        if type(config['required']) is not bool:
            raise ValueError(platform + '.required must be boolean')
        _text(config['reason'], platform + '.reason')
        procedure = config['procedure']
        if procedure is None and not config['required']:
            continue
        _object(procedure, ('launch', 'doctor', 'drive', 'evidence', 'cleanup', 'feature_map'), platform)
        launch = procedure['launch']
        _object(launch, ('commands', 'ready_when', 'initial_data'), platform + '.launch')
        _texts(launch['commands'], 'launch.commands')
        _text(launch['ready_when'], 'launch.ready_when')
        _text(launch['initial_data'], 'launch.initial_data')
        _object(procedure['doctor'], DOCTOR_CHECKS, 'doctor')
        for key, instruction in procedure['doctor'].items():
            _text(instruction, 'doctor.' + key)
        drive = procedure['drive']
        if not isinstance(drive, list) or not drive:
            raise ValueError('drive requires user operations, not a build-only claim')
        ids = set()
        for step in drive:
            _object(step, ('id', 'action', 'expected', 'side_effects', 'evidence'), 'drive step')
            for key in ('id', 'action', 'expected', 'side_effects'):
                _text(step[key], 'drive.' + key)
            if step['id'] in ids:
                raise ValueError('drive step IDs must be unique')
            ids.add(step['id'])
            _texts(step['evidence'], 'drive.evidence')
        evidence = procedure['evidence']
        _object(evidence, ('paths', 'capture', 'verify_after_cleanup'), 'evidence')
        _texts(evidence['paths'], 'evidence.paths')
        paths = [_path(p, 'evidence.paths') for p in evidence['paths']]
        _text(evidence['capture'], 'evidence.capture')
        _text(evidence['verify_after_cleanup'], 'evidence.verify_after_cleanup')
        cleanup = procedure['cleanup']
        _object(cleanup, ('commands', 'owned_resources', 'temporary_paths', 'preserve_evidence'), 'cleanup')
        _texts(cleanup['commands'], 'cleanup.commands')
        _texts(cleanup['owned_resources'], 'cleanup.owned_resources')
        if cleanup['preserve_evidence'] is not True:
            raise ValueError('cleanup must preserve evidence')
        if not isinstance(cleanup['temporary_paths'], list):
            raise ValueError('cleanup.temporary_paths must be an explicit list')
        temporary = [_path(p, 'cleanup.temporary_paths') for p in cleanup['temporary_paths']]
        if any(e == t or t in e.parents or e in t.parents for e in paths for t in temporary):
            raise ValueError('cleanup temporary paths must be disjoint from evidence paths')
        features = procedure['feature_map']
        if not isinstance(features, list) or not features:
            raise ValueError('feature_map requires feature entry paths')
        seen = set()
        for feature in features:
            _object(feature, ('id', 'entry', 'preconditions', 'success', 'cautions', 'drive_steps'), 'feature')
            for key in ('id', 'entry', 'preconditions', 'success', 'cautions'):
                _text(feature[key], 'feature.' + key)
            if feature['id'] in seen:
                raise ValueError('feature IDs must be unique')
            seen.add(feature['id'])
            _texts(feature['drive_steps'], 'feature.drive_steps')
            if not set(feature['drive_steps']).issubset(ids):
                raise ValueError('feature references unknown drive step')
        if ids != {step for feature in features for step in feature['drive_steps']}:
            raise ValueError('each drive step must belong to the feature map')
    return copy.deepcopy(data)


def template(required_platforms, owner):
    """Generate an intentionally incomplete draft, never an executable recipe or PASS."""
    if not isinstance(required_platforms, list) or not required_platforms or len(set(required_platforms)) != len(required_platforms) or not set(required_platforms).issubset(PLATFORMS):
        raise ValueError('select distinct required platforms: ' + ', '.join(PLATFORMS))
    _text(owner, 'owner')
    procedure = {
        'launch': {'commands': ['TODO'], 'ready_when': 'TODO', 'initial_data': 'TODO'},
        'doctor': {key: 'TODO' for key in DOCTOR_CHECKS},
        'drive': [{'id': 'STEP-1', 'action': 'TODO', 'expected': 'TODO', 'side_effects': 'TODO', 'evidence': ['TODO']}],
        'evidence': {'paths': ['TODO'], 'capture': 'TODO', 'verify_after_cleanup': 'TODO'},
        'cleanup': {'commands': ['TODO'], 'owned_resources': ['TODO'], 'temporary_paths': [], 'preserve_evidence': True},
        'feature_map': [{'id': 'FEATURE-1', 'entry': 'TODO', 'preconditions': 'TODO', 'success': 'TODO', 'cautions': 'TODO', 'drive_steps': ['STEP-1']}],
    }
    return {'schema_version': 1, 'owner': owner, 'platforms': {
        platform: {'required': platform in required_platforms, 'reason': 'TODO',
                   'procedure': copy.deepcopy(procedure) if platform in required_platforms else None}
        for platform in PLATFORMS}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    generate = sub.add_parser('generate')
    generate.add_argument('--platform', action='append', choices=PLATFORMS, required=True)
    generate.add_argument('--owner', required=True)
    check = sub.add_parser('check')
    check.add_argument('path', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'generate':
            print(json.dumps(template(args.platform, args.owner), ensure_ascii=False, indent=2))
        else:
            validate(json.loads(args.path.read_text()))
            print(json.dumps({'procedure': str(args.path), 'format': 'VALID', 'execution': 'NOT_RUN'}, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
