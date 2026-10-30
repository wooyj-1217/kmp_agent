import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from harness.verification_procedure import main, template, validate


def example():
    data = template(['web'], 'project QA owner')
    for config in data['platforms'].values():
        config['reason'] = 'Project declares this platform in scope' if config['required'] else 'Project has no such client'
    procedure = data['platforms']['web']['procedure']
    procedure['launch'] = {'commands': ['Run project launcher on private port 8109'], 'ready_when': 'Health probe returns project build identity', 'initial_data': 'Seed one note in a private data directory'}
    procedure['doctor'] = {key: 'Check project-owned ' + key + ' identity; stop on mismatch' for key in procedure['doctor']}
    procedure['drive'] = [{'id': 'CREATE', 'action': 'Open composer, type a title, press Save, reload', 'expected': 'The saved title is visible after reload', 'side_effects': 'Inspect private note storage for exactly one new note', 'evidence': ['Capture before/save/reload and storage diff']}]
    procedure['feature_map'] = [{'id': 'NOTE', 'entry': '/notes then New', 'preconditions': 'Private empty store, signed in test user', 'success': 'Saved note survives reload', 'cautions': 'Do not use a personal store', 'drive_steps': ['CREATE']}]
    procedure['evidence'] = {'paths': ['qa-evidence/web'], 'capture': 'Save interaction trace, screenshots and storage diff with hashes', 'verify_after_cleanup': 'Reopen captured files and check frozen hashes after cleanup'}
    procedure['cleanup'] = {'commands': ['Stop the PID created by launch, then delete its private seeded store'], 'owned_resources': ['Launcher PID receipt and private store from this run'], 'temporary_paths': ['qa-temp/web'], 'preserve_evidence': True}
    return data


class VerificationProcedureTests(unittest.TestCase):
    def test_generated_draft_is_not_validated_or_executed(self):
        with self.assertRaises(ValueError):
            validate(template(['android', 'ios', 'web', 'server'], 'QA'))

    def test_valid_procedure_copy_and_cli_never_claim_execution(self):
        data = example()
        self.assertEqual(validate(data), data)
        validate(data)['owner'] = 'other'
        self.assertEqual(data['owner'], 'project QA owner')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'procedure.json'
            path.write_text(json.dumps(data))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(['check', str(path)])
            self.assertEqual(json.loads(output.getvalue())['execution'], 'NOT_RUN')

    def test_all_platform_requirements_are_explicit(self):
        for mutation in (
            lambda d: d['platforms'].pop('ios'),
            lambda d: d['platforms']['android'].update(required=True),
            lambda d: d['platforms']['server'].update(required='false'),
            lambda d: d['platforms']['ios'].update(reason=''),
        ):
            data = example()
            mutation(data)
            with self.assertRaises(ValueError):
                validate(data)

    def test_each_phase_and_identity_check_is_required(self):
        for section in ('launch', 'doctor', 'drive', 'evidence', 'cleanup', 'feature_map'):
            data = example()
            data['platforms']['web']['procedure'].pop(section)
            with self.assertRaises(ValueError):
                validate(data)
        for key in ('build', 'process', 'device', 'port', 'authentication', 'environment'):
            data = example()
            data['platforms']['web']['procedure']['doctor'][key] = 'UNKNOWN'
            with self.assertRaises(ValueError):
                validate(data)

    def test_build_only_and_unmapped_steps_rejected(self):
        for change in ('empty', 'unknown', 'duplicate', 'unmapped'):
            data = example()
            procedure = data['platforms']['web']['procedure']
            if change == 'empty':
                procedure['drive'] = []
            elif change == 'unknown':
                procedure['feature_map'][0]['drive_steps'] = ['MISSING']
            elif change == 'duplicate':
                procedure['drive'].append(copy.deepcopy(procedure['drive'][0]))
            else:
                procedure['drive'].append({**procedure['drive'][0], 'id': 'UNMAPPED'})
            with self.assertRaises(ValueError):
                validate(data)

    def test_cleanup_cannot_cover_or_be_inside_evidence(self):
        for temporary in ('qa-evidence', 'qa-evidence/web', 'qa-evidence/web/temporary', '../outside', '/tmp/all', '.'):
            data = example()
            data['platforms']['web']['procedure']['cleanup']['temporary_paths'] = [temporary]
            with self.assertRaises(ValueError):
                validate(data)
        data = example()
        data['platforms']['web']['procedure']['cleanup']['preserve_evidence'] = False
        with self.assertRaises(ValueError):
            validate(data)

    def test_no_silent_unknown_fields_or_schema_coercion(self):
        for change in ('version', 'extra', 'blank_action', 'missing_effect'):
            data = example()
            if change == 'version':
                data['schema_version'] = True
            elif change == 'extra':
                data['executed'] = True
            elif change == 'blank_action':
                data['platforms']['web']['procedure']['drive'][0]['action'] = ' '
            else:
                data['platforms']['web']['procedure']['drive'][0].pop('side_effects')
            with self.assertRaises(ValueError):
                validate(data)


if __name__ == '__main__':
    unittest.main()
