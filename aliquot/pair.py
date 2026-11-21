"""Two-station load comparison over a continuous travel-delay range.

One delay applies to every sample of the event.  The delay is only known as a
continuous range, so support and load difference are derived as exact
piecewise-linear functions of the delay instead of sampling discrete guesses.
"""
from fractions import Fraction

from .common import number, require, scalar
from .workflow import materialize

DESCRIPTION = 'Compare evidenced loads of two stations of one event over a continuous delay range.'


def _knots(flow):
    """Cumulative anchored volume knots (time, liters); stops at the first gap."""
    knots = []
    for run in flow['runs']:
        if run['prefix_before_l'] is None or run['liters'] is None:
            break
        if not knots:
            knots.append((Fraction(run['seconds'][0]), Fraction(0)))
        knots.append((Fraction(run['seconds'][1]), Fraction(run['prefix_before_l']) + Fraction(run['liters'])))
    return knots


def _volume_at(knots, t):
    """Anchored cumulative liters at time t; uniform within each calibrated run."""
    for (t0, v0), (t1, v1) in zip(knots, knots[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    require(False, f'time outside anchored flow: {t}')


def _time_at(knots, v):
    """Time at which the anchored cumulative volume reaches v; flat runs carry no volume."""
    for (t0, v0), (t1, v1) in zip(knots, knots[1:]):
        if v0 < v1 and v0 <= v <= v1:
            return t0 + (t1 - t0) * (v - v0) / (v1 - v0)
    require(False, f'volume outside anchored flow: {v}')


def _station(station, method, name):
    """Evidenced time slices of one station: bottle volumes back-looked-up through the hydrograph."""
    result = materialize(station)
    require(method in result['methods'], f'method not declared at {name} station: {method}')
    knots = _knots(result['flow'])
    triggers = {t['number']: t for t in result['flow']['triggers']}
    slices = []
    for row in result['assays']:
        if row['method'] != method or row['state'] != 'supported':
            continue
        start_l, end_l = map(Fraction, triggers[row['trigger']]['volume_l'])
        lo, hi = _time_at(knots, start_l), _time_at(knots, end_l)
        low, high = map(Fraction, row['concentration_mg_l'])
        slices.append({'trigger': row['trigger'], 'bottle': row['bottle'], 'assay': row['assay'],
                       'seconds': [scalar(lo), scalar(hi)], 'liters': scalar(end_l - start_l),
                       'concentration_mg_l': [scalar(low), scalar(high)],
                       'lo': lo, 'hi': hi, 'c': (low, high)})
    summary = {'known_liters': result['flow']['known_liters'],
               'anchored_liters': result['flow']['anchored_liters'],
               'supported_liters': result['methods'][method]['supported_liters'],
               'known_liters_without_assay': result['methods'][method]['known_liters_without_assay'],
               'gaps': result['flow']['gaps']}
    return summary, knots, slices


def _evaluate(slices_a, knots_a, slices_b, knots_b, delay):
    """Aligned overlap at one delay: per-station evidenced liters and downstream-minus-upstream load bounds."""
    liters_a = liters_b = diff_lo = diff_hi = Fraction(0)
    for s_a in slices_a:
        for s_b in slices_b:
            o_lo = max(s_a['lo'], s_b['lo'] - delay)
            o_hi = min(s_a['hi'], s_b['hi'] - delay)
            if o_lo < o_hi:
                v_a = _volume_at(knots_a, o_hi) - _volume_at(knots_a, o_lo)
                v_b = _volume_at(knots_b, o_hi + delay) - _volume_at(knots_b, o_lo + delay)
                liters_a += v_a
                liters_b += v_b
                diff_lo += v_b * s_b['c'][0] - v_a * s_a['c'][1]
                diff_hi += v_b * s_b['c'][1] - v_a * s_a['c'][0]
    return liters_a, liters_b, diff_lo, diff_hi


def _slot(p, q, f_p, f_q, x):
    """Evaluate at x the linear slot through (p, f_p) and (q, f_q)."""
    return f_p if p == q else f_p + (f_q - f_p) * (x - p) / (q - p)


def _ge(p, q, f_p, f_q, bound):
    """Sub-interval of [p, q] where the linear slot is >= bound, or None."""
    if f_p >= bound and f_q >= bound:
        return (p, q)
    if f_p < bound and f_q < bound:
        return None
    root = p + (q - p) * (bound - f_p) / (f_q - f_p)
    return (root, q) if f_q > f_p else (p, root)


def _le(p, q, f_p, f_q, bound):
    """Sub-interval of [p, q] where the linear slot is <= bound, or None."""
    return _ge(p, q, -f_p, -f_q, -bound)


def _meet(first, second):
    if first is None or second is None:
        return None
    lo, hi = max(first[0], second[0]), min(first[1], second[1])
    return (lo, hi) if lo <= hi else None


def _merge(intervals):
    """Sorted union of closed intervals; touching intervals merge."""
    merged = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _analyze(slices_a, knots_a, slices_b, knots_b, delay, min_support, max_difference):
    """Exact piecewise-linear answer over the whole delay range; no sampling.

    Kinks can only occur where a downstream slice endpoint aligns with an
    upstream slice endpoint or crosses an upstream flow knot, and vice versa.
    Between consecutive kinks every quantity is linear in the delay, so closed
    regions plus the min() branch roots determine the full range.
    """
    d_lo, d_hi = delay
    points = {d_lo, d_hi}
    a_ends = {x for s in slices_a for x in (s['lo'], s['hi'])}
    b_ends = {x for s in slices_b for x in (s['lo'], s['hi'])}
    a_knots = {t for t, _ in knots_a}
    b_knots = {t for t, _ in knots_b}
    for a in a_ends:
        for b in b_ends:
            points.add(b - a)
        for r in b_knots:
            points.add(r - a)
    for b in b_ends:
        for r in a_knots:
            points.add(b - r)
    points = sorted(p for p in points if d_lo <= p <= d_hi)
    if len(points) == 1:
        points *= 2
    lows = {'support': None, 'a': None, 'b': None, 'diff': None}
    highs = {'support': None, 'a': None, 'b': None, 'diff': None}

    def stretch(key, *values):
        lows[key] = min(values) if lows[key] is None else min(lows[key], *values)
        highs[key] = max(values) if highs[key] is None else max(highs[key], *values)

    support_ok, difference_ok, joint_ok = [], [], []
    for p, q in zip(points, points[1:]):
        a_p, b_p, lo_p, hi_p = _evaluate(slices_a, knots_a, slices_b, knots_b, p)
        a_q, b_q, lo_q, hi_q = _evaluate(slices_a, knots_a, slices_b, knots_b, q)
        gap_p, gap_q = a_p - b_p, a_q - b_q
        cuts = [p, q]
        if (gap_p < 0 < gap_q) or (gap_q < 0 < gap_p):
            cuts.insert(1, p + (q - p) * gap_p / (gap_p - gap_q))
        for u, v in zip(cuts, cuts[1:]):
            a_u, b_u = _slot(p, q, a_p, a_q, u), _slot(p, q, b_p, b_q, u)
            a_v, b_v = _slot(p, q, a_p, a_q, v), _slot(p, q, b_p, b_q, v)
            s_u, s_v = min(a_u, b_u), min(a_v, b_v)
            lo_u, lo_v = _slot(p, q, lo_p, lo_q, u), _slot(p, q, lo_p, lo_q, v)
            hi_u, hi_v = _slot(p, q, hi_p, hi_q, u), _slot(p, q, hi_p, hi_q, v)
            stretch('support', s_u, s_v)
            stretch('a', a_u, a_v)
            stretch('b', b_u, b_v)
            stretch('diff', lo_u, lo_v, hi_u, hi_v)
            here_support = _ge(u, v, s_u, s_v, min_support)
            here_difference = _meet(_le(u, v, hi_u, hi_v, max_difference),
                                    _ge(u, v, lo_u, lo_v, -max_difference))
            here_joint = _meet(here_support, here_difference)
            for bag, item in ((support_ok, here_support), (difference_ok, here_difference), (joint_ok, here_joint)):
                if item is not None:
                    bag.append(item)
    feasible = {name: [[scalar(lo), scalar(hi)] for lo, hi in _merge(items)]
                for name, items in (('support_feasible_s', support_ok),
                                    ('difference_feasible_s', difference_ok),
                                    ('joint_feasible_s', joint_ok))}
    witness = None
    if joint_ok:
        lo, hi = _merge(joint_ok)[0]
        at = (lo + hi) / 2
        liters_a, liters_b, diff_lo, diff_hi = _evaluate(slices_a, knots_a, slices_b, knots_b, at)
        witness = {'delay_s': scalar(at), 'common_support_l': scalar(min(liters_a, liters_b)),
                   'load_difference_mg': [scalar(diff_lo), scalar(diff_hi)]}
    return {'common_support_l': [scalar(lows['support']), scalar(highs['support'])],
            'aligned_liters': {'upstream': [scalar(lows['a']), scalar(highs['a'])],
                               'downstream': [scalar(lows['b']), scalar(highs['b'])]},
            'load_difference_mg': [scalar(lows['diff']), scalar(highs['diff'])],
            'feasible': feasible, 'witness': witness}


def compare_bundle(doc):
    require(isinstance(doc, dict), 'pair bundle must be an object')
    event = doc['event']
    method = doc['method']
    require(isinstance(method, str) and method.strip(), 'method must be a non-blank string')
    delay = doc['delay_s']
    require(isinstance(delay, list) and len(delay) == 2, 'invalid delay_s: want [lower, upper]')
    d_lo, d_hi = (number(x, 'travel delay bound') for x in delay)
    require(d_lo <= d_hi, 'delay_s must be ordered')
    min_support = number(doc['min_common_support_l'], 'minimum common support')
    max_difference = number(doc['max_load_difference_mg'], 'load difference bound')
    stations = doc['stations']
    require(isinstance(stations, dict) and set(stations) == {'upstream', 'downstream'},
            'stations must name exactly upstream and downstream')
    require(all(isinstance(stations[name], dict) and stations[name].get('event') == event
                for name in ('upstream', 'downstream')), 'station event must match the pair event')
    summary_a, knots_a, slices_a = _station(stations['upstream'], method, 'upstream')
    summary_b, knots_b, slices_b = _station(stations['downstream'], method, 'downstream')
    analysis = _analyze(slices_a, knots_a, slices_b, knots_b, (d_lo, d_hi), min_support, max_difference)

    def public(rows):
        return [{k: v for k, v in row.items() if k not in ('lo', 'hi', 'c')} for row in rows]

    summary_a['slices'] = public(slices_a)
    summary_b['slices'] = public(slices_b)
    return {'event': event, 'method': method, 'delay_s': [scalar(d_lo), scalar(d_hi)],
            'stations': {'upstream': summary_a, 'downstream': summary_b},
            'common_support_l': analysis['common_support_l'],
            'aligned_liters': analysis['aligned_liters'],
            'load_difference_mg': analysis['load_difference_mg'],
            'conditions': {'min_common_support_l': scalar(min_support),
                           'max_load_difference_mg': scalar(max_difference),
                           **analysis['feasible']},
            'verdict': 'witness' if analysis['witness'] else 'conflict',
            'witness': analysis['witness']}
