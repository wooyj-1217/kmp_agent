"""Local-only verification output directories; existing evidence is never relocated."""
import argparse
from pathlib import Path
import uuid


def directory(root, *parts):
    """Create an ignored project-local evidence directory, rejecting escaped paths."""
    root = Path(root).resolve()
    names = ('verification',) + parts
    for name in names:
        if not isinstance(name, str) or not name or Path(name).name != name or name in {'.', '..'}:
            raise ValueError('verification directory components must be single relative names')
    current = root
    for name in names:
        current = current / name
        if current.is_symlink():
            raise ValueError('verification directory cannot be a symlink')
        current.mkdir(parents=True, exist_ok=True, mode=0o700)
        if name == 'verification' and current.parent == root:
            ignore = current / '.gitignore'
            try:
                with ignore.open('x') as handle:
                    handle.write('*\n')
            except FileExistsError:
                pass
    return current


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--name', default=None, help='single directory name; defaults to a new UUID')
    args = parser.parse_args(argv)
    try:
        print(directory(args.root, 'manual', args.name or str(uuid.uuid4())))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
