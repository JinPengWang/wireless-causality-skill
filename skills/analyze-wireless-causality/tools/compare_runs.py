"""Summarize compatible measurements and compare declared independent pairs."""
import argparse
from collections import defaultdict
import numpy as np
from common import (finite_number, known_identity, measurement_signature, read_json,
                    source_paths, validate_windows, write_json, ensure_output_safe)


def weighted_quantile(values, weights, q):
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    return float(v[min(len(v) - 1, np.searchsorted(np.cumsum(w), q * sum(w), side='left'))])


def summarize(windows, min_coverage=0.8):
    min_coverage = finite_number(min_coverage, 'min_coverage', positive=True)
    if min_coverage > 1:
        raise ValueError('min_coverage must be in (0,1]')
    groups = defaultdict(list)
    for w in validate_windows(windows):
        groups[tuple(w[k] for k in ['run_id', 'entity', 'direction', 'condition', 'pair_id', 'metric', 'unit'])].append(w)
    result = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: r['start_s'])
        valid = [r for r in rows if r['value'] is not None and r['coverage'] >= min_coverage]
        item = dict(zip(['run_id', 'entity', 'direction', 'condition', 'pair_id', 'metric', 'unit'], key))
        item.update(kind=rows[0].get('kind', 'external_interval_mean'), definition=rows[0]['definition'],
                    measurement_id=rows[0].get('measurement_id'),
                    measurement_signature=list(measurement_signature(rows[0])),
                    total_windows=len(rows), valid_windows=len(valid), excluded_windows=len(rows) - len(valid),
                    valid_seconds=sum((r['end_s'] - r['start_s']) * r['coverage'] for r in valid),
                    analyzed_span_s=rows[-1]['end_s'] - rows[0]['start_s'],
                    represented_window_seconds=sum(r['end_s'] - r['start_s'] for r in rows))
        item['valid_time_fraction'] = item['valid_seconds'] / item['analyzed_span_s']
        if valid:
            values = [r['value'] for r in valid]
            weights = [(r['end_s'] - r['start_s']) * r['coverage'] for r in valid]
            mean = float(np.average(values, weights=weights))
            item['mean_aggregation'] = 'valid_duration_weighted'
            if item['kind'] in {'ratio', 'event_mean', 'event_fraction'}:
                if any(not {'aggregation_numerator', 'aggregation_denominator', 'scale'} <= r.keys() for r in valid):
                    raise ValueError('Count/observation means require retained primitives')
                scales = {r['scale'] for r in valid}
                if len(scales) != 1:
                    raise ValueError('Inconsistent metric scale')
                denominator = sum(r['aggregation_denominator'] for r in valid)
                mean = sum(r['aggregation_numerator'] for r in valid) / denominator * next(iter(scales))
                item['mean_aggregation'] = 'pooled_counts_or_observations'
            item.update(mean=finite_number(mean, 'run mean'), p10=weighted_quantile(values, weights, .1),
                        median=weighted_quantile(values, weights, .5), p90=weighted_quantile(values, weights, .9))
            item['spread_p90_p10'] = item['p90'] - item['p10']
        else:
            item.update(mean=None, p10=None, median=None, p90=None, spread_p90_p10=None)
        result.append(item)
    return result


def paired_compare(summaries, reference, seed=0, bootstrap=1000, min_pairs=8):
    if any(type(x) is not int for x in [seed, bootstrap, min_pairs]) or seed < 0 or min_pairs < 2 or bootstrap < 100:
        raise ValueError('Invalid seed or inference budget')
    strata = defaultdict(dict)
    entities, contracts = set(), {}
    for s in summaries:
        entities.add(s['entity'])
        signature = measurement_signature(s)
        family = (s['direction'], s['metric'], s['unit'])
        if family in contracts and contracts[family] != signature:
            raise ValueError('Incompatible measurement contracts: harmonize definitions and weighting before comparison')
        contracts[family] = signature
        if s['mean'] is None:
            continue
        finite_number(s['mean'], 'summary mean')
        if not all(known_identity(s[k]) for k in ['pair_id', 'condition', 'direction', 'entity']):
            continue
        key = (s['direction'], s['condition'], s['pair_id'], s['metric'], s['unit'])
        if s['entity'] in strata[key]:
            raise ValueError('Multiple runs per entity/pair/condition: define independent units first')
        strata[key][s['entity']] = s
    if reference not in entities:
        raise ValueError('Reference entity absent')
    output = []
    families = {(k[0], k[3], k[4]) for k in strata}
    for direction, metric, unit in sorted(families):
        for target in sorted(entities - {reference}):
            keys = sorted(k for k in strata if (k[0], k[3], k[4]) == (direction, metric, unit))
            refkeys = [k for k in keys if reference in strata[k]]
            targetkeys = [k for k in keys if target in strata[k]]
            common = [k for k in refkeys if target in strata[k]]
            pair_differences = defaultdict(list)
            condition_contrasts = []
            for k in common:
                ref, other = strata[k][reference], strata[k][target]
                delta = other['mean'] - ref['mean']
                pair_differences[k[2]].append(delta)
                condition_contrasts.append({'pair_id': k[2], 'condition': k[1], 'reference_run': ref['run_id'],
                                            'target_run': other['run_id'], 'target_minus_reference': delta,
                                            'reference_valid_time_fraction': ref.get('valid_time_fraction'),
                                            'target_valid_time_fraction': other.get('valid_time_fraction'),
                                            'incomplete_observation': any(x.get('valid_time_fraction', 0) < 1 - 1e-9 for x in [ref, other])})
            pairs = [{'pair_id': key, 'n_conditions': len(pair_differences[key]),
                      'target_minus_reference': float(np.mean(pair_differences[key]))} for key in sorted(pair_differences)]
            diffs = np.array([p['target_minus_reference'] for p in pairs])
            row = {'reference': reference, 'target': target, 'direction': direction, 'metric': metric, 'unit': unit,
                   'measurement_signature': list(contracts[(direction, metric, unit)]),
                   'n_pairs': len(diffs), 'common_conditions': len(common),
                   'condition_contrasts': condition_contrasts, 'pair_contrasts': pairs,
                   'reference_support_fraction': len(common) / len(refkeys) if refkeys else 0,
                   'target_support_fraction': len(common) / len(targetkeys) if targetkeys else 0,
                   'unmatched_reference': [list(k) for k in refkeys if k not in common],
                   'unmatched_target': [list(k) for k in targetkeys if k not in common],
                   'mean_target_minus_reference': float(diffs.mean()) if len(diffs) else None,
                   'ci95': None, 'status': 'descriptive_paired' if len(diffs) else 'blocked_no_common_support'}
            if len(diffs) >= min_pairs:
                if bootstrap * len(diffs) > 10000000:
                    raise ValueError('Bootstrap budget exceeds 10 million draws')
                rng = np.random.default_rng(seed)
                draws = np.mean(rng.choice(diffs, (bootstrap, len(diffs)), replace=True), axis=1)
                row['ci95'] = [float(x) for x in np.quantile(draws, [.025, .975])]
            row['assumptions'] = 'Equal weight per declared independent pair; conditions averaged within pair. CI assumes independence and is marginal, not simultaneous. Not a causal vendor effect.'
            output.append(row)
    return output or [{'status': 'blocked_no_eligible_pairs', 'reason': 'Provide verified pair identities, conditions, directions and at least two entities'}]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--windows', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--reference')
    p.add_argument('--min-coverage', type=float, default=.8)
    p.add_argument('--seed', type=int, default=0)
    a = p.parse_args()
    q = read_json(a.windows)
    inputs = [a.windows] + source_paths(q)
    ensure_output_safe(a.output, inputs, '.json')
    summaries = summarize(q['windows'], a.min_coverage)
    write_json(a.output, {'summaries': summaries,
                         'comparisons': paired_compare(summaries, a.reference, a.seed) if a.reference else [],
                         'min_coverage': a.min_coverage, 'seed': a.seed}, inputs)


if __name__ == '__main__':
    main()
