from fractions import Fraction

from .common import integer, number, require, scalar, unique


def load_report(method_rows, assay_rows, triggers, samples):
    """Score assays against the sample lineage.

    ``samples`` maps every field bottle and aliquot id to its resolved lineage
    (``kind``, ``root``, ``trigger``, ``representative``, ``usable``,
    ``received_s`` and ``collected_s``).  A field bottle and every aliquot
    derived from it share one root: they represent the same trigger volume, so
    within one method that volume is only accounted once, however many splits
    the reading travelled through.
    """
    methods = unique(method_rows)
    holds = {k: integer(r['hold_s'], 'method holding time', 0) for k, r in methods.items()}
    tolerances = {k: number(r.get('tolerance_mg_l', 0), 'method reading tolerance')
                  for k, r in methods.items()}
    trigger_index = {t['number']: t for t in triggers}
    reports, qualified = [], []
    seen = set()
    for key, row in sorted(unique(assay_rows).items()):
        refs = [row.get(field) for field in ('bottle', 'aliquot') if row.get(field) is not None]
        require(len(refs) == 1, f'assay needs exactly one bottle or aliquot: {key}')
        sample_id, method = refs[0], row['method']
        require(sample_id in samples, f'unknown sample for assay {key}: {sample_id}')
        require(method in methods, f'unknown method for assay {key}: {method}')
        info = samples[sample_id]
        require((sample_id, method) not in seen, f'duplicate assay for sample and method: {key}')
        seen.add((sample_id, method))
        at = integer(row['at_s'], 'assay time')
        result = row['status']
        require(result in ('measured', 'below_limit', 'invalid'), 'unknown assay status')
        low, high = (0, 0)
        if result != 'invalid':
            high = number(row['mg_l'], 'concentration or limit')
            require(result != 'below_limit' or high > 0, 'detection limit must be positive')
            low = high if result == 'measured' else 0
        max_hold = holds[method]
        state = ('bottle_unusable' if info['kind'] == 'bottle' and not info['usable'] else
                 'aliquot_unusable' if info['kind'] == 'aliquot' and not info['usable'] else
                 'assay_before_receipt' if at < info['received_s'] else
                 'holding_expired' if at - info['collected_s'] > max_hold else
                 'invalid_result' if result == 'invalid' else
                 'aliquot_unrepresentative' if info['kind'] == 'aliquot' and not info['representative'] else
                 'supported')
        evidence = {'assay': key, 'method': method, 'trigger': info['trigger'],
                    'source_status': result, 'state': state}
        if info['kind'] == 'aliquot':
            evidence['aliquot'] = sample_id
        else:
            evidence['bottle'] = sample_id
        if state == 'supported':
            a, b = map(Fraction, trigger_index[info['trigger']]['volume_l'])
            volume = b - a
            evidence.update(liters=scalar(volume), concentration_mg_l=[scalar(low), scalar(high)],
                            load_mg=[scalar(volume * low), scalar(volume * high)])
            qualified.append((method, info['root'], evidence, low, high, volume))
        reports.append(evidence)

    groups = {}
    for method, root, evidence, low, high, volume in qualified:
        groups.setdefault((method, root), []).append((evidence, low, high, volume))
    totals = {}
    for method in methods:
        volume_total, bounds, assays = Fraction(0), [Fraction(0), Fraction(0)], []
        for (owner, _), entries in sorted(groups.items()):
            if owner != method:
                continue
            if conflict(entries, tolerances[method]):
                for evidence, _, _, _ in entries:
                    evidence['state'] = 'conflicting'
                    evidence.pop('liters', None)
                    evidence.pop('concentration_mg_l', None)
                    evidence.pop('load_mg', None)
                continue
            volume = entries[0][3]
            low = min(reading[1] for reading in entries)
            high = max(reading[2] for reading in entries)
            volume_total += volume
            bounds[0] += volume * low
            bounds[1] += volume * high
            assays.extend(evidence['assay'] for evidence, _, _, _ in entries)
        totals[method] = {'supported_liters': scalar(volume_total),
                          'load_mg': list(map(scalar, bounds)) if assays else None,
                          'assays': sorted(assays)}
    return reports, totals


def conflict(entries, tolerance):
    """True when two qualified readings of one represented volume disagree.

    Readings are closed intervals; a gap no wider than the method tolerance is
    agreement, anything wider is a contradiction.  Contested portions are
    neither force-selected nor averaged, so the whole portion drops out.
    """
    intervals = [(low, high) for _, low, high, _ in entries]
    return any(max(a[0], b[0]) - min(a[1], b[1]) > tolerance
               for index, a in enumerate(intervals) for b in intervals[index + 1:])
