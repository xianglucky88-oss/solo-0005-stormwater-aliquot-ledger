"""Behaviour checks for method-blank corrections and reviewer group bounds."""
import json
import unittest
from copy import deepcopy
from pathlib import Path

from aliquot.archive import history, load, publish
from aliquot.common import encode
from aliquot.workflow import materialize

EXAMPLES = Path(__file__).resolve().parent.parent / 'examples'


def bundle(name):
    return json.loads((EXAMPLES / f'{name}.json').read_text(encoding='utf-8'))


def assays(result):
    return {row['assay']: row for row in result['assays']}


class BlankCorrectionTest(unittest.TestCase):
    def test_original_load_is_never_rewritten(self):
        before = {row['assay']: row.get('load_mg') for row in materialize(bundle('baseline'))['assays']}
        after = assays(materialize(bundle('blanks')))
        self.assertEqual(after['a1']['load_mg'], [0, 30])
        self.assertEqual(after['a2']['load_mg'], [0, 0])
        self.assertEqual(after['a4']['load_mg'], [20, 20])
        self.assertEqual(before['a4'], [20, 20])

    def test_measured_blank_subtracts_from_measured_result(self):
        result = assays(materialize(bundle('blanks')))
        row = result['a4']
        self.assertEqual(row['correction'], 'applied')
        self.assertEqual(row['blank'], 'z2')
        self.assertEqual(row['corrected_concentration_mg_l'], [1, 1])
        self.assertEqual(row['corrected_load_mg'], [10, 10])
        self.assertEqual(row['load_mg'], [20, 20])

    def test_below_limit_blank_keeps_lower_bound_physical(self):
        row = assays(materialize(bundle('blanks')))['a1']
        self.assertEqual(row['source_status'], 'below_limit')
        self.assertEqual(row['corrected_concentration_mg_l'], [0, 3])
        self.assertEqual(row['corrected_load_mg'], [0, 30])

    def test_missing_blank_is_unknown_not_zero(self):
        row = assays(materialize(bundle('blanks')))['a7']
        self.assertEqual(row['correction'], 'no_blank')
        self.assertIsNone(row['blank'])
        self.assertIsNone(row['corrected_load_mg'])
        self.assertIsNone(row['corrected_concentration_mg_l'])
        method = materialize(bundle('blanks'))['methods']['m2']
        self.assertIsNone(method['corrected_load_mg'])
        self.assertEqual(method['uncorrected_assays'], ['a7'])

    def test_one_blank_shared_by_whole_batch(self):
        result = materialize(bundle('blanks'))
        self.assertEqual(result['blanks']['z1']['assays'], ['a1', 'a2'])
        batches = {(b['method'], b['batch']): b for b in result['batches']}
        self.assertEqual(batches[('m1', 'L1')]['blank'], 'z1')
        self.assertEqual(batches[('m1', 'L1')]['assays'], ['a1', 'a2'])
        self.assertIsNone(batches[('m2', 'L3')]['blank'])

    def test_correction_clamps_negative_end(self):
        doc = bundle('blanks')
        for assay in doc['assays']:
            if assay['id'] == 'a4':
                assay['mg_l'] = 1
        for blank in doc['blanks']:
            if blank['id'] == 'z2':
                blank['mg_l'] = 2
        row = assays(materialize(doc))['a4']
        self.assertEqual(row['corrected_concentration_mg_l'], [0, 0])
        self.assertEqual(row['corrected_load_mg'], [0, 0])

    def test_duplicate_blank_for_same_method_and_batch_is_rejected(self):
        doc = bundle('blanks')
        doc['blanks'].append({'id': 'z9', 'method': 'm1', 'batch': 'L1',
                              'status': 'measured', 'mg_l': 1})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_blank_for_unknown_method_is_rejected(self):
        doc = bundle('blanks')
        doc['blanks'].append({'id': 'z9', 'method': 'mX', 'batch': 'L1',
                              'status': 'measured', 'mg_l': 1})
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_invalid_blank_leaves_correction_unknown(self):
        doc = bundle('blanks')
        for blank in doc['blanks']:
            if blank['id'] == 'z2':
                blank['status'] = 'invalid'
                blank.pop('mg_l')
        result = materialize(doc)
        self.assertEqual(assays(result)['a4']['correction'], 'blank_invalid')
        self.assertIsNone(assays(result)['a4']['corrected_load_mg'])
        self.assertEqual(result['blanks']['z2']['state'], 'invalid')

    def test_custody_failure_blocks_correction(self):
        doc = bundle('blanks')
        for bottle in doc['bottles']:
            if bottle['id'] == 'b4':
                bottle['custody'] = bottle['custody'][:-1]
        result = assays(materialize(doc))
        self.assertEqual(result['a4']['state'], 'bottle_unusable')
        self.assertEqual(result['a4']['correction'], 'not_supported')
        self.assertIsNone(result['a4']['corrected_load_mg'])

    def test_no_batch_reports_unknown_correction(self):
        doc = bundle('blanks')
        for assay in doc['assays']:
            if assay['id'] == 'a1':
                assay.pop('batch')
        result = materialize(doc)
        self.assertEqual(assays(result)['a1']['correction'], 'no_batch')
        self.assertEqual(result['methods']['m1']['correction'], 'partial')


class ReviewTest(unittest.TestCase):
    def test_lower_group_and_upper_group_can_both_hold(self):
        doc = bundle('blanks')
        doc['review'] = {'groups': [{'id': 'A', 'load_mg': [60, None]},
                                    {'id': 'B', 'load_mg': [None, 80]}]}
        review = materialize(doc)['review']
        self.assertTrue(review['compatible'])
        self.assertEqual(review['joint_load_mg'], [60, 80])

    def test_overlapping_groups_intersect_not_union(self):
        doc = bundle('blanks')
        doc['review'] = {'groups': [{'id': 'A', 'load_mg': [40, 60]},
                                    {'id': 'B', 'load_mg': [50, 70]}]}
        review = materialize(doc)['review']
        self.assertEqual(review['joint_load_mg'], [50, 60])

    def test_groups_that_cannot_both_hold_are_rejected(self):
        doc = bundle('blanks')
        doc['review'] = {'groups': [{'id': 'A', 'load_mg': [60, None]},
                                    {'id': 'B', 'load_mg': [None, 50]}]}
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_review_requires_two_groups(self):
        doc = bundle('blanks')
        doc['review'] = {'groups': [{'id': 'A', 'load_mg': [40, 60]}]}
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_review_groups_link_batches_one_to_many(self):
        review = materialize(bundle('blanks'))['review']
        groups = {group['id']: group for group in review['groups']}
        self.assertEqual(groups['g1']['batches'], [{'method': 'm1', 'batch': 'L1'}])
        self.assertEqual(groups['g1']['assays'], ['a1', 'a2'])
        self.assertEqual(groups['g2']['assays'], ['a4'])

    def test_review_unknown_batch_reference_is_rejected(self):
        doc = bundle('blanks')
        doc['review']['groups'][0]['batches'] = [{'method': 'm1', 'batch': 'L9'}]
        with self.assertRaises(ValueError):
            materialize(doc)

    def test_touching_groups_still_intersect_at_one_point(self):
        doc = bundle('blanks')
        doc['review'] = {'groups': [{'id': 'A', 'load_mg': [40, 60]},
                                    {'id': 'B', 'load_mg': [60, 70]}]}
        self.assertEqual(materialize(doc)['review']['joint_load_mg'], [60, 60])

    def test_one_sided_group_bound_leaves_other_side_unknown(self):
        doc = bundle('blanks')
        doc['review'] = {'groups': [{'id': 'A', 'load_mg': [None, 60]},
                                    {'id': 'B', 'load_mg': [None, 70]}]}
        review = materialize(doc)['review']
        self.assertEqual(review['joint_load_mg'], [None, 60])
        self.assertEqual(review['groups'][0]['load_mg'], [None, 60])

    def test_absent_review_is_null(self):
        self.assertIsNone(materialize(bundle('baseline'))['review'])


class ArchiveTest(unittest.TestCase):
    def test_publish_replay_roundtrip_with_blanks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.sqlite'
            doc = bundle('blanks')
            publish(path, 'one', doc, materialize(doc))
            stored = load(path, 'one')
            self.assertEqual(encode(stored), encode(materialize(load(path, 'one', source=True))))
            self.assertEqual([row['edition'] for row in history(path)], ['one'])

    def test_edition_names_are_immutable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ledger.sqlite'
            doc = bundle('baseline')
            publish(path, 'one', doc, materialize(doc))
            with self.assertRaises(ValueError):
                publish(path, 'one', doc, materialize(doc))


if __name__ == '__main__':
    unittest.main()
