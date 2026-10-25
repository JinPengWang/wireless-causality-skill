"""Build comparable windows from explicit mappings, with missingness and lineage."""
import argparse
import math
from collections import defaultdict
from pathlib import Path
from common import (finite_number, number, read_json, require_keys, sha256,
                    table_rows, write_json, ensure_output_safe, measurement_signature)

META = {'run_id', 'entity', 'direction', 'condition', 'pair_id'}
KINDS = {'interval_mean', 'interval_amount', 'ratio', 'event_mean', 'event_sum', 'event_count', 'event_fraction'}


def grid_position(time_s, width):
    q = time_s / width
    if not math.isfinite(q):
        raise ValueError('Grid position is not finite; check time units')
    nearest = round(q)
    return float(nearest) if abs(q - nearest) <= max(1e-12, 8 * math.ulp(q)) else q


def build(request):
    require_keys(request, {'schema_version', 'window_s', 'sources'},
                 {'schema_version', 'window_s', 'sources', 'max_windows'}, 'window request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('Unsupported window request version')
    width = finite_number(request['window_s'], 'window_s', positive=True)
    budget = request.get('max_windows', 100000)
    if type(budget) is not int or budget < 1:
        raise ValueError('max_windows must be a positive integer')
    if not isinstance(request['sources'], list) or not request['sources']:
        raise ValueError('sources must be a nonempty list')
    out, provenance = [], []
    unique_sources, run_metadata = set(), {}
    for src in request['sources']:
        require_keys(src, {'path', 'metadata', 'time', 'metrics'},
                     {'path', 'sheet', 'header_row', 'where', 'metadata', 'time', 'metrics', 'capture_complete'}, 'source')
        meta = src['metadata']
        require_keys(meta, META, META, 'metadata')
        if any(not isinstance(meta[k], str) or not meta[k].strip() for k in META):
            raise ValueError('Metadata requires explicit nonempty strings; unknown is descriptive only')
        if meta['run_id'] in run_metadata and run_metadata[meta['run_id']] != meta:
            raise ValueError('Conflicting metadata for the same run_id')
        run_metadata[meta['run_id']] = meta
        time = src['time']
        require_keys(time, {'start', 'scale', 'origin', 'split_policy'},
                     {'start', 'end', 'scale', 'origin', 'split_policy', 'observation_interval'}, 'time')
        scale = finite_number(time['scale'], 'time scale', positive=True)
        origin = finite_number(time['origin'], 'time origin')
        if time['split_policy'] not in {'reject', 'uniform'}:
            raise ValueError('Unknown split_policy')
        event = 'end' not in time
        exposure = time.get('observation_interval')
        if event:
            if not isinstance(exposure, list) or len(exposure) != 2:
                raise ValueError('Event data require observation_interval in normalized seconds')
            exposure = [finite_number(x, 'observation boundary') for x in exposure]
            if exposure[1] <= exposure[0] or type(src.get('capture_complete')) is not bool:
                raise ValueError('Declare positive observation exposure and boolean capture_complete')
        where = src.get('where', {})
        if not isinstance(where, dict) or any(not isinstance(v, list) for v in where.values()):
            raise ValueError('where must map exact column names to value lists')
        specs = src['metrics']
        if not isinstance(specs, list) or not specs:
            raise ValueError('metrics must be a nonempty list')
        normalized = []
        required_columns = set(where) | {time['start']}
        if not event:
            required_columns.add(time['end'])
        for original in specs:
            require_keys(original, {'name', 'unit', 'kind', 'scale', 'definition'},
                         {'name', 'unit', 'kind', 'scale', 'column', 'numerator', 'denominator',
                          'definition', 'value_map', 'measurement_id', 'min_observations', 'min_denominator'}, 'metric')
            spec = dict(original)
            for field in ['name', 'unit', 'definition']:
                if not isinstance(spec[field], str) or not spec[field].strip():
                    raise ValueError('Metric requires a nonempty ' + field)
            kind = spec['kind']
            if kind not in KINDS or kind.startswith('event') != event:
                raise ValueError('Metric kind does not match event/interval time model')
            spec['scale'] = finite_number(spec['scale'], 'metric scale')
            measurement_signature(spec)
            if kind in {'ratio', 'event_fraction'} and spec['scale'] <= 0:
                raise ValueError('Fraction scale must be positive')
            key = (meta['run_id'], spec['name'])
            if key in unique_sources:
                raise ValueError('A run/metric may have only one source; reconcile duplicate sources explicitly')
            unique_sources.add(key)
            fields = ['numerator', 'denominator'] if kind == 'ratio' else ([] if kind == 'event_count' else ['column'])
            for field in fields:
                if not isinstance(spec.get(field), str) or not spec[field]:
                    raise ValueError('Metric requires column mapping: ' + field)
                required_columns.add(spec[field])
            if 'value_map' in spec and not isinstance(spec['value_map'], dict):
                raise ValueError('value_map must be an object')
            if 'value_map' in spec and kind in {'ratio', 'event_count'}:
                raise ValueError('value_map applies only to a value column')
            spec['min_observations'] = spec.get('min_observations', 0)
            if type(spec['min_observations']) is not int or spec['min_observations'] < 0:
                raise ValueError('min_observations must be a nonnegative integer')
            spec['min_denominator'] = finite_number(spec.get('min_denominator', 0), 'min_denominator')
            if spec['min_denominator'] < 0 or (spec['min_denominator'] and kind not in {'ratio', 'event_mean', 'event_fraction'}):
                raise ValueError('min_denominator is a nonnegative count threshold for ratio/observation means')
            normalized.append(spec)
        if any(not isinstance(f, str) or not f for f in required_columns):
            raise ValueError('All mapped headers must be nonempty strings')
        before = sha256(src['path'])
        def empty_bin():
            return {'num': 0., 'den': 0., 'coverage': 0., 'rows': [], 'invalid_rows': []}
        bins = defaultdict(lambda: defaultdict(empty_bin))
        previous_end = None
        lower = upper = None
        selected = 0
        missing = defaultdict(int)
        for rowno, row in table_rows(src['path'], src.get('sheet'), src.get('header_row', 1), required_columns):
            if any(row[k] not in values for k, values in where.items()):
                continue
            selected += 1
            start = finite_number(row[time['start']], 'time at source row ' + str(rowno)) * scale - origin
            end = start if event else finite_number(row[time['end']], 'interval end') * scale - origin
            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError('Normalized time overflow')
            if not event:
                if end <= start or (previous_end is not None and start < previous_end - 1e-9):
                    raise ValueError(f'Nonpositive, overlapping or unsorted intervals at row {rowno}')
                previous_end = end
            elif not grid_position(exposure[0], width) <= grid_position(start, width) < grid_position(exposure[1], width):
                raise ValueError(f'Event outside declared observation_interval at row {rowno}')
            lower = start if lower is None else min(lower, start)
            upper = end if upper is None else max(upper, end)
            first = math.floor(grid_position(start, width))
            last = first if event else math.ceil(grid_position(end, width)) - 1
            if last < first:
                raise ValueError('Interval is below usable grid precision')
            if last - first + 1 > budget:
                raise ValueError('Excessive window expansion: check units or max_windows')
            if not event and last > first and time['split_policy'] == 'reject':
                raise ValueError('A source interval crosses windows; coarsen or explicitly allow uniform allocation')
            for spec in normalized:
                kind = spec['kind']
                value = row.get(spec.get('column', ''))
                if 'value_map' in spec:
                    value = spec['value_map'].get(str(value))
                value = 1. if kind == 'event_count' else number(value)
                num = number(row.get(spec.get('numerator', '')))
                den = number(row.get(spec.get('denominator', '')))
                invalid = (num is None or den is None) if kind == 'ratio' else value is None
                if kind == 'ratio' and not invalid and (num < 0 or den < 0 or num > den):
                    raise ValueError('Ratio requires 0 <= numerator <= denominator')
                if kind == 'event_fraction' and not invalid and value not in {0., 1.}:
                    raise ValueError('event_fraction needs normalized 0/1 values')
                if invalid:
                    missing[spec['name']] += 1
                for idx in range(first, last + 1):
                    overlap = 0. if event else max(0., min(end, (idx + 1) * width) - max(start, idx * width))
                    b = bins[idx][spec['name']]
                    if invalid:
                        b['invalid_rows'].append(rowno)
                        continue
                    b['rows'].append(rowno)
                    if not event:
                        b['coverage'] += overlap
                    if kind == 'ratio':
                        b['num'] += num * overlap / (end - start)
                        b['den'] += den * overlap / (end - start)
                    elif kind == 'interval_mean':
                        b['num'] += value * overlap
                        b['den'] += overlap
                    elif kind == 'interval_amount':
                        b['num'] += value * overlap / (end - start)
                        b['den'] += overlap
                    else:
                        b['num'] += value
                        b['den'] += 1
        if selected == 0 and not event:
            raise ValueError('Interval source selection is empty')
        lo, hi = exposure if event else (lower, upper)
        begin = math.floor(grid_position(lo, width))
        finish = math.ceil(grid_position(hi, width))
        if finish <= begin or any(idx < begin or idx >= finish for idx in bins):
            raise ValueError('Exposure/grid precision would omit observations; review endpoint bounds')
        if len(out) + (finish - begin) * len(normalized) > budget:
            raise ValueError('Excessive output windows: check units or max_windows')
        for idx in range(begin, finish):
            for spec in normalized:
                b = bins[idx][spec['name']]
                kind = spec['kind']
                exposure_s = max(0., min(hi, (idx + 1) * width) - max(lo, idx * width))
                cov = exposure_s / width if event else b['coverage'] / width
                if math.isclose(cov, 1., rel_tol=1e-9, abs_tol=1e-12):
                    cov = 1.
                if event and not b['rows'] and not src['capture_complete']:
                    cov = 0.
                denominator = exposure_s if kind in {'event_sum', 'event_count'} else b['den']
                value = b['num'] / denominator * spec['scale'] if denominator > 0 and cov > 0 else None
                status = 'valid' if value is not None else 'no_valid_support'
                if kind == 'event_sum' and b['invalid_rows']:
                    value, status = None, 'unknown_total_due_to_invalid_values'
                if len(b['rows']) < spec['min_observations'] or denominator < spec['min_denominator']:
                    value, status = None, 'insufficient_sample_support'
                if value is not None and not math.isfinite(value):
                    raise ValueError('Metric arithmetic overflow')
                out.append({**meta, 'metric': spec['name'], 'unit': spec['unit'],
                            'start_s': idx * width, 'end_s': (idx + 1) * width, 'value': value, 'coverage': cov,
                            'source_rows': b['rows'], 'invalid_source_rows': b['invalid_rows'],
                            'source_path': str(Path(src['path']).resolve()), 'source_sheet': src.get('sheet'),
                            'kind': kind, 'aggregation_numerator': b['num'], 'aggregation_denominator': denominator,
                            'valid_observations': len(b['rows']), 'invalid_observations': len(b['invalid_rows']),
                            'scale': spec['scale'], 'definition': spec['definition'],
                            'measurement_id': spec.get('measurement_id'), 'status': status})
        if sha256(src['path']) != before:
            raise RuntimeError('Source changed during processing')
        provenance.append({'path': str(Path(src['path']).resolve()), 'sha256': before, 'mapping': src,
                           'selected_rows': selected, 'invalid_metric_rows': dict(missing)})
    return {'schema_version': 1, 'window_s': width, 'sources': provenance, 'windows': out,
            'limitations': ['Uniform splitting assumes uniform accrual within each source interval.',
                           'Event exposure is declared capture time, not proof of observing every transmitted frame.',
                           'Event means/fractions summarize valid observations; inspect excluded rows and sample support.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    req = read_json(a.request)
    inputs = [a.request] + [s['path'] for s in req['sources']]
    ensure_output_safe(a.output, inputs, '.json')
    write_json(a.output, build(req), inputs)


if __name__ == '__main__':
    main()
