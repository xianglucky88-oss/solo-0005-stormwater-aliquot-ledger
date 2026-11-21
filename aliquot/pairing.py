"""Reconcile two independent sampling plans on one provable cumulative axis.

Plans may use different trigger volumes, bottle chains and method records, so
trigger numbers are local labels and never used to intersect evidence. Only
geometric volume intervals backed by certified flow count as common support.
"""
from fractions import Fraction

from .common import pieces, require, scalar


def certified_segments(flow):
    """Certified volume intervals with provable absolute coordinates.

    The anchored prefix is one continuous segment ending at the first flow
    gap; each later measured run is a segment whose coordinate origin is
    unknown, so it cannot be placed on the shared axis and is omitted here
    but still appears in the plan's known liters.
    """
    segments = []
    anchored = Fraction(flow['anchored_liters'])
    if anchored > 0:
        segments.append((Fraction(0), anchored))
    return segments


def interval_union(intervals):
    ordered = sorted(intervals)
    merged = []
    for lo, hi in ordered:
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def interval_intersection(a_list, b_list):
    out = []
    for a in a_list:
        for b in b_list:
            piece = pieces(a, b)
            if piece is not None:
                out.append(piece)
    return out


def supported_map(result, method_id):
    """Plan-local trigger intervals carrying a supported assay for a method."""
    wanted = set(result['methods'][method_id]['assays'])
    by_trigger = {}
    for evidence in result['assays']:
        if evidence['assay'] in wanted:
            by_trigger[evidence['trigger']] = evidence
    intervals = []
    for trigger in result['flow']['triggers']:
        evidence = by_trigger.get(trigger['number'])
        if evidence is None:
            continue
        lo, hi = map(Fraction, trigger['volume_l'])
        intervals.append((lo, hi, trigger['number'], evidence))
    intervals.sort()
    return intervals


def split_piece(intervals, piece):
    """Cut supported intervals down to one common-support piece."""
    lo, hi = piece
    cuts = []
    for a, b, number, evidence in intervals:
        part = pieces((a, b), (lo, hi))
        if part is not None:
            cuts.append((part[0], part[1], number, evidence))
    return cuts


def recompute_load(cuts):
    low = high = Fraction(0)
    liters = Fraction(0)
    for lo, hi, _number, evidence in cuts:
        volume = hi - lo
        c_lo, c_hi = map(Fraction, evidence['concentration_mg_l'])
        low += volume * c_lo
        high += volume * c_hi
        liters += volume
    return liters, low, high


def _no_common_reason(a_trigger, b_trigger, common_volume):
    if common_volume == 0:
        return 'no_geometric_overlap'
    if a_trigger is None or b_trigger is None:
        return 'one_side_not_supported'
    return 'overlap_not_supported'


def pair_plans(first, second, compare_method_first, compare_method_second,
               mixed_first, mixed_second):
    """Build the auditable paired result for two materialized plans."""
    plan_a, plan_b = first['plan'], second['plan']
    result_a, result_b = first['result'], second['result']
    method_a, method_b = result_a['methods'][compare_method_first], result_b['methods'][compare_method_second]

    segments_a = certified_segments(result_a['flow'])
    segments_b = certified_segments(result_b['flow'])
    overlap_pieces = interval_intersection(segments_a, segments_b)
    overlap_liters = sum((hi - lo for lo, hi in overlap_pieces), Fraction(0))

    supported_a = supported_map(result_a, compare_method_first)
    supported_b = supported_map(result_b, compare_method_second)
    union_a = interval_union([(lo, hi) for lo, hi, _n, _e in supported_a])
    union_b = interval_union([(lo, hi) for lo, hi, _n, _e in supported_b])
    common_pieces = interval_intersection(
        interval_intersection(union_a, union_b), overlap_pieces)
    common_liters = sum((hi - lo for lo, hi in common_pieces), Fraction(0))

    # Same-number audit: equal trigger labels never establish common support.
    numbers = {t['number'] for t in result_a['flow']['triggers']}
    numbers.update(t['number'] for t in result_b['flow']['triggers'])
    triggers_a = {t['number']: t for t in result_a['flow']['triggers']}
    triggers_b = {t['number']: t for t in result_b['flow']['triggers']}
    same_number = []
    for number in sorted(numbers):
        ta, tb = triggers_a.get(number), triggers_b.get(number)
        if ta is None or tb is None:
            continue
        overlap = pieces(tuple(map(Fraction, ta['volume_l'])),
                         tuple(map(Fraction, tb['volume_l'])))
        piece_volume = Fraction(0) if overlap is None else overlap[1] - overlap[0]
        has_common = overlap is not None and any(
            pieces(overlap, piece) is not None for piece in common_pieces)
        if has_common:
            continue
        evidence_a = next((e for _lo, _hi, n, e in supported_a if n == number), None)
        evidence_b = next((e for _lo, _hi, n, e in supported_b if n == number), None)
        same_number.append({
            'trigger_number': number,
            'volume_l': [[scalar(x) for x in ta['volume_l']], [scalar(x) for x in tb['volume_l']]],
            'overlap_liters': scalar(piece_volume),
            'reason': _no_common_reason(evidence_a, evidence_b, piece_volume)})

    # Cross-number matches prove intersection is geometric, not label based.
    cross_number = []
    piece_records = []
    for lo, hi in common_pieces:
        cuts_a = split_piece(supported_a, (lo, hi))
        cuts_b = split_piece(supported_b, (lo, hi))
        for _plo, _phi, number_a, _evidence in cuts_a:
            for _qlo, _qhi, number_b, _evidence in cuts_b:
                if number_a != number_b:
                    cross_number.append({
                        'piece_l': [scalar(lo), scalar(hi)],
                        'triggers': {plan_a: number_a, plan_b: number_b}})
        piece_records.append({'piece_l': [scalar(lo), scalar(hi)],
                              'triggers': {plan_a: sorted({n for _a, _b, n, _e in cuts_a}),
                                           plan_b: sorted({n for _a, _b, n, _e in cuts_b})}})

    method_loads = {
        plan_a: {'method': compare_method_first,
                 'supported_liters': method_a['supported_liters'],
                 'load_mg': method_a['load_mg']},
        plan_b: {'method': compare_method_second,
                 'supported_liters': method_b['supported_liters'],
                 'load_mg': method_b['load_mg']}}

    pairing = {
        'plans': [plan_a, plan_b],
        'methods': {plan_a: compare_method_first, plan_b: compare_method_second},
        'certified_axis': {
            plan_a: {'segments_l': [[scalar(lo), scalar(hi)] for lo, hi in segments_a],
                     'known_liters': result_a['flow']['known_liters'],
                     'anchored_liters': result_a['flow']['anchored_liters']},
            plan_b: {'segments_l': [[scalar(lo), scalar(hi)] for lo, hi in segments_b],
                     'known_liters': result_b['flow']['known_liters'],
                     'anchored_liters': result_b['flow']['anchored_liters']}},
        'overlap_certified_liters': scalar(overlap_liters),
        'common_support_liters': scalar(common_liters),
        'common_pieces': piece_records,
        'same_number_without_common': same_number,
        'cross_number_matches': cross_number,
        'method_loads_on_own_support': method_loads}

    if common_liters == 0:
        pairing['recomputable'] = False
        pairing['reason'] = 'no_common_supported_subvolume'
        pairing['common_load_mg'] = None
        pairing['load_difference_mg'] = None
        return pairing

    if not (mixed_first and mixed_second):
        pairing['recomputable'] = False
        pairing['reason'] = 'plan_protocol_does_not_permit_subvolume_recompute'
        pairing['common_load_mg'] = None
        pairing['load_difference_mg'] = None
        return pairing

    liters_a, low_a, high_a = recompute_load(
        [cut for piece in common_pieces for cut in split_piece(supported_a, piece)])
    liters_b, low_b, high_b = recompute_load(
        [cut for piece in common_pieces for cut in split_piece(supported_b, piece)])
    require(liters_a == common_liters and liters_b == common_liters,
            'common subvolume denominator mismatch')
    pairing['recomputable'] = True
    pairing['reason'] = 'bottles_mixed_and_subvolume_permitted'
    pairing['common_load_mg'] = {
        plan_a: list(map(scalar, (low_a, high_a))),
        plan_b: list(map(scalar, (low_b, high_b)))}
    # Bounds of (plan_a load - plan_b load) over the identical denominator.
    pairing['load_difference_mg'] = {
        'expression': f'{plan_a}-{plan_b}',
        'bounds_mg': list(map(scalar, (low_a - high_b, high_a - low_b)))}
    return pairing
