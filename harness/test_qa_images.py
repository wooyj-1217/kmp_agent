"""Mock transport and native snapshot tests; no real model/image understanding claimed."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.delegation_runtime import run_codex
from harness.logging import Logger
from harness.qa import QA
from harness.roles import Roles
from harness.tasks import Tasks


PNG = b'\x89PNG\r\n\x1a\nsynthetic image fixture'


class QAImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'request.md').write_text('Synthetic original requirement')
        (self.root / 'design').mkdir()
        (self.root / 'design/capture.png').write_bytes(PNG)
        self.run = Logger(self.root).start('HARNESS_BUILD', 'orchestrator', 'synthetic image transport')
        self.tasks = Tasks(self.root, self.run)
        self.tasks.register('F', 'TARGET', 'design', 'Design fixture', 'document only',
                            [{'id': 'AC', 'required': True, 'description': 'Review design'}],
                            ['request.md'], execution_scope='documentation')
        self.qa = QA(self.root, self.run)

    def configure(self):
        return self.qa.configure('QA', 'design', 'TARGET', ['request.md'],
                                 [{'id': 'Q', 'required': True, 'description': 'Review capture'}],
                                 images=['design/capture.png'])

    def begin(self):
        self.configure()
        self.tasks.ready('QA')
        return self.tasks.begin('QA', 'verification')['agent_run_id']

    def test_image_is_frozen_input_and_target_scope(self):
        config = self.configure()
        ref = config['images'][0]
        self.assertEqual(ref['path'], 'design/capture.png')
        self.assertEqual(ref['sha256'], hashlib.sha256(PNG).hexdigest())
        self.assertIn('design/capture.png', config['manifest_scope']['paths'])
        self.assertEqual(config['target_manifest']['design/capture.png'], ref['sha256'])
        inputs = self.tasks.read()['tasks']['QA']['inputs']
        frozen = next(r for r in inputs if r['path'] == 'design/capture.png')
        (self.root / 'design/capture.png').write_bytes(PNG + b'changed')
        self.assertEqual((self.root / frozen['snapshot']).read_bytes(), PNG)
        with self.assertRaisesRegex(ValueError, 'target changed'):
            self.qa.execute('QA', worker=lambda *_: self.fail('changed image reached QA worker'))

    def test_mock_popen_receives_image_and_hashed_attachment_manifest(self):
        aid = self.begin()
        received = []
        class Child:
            pid = 987654
            returncode = 0
            def __init__(self, argv, **kwargs):
                received.extend(argv)
                Path(argv[argv.index('-o') + 1]).write_text('{}')
            def communicate(self, *args, **kwargs):
                return '', ''
        output = self.root / 'runtime-evidence'
        with patch('harness.delegation_runtime.subprocess.Popen', Child), \
                patch.object(Roles, 'collect_codex', return_value={'usage': 'UNKNOWN'}):
            result = run_codex(self.tasks, 'QA', aid, self.root, {}, output, 'mock-native', 5,
                               image_paths=['design/capture.png'], result_schema={'type': 'object'},
                               result_validator=lambda value: value)
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(received[received.index('--image') + 1], str(self.root / 'design/capture.png'))
        self.assertEqual(received[-1], '-')
        manifest = json.loads((output / 'attached-images.json').read_text())
        self.assertEqual(manifest, [{'path': 'design/capture.png', 'sha256': hashlib.sha256(PNG).hexdigest()}])
        self.assertEqual(result['usage_status'], 'UNKNOWN')

    def test_execution_context_frozen_separately_from_original_user_requests(self):
        evidence = self.root / 'execution-result.json'
        original = b'{"status":"PASS","source":"synthetic command evidence"}\n'
        evidence.write_bytes(original)
        config = self.qa.configure('QA', 'implementation', 'TARGET', ['request.md'],
                                   [{'id': 'Q', 'required': True, 'description': 'Review execution evidence'}],
                                   context_files=['execution-result.json'])
        self.assertEqual([ref['path'] for ref in config['original_requests']], ['request.md'])
        self.assertEqual([ref['path'] for ref in config['context_artifacts']], ['execution-result.json'])
        expected_hash = hashlib.sha256(original).hexdigest()
        self.assertEqual(config['context_artifacts'][0]['sha256'], expected_hash)
        self.assertIn('execution-result.json', config['manifest_scope']['paths'])
        self.assertEqual(config['target_manifest']['execution-result.json'], expected_hash)
        inputs = self.tasks.read()['tasks']['QA']['inputs']
        frozen = next(ref for ref in inputs if ref['path'] == 'execution-result.json')
        self.assertEqual(frozen['sha256'], expected_hash)
        evidence.write_text('{"status":"changed"}')
        self.assertEqual((self.root / frozen['snapshot']).read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'target changed'):
            self.qa.execute('QA', worker=lambda *_: self.fail('changed evidence reached QA worker'))

    def test_invalid_path_extension_and_bytes_never_spawn(self):
        aid = self.begin()
        cases = [('missing.png', None), ('../outside.png', None),
                 ('design/plain.png', b'not an image'), ('design/disguised.txt', PNG),
                 ('design/wrong.jpg', PNG)]
        for index, (path, raw) in enumerate(cases):
            if raw is not None:
                (self.root / path).write_bytes(raw)
            with self.subTest(path=path), patch('harness.delegation_runtime.subprocess.Popen') as popen:
                with self.assertRaises(ValueError):
                    run_codex(self.tasks, 'QA', aid, self.root, {}, self.root / f'invalid-{index}',
                              'mock-native', 5, image_paths=[path])
                popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
