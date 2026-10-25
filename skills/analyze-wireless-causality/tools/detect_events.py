"""Detect threshold excursions with explicit recovery and censoring states."""
import argparse
import math
from common import (ensure_output_safe, finite_number, read_json, source_paths,
                    validate_windows, write_json)


def detect(rows, threshold, bad_direction, min_duration_s, min_coverage, recovery_hold_s):
    threshold = finite_number(threshold, 'threshold')
    min_duration_s = finite_number(min_duration_s, 'min_duration_s', positive=True)
    recovery_hold_s = finite_number(recovery_hold_s, 'recovery_hold_s', positive=True)
    min_coverage = finite_number(min_coverage, 'min_coverage', positive=True)
    if bad_direction not in {'below', 'above'} or min_coverage > 1:
        raise ValueError('Invalid direction or coverage policy')
    rows = sorted(validate_windows(rows), key=lambda r: r['start_s'])
    if len({(r['run_id'], r['metric'], r['direction']) for r in rows}) != 1:
        raise ValueError('Select one run, metric and direction')
    def valid(row):
        # Partial coverage does not locate the gap, so cannot establish continuity.
        return (row['value'] is not None and row['coverage'] >= min_coverage
                and math.isclose(row['coverage'], 1., rel_tol=1e-9, abs_tol=1e-12))
    def bad(row):
        return valid(row) and (row['value'] < threshold if bad_direction == 'below' else row['value'] > threshold)
    def adjacent(left, right):
        return math.isclose(left['end_s'], right['start_s'], rel_tol=0, abs_tol=1e-8)
    events, i = [], 0
    while i < len(rows):
        if not bad(rows[i]):
            i += 1
            continue
        first, j = i, i + 1
        while j < len(rows) and bad(rows[j]) and adjacent(rows[j - 1], rows[j]):
            j += 1
        duration = rows[j - 1]['end_s'] - rows[first]['start_s']
        if duration + 1e-10 >= min_duration_s:
            previous_ok = first > 0 and valid(rows[first - 1]) and not bad(rows[first - 1]) and adjacent(rows[first - 1], rows[first])
            confirmed, k = 0., j
            end, recovery, confirmed_at = rows[j - 1]['end_s'], None, None
            status, reason = 'right_censored', 'recording_ended_before_sustained_recovery'
            while k < len(rows):
                if not math.isclose(rows[k]['start_s'], end, rel_tol=0, abs_tol=1e-8) or not valid(rows[k]):
                    status, reason = 'gap_censored', 'missing_or_partial_observation_breaks_continuity'
                    break
                if bad(rows[k]):
                    status, reason = 'interrupted_by_relapse', 'another_observed_excursion_before_recovery_hold'
                    break
                confirmed += rows[k]['end_s'] - rows[k]['start_s']
                end = rows[k]['end_s']
                if confirmed + 1e-10 >= recovery_hold_s:
                    recovery, confirmed_at = rows[j]['start_s'], end
                    status, reason = 'observed', 'sustained_recovery_observed'
                    break
                k += 1
            integral = sum(abs(r['value'] - threshold) * (r['end_s'] - r['start_s']) for r in rows[first:j])
            finite_number(integral, 'integrated excursion')
            events.append({'run_id': rows[i]['run_id'], 'metric': rows[i]['metric'], 'direction': rows[i]['direction'],
                           'unit': rows[i]['unit'], 'integrated_excursion_unit': rows[i]['unit'] + '*s',
                           'start_s': rows[first]['start_s'], 'end_s': rows[j - 1]['end_s'], 'duration_s': duration,
                           'onset_observed': previous_ok, 'recovery_start_s': recovery,
                           'recovery_confirmed_at_s': confirmed_at, 'recovery_status': status,
                           'recovery_censored': status in {'right_censored', 'gap_censored'},
                           'recovery_followup_end_s': end, 'recovery_stop_reason': reason,
                           'threshold': threshold, 'threshold_direction': bad_direction,
                           'integrated_excursion': integral,
                           'source_rows': sorted({n for r in rows[first:j] for n in r.get('source_rows', [])}),
                           'source_windows': [{k: r.get(k) for k in ['start_s', 'end_s', 'source_path', 'source_sheet', 'source_rows']}
                                              for r in rows[first:j]],
                           'interpretation': 'A contiguous abnormal excursion. A relapse starts another excursion; only recovery_status=observed establishes sustained recovery.'})
        i = j
    return events


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ['windows', 'run-id', 'metric', 'direction', 'output']:
        p.add_argument('--' + arg, required=True)
    p.add_argument('--threshold', type=float, required=True)
    p.add_argument('--bad-direction', choices=['above', 'below'], required=True)
    p.add_argument('--min-duration-s', type=float, required=True)
    p.add_argument('--recovery-hold-s', type=float, required=True)
    p.add_argument('--min-coverage', type=float, default=.8)
    a = p.parse_args()
    q = read_json(a.windows)
    inputs = [a.windows] + source_paths(q)
    ensure_output_safe(a.output, inputs, '.json')
    rows = [r for r in q['windows'] if (r['run_id'], r['metric'], r['direction']) == (a.run_id, a.metric, a.direction)]
    events = detect(rows, a.threshold, a.bad_direction, a.min_duration_s, a.min_coverage, a.recovery_hold_s)
    partial = sum(finite_number(r['coverage'], 'coverage') < 1 - 1e-9 for r in rows)
    write_json(a.output, {'events': events, 'partial_windows_excluded_from_continuity': partial,
                         'coverage_policy': 'Require fully observed windows for duration and sustained recovery.',
                         'policy': {'threshold': a.threshold, 'bad_direction': a.bad_direction,
                                    'min_duration_s': a.min_duration_s, 'min_coverage': a.min_coverage,
                                    'recovery_hold_s': a.recovery_hold_s}}, inputs)


if __name__ == '__main__':
    main()
