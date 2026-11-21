from fractions import Fraction

from .chemistry import load_report
from .common import number, scalar
from .custody import reconcile
from .flow import hydrograph
from .reconcile import balance

DESCRIPTION = 'Build volume-trigger and load evidence for a synthetic stormwater event.'


def materialize(doc):
    flow = hydrograph(doc)
    segmented = flow.get('segmented', False)
    bottles = reconcile(doc['bottles'], flow['triggers'],
                        number(doc['tolerance_s'], 'sample time tolerance'), segmented)
    assays, methods = load_report(doc['methods'], doc['assays'], bottles, flow['triggers'], segmented)
    segmented = 'segments' in flow
    for row in methods.values():
        row['known_liters_without_assay'] = scalar(Fraction(flow['known_liters']) - Fraction(row['supported_liters']))
    result = {'event': doc['event'], 'flow': flow, 'bottles': bottles, 'assays': assays, 'methods': methods}
    if segmented:
        result['reconciliation'] = balance(flow, bottles, methods, assays)
    return result
