"""Standard-library acceptance checks for single-plan and paired bundles."""
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from aliquot.archive import history, load, publish
from aliquot.common import decode, encode
from aliquot.workflow import materialize

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples'


def load_example(name):
    return decode((EXAMPLES / name).read_text(encoding='utf-8'))


def paired(overrides=None):
    doc = load_example('paired.json')
    if overrides:
        for key, value in overrides.items():
            doc[key] = value
    return doc


class LegacyContract(unittest.TestCase):
    def test_baseline_independent_values(self):
        result = materialize(load_example('baseline.json'))
        self.assertEqual(result['flow']['known_liters'], 72)
        self.assertEqual(result['flow']['anchored_liters'], 52)
        m1 = result['methods']['m1']
        self.assertEqual(m1['supported_liters'], 30)
        self.assertEqual(m1['load_mg'], [20, 50])

    def test_changed_edition_loses_lab_handoff(self):
        result = materialize(load_example('changed.json'))
        m1 = result['methods']['m1']
        self.assertEqual(m1['supported_liters'], 20)
        self.assertEqual(m1['load_mg'], [0, 30])

    def test_invalid_bundle_rejected(self):
        with self.assertRaises(ValueError):
            materialize(load_example('invalid.json'))

    def test_archive_roundtrip_and_replay(self):
        doc = load_example('baseline.json')
        result = materialize(doc)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'ledger.sqlite'
            publish(db, 'original', doc, result)
            self.assertEqual([row['edition'] for row in history(db)], ['original'])
            stored = load(db, 'original')
            self.assertEqual(encode(stored), encode(result))
            self.assertEqual(encode(load(db, 'original', source=True)), encode(doc))
            with self.assertRaises(ValueError):
                publish(db, 'original', doc, result)


class PairedGeometry(unittest.TestCase):
    def setUp(self):
        self.result = materialize(paired())
        self.pair = self.result['pairing']

    def test_plans_share_one_provable_axis(self):
        axis = self.pair['certified_axis']
        for plan in ('planA', 'planB'):
            self.assertEqual(axis[plan]['anchored_liters'], 52)
            self.assertEqual(axis[plan]['known_liters'], 72)
            self.assertEqual(axis[plan]['segments_l'], [[0, 52]])
        self.assertEqual(self.pair['overlap_certified_liters'], 52)

    def test_common_support_is_geometric_denominator(self):
        # A supports [0,20] U [30,40]; B supports [0,30] U [37.5,45];
        # inside the certified [0,52] axis -> [0,15] U [30,37.5] = 25 L.
        self.assertEqual(self.pair['common_support_liters'], 25)
        self.assertEqual(Fraction(self.pair['common_support_liters']), Fraction(25))

    def test_trigger_number_intersection_is_not_used(self):
        audit = {row['trigger_number']: row for row in self.pair['same_number_without_common']}
        self.assertEqual({3, 4, 5}, set(audit))
        self.assertEqual(audit[3]['reason'], 'one_side_not_supported')
        self.assertEqual(audit[3]['overlap_liters'], '5/2')
        self.assertEqual(audit[4]['reason'], 'no_geometric_overlap')
        self.assertEqual(audit[4]['overlap_liters'], 0)
        self.assertEqual(audit[5]['reason'], 'no_geometric_overlap')

    def test_cross_number_matches_prove_geometry(self):
        matched = {(tuple(m['triggers'].values())) for m in self.pair['cross_number_matches']}
        self.assertIn((1, 2), matched)
        self.assertIn((2, 1), matched)
        self.assertIn((4, 5), matched)
        self.assertIn((4, 6), matched)

    def test_mixed_protocol_recomputes_common_load(self):
        pair = self.pair
        self.assertTrue(pair['recomputable'])
        # A: piece [0,10] at 4 mg/L + [10,15] true zero + [30,37.5] at 2 mg/L.
        load_a = tuple(map(Fraction, pair['common_load_mg']['planA']))
        self.assertEqual(load_a, (Fraction(60), Fraction(60)))
        load_b = tuple(map(Fraction, pair['common_load_mg']['planB']))
        self.assertEqual(load_b, (Fraction(165, 2), Fraction(175, 2)))
        bounds = tuple(map(Fraction, pair['load_difference_mg']['bounds_mg']))
        self.assertEqual(bounds, (Fraction(-55, 2), Fraction(-45, 2)))

    def test_true_zero_is_a_measurement_not_null(self):
        a2 = next(a for a in self.result['plans'][0]['assays'] if a['assay'] == 'A-a2')
        self.assertEqual(a2['state'], 'supported')
        self.assertEqual(a2['concentration_mg_l'], [0, 0])
        # The zero piece contributes 0 mg but still counts toward the denominator.
        self.assertEqual(Fraction(self.pair['common_support_liters']), Fraction(25))

    def test_own_support_loads_remain_separately_listed(self):
        own = self.pair['method_loads_on_own_support']
        self.assertEqual(own['planA']['load_mg'], [60, 60])
        self.assertEqual(own['planB']['supported_liters'], '75/2')


class PairedProtocols(unittest.TestCase):
    def test_unmixed_protocol_blocks_recompute(self):
        doc = paired({'bottle_mixed': {'planA': False, 'planB': True}})
        pair = materialize(doc)['pairing']
        self.assertFalse(pair['recomputable'])
        self.assertEqual(pair['reason'], 'plan_protocol_does_not_permit_subvolume_recompute')
        self.assertIsNone(pair['common_load_mg'])
        # Overlap water and own-method quantities stay auditable separately.
        self.assertEqual(pair['overlap_certified_liters'], 52)
        self.assertEqual(pair['common_support_liters'], 25)
        self.assertIsNotNone(pair['method_loads_on_own_support']['planA']['load_mg'])

    def test_missing_protocol_rejected(self):
        doc = paired()
        del doc['bottle_mixed']
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_no_common_supported_subvolume(self):
        doc = paired()
        for bottle in doc['plans'][0]['bottles']:
            bottle['custody'] = bottle['custody'][:1]
        pair = materialize(doc)['pairing']
        self.assertEqual(pair['common_support_liters'], 0)
        self.assertFalse(pair['recomputable'])
        self.assertEqual(pair['reason'], 'no_common_supported_subvolume')
        self.assertIsNone(pair['common_load_mg'])
        self.assertEqual(pair['overlap_certified_liters'], 52)

    def test_all_zero_common_load_is_real_zero(self):
        doc = paired()
        for assay in doc['plans'][0]['assays']:
            assay['mg_l'] = 0
        pair = materialize(doc)['pairing']
        self.assertEqual(pair['common_load_mg']['planA'], [0, 0])
        self.assertEqual(pair['common_support_liters'], 25)

    def test_below_limit_stays_interval_in_recompute(self):
        doc = paired()
        pair = materialize(doc)['pairing']
        # B-a6 below_limit 2 mg/L over [37.5,40] keeps [0,2] bounds.
        low_b, high_b = map(Fraction, pair['common_load_mg']['planB'])
        self.assertLess(low_b, high_b)


class PairedRejection(unittest.TestCase):
    def test_flow_rate_disagreement_rejected(self):
        doc = paired()
        doc['plans'][1]['runs'][0]['units'] = 5
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_one_sided_gap_overlap_rejected(self):
        doc = paired()
        doc['plans'][1]['runs'][5]['units'] = 3
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_duplicate_plan_id_rejected(self):
        doc = paired()
        doc['plans'][1]['id'] = doc['plans'][0]['id']
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_unknown_compare_method_rejected(self):
        doc = paired({'compare_method': {'planA': 'nope', 'planB': 'mB'}})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_null_compare_method_rejected(self):
        doc = paired({'compare_method': {'planA': None, 'planB': 'mB'}})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_leaked_plan_field_rejected(self):
        doc = paired({'runs': []})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_wrong_plan_count_rejected(self):
        doc = paired()
        doc['plans'] = [doc['plans'][0]]
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_non_boolean_protocol_rejected(self):
        doc = paired({'bottle_mixed': {'planA': 'yes', 'planB': True}})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_malformed_protocol_container_rejected(self):
        doc = paired({'bottle_mixed': [True, True]})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_plans_not_a_list_rejected(self):
        doc = paired()
        doc['plans'] = {'planA': doc['plans'][0]}
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_multiple_methods_require_explicit_compare(self):
        doc = load_example('paired.json')
        del doc['compare_method']
        doc['plans'][0]['methods'].append({'id': 'mA2', 'hold_s': 10})
        with self.assertRaises(ValueError):
            materialize(doc)
        explicit = paired({'compare_method': {'planA': 'mA', 'planB': 'mB'}})
        pair = materialize(explicit)['pairing']
        self.assertEqual(pair['methods']['planA'], 'mA')
        self.assertTrue(pair['recomputable'])

    def test_paired_archive_roundtrip(self):
        doc = paired()
        result = materialize(doc)
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'ledger.sqlite'
            publish(db, 'pair-1', doc, result)
            self.assertEqual(encode(load(db, 'pair-1')), encode(result))
            replay = materialize(load(db, 'pair-1', source=True))
            self.assertEqual(encode(replay), encode(result))


if __name__ == '__main__':
    unittest.main(verbosity=2)
