from fractions import Fraction

from . import blanks, review
from .chemistry import load_report
from .common import number, scalar
from .custody import reconcile
from .flow import hydrograph

DESCRIPTION = 'Build volume-trigger and load evidence for a synthetic stormwater event.'


def materialize(doc):
    flow = hydrograph(doc)
    bottles = reconcile(doc['bottles'], flow['triggers'], number(doc['tolerance_s'], 'sample time tolerance'))
    assays, methods = load_report(doc['methods'], doc['assays'], bottles, flow['triggers'])
    blank_rows, batches = blanks.apply(assays, methods, doc.get('blanks', []))
    for row in methods.values():
        row['known_liters_without_assay'] = scalar(Fraction(flow['known_liters']) - Fraction(row['supported_liters']))
    return {'event': doc['event'], 'flow': flow, 'bottles': bottles, 'assays': assays,
            'blanks': blank_rows, 'batches': batches, 'methods': methods,
            'review': review.judge(doc.get('review'), batches)}
