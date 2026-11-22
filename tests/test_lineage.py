"""Contract tests for the aliquot lineage extension (standard library only)."""
import copy
import json
import unittest
from pathlib import Path

from aliquot.workflow import materialize

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / 'examples' / 'baseline.json').read_text(encoding='utf-8'))
ALIQUOTS = json.loads((ROOT / 'examples' / 'aliquots.json').read_text(encoding='utf-8'))


def bundle(assays=None, aliquots=None, methods=None, bottles=None):
    doc = copy.deepcopy(BASE)
    if assays is not None:
        doc['assays'] = assays
    if aliquots is not None:
        doc['aliquots'] = aliquots
    if methods is not None:
        doc['methods'] = methods
    if bottles is not None:
        doc['bottles'] = bottles
    return doc


def assay(key, method='m1', at=35, status='measured', mg=2, bottle=None, aliquot=None):
    row = {'id': key, 'method': method, 'at_s': at, 'status': status}
    if mg is not None:
        row['mg_l'] = mg
    if bottle is not None:
        row['bottle'] = bottle
    if aliquot is not None:
        row['aliquot'] = aliquot
    return row


def split(key, source, at, homogenized=True, rooms=('lab',), gap=10):
    """Build an aliquot split starting at ``at`` and moving through ``rooms``."""
    path = [{'holder': room, 'at_s': at + gap * index} for index, room in enumerate(rooms)]
    return {'id': key, 'source': source, 'homogenized': homogenized, 'custody': path}


def result(doc):
    return materialize(doc)


def method(doc, name='m1'):
    return materialize(doc)['methods'][name]


class Lineage(unittest.TestCase):
    def test_one_representative_volume_is_counted_once(self):
        # b1 and a split that provably represents b1 are the same volume.
        got = method(bundle(assays=[assay('x1', bottle='b1'), assay('x2', aliquot='s1')],
                            aliquots=[split('s1', 'b1', 30)]))
        self.assertEqual(got['supported_liters'], 10)
        self.assertEqual(got['load_mg'], [20, 20])
        self.assertEqual(sorted(got['assays']), ['x1', 'x2'])

    def test_sub_bottle_chain_also_counts_once(self):
        got = method(bundle(assays=[assay('x1', aliquot='s1'), assay('x2', aliquot='s2')],
                            aliquots=[split('s1', 'b2', 30), split('s2', 's1', 40)]))
        self.assertEqual(got['supported_liters'], 10)
        self.assertEqual(got['load_mg'], [20, 20])

    def test_direct_and_deep_split_reach_the_same_volume(self):
        # A reading taken directly after the split and one taken further down
        # the sub-bottle chain still describe the single trigger volume.
        got = method(bundle(assays=[assay('x1', aliquot='s1', at=45),
                                    assay('x2', aliquot='s2', at=50)],
                            aliquots=[split('s1', 'b1', 30), split('s2', 's1', 40)]))
        self.assertEqual(got['supported_liters'], 10)
        self.assertEqual(sorted(got['assays']), ['x1', 'x2'])

    def test_reading_only_at_the_deepest_bottle_counts_the_root(self):
        got = method(bundle(assays=[assay('x1', aliquot='s2', at=50)],
                            aliquots=[split('s1', 'b2', 30), split('s2', 's1', 40)]))
        self.assertEqual(got['supported_liters'], 10)
        self.assertEqual(got['load_mg'], [20, 20])

    def test_readings_within_tolerance_agree_and_span_bounds(self):
        got = method(bundle(assays=[assay('x1', bottle='b1', mg=2), assay('x2', aliquot='s1', mg=3)],
                            aliquots=[split('s1', 'b1', 30)],
                            methods=[{'id': 'm1', 'hold_s': 60, 'tolerance_mg_l': 1},
                                     {'id': 'm2', 'hold_s': 20}]))
        self.assertEqual(got['supported_liters'], 10)
        self.assertEqual(got['load_mg'], [20, 30])

    def test_contradictory_readings_drop_the_portion(self):
        seen = result(bundle(assays=[assay('x1', bottle='b1', mg=2), assay('x2', aliquot='s1', mg=9)],
                             aliquots=[split('s1', 'b1', 30)],
                             methods=[{'id': 'm1', 'hold_s': 60, 'tolerance_mg_l': 1},
                                      {'id': 'm2', 'hold_s': 20}]))
        got = seen['methods']['m1']
        self.assertEqual(got['supported_liters'], 0)
        self.assertIsNone(got['load_mg'])
        contested = [row for row in seen['assays'] if row['method'] == 'm1']
        self.assertEqual({row['state'] for row in contested}, {'conflicting'})
        self.assertTrue(all('load_mg' not in row and 'liters' not in row for row in contested))
        # The conflict is confined to m1; no other method is touched.
        self.assertIsNone(seen['methods']['m2']['load_mg'])

    def test_conflict_in_one_method_does_not_withdraw_another(self):
        seen = result(bundle(assays=[assay('x1', bottle='b4', at=70, mg=2),
                                     assay('x2', aliquot='s7', at=66, mg=9),
                                     assay('y1', aliquot='s4', method='m2', at=65, mg=4)],
                              aliquots=[split('s7', 'b4', 58), split('s4', 'b4', 60)],
                              methods=[{'id': 'm1', 'hold_s': 60, 'tolerance_mg_l': 1},
                                       {'id': 'm2', 'hold_s': 20, 'tolerance_mg_l': 1}]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertEqual(seen['methods']['m2']['supported_liters'], 10)
        self.assertEqual(seen['methods']['m2']['load_mg'], [40, 40])

    def test_unproven_mixing_withholds_whole_volume(self):
        seen = result(bundle(assays=[assay('x1', aliquot='s6')],
                             aliquots=[split('s6', 'b1', 30, homogenized=False)]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertIsNone(seen['methods']['m1']['load_mg'])
        self.assertEqual(seen['assays'][0]['state'], 'aliquot_unrepresentative')

    def test_mixing_cannot_be_restored_downstream(self):
        seen = result(bundle(assays=[assay('x2', aliquot='s2', at=55)],
                             aliquots=[split('s1', 'b2', 30, homogenized=False),
                                       split('s2', 's1', 40)]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertEqual(seen['assays'][0]['state'], 'aliquot_unrepresentative')

    def test_broken_chain_and_its_children_are_unusable(self):
        seen = result(bundle(assays=[assay('x1', aliquot='s1'), assay('x2', aliquot='s2')],
                             aliquots=[split('s1', 'b2', 40, rooms=('lab', 'transport')),
                                       split('s2', 's1', 50)]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertEqual({row['aliquot']: row['state'] for row in seen['assays']},
                         {'s1': 'aliquot_unusable', 's2': 'aliquot_unusable'})
        self.assertEqual({row['aliquot']: row['state'] for row in seen['aliquots']},
                         {'s1': 'incomplete_custody', 's2': 'source_unusable'})

    def test_split_of_unusable_bottle_is_unusable(self):
        seen = result(bundle(assays=[assay('x1', aliquot='s1')],
                             aliquots=[split('s1', 'b3', 50)]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertEqual(seen['assays'][0]['state'], 'aliquot_unusable')

    def test_split_before_collection_is_not_counted(self):
        seen = result(bundle(assays=[assay('x1', aliquot='s1')],
                             aliquots=[split('s1', 'b1', 5)]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertEqual(seen['aliquots'][0]['state'], 'split_before_source')

    def test_holding_time_runs_from_original_collection(self):
        # b1 was collected at 12 s, so an assay at 80 s exceeds m1's 60 s hold.
        seen = result(bundle(assays=[assay('x1', aliquot='s1', at=80)],
                             aliquots=[split('s1', 'b1', 30)]))
        self.assertEqual(seen['methods']['m1']['supported_liters'], 0)
        self.assertEqual(seen['assays'][0]['state'], 'holding_expired')


class Legacy(unittest.TestCase):
    def test_field_bottle_result_unchanged(self):
        self.assertEqual(method(bundle(assays=[assay('x1', bottle='b1')])),
                         {'supported_liters': 10, 'load_mg': [20, 20],
                          'assays': ['x1'], 'known_liters_without_assay': 62})

    def test_baseline_and_changed_documents(self):
        for name, expected in (('baseline', (30, [20, 50], ['a1', 'a2', 'a4'])),
                               ('changed', (20, [0, 30], ['a1', 'a2']))):
            doc = json.loads((ROOT / 'examples' / f'{name}.json').read_text(encoding='utf-8'))
            seen = materialize(doc)
            got = seen['methods']['m1']
            self.assertEqual((got['supported_liters'], got['load_mg'], got['assays']), expected, name)
            self.assertNotIn('aliquots', seen)

    def test_aliquots_example(self):
        first, second = materialize(ALIQUOTS)['methods'].values()
        self.assertEqual((first['supported_liters'], first['load_mg'], first['assays']),
                         (20, [0, 30], ['a1', 'a2', 'a7', 'a8']))
        self.assertEqual((second['supported_liters'], second['load_mg'], second['assays']),
                         (10, [40, 40], ['a9']))


class Rejection(unittest.TestCase):
    def assert_rejected(self, doc):
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_cycle(self):
        self.assert_rejected(bundle(assays=[], aliquots=[split('s1', 's2', 30), split('s2', 's1', 40)]))

    def test_unknown_source(self):
        self.assert_rejected(bundle(assays=[assay('x1', aliquot='s1')],
                                    aliquots=[split('s1', 'missing', 30)]))

    def test_assay_needs_one_reference(self):
        self.assert_rejected(bundle(assays=[assay('x1', bottle='b1', aliquot='s1')],
                                    aliquots=[split('s1', 'b1', 30)]))
        self.assert_rejected(bundle(assays=[assay('x1')]))

    def test_duplicate_sample_and_method(self):
        self.assert_rejected(bundle(assays=[assay('x1', aliquot='s1'), assay('x2', aliquot='s1')],
                                    aliquots=[split('s1', 'b1', 30)]))

    def test_homogenized_must_be_boolean(self):
        bad = split('s1', 'b1', 30)
        bad['homogenized'] = 'yes'
        self.assert_rejected(bundle(assays=[assay('x1', aliquot='s1')], aliquots=[bad]))

    def test_trigger_must_match_source(self):
        bad = split('s1', 'b1', 30)
        bad['trigger'] = 4
        self.assert_rejected(bundle(assays=[assay('x1', aliquot='s1')], aliquots=[bad]))

    def test_unknown_holder(self):
        self.assert_rejected(bundle(assays=[assay('x1', aliquot='s1')],
                                    aliquots=[split('s1', 'b1', 30, rooms=('courier',))]))


if __name__ == '__main__':
    unittest.main()
