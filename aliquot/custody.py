from fractions import Fraction

from .common import integer, require, unique


def reconcile(bottles, triggers, tolerance):
    claims = {}
    known = {t['number']: t for t in triggers}
    extras = []
    rooms = ('field', 'transport', 'lab')
    for key, row in sorted(unique(bottles).items()):
        trigger_no = integer(row['trigger'], 'trigger number', 1)
        require(trigger_no not in claims, f'duplicate bottle for trigger: {trigger_no}')
        sampled_s = integer(row['sampled_s'], 'bottle sample time')
        path = row['custody']
        times = [integer(p['at_s'], 'handoff time') for p in path]
        names = [p['holder'] for p in path]
        trigger = known.get(trigger_no)
        state = ('unconfirmed_trigger' if trigger is None else
                 'sample_time_outside_tolerance' if abs(Fraction(trigger['at_s']) - sampled_s) > tolerance else
                 'incomplete_custody' if tuple(names) != rooms or times != sorted(times) or times[0] != sampled_s else
                 'received')
        fact = {'bottle': key, 'trigger': trigger_no, 'state': state, 'sampled_s': sampled_s,
                'received_s': times[-1] if state == 'received' else None}
        claims[trigger_no] = fact
        if trigger is None:
            extras.append(fact)
    confirmed = [claims.get(t['number'], {'bottle': None, 'state': 'no_bottle', 'trigger': t['number']}) for t in triggers]
    return confirmed + extras
