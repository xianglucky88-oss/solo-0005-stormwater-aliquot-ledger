from fractions import Fraction

from .common import integer, number, require, scalar, unique


def load_report(method_rows, assay_rows, bottles, triggers):
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
        batch = row.get('batch')
        require(batch is None or (isinstance(batch, str) and batch.strip()), f'invalid assay batch: {batch!r}')
        result = row['status']
        require(result in ('measured', 'below_limit', 'invalid'), 'unknown assay status')
        low, high = (0, 0)
        if result != 'invalid':
            high = number(row['mg_l'], 'concentration or limit')
            require(result != 'below_limit' or high > 0, 'detection limit must be positive')
            low = high if result == 'measured' else 0
        state = ('bottle_unusable' if bottle['state'] != 'received' else
                 'assay_before_receipt' if at < bottle['received_s'] else
                 'holding_expired' if at - bottle['sampled_s'] > max_hold else
                 'invalid_result' if result == 'invalid' else 'supported')
        evidence = {'assay': key, 'bottle': bottle['bottle'], 'method': method, 'batch': batch,
                    'trigger': bottle['trigger'], 'source_status': result, 'state': state}
        if state == 'supported':
            a, b = map(Fraction, trigger_index[bottle['trigger']]['volume_l'])
            volume = b - a
            evidence.update(liters=scalar(volume), concentration_mg_l=[scalar(low), scalar(high)],
                            load_mg=[scalar(volume * low), scalar(volume * high)])
            supports[method].append(evidence)
        reports.append(evidence)
    totals = {}
    for method, records in supports.items():
        volume = sum(Fraction(r['liters']) for r in records)
        bounds = [sum(Fraction(r['load_mg'][i]) for r in records) for i in (0, 1)]
        totals[method] = {'supported_liters': scalar(volume), 'load_mg': list(map(scalar, bounds)) if records else None,
                          'assays': [r['assay'] for r in records]}
    return reports, totals
