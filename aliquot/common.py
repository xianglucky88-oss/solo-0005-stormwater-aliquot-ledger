"""Strict JSON and exact numeric values shared by the local command boundary."""
import json
from fractions import Fraction


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, label, minimum=None):
    require(type(value) is int and (minimum is None or value >= minimum), f'invalid {label}: {value!r}')
    return value


def number(value, label, minimum=0):
    require(type(value) in (int, str), f'{label} must be an integer or exact numeric string')
    result = Fraction(value)
    require(minimum is None or result >= minimum, f'{label} below minimum')
    return result


def span(value, label):
    require(isinstance(value, list) and len(value) == 2, f'invalid {label}: want [start, end]')
    lo, hi = (integer(x, label) for x in value)
    require(lo < hi, f'{label} must have positive length')
    return lo, hi


def unique(rows, field='id'):
    index = {}
    for row in rows:
        key = row[field]
        require(isinstance(key, str) and key.strip() and key not in index, f'invalid or duplicate {field}: {key!r}')
        index[key] = row
    return index


def disjoint(items, label):
    ordered = sorted(items)
    require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), f'overlapping {label}')
    return ordered


def pieces(a, b):
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo < hi else None


def scalar(x):
    q = Fraction(x)
    return q.numerator if q.denominator == 1 else str(q)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode(text):
    def pairs(raw):
        obj = dict(raw)
        require(len(obj) == len(raw), 'duplicate JSON member')
        return obj

    def invalid(token):
        raise ValueError(f'invalid JSON constant: {token}')

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
