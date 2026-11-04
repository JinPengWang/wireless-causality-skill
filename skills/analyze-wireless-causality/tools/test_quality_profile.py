"""Opt-in mapped-source diagnostics; never repair observations implicitly."""
import csv
import tempfile
import unittest
from pathlib import Path
from common import sha256
from quality_profile import profile


class QualityProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'measurements.csv'

    def request(self, rows, headers=('clock', 'device', 'seq')):
        with self.path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(headers); writer.writerows(rows)
        return {'schema_version': 1, 'source': {'path': str(self.path)},
                'time': {'column': headers[0], 'scale': .001, 'origin': 0},
                'identity_columns': [headers[1]], 'key_columns': [headers[2]],
                'density_window_s': 1, 'gap_threshold_s': 2}

    def test_monotone_gap_and_duplicate_candidates_preserve_rows(self):
        q = self.request([[0,'a',1],[100,'a',1],[3500,'a',2],[0,'b',1]])
        before = sha256(self.path); r = profile(q); a = r['groups'][0]
        self.assertEqual(a['duplicate_keys']['count'], 1)
        self.assertEqual(a['duplicate_keys']['examples'][0]['source_rows'], [2,3])
        self.assertEqual(a['forward_gaps']['count'], 1)
        self.assertEqual(a['forward_gaps']['examples'][0]['source_rows'], [3,4])
        self.assertEqual(a['density'], [{'start_s':0.,'end_s':1.,'records':2}, {'start_s':3.,'end_s':4.,'records':1}])
        self.assertEqual(r['selected_rows'], 4); self.assertEqual(sha256(self.path), before)

    def test_backward_invalid_and_equal_time_do_not_certify_gaps(self):
        q = self.request([[1000,'a',1],[1000,'a',2],[0,'a',3],['bad','a',4]])
        a = profile(q)['groups'][0]
        self.assertEqual(a['time_reversals']['count'], 1)
        self.assertEqual(a['adjacent_equal_times']['count'], 1)
        self.assertEqual(a['invalid_times']['count'], 1)
        self.assertEqual(a['forward_gaps']['status'], 'unavailable')

    def test_no_keys_means_no_duplication_judgment(self):
        q = self.request([[0,'a',1],[0,'a',1]]); q['key_columns'] = []
        self.assertEqual(profile(q)['groups'][0]['duplicate_keys']['status'], 'unavailable')

    def test_missing_identity_not_pooled_as_one_device(self):
        q = self.request([[0,'',1],[1,'',1],[2,'a',2]])
        r = profile(q)
        self.assertEqual(r['missing_identity']['count'], 2)
        self.assertEqual(r['groups'][0]['records'], 1)

    def test_explicit_names_and_units_not_guessed(self):
        q = self.request([[0,'a',1],[3500,'a',2]], ('ticks','unit','token'))
        self.assertEqual(profile(q)['groups'][0]['forward_gaps']['count'], 1)
        q['time']['scale'] = 0
        with self.assertRaises(ValueError): profile(q)

    def test_budgets_and_unknown_keys_fail_explicitly(self):
        q = self.request([[0,'a',1],[3500,'a',2]]); q['max_bins'] = 1
        with self.assertRaisesRegex(ValueError, 'budget'): profile(q)
        q.pop('max_bins'); q['auto_fill'] = True
        with self.assertRaises(ValueError): profile(q)

    def test_where_and_example_limit_keep_total_counts(self):
        q = self.request([[i,'a' if i<5 else 'b',1] for i in range(7)])
        q['source']['where'] = {'device':['a']}; q['max_examples'] = 1
        r = profile(q); a = r['groups'][0]
        self.assertEqual(r['selected_rows'],5)
        self.assertEqual(a['duplicate_keys']['count'],4)
        self.assertEqual(len(a['duplicate_keys']['examples']),1)


if __name__ == '__main__': unittest.main()
