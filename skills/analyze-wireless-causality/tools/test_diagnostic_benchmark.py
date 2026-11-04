import tempfile
import unittest
from pathlib import Path
from common import read_json, sha256
from diagnostic_benchmark import prepare


class DiagnosticBenchmarkTests(unittest.TestCase):
    def test_reference_arithmetic_censoring_and_unperformed_behavioral_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'benchmark'; r=prepare(root)
            self.assertEqual(r['B01']['bitmap_states_only']['101'],'not_acknowledged_in_this_bitmap')
            self.assertEqual(r['B03']['groups'][0]['duplicate_keys']['count'],1)
            self.assertEqual(r['B03']['groups'][0]['forward_gaps']['examples'][0]['duration_s'],3)
            event=r['B04'][0]
            self.assertEqual((event['start_s'],event['end_s'],event['recovery_confirmed_at_s']),(2,4,6))
            self.assertEqual([v['mean'] for v in r['B05']],[100.,100.])
            paired=r['B06']['analyses'][0]['result']
            self.assertEqual(paired['p_value'],.03125)
            self.assertEqual([p['difference'] for p in paired['pairs']],[2.]*6)
            self.assertEqual(paired['claim_type'],'intervention_effect')
            self.assertFalse(paired['inference']['assumptions_verified_by_software'])
            manifest=read_json(root/'manifest.json')
            self.assertEqual(manifest['behavioral_review'],'not_checked')
            self.assertTrue(all(sha256(root/name)==h for name,h in manifest['artifacts'].items()))
            self.assertTrue(any(Path(p).name == 'wifi-analysis.md' for p in manifest['sources']))
            self.assertTrue(all(sha256(p)==h for p,h in manifest['sources'].items()))
            review=read_json(root/'review_template.json')
            self.assertTrue(all(c['status']=='not_checked' for row in review['cases'] for c in row['criteria']))
            with self.assertRaises(ValueError): prepare(root)


if __name__ == '__main__': unittest.main()
