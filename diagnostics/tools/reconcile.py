#!/usr/bin/env python3
"""Time-phased reconciliation diagnostic (read-only, does not touch the reducer).

Inputs are materialized result documents produced by the original entrypoint
(`python -m aliquot preview|replay`). The tool re-derives which *time* interval
each certified trigger volume actually occupies by walking the certified
cumulative flow and the trigger's provenance runs -- never the bottle sample
times and never trigger numbers alone.

Reconciliation rules implemented here (mirrors PROJECT_SPEC.md, adds nothing to
the production reducer):
  * flow inside a calibrated run is interpreted at constant rate;
  * a trigger fully inside the query window contributes its whole certified
    load closure; one fully outside contributes nothing;
  * a trigger only partially intersecting the window yields an exact certified
    sub-volume from the rate map, but its load MUST NOT be pro-rated: the only
    defensible closure is [0, trigger high bound] on that partial piece;
  * uncensored (unanchored / missing-flow) volume is never treated as zero and
    whole-bottle loads are never spread by time share.
"""
import argparse
import json
from fractions import Fraction


def F(x):
    return Fraction(x) if not isinstance(x, Fraction) else x


def rate_map(result):
    """Per-run constant rate (L/s) from certified liters and run seconds."""
    out = {}
    for row in result['flow']['runs']:
        if row['liters'] is not None:
            lo, hi = map(F, row['seconds'])
            out[row['run']] = (lo, hi, F(row['liters']) / (hi - lo))
    return out


def trigger_footprints(result):
    """Reconstruct the time interval covered by each trigger's certified volume.

    Walks the trigger's provenance runs (the reducer records which runs feed a
    trigger) and maps cumulative liters back onto seconds at each run's rate.
    Bottle sample times and trigger numbers are never used for this mapping.
    """
    rates = rate_map(result)
    feet = {}
    for t in result['flow']['triggers']:
        vlo, vhi = map(F, t['volume_l'])
        segments = []
        remaining_lo, remaining_hi = vlo, vhi
        # cumulative liters before each run come from the ordered, certified
        # run list itself (the same prefix the reducer walks); uncensored runs
        # carry None and can never supply a trigger's provenance.
        cursor = F(0)
        run_pieces = []
        for row in result['flow']['runs']:
            lo, hi = map(F, row['seconds'])
            if row['liters'] is None:
                run_pieces.append((row['run'], lo, hi, None, None))
                continue
            vol = F(row['liters'])
            run_pieces.append((row['run'], lo, hi, cursor, cursor + vol))
            cursor += vol
        for run, lo, hi, pre, post in run_pieces:
            if run not in t['runs'] or pre is None:
                continue
            a = max(pre, remaining_lo)
            b = min(post, remaining_hi)
            if a < b:
                _, _, rate = rates[run]
                t0 = lo + (a - pre) / rate
                t1 = lo + (b - pre) / rate
                segments.append({'run': run, 'seconds': [t0, t1],
                                 'liters': [a, b], 'piece_liters': b - a})
        start = min(s['seconds'][0] for s in segments)
        end = max(s['seconds'][1] for s in segments)
        total_piece = sum((s['piece_liters'] for s in segments), Fraction(0))
        feet[t['number']] = {'trigger': t['number'], 'seconds': [start, end],
                             'volume_l': [vlo, vhi], 'segments': segments,
                             'reconstructed_liters': total_piece,
                             'at_s': F(t['at_s'])}
    return feet


def method_support(result):
    """Map method -> trigger -> certified assay evidence (supported only)."""
    support = {}
    for ev in result['assays']:
        if ev['state'] != 'supported':
            continue
        support.setdefault(ev['method'], {})[ev['trigger']] = ev
    return support


def reconcile_window(result, method, wlo, whi):
    feet = trigger_footprints(result)
    support = method_support(result).get(method, {})
    rows = []
    exact_low = exact_high = Fraction(0)
    bound_low = bound_high = Fraction(0)
    certified_in_window = Fraction(0)
    for trig in sorted(support):
        ev = support[trig]
        foot = feet[trig]
        slo, shi = foot['seconds']
        load_lo, load_hi = map(F, ev['load_mg'])
        if shi <= wlo or slo >= whi:
            relation = 'outside'
            piece_liters = Fraction(0)
            piece_load = [Fraction(0), Fraction(0)]
            defensible = [Fraction(0), Fraction(0)]
        elif slo >= wlo and shi <= whi:
            relation = 'full'
            piece_liters = sum((s['piece_liters'] for s in foot['segments']), Fraction(0))
            piece_load = [load_lo, load_hi]
            defensible = [load_lo, load_hi]
            exact_low += load_lo
            exact_high += load_hi
            certified_in_window += piece_liters
        else:
            relation = 'partial'
            piece_liters = Fraction(0)
            for seg in foot['segments']:
                a, b = seg['seconds']
                ov_lo, ov_hi = max(a, wlo), min(b, whi)
                if ov_lo < ov_hi:
                    _, _, rate = rate_map(result)[seg['run']]
                    piece_liters += (ov_hi - ov_lo) * rate
            # no pro-rata load: partial piece only earns a [0, high] closure
            piece_load = [Fraction(0), load_hi]
            defensible = [Fraction(0), load_hi]
            certified_in_window += piece_liters
        bound_low += defensible[0]
        bound_high += defensible[1]
        rows.append({'trigger': trig, 'footprint_s': [_scalar(slo), _scalar(shi)],
                     'relation': relation,
                     'certified_piece_liters': _scalar(piece_liters),
                     'full_trigger_load_mg': [_scalar(load_lo), _scalar(load_hi)],
                     'defensible_load_in_window_mg': [_scalar(defensible[0]), _scalar(defensible[1])],
                     'load_is_exact': relation == 'full'})
    full_only = all(r['relation'] in ('full', 'outside') for r in rows)
    if not full_only:
        comparability = 'bounds_only_no_proration'
    elif certified_in_window == 0:
        comparability = 'no_certified_support_evidence_insufficient'
    else:
        comparability = 'direct_exact'
    return {
        'method': method, 'window_s': [_scalar(wlo), _scalar(whi)],
        'supported_triggers_present': sorted(support),
        'rows': rows,
        'certified_supported_liters_in_window': _scalar(certified_in_window),
        'exact_load_mg': [_scalar(exact_low), _scalar(exact_high)] if full_only else None,
        'defensible_load_bounds_mg': [_scalar(bound_low), _scalar(bound_high)],
        'comparability': comparability,
    }


def flow_coverage(result, wlo, whi):
    """Split the liters inside a window into certified vs uncensored pieces.

    Known flow after the first gap stays known as liters but loses cumulative
    anchoring: it can never back a trigger. Gap time has no certified liters at
    all -- neither class is ever reported as a measured zero.
    """
    rates = rate_map(result)
    certified_liters = gap_seconds = Fraction(0)
    unanchored_known_liters = Fraction(0)
    anchored_prefix = F(result['flow']['anchored_liters'])
    for row in result['flow']['runs']:
        lo, hi = map(F, row['seconds'])
        a, b = max(lo, wlo), min(hi, whi)
        if a >= b:
            continue
        if row['liters'] is None:
            gap_seconds += b - a
            continue
        _, _, rate = rates[row['run']]
        piece = (b - a) * rate
        if row['prefix_before_l'] is None:
            unanchored_known_liters += piece
        else:
            certified_liters += piece
    return {'window_s': [_scalar(wlo), _scalar(whi)],
            'certified_anchored_liters_in_window': _scalar(certified_liters),
            'known_but_unanchored_liters_in_window': _scalar(unanchored_known_liters),
            'no_calibration_gap_seconds_in_window': _scalar(gap_seconds),
            'event_known_liters': result['flow']['known_liters'],
            'event_anchored_prefix_liters': result['flow']['anchored_liters'],
            'note': 'unanchored liters and gaps are never treated as measured zero'}


def _scalar(q):
    q = F(q)
    return q.numerator if q.denominator == 1 else f'{q.numerator}/{q.denominator}'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('result_json', nargs='+', help='materialized result documents, label=path or path')
    ap.add_argument('--method', default='m1')
    ap.add_argument('--window', action='append', default=[],
                    help='lo-hi seconds, repeatable; defaults to the demo set')
    args = ap.parse_args()
    docs = {}
    for item in args.result_json:
        label, _, path = item.partition('=')
        if not path:
            label, path = item, item
        with open(path, encoding='utf-8') as fh:
            docs[label] = json.load(fh)
    windows = []
    for w in args.window or ['0-65', '40-55', '5-25', '0-100', '70-90']:
        lo, hi = w.split('-')
        windows.append((Fraction(lo), Fraction(hi)))

    report = {'footprints': {}, 'reconciliation': {}}
    for label, doc in docs.items():
        feet = trigger_footprints(doc)
        # sanity: every reconstructed footprint must reproduce its trigger volume
        for n, foot in feet.items():
            assert foot['reconstructed_liters'] == (F(foot['volume_l'][1]) - F(foot['volume_l'][0])), label
        report['footprints'][label] = {
            n: {'seconds': [_scalar(f['seconds'][0]), _scalar(f['seconds'][1])],
                'volume_l': [_scalar(f['volume_l'][0]), _scalar(f['volume_l'][1])],
                'at_s_reducer': _scalar(f['at_s']),
                'segments': [{'run': s['run'],
                              'seconds': [_scalar(s['seconds'][0]), _scalar(s['seconds'][1])],
                              'piece_liters': _scalar(s['piece_liters'])} for s in f['segments']]}
            for n, f in sorted(feet.items())}
        report['reconciliation'][label] = [
            reconcile_window(doc, args.method, lo, hi) for lo, hi in windows]
        report.setdefault('flow_coverage', {})[label] = [
            flow_coverage(doc, lo, hi) for lo, hi in windows]
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
