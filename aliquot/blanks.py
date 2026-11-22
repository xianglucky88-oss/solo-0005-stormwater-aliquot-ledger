from fractions import Fraction

from .common import number, require, scalar, unique

BLANK_STATUSES = ('measured', 'below_limit', 'invalid')


def _interval(row, label):
    """Blank concentration is an interval: measured is a point, below limit is [0, limit]."""
    status = row['status']
    require(status in BLANK_STATUSES, f'unknown {label} status')
    if status == 'invalid':
        return status, None, None
    high = number(row['mg_l'], f'{label} concentration or limit')
    require(status != 'below_limit' or high > 0, 'detection limit must be positive')
    return status, (high if status == 'measured' else Fraction(0)), high


def index_blanks(rows, methods):
    """Index late-submitted method blanks by (method, batch).

    One blank value serves every assay in its batch, so a repeated method and
    batch is a conflicting reference rather than a second blank.
    """
    require(isinstance(rows, list), 'blanks must be a list')
    blanks = {}
    for key, row in sorted(unique(rows).items()):
        require(isinstance(row, dict), 'blank must be an object')
        method = row.get('method')
        require(method in methods, f'unknown method for blank: {method!r}')
        batch = row.get('batch')
        require(isinstance(batch, str) and batch.strip(), f'invalid blank batch: {batch!r}')
        status, low, high = _interval(row, 'blank')
        pair = (method, batch)
        require(pair not in blanks, f'duplicate blank for method and batch: {method}/{batch}')
        blanks[pair] = {'id': key, 'method': method, 'batch': batch, 'status': status,
                        'low': low, 'high': high, 'assays': []}
    return blanks


def _blank_rows(blanks):
    report = {}
    for blank in blanks.values():
        valid = blank['status'] != 'invalid'
        report[blank['id']] = {
            'id': blank['id'], 'method': blank['method'], 'batch': blank['batch'],
            'status': blank['status'],
            'concentration_mg_l': [scalar(blank['low']), scalar(blank['high'])] if valid else None,
            'state': ('invalid' if not valid else
                      'applied' if blank['assays'] else 'unused'),
            'assays': sorted(blank['assays'])}
    return report


def _batches(reports, blanks):
    """Batch membership is a factual one-to-many reference, independent of custody."""
    grouped = {}
    for row in reports:
        if row.get('batch') is not None:
            grouped.setdefault((row['method'], row['batch']), []).append(row)
    result = []
    for (method, batch), rows in sorted(grouped.items()):
        blank = blanks.get((method, batch))
        result.append({
            'method': method,
            'batch': batch,
            'blank': blank['id'] if blank is not None else None,
            'assays': sorted(row['assay'] for row in rows),
            'corrected_assays': sorted(row['assay'] for row in rows
                                       if row['correction'] == 'applied')})
    return result


def apply(reports, methods, rows):
    """Attach original and corrected loads without touching the original load.

    Correction needs custody, method and blank evidence to line up. A missing or
    unusable blank leaves the corrected load explicitly unknown, never zero, and
    the corrected concentration is clamped at the physical zero end.
    """
    blanks = index_blanks(rows, methods)
    for row in reports:
        row['blank'] = None
        row['corrected_concentration_mg_l'] = None
        row['corrected_load_mg'] = None
        if row['state'] != 'supported':
            row['correction'] = 'not_supported'
            continue
        batch = row.get('batch')
        if batch is None:
            row['correction'] = 'no_batch'
            continue
        blank = blanks.get((row['method'], batch))
        if blank is None:
            row['correction'] = 'no_blank'
            continue
        row['blank'] = blank['id']
        if blank['status'] == 'invalid':
            row['correction'] = 'blank_invalid'
            continue
        low, high = (Fraction(x) for x in row['concentration_mg_l'])
        liters = Fraction(row['liters'])
        corrected_low = max(Fraction(0), low - blank['high'])
        corrected_high = max(Fraction(0), high - blank['low'])
        row['corrected_concentration_mg_l'] = [scalar(corrected_low), scalar(corrected_high)]
        row['corrected_load_mg'] = [scalar(corrected_low * liters), scalar(corrected_high * liters)]
        row['correction'] = 'applied'
        blank['assays'].append(row['assay'])
    by_method = {}
    for row in reports:
        by_method.setdefault(row['method'], []).append(row)
    for method, total in methods.items():
        supported = [row for row in by_method.get(method, []) if row['state'] == 'supported']
        applied = [row for row in supported if row['correction'] == 'applied']
        total['corrected_assays'] = sorted(row['assay'] for row in applied)
        total['uncorrected_assays'] = sorted(row['assay'] for row in supported
                                             if row['correction'] != 'applied')
        total['blanks'] = sorted(blank['id'] for blank in blanks.values() if blank['method'] == method)
        # The original load above is never rewritten; the corrected total stays
        # unknown unless every supported assay had a usable blank.
        total['corrected_load_mg'] = None
        if supported and not total['uncorrected_assays']:
            total['corrected_load_mg'] = [
                scalar(sum(Fraction(row['corrected_load_mg'][i]) for row in applied)) for i in (0, 1)]
        total['correction'] = ('complete' if supported and not total['uncorrected_assays'] else
                               'partial' if applied else 'none')
    return _blank_rows(blanks), _batches(reports, blanks)
