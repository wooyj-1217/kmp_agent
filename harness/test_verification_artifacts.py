"""Local evidence creation boundaries; no model or product validation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness.verification_artifacts import directory
from harness.qa import manifest


class VerificationArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_created_evidence_is_ignored_and_reuse_preserves_files(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        path = directory(self.root, 'manual', 'review')
        proof = path / 'proof.log'
        proof.write_text('original')
        self.assertEqual(directory(self.root, 'manual', 'review'), path)
        self.assertEqual(proof.read_text(), 'original')
        result = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=self.root, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, '')
        subprocess.run(['git', 'check-ignore', str(proof)], cwd=self.root, check=True, capture_output=True)

    def test_invalid_names_and_linked_output_are_rejected(self):
        for name in ('', '.', '..', '../escape', '/tmp/escape', 'a/b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                directory(self.root, name)
        (self.root / 'verification').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            directory(self.root, 'manual')
        self.assertFalse((self.root / 'outside').exists())

    def test_manifest_excludes_root_evidence_but_keeps_nested_source(self):
        directory(self.root, 'manual', 'review').joinpath('report.json').write_text('{}')
        nested = self.root / 'src/verification'
        nested.mkdir(parents=True)
        (nested / 'source.txt').write_text('product source')
        self.assertEqual(set(manifest(self.root)), {'src/verification/source.txt'})
        from harness.logging import snapshot
        self.assertEqual(set(snapshot(self.root)), {'src/verification/source.txt'})

    def test_cli_defaults_to_distinct_project_local_directories(self):
        argv = [sys.executable, '-B', '-m', 'harness.verification_artifacts', '--root', str(self.root)]
        paths = [Path(subprocess.check_output(argv, text=True).strip()) for _ in range(2)]
        self.assertNotEqual(*paths)
        self.assertTrue(all(p.is_dir() and p.parent == self.root / 'verification/manual' for p in paths))
