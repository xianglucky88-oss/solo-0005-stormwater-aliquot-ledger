from fractions import Fraction

from .common import integer, number, require, scalar, unique


def _bounds(status, mg_l, label):
    high = number(mg_l, label)
    require(status != 'below_limit' or high > 0, 'detection limit must be positive')
    low = high if status == 'measured' else Fraction(0)
    return low, high


def _composition(entries, trigger):
    parts = {part['segment']: Fraction(part['liters']) for part in trigger['segments']}
    require(isinstance(entries, list) and entries, 'composition needs at least one segment entry')
    seen = set()
    evidence = {}
    for entry in entries:
        seg = integer(entry['segment'], 'composition segment', 1)
        require(seg in parts, f'composition segment not covered by trigger: {seg}')
        require(seg not in seen, f'duplicate composition segment: {seg}')
        seen.add(seg)
        status = entry['status']
        require(status in ('measured', 'below_limit'), 'composition status must be measured or below_limit')
        low, high = _bounds(status, entry['mg_l'], 'composition concentration or limit')
        evidence[seg] = (status, low, high)
    require(seen == set(parts), 'composition must cover every segment of the cross-split trigger')
    return evidence, parts


def load_report(method_rows, assay_rows, bottles, triggers, segmented=False):
    methods = unique(method_rows)
    bottle_index = {b['bottle']: b for b in bottles if b['bottle'] is not None}
    trigger_index = {t['number']: t for t in triggers}
    supports = {k: [] for k in sorted(methods)}
    holds = {k: integer(r['hold_s'], 'method holding time', 0) for k, r in methods.items()}
    reports = []
    seen = set()
    for key, row in sorted(unique(assay_rows).items()):
        bottle, method = bottle_index[row['bottle']], row['method']
        max_hold = holds[method]
        require((bottle['bottle'], method) not in seen, f'duplicate assay for bottle and method: {key}')
        seen.add((bottle['bottle'], method))
        at = integer(row['at_s'], 'assay time')
        result = row['status']
        require(result in ('measured', 'below_limit', 'invalid'), 'unknown assay status')
        low, high = (0, 0)
        if result != 'invalid':
            low, high = _bounds(result, row['mg_l'], 'concentration or limit')
        state = ('bottle_unusable' if bottle['state'] != 'received' else
                 'assay_before_receipt' if at < bottle['received_s'] else
                 'holding_expired' if at - bottle['sampled_s'] > max_hold else
                 'invalid_result' if result == 'invalid' else 'supported')
        trigger = trigger_index.get(bottle['trigger'])
        evidence = {'assay': key, 'bottle': bottle['bottle'], 'method': method, 'trigger': bottle['trigger'],
                    'source_status': result, 'state': state}
        if state == 'supported':
            a, b = map(Fraction, trigger['volume_l'])
            volume = b - a
            evidence.update(liters=scalar(volume), concentration_mg_l=[scalar(low), scalar(high)],
                            load_mg=[scalar(volume * low), scalar(volume * high)])
            if segmented:
                _segment_evidence(evidence, row, trigger, low, high, key)
            supports[method].append(evidence)
        elif 'composition' in row:
            require(False, f'composition cannot support unusable assay: {key}')
        reports.append(evidence)
    totals = {}
    for method, records in supports.items():
        volume = sum(Fraction(r['liters']) for r in records)
        bounds = [sum(Fraction(r['load_mg'][i]) for r in records) for i in (0, 1)]
        total = {'supported_liters': scalar(volume),
                 'load_mg': list(map(scalar, bounds)) if records else None,
                 'assays': [r['assay'] for r in records]}
        if segmented:
            total['segments'], total['cross_split_unsplit'] = _segment_totals(records)
        totals[method] = total
    return reports, totals


def _segment_evidence(evidence, row, trigger, low, high, key):
    has_composition = 'composition' in row
    if trigger['crosses_split']:
        if has_composition:
            comp, parts = _composition(row['composition'], trigger)
            loads = []
            for seg in sorted(parts):
                status, c_low, c_high = comp[seg]
                part_volume = parts[seg]
                loads.append({'segment': seg, 'liters': scalar(part_volume),
                              'source_status': status,
                              'concentration_mg_l': [scalar(c_low), scalar(c_high)],
                              'load_mg': [scalar(part_volume * c_low), scalar(part_volume * c_high)]})
            evidence.update(split_state='split_by_composition', segment_loads=loads)
        else:
            loads = [{'segment': part['segment'], 'liters': part['liters'],
                      'concentration_mg_l': None, 'load_mg': None}
                     for part in trigger['segments']]
            evidence.update(split_state='unsplit_cross_split', segment_loads=loads)
    else:
        require(not has_composition, f'composition only applies to cross-split triggers: {key}')
        seg = trigger['segments'][0]['segment']
        evidence.update(split_state='single_segment',
                        segment_loads=[{'segment': seg, 'liters': trigger['segments'][0]['liters'],
                                        'source_status': evidence['source_status'],
                                        'concentration_mg_l': [scalar(low), scalar(high)],
                                        'load_mg': [scalar(Fraction(trigger['segments'][0]['liters']) * low),
                                                    scalar(Fraction(trigger['segments'][0]['liters']) * high)]}])


def _segment_totals(records):
    acc, unsplit = {}, []
    for record in records:
        if record['split_state'] == 'unsplit_cross_split':
            unsplit.append({'assay': record['assay'], 'trigger': record['trigger'],
                            'liters': record['liters'], 'load_mg': record['load_mg'],
                            'segments': [entry['segment'] for entry in record['segment_loads']]})
            continue
        for entry in record['segment_loads']:
            item = acc.setdefault(entry['segment'], {'segment': entry['segment'], 'liters': Fraction(0),
                                                      'low': Fraction(0), 'high': Fraction(0),
                                                      'assays': []})
            item['liters'] += Fraction(entry['liters'])
            item['low'] += Fraction(entry['load_mg'][0])
            item['high'] += Fraction(entry['load_mg'][1])
            item['assays'].append(record['assay'])
    segments = [{'segment': seg, 'anchored_liters': scalar(item['liters']),
                 'load_mg': [scalar(item['low']), scalar(item['high'])],
                 'assays': item['assays']}
                for seg, item in sorted(acc.items())]
    return segments, unsplit
