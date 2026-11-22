from .common import number, require, scalar

NO_BOUND = 'unbounded'


def _bound(value, label):
    return None if value is None else number(value, label)


def _interval(row):
    """Read one reviewer group's load boundary; a missing side is unbounded."""
    group = row['id']
    require('load_mg' in row, f'review group {group} must supply load_mg')
    bounds = row['load_mg']
    if not isinstance(bounds, list):
        bounds = [bounds, bounds]
    require(len(bounds) == 2, f'invalid review group load_mg: {group}')
    low = _bound(bounds[0], f'review group {group} lower load')
    high = _bound(bounds[1], f'review group {group} upper load')
    require(low is not None or high is not None, f'review group {group} needs at least one load bound')
    require(low is None or high is None or low <= high, f'review group {group} has inverted load bounds')
    return low, high


def _reference(ref):
    """Accept {method, batch}, [method, batch] or a bare batch name."""
    if isinstance(ref, dict):
        return ref.get('method'), ref.get('batch')
    if isinstance(ref, list):
        require(len(ref) == 2, f'invalid review batch reference: {ref!r}')
        return ref[0], ref[1]
    return None, ref


def _references(row, batches):
    """Resolve optional method/batch references against materialized batches."""
    group = row['id']
    wanted = row.get('batches', [])
    require(isinstance(wanted, list), f'invalid review group batches: {group}')
    index = {(item['method'], item['batch']): item for item in batches}
    refs, assays = set(), set()
    for raw in wanted:
        method, batch = _reference(raw)
        require(method is None or isinstance(method, str), f'invalid review batch reference: {raw!r}')
        require(isinstance(batch, str) and batch.strip(), f'invalid review batch reference: {raw!r}')
        matches = [item for key, item in index.items()
                   if key[1] == batch and (method is None or key[0] == method)]
        require(matches, f'review group {group} references unknown batch: {batch!r}')
        for item in matches:
            refs.add((item['method'], item['batch']))
            assays.update(item['assays'])
    return sorted(refs), sorted(assays)


def _text(low, high):
    """An unbounded side stays unknown (null), never zero."""
    return (scalar(low) if low is not None else None,
            scalar(high) if high is not None else None)


def _label(low, high):
    return '[%s, %s]' % tuple(NO_BOUND if value is None else scalar(value)
                              for value in (low, high))


def judge(review, batches):
    """Judge two reviewer-supplied grouped load boundaries as one joint witness.

    The two groups have to hold together, so the joint range is their
    intersection: the highest lower bound with the lowest upper bound. Each
    group's own extremes are never spliced into a joint witness.
    """
    if review is None:
        return None
    require(isinstance(review, dict), 'review must be an object')
    groups = review.get('groups')
    require(isinstance(groups, list) and len(groups) == 2, 'review must supply exactly two groups')
    parsed, seen = [], set()
    for row in groups:
        require(isinstance(row, dict), 'review group must be an object')
        key = row.get('id')
        require(isinstance(key, str) and key.strip() and key not in seen,
                f'invalid or duplicate review group: {key!r}')
        seen.add(key)
        low, high = _interval(row)
        refs, assays = _references(row, batches)
        parsed.append({'id': key, 'low': low, 'high': high, 'refs': refs, 'assays': assays})
    lower = max((group['low'] for group in parsed if group['low'] is not None), default=None)
    upper = min((group['high'] for group in parsed if group['high'] is not None), default=None)
    shown = ', '.join(f'{group["id"]} {_label(group["low"], group["high"])}' for group in parsed)
    require(lower is None or upper is None or lower <= upper,
            f'group load bounds cannot both hold: {shown}')
    return {'groups': [{'id': group['id'],
                        'load_mg': list(_text(group['low'], group['high'])),
                        'batches': [{'method': method, 'batch': batch}
                                    for method, batch in group['refs']],
                        'assays': group['assays']}
                       for group in parsed],
            'compatible': True,
            'joint_load_mg': [scalar(lower) if lower is not None else None,
                              scalar(upper) if upper is not None else None]}
