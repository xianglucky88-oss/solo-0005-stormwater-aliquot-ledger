"""Bottle custody and aliquot lineage.

Field bottles claim a trigger volume.  An aliquot is a portion split out of a
field bottle or out of another aliquot; it records the ``source`` it came from,
whether the source was ``homogenized`` before the split, and the custody
handoffs that followed.  An aliquot either provably represents its source's
whole trigger volume or it does not; an aliquot that does not is simply not
counted, because no partial volume is ever taken on faith.
"""
from fractions import Fraction

from .common import integer, require, unique

ROOMS = ('field', 'transport', 'lab')
_MIXED = ('homogenized', 'well_mixed', 'mixed')


def mixed(row, key):
    """Read the ``是否充分混匀`` flag, accepting a standard spelling."""
    found = [row[field] for field in _MIXED if field in row]
    require(all(type(value) is bool for value in found), f'homogenized must be boolean: {key}')
    require(len(set(found)) <= 1, f'contradictory homogenized flags: {key}')
    return bool(found) and found[0]


def handoffs(path, key):
    """Return the recorded ``(times, names)`` of a custody path.

    Only the shape is checked here; whether the path is *sufficient* is a
    scoring question handled by the caller, so a bad route degrades to
    ``incomplete_custody`` rather than rejecting the whole bundle.
    """
    require(isinstance(path, list) and bool(path), f'missing custody: {key}')
    times = [integer(p['at_s'], 'handoff time') for p in path]
    names = [p['holder'] for p in path]
    return times, names


def ordered(times):
    return times == sorted(times)


def reconcile(bottles, aliquots, triggers, tolerance):
    """Validate field bottles and resolve the aliquot lineage.

    Returns ``(facts, aliquot_facts, samples)``.  ``facts`` keeps the
    historical trigger-oriented bottle list; ``aliquot_facts`` describes every
    split; ``samples`` maps every bottle and aliquot id to its resolved lineage
    for the assay scorer.
    """
    rows = unique(bottles)
    listed = unique(aliquots) if aliquots else {}
    clash = set(rows) & set(listed)
    require(not clash, 'id defined as both bottle and aliquot')
    splits = dict(listed)
    for key, row in rows.items():
        if row.get('source') is not None:
            splits[key] = row
    field = {key: row for key, row in rows.items() if row.get('source') is None}
    samples_of = dict(rows, **listed)

    known = {t['number']: t for t in triggers}
    claims, extras = {}, []
    contexts, facts_by_key, samples = {}, {}, {}

    for key, row in sorted(field.items()):
        trigger_no = integer(row['trigger'], 'trigger number', 1)
        require(trigger_no not in claims, f'duplicate bottle for trigger: {trigger_no}')
        sampled_s = integer(row['sampled_s'], 'bottle sample time')
        times, names = handoffs(row['custody'], key)
        trigger = known.get(trigger_no)
        state = ('unconfirmed_trigger' if trigger is None else
                 'sample_time_outside_tolerance' if abs(Fraction(trigger['at_s']) - sampled_s) > tolerance else
                 'incomplete_custody' if tuple(names) != ROOMS or not ordered(times) or times[0] != sampled_s else
                 'received')
        fact = {'bottle': key, 'trigger': trigger_no, 'state': state, 'sampled_s': sampled_s,
                'received_s': times[-1] if state == 'received' else None}
        claims[trigger_no] = fact
        usable = state == 'received'
        samples[key] = {'kind': 'bottle', 'root': key, 'trigger': trigger_no, 'usable': usable,
                        'representative': usable, 'received_s': fact['received_s'],
                        'collected_s': sampled_s}
        contexts[key] = {'trigger': trigger_no, 'started_s': sampled_s, 'collected_s': sampled_s,
                         'root': key, 'usable': usable, 'representative': usable}
        if trigger is None:
            extras.append(fact)

    def resolve(key, trail):
        if key in contexts:
            return contexts[key]
        require(key not in trail, f'cyclic source chain: {key}')
        row = splits[key]
        source = row.get('source')
        require(isinstance(source, str) and bool(source.strip()), f'aliquot needs a source: {key}')
        require(source in samples_of, f'unknown source for aliquot {key}: {source}')
        parent = resolve(source, trail + (key,))
        homogenized = mixed(row, key)
        times, names = handoffs(row.get('custody', row.get('handoffs')), key)
        require(all(isinstance(name, str) and name in ROOMS for name in names),
                f'invalid handoff holder: {key}')
        require(ordered(times), f'handoff times out of order: {key}')
        ranks = [ROOMS.index(name) for name in names]
        split_s = times[0]
        if row.get('sampled_s') is not None:
            require(integer(row['sampled_s'], 'split time') == split_s,
                    f'split time disagrees with custody: {key}')
        if row.get('trigger') is not None:
            require(integer(row['trigger'], 'trigger number', 1) == parent['trigger'],
                    f'aliquot trigger does not match source: {key}')
        complete = names[-1] == 'lab' and ranks == sorted(ranks)
        state = ('split_before_source' if split_s < parent['started_s'] else
                 'source_unusable' if not parent['usable'] else
                 'incomplete_custody' if not complete else
                 'received')
        representative = state == 'received' and parent['representative'] and homogenized
        fact = {'aliquot': key, 'source': source, 'trigger': parent['trigger'], 'state': state,
                'split_s': split_s, 'collected_s': parent['collected_s'],
                'received_s': times[-1] if state == 'received' else None,
                'homogenized': homogenized, 'representative': representative}
        facts_by_key[key] = fact
        samples[key] = {'kind': 'aliquot', 'root': parent['root'], 'trigger': parent['trigger'],
                        'usable': state == 'received', 'representative': representative,
                        'received_s': fact['received_s'], 'collected_s': parent['collected_s']}
        contexts[key] = {'trigger': parent['trigger'], 'started_s': split_s,
                         'collected_s': parent['collected_s'], 'root': parent['root'],
                         'usable': state == 'received', 'representative': representative}
        return contexts[key]

    for key in sorted(splits):
        resolve(key, ())

    confirmed = [claims.get(t['number'], {'bottle': None, 'state': 'no_bottle', 'trigger': t['number']})
                 for t in triggers]
    return confirmed + extras, [facts_by_key[key] for key in sorted(splits)], samples
