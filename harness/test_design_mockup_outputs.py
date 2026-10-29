"""Synthetic native task gate regressions; not visual or independent model QA."""
import tempfile
from pathlib import Path
import unittest

from harness import logging
from harness.development_tracking import document_outputs
from harness.tasks import Tasks


MOCKUP = {'specification': 'COMPLETE', 'mockup': 'COMPLETE', 'visual_review': 'NOT_RUN'}


class DesignMockupOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'input.md').write_text('Original synthetic design scope')
        self.run = logging.Logger(self.root).start('HARNESS_BUILD', 'orchestrator', 'synthetic mockup gates')
        self.tasks = Tasks(self.root, self.run)

    def task(self, role='design'):
        self.tasks.register('F', 'T', role, 'Synthetic artifact', 'documentation only',
                            [{'id': 'AC', 'required': True, 'text': 'Submit artifact, visual review remains pending'}],
                            ['input.md'], execution_scope='documentation')
        self.tasks.ready('T')
        return self.tasks.begin('T', role)['agent_run_id']

    def test_normal_documentation_rejects_source(self):
        for role in ('planning', 'design', 'verification'):
            for suffix in ('.kt', '.js'):
                with self.subTest(role=role, suffix=suffix), self.assertRaises(ValueError):
                    document_outputs({'role': role, 'execution_scope': 'documentation'}, ['output' + suffix])

    def test_development_cannot_use_design_mockup_escape(self):
        task = {'role': 'development', 'execution_scope': 'documentation'}
        for path in ('index.html', 'style.css', 'app.js', 'Main.kt'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                document_outputs(task, [path], MOCKUP)

    def test_design_requires_explicit_complete_mockup_and_unreviewed_status(self):
        for status in (None, {}, {'mockup': 'IN_PROGRESS', 'visual_review': 'NOT_RUN'},
                       {'mockup': 'COMPLETE'}, {'mockup': 'COMPLETE', 'visual_review': 'PASS'}):
            with self.subTest(status=status), self.assertRaises(ValueError):
                document_outputs({'role': 'design', 'execution_scope': 'documentation'}, ['index.html'], status)

    def test_native_design_submission_accepts_prototype_assets_without_visual_pass(self):
        aid = self.task()
        paths = ['index.html', 'style.css', 'app.js', 'icon.svg', 'capture.png', 'photo.jpg',
                 'photo.jpeg', 'capture.webp', 'design.md']
        for path in paths:
            (self.root / path).write_text('synthetic artifact; no image rendering claimed')
        self.tasks.submit('T', aid, paths, 'prototype produced, review pending', MOCKUP)
        task = self.tasks.read()['tasks']['T']
        self.assertEqual(task['state'], 'IN_REVIEW')
        self.assertEqual(task['design_status']['mockup'], 'COMPLETE')
        self.assertEqual(task['design_status']['visual_review'], 'NOT_RUN')
        self.assertIsNone(task['design_status']['visual_evidence'])
        self.assertEqual({ref['path'] for ref in task['outputs']}, set(paths))

    def test_native_submit_rejects_self_reported_visual_pass(self):
        aid = self.task()
        (self.root / 'design.md').write_text('Synthetic specification')
        with self.assertRaisesRegex(ValueError, 'separate visual review'):
            self.tasks.submit('T', aid, ['design.md'], 'unauthorized pass', dict(MOCKUP, visual_review='PASS'))
        task = self.tasks.read()['tasks']['T']
        self.assertEqual(task['state'], 'IN_PROGRESS')
        self.assertEqual(task['outputs'], [])
        self.assertEqual(task['design_status']['visual_review'], 'NOT_RUN')

    def test_native_submit_without_design_status_rejects_html(self):
        aid = self.task()
        (self.root / 'index.html').write_text('<h1>Synthetic prototype</h1>')
        with self.assertRaisesRegex(ValueError, 'non-code task'):
            self.tasks.submit('T', aid, ['index.html'], 'missing explicit status')
        self.assertEqual(self.tasks.read()['tasks']['T']['state'], 'IN_PROGRESS')

    def test_complete_mockup_still_rejects_product_source(self):
        with self.assertRaises(ValueError):
            document_outputs({'role': 'design', 'execution_scope': 'documentation'}, ['Main.kt'], MOCKUP)


if __name__ == '__main__':
    unittest.main()
