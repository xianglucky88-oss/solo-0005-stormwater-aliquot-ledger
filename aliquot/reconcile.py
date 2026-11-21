from fractions import Fraction


def _f(value):
    return Fraction(value)


def _scalar(value):
    value = Fraction(value)
    return value.numerator if value.denominator == 1 else str(value)


def balance(flow, bottles, methods, assays):
    """Cross-check event, per-segment and cross-split evidence.

    Water volume always closes exactly. Loads only close against the event view
    when no independent composition evidence re-describes a cross-split trigger;
    composition-based segment loads are reported as a separate, finer-grained view.
    """
    segments = flow['segments']
    known = sum(_f(seg['known_liters']) for seg in segments)
    anchored = sum(_f(seg['anchored_liters']) for seg in segments)
    checks = []

    def check(name, condition):
        checks.append({'check': name, 'ok': bool(condition)})
        if not condition:
            raise ValueError(f'reconciliation failed: {name}')

    check('segment_known_liters_equal_event', known == _f(flow['known_liters']))
    missing_s = sum(seg['missing_seconds'] for seg in segments)
    anchored_ok = anchored == _f(flow['anchored_liters'])
    checks.append({'check': 'segment_anchored_liters_equal_event', 'ok': bool(anchored_ok),
                   'note': None if anchored_ok else 'missing evidence interrupts the anchored prefix'})
    if not anchored_ok:
        # Not a hard failure: a documented gap legitimately prevents an anchored-prefix closure.
        assert missing_s > 0

    for trigger in flow['triggers']:
        a, b = map(_f, trigger['volume_l'])
        part_total = sum(_f(part['liters']) for part in trigger['segments'])
        check(f'trigger_{trigger["number"]}_segment_liters', part_total == b - a)

    split_by_composition = {a['assay'] for a in assays if a.get('split_state') == 'split_by_composition'}
    method_rows = []
    for method, total in methods.items():
        attributed = [Fraction(0), Fraction(0)]
        unattributed = [Fraction(0), Fraction(0)]
        composition_load = [Fraction(0), Fraction(0)]
        composition_assays = []
        for assay in (a for a in assays if a['method'] == method and a['state'] == 'supported'):
            if assay.get('split_state') == 'split_by_composition':
                composition_assays.append(assay['assay'])
                for entry in assay['segment_loads']:
                    composition_load[0] += _f(entry['load_mg'][0])
                    composition_load[1] += _f(entry['load_mg'][1])
        for row in total['segments']:
            attributed[0] += _f(row['load_mg'][0])
            attributed[1] += _f(row['load_mg'][1])
        for row in total['cross_split_unsplit']:
            unattributed[0] += _f(row['load_mg'][0])
            unattributed[1] += _f(row['load_mg'][1])
        event_load = list(map(_f, total['load_mg'])) if total['load_mg'] is not None else [Fraction(0), Fraction(0)]
        # The event view counts whole-trigger assays; composition assays replace, not add to, that load.
        event_without_composition = [
            event_load[i] - sum(_f(a['load_mg'][i]) for a in assays
                                if a['method'] == method and a.get('split_state') == 'split_by_composition')
            for i in (0, 1)]
        closes = (attributed[i] - composition_load[i] + unattributed[i] == event_without_composition[i]
                  for i in (0, 1))
        check(f'{method}_load_mg_reconciles', all(closes))
        method_rows.append({
            'method': method,
            'segment_load_mg': list(map(_scalar, attributed)),
            'cross_split_unsplit_load_mg': list(map(_scalar, unattributed)),
            'composition_split_load_mg': list(map(_scalar, composition_load)),
            'composition_assays': composition_assays,
            'event_load_mg': list(map(_scalar, event_load))})

    classification = {'single_segment': [], 'cross_split': [], 'no_bottle': [], 'unconfirmed': []}
    for bottle in bottles:
        if bottle['bottle'] is None:
            classification['no_bottle'].append(bottle['trigger'])
        elif not bottle.get('crosses_split', False) and 'segments' not in bottle:
            classification['unconfirmed'].append(bottle['bottle'])
        elif bottle.get('crosses_split'):
            classification['cross_split'].append(bottle['bottle'])
        else:
            classification['single_segment'].append(bottle['bottle'])
    check('cross_split_bottle_set_matches_composition_evidence',
          {a['bottle'] for a in assays if a.get('split_state') in
           ('split_by_composition', 'unsplit_cross_split')} == set(classification['cross_split']))
    return {'checks': checks, 'methods': method_rows, 'bottles': classification,
            'segment_known_liters': _scalar(known), 'segment_anchored_liters': _scalar(anchored)}
