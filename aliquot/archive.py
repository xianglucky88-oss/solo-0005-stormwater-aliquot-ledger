"""Immutable editions. Read-only commands never create an archive."""
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from .common import decode, encode, require


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def open_reader(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def publish(path, edition, source, result):
    require(bool(edition.strip()), 'edition must not be blank')
    source_text, result_text = encode(source), encode(result)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS editions (
            seq INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
            source_hash TEXT NOT NULL, result_hash TEXT NOT NULL,
            source TEXT NOT NULL, result TEXT NOT NULL)''')
        try:
            db.execute('INSERT INTO editions (name, source_hash, result_hash, source, result) VALUES (?, ?, ?, ?, ?)',
                       (edition, digest(source_text), digest(result_text), source_text, result_text))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'edition already exists: {edition}') from exc
    return {'edition': edition, 'source_sha256': digest(source_text), 'result_sha256': digest(result_text)}


def load(path, edition, source=False):
    with closing(open_reader(path)) as db:
        row = db.execute('SELECT source_hash, result_hash, source, result FROM editions WHERE name=?', (edition,)).fetchone()
    require(row is not None, f'unknown edition: {edition}')
    require(digest(row[2]) == row[0] and digest(row[3]) == row[1], f'content digest mismatch: {edition}')
    return decode(row[2] if source else row[3])


def history(path):
    with closing(open_reader(path)) as db:
        rows = db.execute('SELECT name, source_hash, result_hash FROM editions ORDER BY seq').fetchall()
    return [{'edition': name, 'source_sha256': a, 'result_sha256': b} for name, a, b in rows]
