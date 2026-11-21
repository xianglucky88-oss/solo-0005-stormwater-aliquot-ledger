"""Read a complete synthetic evidence bundle without external services."""
import argparse
import sqlite3
import sys
from pathlib import Path

from .archive import history, load, publish
from .common import decode, encode, require
from .workflow import DESCRIPTION, materialize


def main(argv=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('preview', help='compute results without writing an archive').add_argument('bundle', type=Path)
    rel = subs.add_parser('publish', help='commit one immutable edition')
    rel.add_argument('bundle', type=Path)
    rel.add_argument('archive', type=Path)
    rel.add_argument('edition')
    for command in ('show', 'source', 'replay'):
        p = subs.add_parser(command)
        p.add_argument('archive', type=Path)
        p.add_argument('edition')
    subs.add_parser('history').add_argument('archive', type=Path)
    args = parser.parse_args(argv)
    try:
        match args.command:
            case 'preview' | 'publish':
                doc = decode(args.bundle.read_text(encoding='utf-8'))
                require(isinstance(doc, dict), 'bundle must be an object')
                result = materialize(doc)
                if args.command == 'publish':
                    result = publish(args.archive, args.edition, doc, result)
            case 'history':
                result = history(args.archive)
            case 'replay':
                stored = load(args.archive, args.edition)
                result = materialize(load(args.archive, args.edition, source=True))
                require(encode(stored) == encode(result), f'replay differs: {args.edition}')
            case _:
                result = load(args.archive, args.edition, source=args.command == 'source')
        print(encode(result))
        return 0
    except (OSError, ValueError, LookupError, TypeError, ArithmeticError, sqlite3.Error) as exc:
        print(f'{parser.prog}: {exc}', file=sys.stderr)
        return 2
