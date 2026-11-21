from fractions import Fraction

from .common import disjoint, number, require, scalar, span, unique


def hydrograph(doc):
    start, end = span(doc['event_seconds'], 'event window')
    rate = number(doc['liters_per_unit'], 'flow calibration')
    threshold = number(doc['trigger_liters'], 'trigger volume')
    require(rate > 0 and threshold > 0, 'calibration and trigger must be positive')
    rows = []
    for key, row in unique(doc['runs']).items():
        lo, hi = span(row['seconds'], 'flow run')
        require(start <= lo < hi <= end, f'run outside event: {key}')
        volume = number(row['units'], 'flow units') * rate if row['units'] is not None else None
        rows.append((lo, hi, key, volume))
    rows = disjoint(rows, 'flow runs')
    cursor, anchored, total, prefix = start, True, Fraction(0), Fraction(0)
    runoff, triggers, gaps, contributions = [], [], [], []
    ordinal = 1
    for lo, hi, key, volume in rows:
        if cursor != lo:
            gaps.append({'seconds': [cursor, lo], 'run': None})
            anchored = False
        cursor = hi
        runoff.append({'run': key, 'seconds': [lo, hi], 'liters': scalar(volume) if volume is not None else None,
                       'prefix_before_l': scalar(prefix) if anchored else None})
        if volume is None:
            gaps.append({'seconds': [lo, hi], 'run': key})
            anchored = False
            continue
        total += volume
        if not anchored:
            continue
        contributions.append((prefix, prefix + volume, key, lo, hi))
        require((prefix + volume) // threshold <= 100_000, 'synthetic event exceeds 100000 trigger limit')
        while threshold * ordinal <= prefix + volume:
            target = threshold * ordinal
            start_l = target - threshold
            used = [name for a, b, name, _, _ in contributions if max(a, start_l) < min(b, target)]
            at = lo + (hi - lo) * (target - prefix) / volume
            triggers.append({'number': ordinal, 'at_s': scalar(at), 'volume_l': [scalar(start_l), scalar(target)],
                             'runs': used})
            contributions = [(a, b, name, s, e) for a, b, name, s, e in contributions if b > target]
            ordinal += 1
        prefix += volume
    if cursor != end:
        gaps.append({'seconds': [cursor, end], 'run': None})
    return {'runs': runoff, 'triggers': triggers, 'gaps': gaps,
            'known_liters': scalar(total), 'anchored_liters': scalar(prefix)}
