"""Explicit PR snapshot/scope checks; no publishing or semantic approval."""
import argparse
import hashlib
import json
import os
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    return (isinstance(path, str) and bool(path) and not path.startswith('/')
            and '..' not in path.split('/') and '\\' not in path)


def snapshot(root, base, source_id, ignored=()):
    """Capture all tracked changes and nonignored untracked files, including deletes."""
    base = git(root, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
    paths = set(git(root, 'diff', '--name-only', '--no-renames', '-z', base, '--').decode().split('\0'))
    paths.update(git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))
    paths.update(ignored)
    entries = []
    for name in sorted(paths - {''}):
        if not safe_path(name):
            raise ValueError('unsafe source path: ' + name)
        path = Path(root) / name
        for parent in Path(name).parents:
            if parent != Path('.') and (Path(root) / parent).is_symlink():
                raise ValueError('symlink parent in source path: ' + name)
        # Do not follow a symlink into private material outside this checkout.
        data = os.readlink(path).encode() if path.is_symlink() else (path.read_bytes() if path.exists() else None)
        entries.append({'path': name, 'sha256': digest(data) if data is not None else None})
    return {'id': source_id, 'base': base, 'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
            'ignored_included': list(ignored), 'entries': entries}


def check(root, base, manifest, sources=None, body=None):
    errors, skipped = [], []
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    base = git(root, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
    if git(root, 'status', '--porcelain', '--untracked-files=all').strip():
        errors.append('target checkout is not clean')
    files = set(git(root, 'ls-tree', '-r', '--name-only', '-z', head).decode().split('\0')) - {''}
    changed = set(git(root, 'diff', '--name-only', '--no-renames', '-z', base, head, '--').decode().split('\0')) - {''}

    def blob(path):
        if not safe_path(path) or path not in files:
            errors.append('not submitted: ' + str(path))
            return None
        return git(root, 'show', head + ':' + path)

    originals = {}
    ids = set()
    for source in manifest.get('sources', []):
        sid = source['id']
        if sid in ids:
            errors.append('duplicate source id: ' + sid)
        ids.add(sid)
        if sources is not None and sid in sources:
            current = snapshot(sources[sid], source['base'], sid, source.get('ignored_included', []))
            if current != source:
                errors.append('source changed since snapshot: ' + sid)
        else:
            skipped.append('NOT_RUN live source recapture: ' + sid)
        for entry in source['entries']:
            key = (sid, entry['path'])
            if key in originals or not safe_path(entry['path']):
                errors.append('duplicate or unsafe source entry: ' + str(key))
            originals[key] = entry['sha256']
    covered, decided = set(), set()
    for decision in manifest.get('decisions', []):
        key = (decision['source'], decision['path'])
        if key in decided or key not in originals:
            errors.append('duplicate or unknown decision: ' + str(key))
            continue
        decided.add(key)
        action, reason = decision.get('action'), decision.get('reason', '').strip()
        if action == 'unresolved':
            errors.append('unresolved source: ' + str(key))
            continue
        if not reason:
            errors.append('missing decision reason: ' + str(key))
        if action == 'exclude':
            if decision.get('in_scope') is not False:
                errors.append('requested scope cannot be excluded: ' + str(key))
            continue
        if action not in ('include', 'transform'):
            errors.append('unknown action: ' + str(key))
            continue
        target = decision.get('target', decision['path'])
        if not safe_path(target):
            errors.append('unsafe target: ' + str(target))
            continue
        covered.add(target)
        original = originals[key]
        if original is None:
            if target in files:
                errors.append('source deletion not submitted: ' + target)
            continue
        data = blob(target)
        if data is None:
            continue
        actual = digest(data)
        if action == 'include' and actual != original:
            errors.append('content differs without transform decision: ' + target)
        if action == 'transform' and actual != decision.get('target_sha256'):
            errors.append('transformed content hash differs: ' + target)
    for key in originals.keys() - decided:
        errors.append('missing source decision: ' + str(key))
    for addition in manifest.get('additional', []):
        path = addition['path']
        if not safe_path(path) or not addition.get('reason', '').strip():
            errors.append('invalid additional file: ' + str(path))
            continue
        covered.add(path)
        blob(path)
    for path in changed - covered:
        errors.append('unclassified PR change: ' + path)
    for path in manifest.get('required', []):
        blob(path)

    def links(text, document):
        # Check file targets, not heading anchors, network access or code samples.
        text = re.sub(r'(?ms)^```.*?^```[^\n]*', '', text)
        if re.search(r'(?m)^\s*\[[^\]]+\]:|!?\[[^\]]*\]\[', text):
            skipped.append('NOT_RUN reference-style Markdown links in: ' + document)
        for raw in re.findall(r'!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\)', text):
            url = urlsplit(raw.strip('<>'))
            if url.scheme or url.netloc:
                skipped.append('NOT_RUN external URL: ' + raw)
                continue
            if not url.path:
                skipped.append('NOT_RUN heading anchor in: ' + document)
                continue
            path = unquote(url.path)
            target = posixpath.normpath(path.lstrip('/') if path.startswith('/') else posixpath.join(posixpath.dirname(document), path))
            if not safe_path(target) or target not in files:
                errors.append('broken submitted link: ' + document + ' -> ' + raw)
            elif url.fragment:
                skipped.append('NOT_RUN heading anchor in: ' + target)
    for document in manifest.get('documents', []):
        data = blob(document)
        if data is not None:
            links(data.decode('utf-8'), document)
    if body is not None:
        links(body, '')
    return {'result': 'FAIL' if errors else 'PASS', 'base': base, 'head': head,
            'errors': sorted(set(errors)), 'not_run': sorted(set(skipped)),
            'guarantee': 'Declared inventory, byte hashes, submitted files and relative file links only; no semantic completeness, hidden dependency, external URL or authorization approval.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    capture = sub.add_parser('snapshot')
    capture.add_argument('--root', required=True)
    capture.add_argument('--base', required=True)
    capture.add_argument('--id', required=True)
    capture.add_argument('--include-ignored', action='append', default=[])
    verify = sub.add_parser('check')
    verify.add_argument('--root', required=True)
    verify.add_argument('--base', required=True)
    verify.add_argument('--scope', required=True)
    verify.add_argument('--source', action='append', default=[], metavar='ID=ROOT')
    verify.add_argument('--body')
    args = parser.parse_args()
    if args.command == 'snapshot':
        result = snapshot(args.root, args.base, args.id, args.include_ignored)
    else:
        source_roots = dict(value.split('=', 1) for value in args.source)
        result = check(args.root, args.base, json.loads(Path(args.scope).read_text()), source_roots,
                       Path(args.body).read_text() if args.body else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result.get('result') == 'FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
