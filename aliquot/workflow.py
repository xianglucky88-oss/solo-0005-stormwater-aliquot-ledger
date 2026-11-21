from fractions import Fraction

from .chemistry import load_report
from .common import boolean, number, require, scalar, span, unique
from .custody import reconcile
from .flow import hydrograph, hydrograph_plan
from .pairing import pair_plans

DESCRIPTION = 'Build volume-trigger and load evidence for a synthetic stormwater event.'

PLAN_SCOPED_FIELDS = frozenset(
    {'trigger_liters', 'tolerance_s', 'runs', 'bottles', 'methods', 'assays'})


def materialize(doc):
    if isinstance(doc, dict) and 'plans' in doc:
        return materialize_paired(doc)
    flow = hydrograph(doc)
    bottles = reconcile(doc['bottles'], flow['triggers'], number(doc['tolerance_s'], 'sample time tolerance'))
    assays, methods = load_report(doc['methods'], doc['assays'], bottles, flow['triggers'])
    for row in methods.values():
        row['known_liters_without_assay'] = scalar(Fraction(flow['known_liters']) - Fraction(row['supported_liters']))
    return {'event': doc['event'], 'flow': flow, 'bottles': bottles, 'assays': assays, 'methods': methods}


def _rate_rows(doc, runs):
    rate = number(doc['liters_per_unit'], 'flow calibration')
    start, end = span(doc['event_seconds'], 'event window')
    rows = []
    for row in runs:
        lo, hi = span(row['seconds'], 'flow run')
        require(start <= lo < hi <= end, f'run outside event: {row.get("id")!r}')
        if row['units'] is None:
            rows.append((lo, hi, None, None))
        else:
            units = number(row['units'], 'flow units')
            rows.append((lo, hi, units, units * rate / (hi - lo)))
    return rows


def _check_shared_flow(doc):
    """Both plans describe one physical event: equal rates on overlapping time."""
    plans = doc['plans']
    require(isinstance(plans, list), 'plans must be a list of two plan objects')
    for index, plan in enumerate(plans):
        require(isinstance(plan, dict), f'plan {index} must be an object')
        for field in ('id', 'trigger_liters', 'tolerance_s', 'runs', 'bottles', 'methods', 'assays'):
            require(field in plan, f'plan missing field: {field}')
    leaked = PLAN_SCOPED_FIELDS.intersection(doc)
    require(not leaked, f'plan-scoped field must live inside plans: {sorted(leaked)}')
    unique(plans, 'id')
    rate_lists = [_rate_rows(doc, p['runs']) for p in plans]
    for a in rate_lists[0]:
        for b in rate_lists[1]:
            lo, hi = max(a[0], b[0]), min(a[1], b[1])
            if lo >= hi:
                continue
            if a[2] is None and b[2] is None:
                continue
            require(a[2] is not None and b[2] is not None,
                    f'unmeasured flow overlap between plans: {[lo, hi]}')
            require(a[3] == b[3],
                    f'flow rate disagrees on overlapping run: {[lo, hi]}')


def materialize_plan(doc, plan):
    start, end = span(doc['event_seconds'], 'event window')
    rate = number(doc['liters_per_unit'], 'flow calibration')
    threshold = number(plan['trigger_liters'], 'trigger volume')
    flow = hydrograph_plan(plan['runs'], start, end, rate, threshold)
    bottles = reconcile(plan['bottles'], flow['triggers'],
                        number(plan['tolerance_s'], 'sample time tolerance'))
    assays, methods = load_report(plan['methods'], plan['assays'], bottles, flow['triggers'])
    for row in methods.values():
        row['known_liters_without_assay'] = scalar(Fraction(flow['known_liters']) - Fraction(row['supported_liters']))
    return {'event': doc['event'], 'flow': flow, 'bottles': bottles, 'assays': assays, 'methods': methods}


def materialize_paired(doc):
    require(isinstance(doc.get('plans'), list) and len(doc['plans']) == 2,
            'paired bundle must contain exactly two plans')
    _check_shared_flow(doc)
    plans = []
    method_ids = set()
    for plan in doc['plans']:
        result = materialize_plan(doc, plan)
        plans.append({'plan': plan['id'], 'result': result})
        ids = set(result['methods'])
        require(not ids.intersection(method_ids), f'method id reused across plans: {sorted(ids)}')
        method_ids.update(ids)
    first, second = plans
    compare = doc.get('compare_method', {})
    require(isinstance(compare, dict), 'compare_method must map plan id to method id')

    def resolve(chosen, result, plan_id):
        if chosen is None:
            require(plan_id not in compare,
                    f'compare_method must not be null for plan: {plan_id}')
            require(len(result['methods']) == 1,
                    f'compare_method required when plan has several methods: {plan_id}')
            return next(iter(result['methods']))
        require(chosen in result['methods'], f'unknown compare method: {chosen}')
        return chosen

    compare_first = resolve(compare.get(first['plan']), first['result'], first['plan'])
    compare_second = resolve(compare.get(second['plan']), second['result'], second['plan'])
    mixed_first = boolean(_mixed_flag(doc, first['plan']), f'bottle_mixed for {first["plan"]}')
    mixed_second = boolean(_mixed_flag(doc, second['plan']), f'bottle_mixed for {second["plan"]}')
    pairing = pair_plans(first, second, compare_first, compare_second, mixed_first, mixed_second)
    return {'event': doc['event'], 'kind': 'paired',
            'plans': [{'plan': p['plan'], **p['result']} for p in plans], 'pairing': pairing}


def _mixed_flag(doc, plan_id):
    require('bottle_mixed' in doc, f'bottle_mixed protocol missing for plan: {plan_id}')
    protocol = doc['bottle_mixed']
    require(isinstance(protocol, dict), 'bottle_mixed must map plan id to boolean')
    require(plan_id in protocol, f'bottle_mixed protocol missing for plan: {plan_id}')
    return protocol[plan_id]
