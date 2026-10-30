"""Event-relative summaries across declared layers, retaining alignment uncertainty and gaps."""
import math
from common import finite_number, known_identity, require_keys, validate_windows


def phase_summary(rows, start, end, split_policy='reject'):
    selected, excluded, total, exposure = [], [], 0., 0.
    for index, row in rows:
        overlap = max(0., min(end, row['end_s']) - max(start, row['start_s']))
        if overlap <= 0 or row['value'] is None or row['coverage'] < 1:
            continue
        if split_policy == 'reject' and (row['start_s'] < start or row['end_s'] > end):
            excluded.append(index)
            continue
        exposure += overlap
        total += row['value'] * overlap
        selected.append(index)
    return {'start_s': start, 'end_s': end, 'value': total / exposure if exposure else None,
            'observed_s': exposure, 'requested_s': end-start,
            'coverage': min(1., exposure/(end-start)), 'window_indices': selected, 'excluded_boundary_windows': excluded,
            'split_policy': split_policy, 'within_window_allocation_assumption': 'uniform' if split_policy == 'uniform' else None,
            'weighting': 'overlap-duration mean of fully observed interval means; partial windows excluded'}


def threshold_followup(rows, start, end):
    """Audit the entire threshold horizon, independently of finding a first onset.

    Fully observed threshold bins contribute their clipped overlap. Missing or
    partial bins contribute no assessable exposure because its location is unknown.
    This preserves bin classification, without changing phase allocation policy.
    """
    cursor, observed, last_observed_end, gaps = start, 0., None, []
    for _, row in rows:
        left, right = max(start, row['start_s']), min(end, row['end_s'])
        if right <= left or row['value'] is None or row['coverage'] < 1:
            continue
        close = math.isclose(left, cursor, rel_tol=0.,
                             abs_tol=max(1e-9, 4*math.ulp(left), 4*math.ulp(cursor)))
        if left > cursor and not close:
            gaps.append([cursor, left])
        observed += max(0., right-max(left, cursor))
        cursor = max(cursor, right)
        last_observed_end = cursor
    close_end = math.isclose(cursor, end, rel_tol=0.,
                             abs_tol=max(1e-9, 4*math.ulp(cursor), 4*math.ulp(end)))
    if last_observed_end is None or (cursor < end and not close_end):
        gaps.append([cursor, end])
    # Normalize floating-point continuity in the same way as the onset scan.
    requested = end-start
    observed = requested if not gaps and last_observed_end is not None else min(requested, observed)
    followup = {'start_s': start, 'end_s': end,
                'status': 'unobserved' if last_observed_end is None else 'partial' if gaps else 'complete',
                'observed_s': observed, 'requested_s': requested, 'coverage': observed/requested,
                'last_observed_end_s': last_observed_end}
    return followup, gaps, last_observed_end is None or not close_end


def analyze(request, data):
    require_keys(request, ['schema_version', 'events', 'signals', 'pre_interval_s', 'post_interval_s'],
                 ['schema_version', 'data', 'events', 'signals', 'pre_interval_s', 'post_interval_s', 'split_policy'], 'event request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('Unsupported event schema')
    split_policy = request.get('split_policy', 'reject')
    if split_policy not in {'reject', 'uniform'}:
        raise ValueError('split_policy must be reject or uniform')
    signal_ids = [s['id'] for s in request['signals']]
    if len(signal_ids) != len(set(signal_ids)):
        raise ValueError('Signal ids must be distinct')
    recording_units = {}
    windows = validate_windows(data['windows'])
    pre, post = request['pre_interval_s'], request['post_interval_s']
    for pair in [pre, post]:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError('Each relative phase interval needs two endpoints')
        for value in pair:
            finite_number(value, 'phase endpoint')
        if pair[1] <= pair[0]:
            raise ValueError('Phase interval must have positive duration')
    if pre[1] > 0 or post[0] < 0:
        raise ValueError('Pre interval must precede zero and post interval must follow zero')
    if not isinstance(request['events'], list) or not request['events'] or not request['signals']:
        raise ValueError('Supply events and signals')
    ids, results = set(), []
    for event in request['events']:
        require_keys(event, ['id', 'unit_id', 'anchor_s', 'anchor_uncertainty_s', 'origin', 'evidence', 'recordings'],
                     ['id', 'unit_id', 'anchor_s', 'anchor_uncertainty_s', 'origin', 'evidence', 'recordings'], 'event')
        if not known_identity(event['id']) or event['id'] in ids or not known_identity(event['unit_id']):
            raise ValueError('Distinct event ids and actual independent units are required')
        ids.add(event['id'])
        if event['origin'] not in {'external', 'assumed', 'outcome_selected'} or not event['evidence']:
            raise ValueError('Declare anchor origin and evidence; events do not prove interventions')
        anchor = finite_number(event['anchor_s'], 'anchor_s')
        a_unc = event['anchor_uncertainty_s']
        if a_unc is not None:
            a_unc = finite_number(a_unc, 'anchor uncertainty')
            if a_unc < 0:
                raise ValueError('Anchor uncertainty cannot be negative')
        for run in event['recordings'].values():
            if recording_units.setdefault(run, event['unit_id']) != event['unit_id']:
                raise ValueError('A recording cannot change independent unit across events')
        for signal in request['signals']:
            require_keys(signal, ['id', 'layer', 'metric', 'relative_clock_uncertainty_s'],
                         ['id', 'layer', 'metric', 'relative_clock_uncertainty_s', 'threshold', 'bad_direction', 'hold_s'], 'signal')
            entry = {'event_id': event['id'], 'unit_id': event['unit_id'], 'signal_id': signal['id'],
                     'layer': signal['layer'], 'anchor_origin': event['origin'], 'anchor_evidence': event['evidence']}
            run_id = event['recordings'].get(signal['id'])
            rows = [(i, w) for i, w in enumerate(windows) if w['run_id'] == run_id and w['metric'] == signal['metric']]
            if not rows:
                entry.update(status='unsupported', reason='No mapped recording/metric for this signal')
                results.append(entry)
                continue
            if any(w.get('kind', 'external_interval_mean') not in {'interval_mean', 'external_interval_mean'} for _, w in rows):
                entry.update(status='unsupported', reason='Event means require interval-mean semantics; adapt other estimands explicitly')
                results.append(entry)
                continue
            rows.sort(key=lambda pair: pair[1]['start_s'])
            clock = signal['relative_clock_uncertainty_s']
            if clock is not None:
                clock = finite_number(clock, 'clock uncertainty')
                if clock < 0:
                    raise ValueError('Clock uncertainty cannot be negative')
            uncertainty = None if clock is None or a_unc is None else float(clock + a_unc)
            # All mapped signals must already use the declared common anchor coordinate.
            before = phase_summary(rows, anchor+pre[0], anchor+pre[1], split_policy)
            after = phase_summary(rows, anchor+post[0], anchor+post[1], split_policy)
            phase_order = uncertainty is not None and pre[1] <= -uncertainty and post[0] >= uncertainty
            entry.update(status='executed', recording_id=run_id, metric=signal['metric'], unit=rows[0][1]['unit'],
                         direction=rows[0][1]['direction'], pre=before, post=after,
                         delta=after['value']-before['value'] if after['value'] is not None and before['value'] is not None else None,
                         alignment_status='bounded' if uncertainty is not None else 'unknown',
                         combined_uncertainty_s=uncertainty, phases_separated_from_uncertain_anchor=phase_order,
                         interpretation='event-relative descriptive contrast' if phase_order else 'nominal alignment only; phase ordering not established')
            if 'threshold' in signal:
                threshold = finite_number(signal['threshold'], 'threshold')
                direction = signal.get('bad_direction')
                hold = finite_number(signal.get('hold_s'), 'hold_s', positive=True)
                if direction not in {'below', 'above'}:
                    raise ValueError('bad_direction must be below or above')
                followup, gaps, right_censored = threshold_followup(rows, anchor, anchor+post[1])
                candidate, previous_end, onset = None, None, None
                for index, row in rows:
                    if row['end_s'] <= anchor or row['start_s'] >= anchor+post[1]:
                        continue
                    continuous = previous_end is not None and math.isclose(row['start_s'], previous_end, abs_tol=max(1e-9, 4*math.ulp(row['start_s']), 4*math.ulp(previous_end)), rel_tol=0.)
                    if not continuous:
                        candidate = None
                    previous_end = row['end_s']
                    if row['value'] is None or row['coverage'] < 1:
                        candidate = None
                        continue
                    bad = row['value'] < threshold if direction == 'below' else row['value'] > threshold
                    if not bad:
                        candidate = None
                        continue
                    if candidate is None:
                        candidate = (index, row)
                    start = max(anchor, candidate[1]['start_s'])
                    confirmed_end = min(row['end_s'], anchor+post[1])
                    if confirmed_end-start >= hold-1e-9:
                        onset = {'window_index': candidate[0], 'window_start_s': candidate[1]['start_s'],
                                 'window_end_s': candidate[1]['end_s'], 'confirmed_at_s': confirmed_end}
                        break
                response = {'status': 'observed_threshold_excursion' if onset else
                                     'not_assessable' if followup['status'] == 'unobserved' else 'not_observed_in_followup',
                            'gaps': gaps, 'onset_window': onset, 'lag_bounds_s': None,
                            'followup': followup, 'right_censored': right_censored,
                            'scope': 'First sustained threshold excursion in observed follow-up; not necessarily a response to the anchor.'}
                earlier = [r for _, r in rows if onset and r['end_s'] <= onset['window_start_s']]
                prior = earlier[-1] if earlier else None
                prior_bad = prior is None or prior['value'] is None or prior['coverage'] < 1 or (prior['value'] < threshold if direction == 'below' else prior['value'] > threshold)
                onset_gaps = [gap for gap in gaps if not onset or gap[0] < onset['window_start_s']]
                response['left_or_gap_censored'] = bool(prior_bad or onset_gaps)
                response['timing_meaning'] = 'Threshold-bin timing only, not a measured physical response onset'
                if onset and uncertainty is not None and not response['left_or_gap_censored']:
                    response['lag_bounds_s'] = [onset['window_start_s']-anchor-uncertainty, onset['window_end_s']-anchor+uncertainty]
                    response['strictly_after_anchor'] = response['lag_bounds_s'][0] > 0 and not onset_gaps
                else:
                    response['strictly_after_anchor'] = None
                entry['response'] = response
            results.append(entry)
    return {'schema_version': 1, 'configuration': request, 'event_signal_results': results,
            'n_independent_units': len({e['unit_id'] for e in request['events']}),
            'statistical_inference': 'not_computed; repeated events within a unit are dependent',
            'limitations': ['Clock transformations are upstream inputs, not fitted here.',
                            'Unknown timing error is never converted into a measured physical delay.',
                            'Threshold onset resolution is an interval, and may be left/gap censored.',
                            'Missing path-layer measurements retain unsupported entries, not healthy-path conclusions.']}


if __name__ == '__main__':
    from investigation_io import run_analysis_cli
    run_analysis_cli(analyze, __file__, __doc__)
