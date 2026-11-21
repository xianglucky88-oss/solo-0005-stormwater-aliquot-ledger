from fractions import Fraction

from .common import disjoint, integer, number, require, scalar, span, unique


def _segment_settings(doc):
    dry = doc.get('dry_seconds')
    window = doc.get('window_seconds')
    present = dry is not None or window is not None
    if not present:
        return None, None, False
    require(dry is not None and window is not None,
            'dry_seconds and window_seconds must be provided together')
    dry_s = integer(dry, 'minimum dry duration', 1)
    window_s = integer(window, 'statistical window', 1)
    return dry_s, window_s, True


def _timeline(start, end, rows):
    """Cover the whole event with classified pieces, turning uncovered time into missing evidence."""
    pieces, cursor = [], start
    for lo, hi, key, volume in rows:
        if cursor != lo:
            pieces.append((cursor, lo, None, None, 'missing'))
        kind = 'missing' if volume is None else 'zero' if volume == 0 else 'flow'
        pieces.append((lo, hi, key, volume, kind))
        cursor = hi
    if cursor != end:
        pieces.append((cursor, end, None, None, 'missing'))
    return pieces


def _merge_run(pieces, i, kind):
    lo = pieces[i][0]
    while i < len(pieces) and pieces[i][4] == kind:
        hi = pieces[i][1]
        i += 1
    return lo, hi, i


def _split_candidates(pieces, dry_s, window_s):
    """Certified cuts need evidenced zero flow on both sides; gaps only keep a split uncertain."""
    candidates, boundaries = [], []
    i = 0
    while i < len(pieces):
        kind = pieces[i][4]
        if kind not in ('zero', 'missing'):
            i += 1
            continue
        lo, hi, i = _merge_run(pieces, i, kind)
        before = any(p[4] == 'flow' for p in pieces if p[1] <= lo)
        after = any(p[4] == 'flow' for p in pieces if p[0] >= hi)
        entry = {'seconds': [lo, hi], 'kind': kind,
                 'zero_seconds': (hi - lo) if kind == 'zero' else None}
        if not (before and after):
            entry.update(state='uncertain', reason='not_between_two_rises', assessment_window=None)
        elif kind == 'missing':
            entry.update(state='uncertain', reason='missing_evidence', assessment_window=None)
        elif hi - lo < dry_s:
            entry.update(state='uncertain', reason='below_minimum_duration', assessment_window=None)
        elif hi - lo < window_s:
            entry.update(state='uncertain', reason='assessment_window_incomplete',
                         assessment_window=None)
        else:
            entry.update(state='certified', reason='evidenced_zero_meets_threshold',
                         assessment_window=[hi - window_s, hi])
            boundaries.append(hi)
        candidates.append(entry)
    return candidates, sorted(boundaries)


def hydrograph(doc):
    start, end = span(doc['event_seconds'], 'event window')
    rate = number(doc['liters_per_unit'], 'flow calibration')
    threshold = number(doc['trigger_liters'], 'trigger volume')
    require(rate > 0 and threshold > 0, 'calibration and trigger must be positive')
    dry_s, window_s, segmented = _segment_settings(doc)
    rows = []
    for key, row in unique(doc['runs']).items():
        lo, hi = span(row['seconds'], 'flow run')
        require(start <= lo < hi <= end, f'run outside event: {key}')
        volume = number(row['units'], 'flow units') * rate if row['units'] is not None else None
        rows.append((lo, hi, key, volume))
    rows = disjoint(rows, 'flow runs')
    pieces = _timeline(start, end, rows)
    candidates, boundaries = (_split_candidates(pieces, dry_s, window_s)
                              if segmented else ([], []))

    def segment_at(lo):
        return 1 + sum(1 for cut in boundaries if cut <= lo)

    cursor, anchored, total, prefix = start, True, Fraction(0), Fraction(0)
    runoff, triggers, gaps, contributions, anchored_runs = [], [], [], [], []
    ordinal = 1
    for lo, hi, key, volume in rows:
        if cursor != lo:
            gaps.append({'seconds': [cursor, lo], 'run': None})
            anchored = False
        cursor = hi
        row_out = {'run': key, 'seconds': [lo, hi],
                   'liters': scalar(volume) if volume is not None else None,
                   'prefix_before_l': scalar(prefix) if anchored else None}
        if segmented:
            row_out['segment'] = segment_at(lo)
        runoff.append(row_out)
        if volume is None:
            gaps.append({'seconds': [lo, hi], 'run': key})
            anchored = False
            continue
        total += volume
        if not anchored:
            continue
        seg = segment_at(lo) if segmented else None
        if segmented:
            anchored_runs.append((lo, hi, volume))
        contributions.append((prefix, prefix + volume, key, lo, hi, seg))
        require((prefix + volume) // threshold <= 100_000, 'synthetic event exceeds 100000 trigger limit')
        while volume > 0 and threshold * ordinal <= prefix + volume:
            target = threshold * ordinal
            start_l = target - threshold
            used = [name for a, b, name, _, _, _ in contributions if max(a, start_l) < min(b, target)]
            at = lo + (hi - lo) * (target - prefix) / volume
            trigger = {'number': ordinal, 'at_s': scalar(at), 'volume_l': [scalar(start_l), scalar(target)],
                       'runs': used}
            if segmented:
                parts = {}
                for a, b, _, _, _, seg in contributions:
                    overlap = min(b, target) - max(a, start_l)
                    if overlap > 0:
                        parts[seg] = parts.get(seg, Fraction(0)) + overlap
                trigger['segments'] = [{'segment': seg, 'liters': scalar(parts[seg])}
                                        for seg in sorted(parts)]
                trigger['crosses_split'] = len(parts) > 1
            triggers.append(trigger)
            contributions = [(a, b, name, s, e, seg)
                             for a, b, name, s, e, seg in contributions if b > target]
            ordinal += 1
        prefix += volume
    if cursor != end:
        gaps.append({'seconds': [cursor, end], 'run': None})

    out = {'runs': runoff, 'triggers': triggers, 'gaps': gaps,
           'known_liters': scalar(total), 'anchored_liters': scalar(prefix)}
    if segmented:
        out['segmented'] = True
        out['dry_seconds'] = dry_s
        out['window_seconds'] = window_s
        out['split_candidates'] = candidates
        out['segments'] = _segment_summary(pieces, boundaries, triggers, segment_at, anchored_runs)
    return out


def _segment_summary(pieces, boundaries, triggers, segment_at, anchored_runs):
    anchored = {(lo, hi): volume for lo, hi, volume in anchored_runs}
    stats = {}
    for lo, hi, _, volume, kind in pieces:
        idx = segment_at(lo)
        item = stats.setdefault(idx, {'index': idx, 'seconds': [lo, hi], 'known_liters': Fraction(0),
                                      'anchored_liters': Fraction(0), 'missing_seconds': 0,
                                      'zero_seconds': 0, 'triggers': []})
        item['seconds'][1] = hi
        if volume is not None:
            item['known_liters'] += volume
        item['anchored_liters'] += anchored.get((lo, hi), Fraction(0))
        if kind == 'missing':
            item['missing_seconds'] += hi - lo
        elif kind == 'zero':
            item['zero_seconds'] += hi - lo
    for trigger in triggers:
        for part in trigger['segments']:
            stats[part['segment']]['triggers'].append(trigger['number'])
    summaries = []
    for idx in sorted(stats):
        item = stats[idx]
        cut = boundaries[idx - 1] if idx - 1 < len(boundaries) else None
        item['split_after_s'] = cut
        for field in ('known_liters', 'anchored_liters'):
            item[field] = scalar(item[field])
        summaries.append(item)
    return summaries
