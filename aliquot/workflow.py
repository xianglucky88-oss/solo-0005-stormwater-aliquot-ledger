from fractions import Fraction

from .chemistry import load_report
from .common import number, scalar
from .custody import reconcile
from .flow import hydrograph

DESCRIPTION = 'Build volume-trigger and load evidence for a synthetic stormwater event.'


def materialize(doc):
    flow = hydrograph(doc)
    bottles, aliquots, samples = reconcile(doc['bottles'], doc.get('aliquots', []), flow['triggers'],
                                           number(doc['tolerance_s'], 'sample time tolerance'))
    assays, methods = load_report(doc['methods'], doc['assays'], flow['triggers'], samples)
    for row in methods.values():
        row['known_liters_without_assay'] = scalar(Fraction(flow['known_liters']) - Fraction(row['supported_liters']))
    result = {'event': doc['event'], 'flow': flow, 'bottles': bottles, 'assays': assays, 'methods': methods}
    if aliquots:
        result['aliquots'] = aliquots
    return result
