import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tools.check_pr_scope import check, digest, snapshot


class PRScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'development source'
        self.target = Path(self.tmp.name) / 'submission'
        self.source.mkdir()
        self.git(self.source, 'init', '-q')
        self.git(self.source, 'config', 'user.email', 'fixture@example.invalid')
        self.git(self.source, 'config', 'user.name', 'Fixture')
        (self.source / 'old.txt').write_text('old\n')
        (self.source / 'deleted.txt').write_text('remove me\n')
        self.commit(self.source)
        self.base = self.git(self.source, 'rev-parse', 'HEAD').strip()
        self.git(self.source, 'clone', '-q', str(self.source), str(self.target))
        self.git(self.target, 'config', 'user.email', 'fixture@example.invalid')
        self.git(self.target, 'config', 'user.name', 'Fixture')
        (self.source / 'old.txt').write_text('new\n')
        (self.source / 'resource with space.txt').write_text('fixture\n')
        (self.source / 'deleted.txt').unlink()
        for name in ('old.txt', 'resource with space.txt'):
            (self.target / name).write_bytes((self.source / name).read_bytes())
        (self.target / 'deleted.txt').unlink()
        self.commit(self.target)
        capture = snapshot(self.source, self.base, 'development')
        self.scope = {'sources': [capture], 'decisions': [
            {'source': 'development', 'path': e['path'], 'action': 'include',
             'reason': 'requested implementation', 'in_scope': True}
            for e in capture['entries']], 'required': ['resource with space.txt']}

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode()

    def commit(self, root):
        self.git(root, 'add', '-A')
        self.git(root, 'commit', '-qm', 'fixture')

    def result(self, scope=None, live=True, body=None):
        return check(self.target, self.base, scope or self.scope,
                     {'development': self.source} if live else None, body)

    def test_complete_contents_deletion_and_untracked_resource(self):
        result = self.result()
        self.assertEqual(result['result'], 'PASS', result)
        self.assertEqual(result['not_run'], [])
        self.assertIn('resource with space.txt', [e['path'] for e in self.scope['sources'][0]['entries']])

    def test_rename_is_checked_as_delete_and_add(self):
        (self.source / 'old.txt').write_text('old\n')
        (self.target / 'old.txt').write_text('old\n')
        (self.source / 'old.txt').rename(self.source / 'renamed.txt')
        (self.target / 'old.txt').rename(self.target / 'renamed.txt')
        self.commit(self.target)
        capture = snapshot(self.source, self.base, 'development')
        self.scope['sources'] = [capture]
        self.scope['decisions'] = [dict(source='development', path=e['path'], action='include',
                                         reason='requested implementation', in_scope=True) for e in capture['entries']]
        self.assertEqual(self.result()['result'], 'PASS')

    def test_unsafe_target_cannot_escape_submission_tree(self):
        self.scope['decisions'][0]['target'] = '../private.txt'
        self.assertIn('unsafe target', '\n'.join(self.result()['errors']))

    def test_missing_source_decision(self):
        self.scope['decisions'].pop()
        self.assertIn('missing source decision', '\n'.join(self.result()['errors']))

    def test_same_count_different_content_fails(self):
        (self.target / 'old.txt').write_text('wrong\n')
        self.commit(self.target)
        self.assertIn('content differs', '\n'.join(self.result()['errors']))

    def test_untracked_required_resource_is_not_submitted(self):
        self.git(self.target, 'rm', '--cached', 'resource with space.txt')
        self.git(self.target, 'commit', '-qm', 'fixture omission')
        errors = '\n'.join(self.result()['errors'])
        self.assertIn('not submitted: resource with space.txt', errors)
        self.assertIn('not clean', errors)

    def test_excluded_fixture_cannot_satisfy_required_input(self):
        scope = copy.deepcopy(self.scope)
        item = next(d for d in scope['decisions'] if d['path'] == 'resource with space.txt')
        item.update(action='exclude', in_scope=False, reason='private input')
        (self.target / 'resource with space.txt').unlink()
        self.commit(self.target)
        self.assertIn('not submitted: resource with space.txt', '\n'.join(self.result(scope)['errors']))

    def test_requested_feature_exclusion_and_unresolved_block(self):
        self.scope['decisions'][0]['action'] = 'exclude'
        self.assertIn('cannot be excluded', '\n'.join(self.result()['errors']))
        self.scope['decisions'][0]['action'] = 'unresolved'
        self.assertIn('unresolved source', '\n'.join(self.result()['errors']))

    def test_transform_requires_exact_target_hash(self):
        (self.target / 'old.txt').write_text('public synthetic replacement\n')
        self.commit(self.target)
        decision = next(d for d in self.scope['decisions'] if d['path'] == 'old.txt')
        decision.update(action='transform', reason='private input replaced; semantics differ',
                        target_sha256=digest((self.target / 'old.txt').read_bytes()))
        self.assertEqual(self.result()['result'], 'PASS')
        decision['target_sha256'] = 'stale'
        self.assertIn('hash differs', '\n'.join(self.result()['errors']))

    def test_original_changed_after_snapshot(self):
        (self.source / 'old.txt').write_text('later change\n')
        self.assertIn('changed since snapshot', '\n'.join(self.result()['errors']))

    def test_no_live_source_is_explicitly_not_run(self):
        self.assertIn('NOT_RUN live source recapture: development', self.result(live=False)['not_run'])

    def test_unclassified_addition(self):
        (self.target / 'extra.txt').write_text('extra')
        self.commit(self.target)
        self.assertIn('unclassified PR change: extra.txt', self.result()['errors'])
        self.scope['additional'] = [{'path': 'extra.txt', 'reason': 'submission verification helper'}]
        self.assertEqual(self.result()['result'], 'PASS')

    def test_links_use_submitted_tree_not_local_files(self):
        (self.target / 'docs').mkdir()
        (self.target / 'docs' / 'review.md').write_text('[good](<../resource with space.txt>)\n[bad](missing.md)\n')
        self.commit(self.target)
        self.scope.update(additional=[{'path': 'docs/review.md', 'reason': 'report'}], documents=['docs/review.md'])
        self.assertIn('broken submitted link: docs/review.md -> missing.md', self.result()['errors'])
        (self.target / 'docs' / 'missing.md').write_text('untracked is not submitted')
        self.assertIn('broken submitted link: docs/review.md -> missing.md', self.result()['errors'])

    def test_reference_style_links_are_explicitly_not_run(self):
        result = self.result(body='[label][id]\n[id]: missing.md\n')
        self.assertIn('NOT_RUN reference-style Markdown links in: ', result['not_run'])

    def test_parent_symlink_is_not_followed(self):
        (self.source / 'linked-directory').symlink_to(Path(self.tmp.name), target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink parent'):
            snapshot(self.source, self.base, 'x', ['linked-directory/private.txt'])

    def test_external_and_anchor_checks_are_not_claimed(self):
        result = self.result(body='[external](https://example.invalid/report) [heading](#heading)')
        self.assertEqual(result['result'], 'PASS')
        self.assertEqual(len(result['not_run']), 2)

    def test_ignored_resource_is_explicit_and_symlink_is_not_followed(self):
        (self.source / '.gitignore').write_text('ignored.txt\n')
        (self.source / 'ignored.txt').write_text('ignored required fixture')
        (self.source / 'outside-link').symlink_to(Path(self.tmp.name) / 'private-nonexistent')
        normal = snapshot(self.source, self.base, 'x')
        self.assertNotIn('ignored.txt', [e['path'] for e in normal['entries']])
        included = snapshot(self.source, self.base, 'x', ['ignored.txt'])
        self.assertIn('ignored.txt', [e['path'] for e in included['entries']])
        link = next(e for e in included['entries'] if e['path'] == 'outside-link')
        self.assertEqual(link['sha256'], digest(str(Path(self.tmp.name) / 'private-nonexistent').encode()))

    def test_new_role_input_contains_common_pr_policy_and_fingerprint(self):
        from harness.roles import Roles, CODE
        root = Path(self.tmp.name) / 'role-input'
        root.mkdir()
        (root / 'input.md').write_text('synthetic requirement')
        roles = Roles(root, 'synthetic-policy-input')
        roles.tasks.register('F', 'P', 'planning', 'fixture', 'input fidelity',
                             [{'id': 'C', 'required': True, 'text': 'synthetic criterion'}], ['input.md'])
        roles.setup('P', 'feature')
        prepared = roles.prepare('P', 'planning')
        packet = json.loads((root / prepared['context']).read_text())
        definition = next(d for d in packet['definitions'] if d['path'] == 'docs/operations.md')
        self.assertEqual(definition['sha256'], digest((CODE / 'docs/operations.md').read_bytes()))
        self.assertEqual(definition['content'], (CODE / 'docs/operations.md').read_text())
        self.assertIn('<a id="pr-submission"></a>', definition['content'])

    def test_cli_and_arbitrary_paths_and_refs(self):
        tool = Path(__file__).resolve().parents[1] / 'tools' / 'check_pr_scope.py'
        output = subprocess.check_output([sys.executable, '-B', str(tool), 'snapshot', '--root', str(self.source),
                                          '--base', self.base, '--id', 'another-source'])
        self.assertEqual(json.loads(output)['id'], 'another-source')
        manifest = Path(self.tmp.name) / 'scope.json'
        manifest.write_text(json.dumps(self.scope))
        output = subprocess.check_output([sys.executable, '-B', str(tool), 'check', '--root', str(self.target),
                                          '--base', self.base, '--scope', str(manifest),
                                          '--source', 'development=' + str(self.source)])
        self.assertEqual(json.loads(output)['result'], 'PASS')


if __name__ == '__main__':
    unittest.main()
