"""Synthetic follow-up completeness checks, separate from phase allocation semantics."""
import copy
import unittest

from event_analysis import analyze


def fixture(intervals, *, offset=0., post_start=0., hold=1.):
    """Intervals contain relative start/end, value and optional observed coverage."""
    windows = []
    for interval in [(-2., 0., 10.), *intervals]:
        start, end, value, *coverage = interval
        windows.append({
            'run_id': 'recording-A', 'entity': 'synthetic-link', 'direction': 'outbound',
            'condition': 'fixed', 'pair_id': 'unit-A', 'metric': 'signal', 'unit': 'Mbit/s',
            'start_s': start+offset, 'end_s': end+offset, 'value': value,
            'coverage': coverage[0] if coverage else 1., 'kind': 'interval_mean',
            'definition': 'Synthetic fully observed interval mean',
        })
    request = {
        'schema_version': 1, 'pre_interval_s': [-2., 0.],
        'post_interval_s': [post_start, 4.],
        'events': [{'id': 'event-A', 'unit_id': 'unit-A', 'anchor_s': offset,
                    'anchor_uncertainty_s': 0., 'origin': 'external',
                    'evidence': 'Synthetic external marker',
                    'recordings': {'radio': 'recording-A'}}],
        'signals': [{'id': 'radio', 'layer': 'wireless', 'metric': 'signal',
                     'relative_clock_uncertainty_s': 0., 'threshold': 5.,
                     'bad_direction': 'below', 'hold_s': hold}],
    }
    return request, {'windows': windows}


def result(intervals, **kwargs):
    request, data = fixture(intervals, **kwargs)
    return analyze(request, data)['event_signal_results'][0]


class EventFollowupTests(unittest.TestCase):
    def assert_followup(self, response, status, observed, *, last_end, offset=0.):
        followup = response.get('followup')
        self.assertIsNotNone(followup, 'Threshold response must disclose follow-up completeness')
        self.assertEqual(followup['status'], status)
        self.assertEqual(followup['start_s'], offset)
        self.assertEqual(followup['end_s'], offset+4.)
        self.assertAlmostEqual(followup['requested_s'], 4.)
        self.assertAlmostEqual(followup['observed_s'], observed)
        self.assertAlmostEqual(followup['coverage'], observed/4.)
        self.assertEqual(followup['last_observed_end_s'], None if last_end is None else offset+last_end)

    def test_complete_healthy_followup_is_a_bounded_negative(self):
        response = result([(0., 1., 10.), (1., 4., 10.)])['response']
        self.assert_followup(response, 'complete', 4., last_end=4.)
        self.assertEqual(response['status'], 'not_observed_in_followup')
        self.assertEqual(response['gaps'], [])
        self.assertFalse(response['right_censored'])

    def test_complete_abnormal_followup_keeps_onset_bin_bounds(self):
        response = result([(0., 1., 10.), (1., 2., 1.), (2., 4., 1.)])['response']
        self.assert_followup(response, 'complete', 4., last_end=4.)
        self.assertEqual(response['status'], 'observed_threshold_excursion')
        self.assertEqual(response['lag_bounds_s'], [1., 2.])
        self.assertEqual(response['onset_window']['confirmed_at_s'], 2.)
        self.assertFalse(response['left_or_gap_censored'])
        self.assertFalse(response['right_censored'])

    def test_no_post_windows_are_not_assessable(self):
        response = result([])['response']
        self.assertEqual(response['status'], 'not_assessable')
        self.assert_followup(response, 'unobserved', 0., last_end=None)
        self.assertEqual(response['gaps'], [[0., 4.]])
        self.assertIsNone(response['onset_window'])
        self.assertTrue(response['right_censored'])

    def test_only_windows_after_followup_do_not_count_as_observed(self):
        response = result([(5., 6., 10.)])['response']
        self.assertEqual(response['status'], 'not_assessable')
        self.assert_followup(response, 'unobserved', 0., last_end=None)
        self.assertEqual(response['gaps'], [[0., 4.]])

    def test_empty_short_horizon_still_records_the_entire_missing_interval(self):
        request, data = fixture([])
        request['post_interval_s'] = [0., 2e-10]
        request['signals'][0]['hold_s'] = 1e-10
        response = analyze(request, data)['event_signal_results'][0]['response']
        self.assertEqual(response['status'], 'not_assessable')
        self.assertEqual(response['gaps'], [[0., 2e-10]])
        self.assertEqual(response['followup']['status'], 'unobserved')
        self.assertTrue(response['right_censored'])

    def test_healthy_truncated_tail_is_retained_as_partial(self):
        response = result([(0., 2., 10.)])['response']
        self.assertEqual(response['status'], 'not_observed_in_followup')
        self.assert_followup(response, 'partial', 2., last_end=2.)
        self.assertEqual(response['gaps'], [[2., 4.]])
        self.assertTrue(response['right_censored'])

    def test_abnormal_tail_too_short_for_hold_is_censored(self):
        response = result([(0., 1., 10.), (1., 1.5, 1.)], hold=1.)['response']
        self.assertEqual(response['status'], 'not_observed_in_followup')
        self.assert_followup(response, 'partial', 1.5, last_end=1.5)
        self.assertEqual(response['gaps'], [[1.5, 4.]])
        self.assertIsNone(response['onset_window'])
        self.assertTrue(response['right_censored'])

    def test_null_and_partial_windows_are_unobserved_for_threshold_followup(self):
        response = result([(0., 2., None), (2., 4., 1., .5)])['response']
        self.assertEqual(response['status'], 'not_assessable')
        self.assert_followup(response, 'unobserved', 0., last_end=None)
        self.assertEqual(response['gaps'], [[0., 4.]])
        self.assertTrue(response['right_censored'])

    def test_invalid_interior_window_is_a_gap_and_breaks_hold(self):
        for value, coverage in [(None, 1.), (1., .5)]:
            with self.subTest(value=value, coverage=coverage):
                response = result([(0., 1., 1.), (1., 2., value, coverage),
                                   (2., 2.5, 1.), (2.5, 4., 10.)], hold=1.5)['response']
                self.assertEqual(response['status'], 'not_observed_in_followup')
                self.assert_followup(response, 'partial', 3., last_end=4.)
                self.assertEqual(response['gaps'], [[1., 2.]])
                self.assertFalse(response['right_censored'])

    def test_missing_prefix_is_disclosed_without_tail_censoring(self):
        response = result([(1., 4., 10.)])['response']
        self.assert_followup(response, 'partial', 3., last_end=4.)
        self.assertEqual(response['gaps'], [[0., 1.]])
        self.assertFalse(response['right_censored'])

    def test_interior_gap_does_not_bridge_a_sustained_excursion(self):
        response = result([(0., 1., 1.), (2., 2.5, 1.), (2.5, 4., 10.)], hold=1.5)['response']
        self.assert_followup(response, 'partial', 3., last_end=4.)
        self.assertEqual(response['gaps'], [[1., 2.]])
        self.assertIsNone(response['onset_window'])

    def test_tail_missing_after_known_onset_does_not_erase_lag(self):
        response = result([(0., 1., 10.), (1., 2., 1.)])['response']
        self.assertEqual(response['gaps'], [[2., 4.]])
        self.assert_followup(response, 'partial', 2., last_end=2.)
        self.assertEqual(response['status'], 'observed_threshold_excursion')
        self.assertEqual(response['lag_bounds_s'], [1., 2.])
        self.assertFalse(response['left_or_gap_censored'])
        self.assertTrue(response['strictly_after_anchor'])
        self.assertTrue(response['right_censored'])

    def test_all_gaps_after_first_onset_are_checked(self):
        response = result([(0., 1., 10.), (1., 2., 1.), (2.5, 3., None),
                           (3., 3.5, 10.)])['response']
        self.assertEqual(response['gaps'], [[2., 3.], [3.5, 4.]])
        self.assert_followup(response, 'partial', 2.5, last_end=3.5)
        self.assertEqual(response['lag_bounds_s'], [1., 2.])
        self.assertFalse(response['left_or_gap_censored'])
        self.assertTrue(response['right_censored'])

    def test_missing_prefix_still_censors_later_onset_timing(self):
        response = result([(1., 2., 10.), (2., 3., 1.), (3., 4., 10.)])['response']
        self.assertEqual(response['status'], 'observed_threshold_excursion')
        self.assertEqual(response['gaps'], [[0., 1.]])
        self.assertTrue(response['left_or_gap_censored'])
        self.assertIsNone(response['lag_bounds_s'])
        self.assert_followup(response, 'partial', 3., last_end=4.)

    def test_epoch_origin_preserves_followup_and_does_not_bridge_a_real_gap(self):
        intervals = [(0., .5, 10.), (.5, 1., 1.), (1.25, 1.75, 1.), (1.75, 3., 10.)]
        for offset in [0., 1e9]:
            with self.subTest(offset=offset):
                response = result(intervals, offset=offset)['response']
                self.assert_followup(response, 'partial', 2.75, last_end=3., offset=offset)
                self.assertEqual(response['gaps'], [[offset+1., offset+1.25], [offset+3., offset+4.]])
                self.assertEqual(response['status'], 'not_observed_in_followup')

    def test_positive_post_start_applies_to_phase_only(self):
        entry = result([(0., 1., 10.), (1., 2., 1.), (2., 4., 10.)], post_start=2.)
        self.assertEqual(entry['post']['start_s'], 2.)
        self.assertEqual(entry['post']['value'], 10.)
        self.assertEqual(entry['response']['status'], 'observed_threshold_excursion')
        self.assertEqual(entry['response']['lag_bounds_s'], [1., 2.])
        self.assert_followup(entry['response'], 'complete', 4., last_end=4.)

    def test_clipped_followup_preserves_threshold_bin_and_phase_split_policy(self):
        request, data = fixture([(0., 5., 1.)])
        for split_policy in ['reject', 'uniform']:
            with self.subTest(split_policy=split_policy):
                request['split_policy'] = split_policy
                entry = analyze(request, data)['event_signal_results'][0]
                self.assert_followup(entry['response'], 'complete', 4., last_end=4.)
                self.assertEqual(entry['response']['onset_window']['window_end_s'], 5.)
                self.assertEqual(entry['response']['onset_window']['confirmed_at_s'], 4.)
                self.assertEqual(entry['response']['lag_bounds_s'], [0., 5.])
                self.assertEqual(entry['post']['value'], None if split_policy == 'reject' else 1.)

    def test_unknown_alignment_still_reports_completeness_without_lag(self):
        request, data = fixture([(0., 1., 10.), (1., 2., 1.)])
        request['signals'][0]['relative_clock_uncertainty_s'] = None
        response = analyze(request, data)['event_signal_results'][0]['response']
        self.assert_followup(response, 'partial', 2., last_end=2.)
        self.assertIsNone(response['lag_bounds_s'])

    def test_no_threshold_keeps_descriptive_phase_shape(self):
        request, data = fixture([(0., 2., 10.)])
        request['signals'][0] = {key: value for key, value in request['signals'][0].items()
                                 if key not in {'threshold', 'bad_direction', 'hold_s'}}
        original_request = copy.deepcopy(request)
        entry = analyze(request, data)['event_signal_results'][0]
        self.assertNotIn('response', entry)
        self.assertEqual(entry['post']['coverage'], .5)
        self.assertEqual(entry['delta'], 0.)
        self.assertEqual(request, original_request)


if __name__ == '__main__':
    unittest.main()
