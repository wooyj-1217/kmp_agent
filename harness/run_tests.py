"""Run every harness test without shadowing Python's stdlib logging module.

Usage from the repository root: rtk proxy python3 -B -m harness.run_tests
Do not use discovery with harness/ as sys.path[0]. Namespace modules are loaded
by qualified names; this also detects import errors instead of skipping files.
"""
from pathlib import Path
import unittest
import sys


def main():
    names = ['harness.' + p.stem for p in sorted(Path(__file__).parent.glob('test_*.py'))]
    if not names:
        raise RuntimeError('no harness tests found')
    unittest.main(module=None, argv=[sys.argv[0], *names, *sys.argv[1:]])


if __name__ == '__main__':
    main()
