"""Opt-in diagnostics of explicitly mapped table observations; no data repair."""
import argparse
import math
from pathlib import Path
from common import finite_number, grid_position, number, read_json, require_keys, sha256, table_rows, write_json


def profile(request):
    require_keys(request, {'schema_version','source','time','density_window_s','gap_threshold_s'},
                 {'schema_version','source','time','density_window_s','gap_threshold_s',
                  'identity_columns','key_columns','max_examples','max_groups','max_keys','max_bins'}, 'quality request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('Expected schema_version 1')
    source, timing = request['source'], request['time']
    require_keys(source, {'path'}, {'path','sheet','header_row','where'}, 'source')
    require_keys(timing, {'column','scale','origin'}, {'column','scale','origin'}, 'time')
    if not isinstance(source['path'], str) or not source['path'].strip():
        raise ValueError('Declare the source path')
    scale = finite_number(timing['scale'], 'time scale', positive=True)
    origin = finite_number(timing['origin'], 'time origin')
    width = finite_number(request['density_window_s'], 'density window', positive=True)
    gap = finite_number(request['gap_threshold_s'], 'gap threshold', positive=True)
    limits = {key: request.get(key, default) for key, default in
              [('max_examples',20),('max_groups',10000),('max_keys',100000),('max_bins',100000)]}
    if any(type(v) is not int or v < 1 for v in limits.values()):
        raise ValueError('Diagnostic budgets must be positive integers')
    identities, keys = request.get('identity_columns', []), request.get('key_columns', [])
    for columns in [identities, keys]:
        if not isinstance(columns, list) or any(not isinstance(c,str) or not c.strip() for c in columns) or len(set(columns)) != len(columns):
            raise ValueError('Declare distinct column names')
    if not isinstance(timing['column'],str) or not timing['column'].strip():
        raise ValueError('Declare a time column; names and units are not inferred')
    where = source.get('where', {})
    if not isinstance(where,dict) or any(not isinstance(k,str) or not isinstance(v,list) or not v for k,v in where.items()):
        raise ValueError('where maps exact headers to nonempty eligibility lists')
    path = Path(source['path']).resolve(); before = sha256(path)
    required = set(identities+keys+[timing['column']]) | set(where)
    groups, key_count, bin_count, scanned, selected = {}, 0, 0, 0, 0

    def counter(): return {'count':0, 'examples':[]}
    def add(record, example):
        record['count'] += 1
        if len(record['examples']) < limits['max_examples']: record['examples'].append(example)
    def absent(value): return value is None or isinstance(value,str) and not value.strip()
    def token(values):
        return tuple((type(v).__name__, str(v)) for v in values)

    missing_identity = counter()
    for rowno, row in table_rows(path, source.get('sheet'), source.get('header_row',1), required):
        scanned += 1
        if any(row[k] not in values for k,values in where.items()): continue
        selected += 1
        identity = [row[c] for c in identities]
        if any(absent(v) for v in identity):
            add(missing_identity, {'source_row':rowno}); continue
        group_key = token(identity)
        if group_key not in groups:
            if len(groups) >= limits['max_groups']: raise ValueError('Group budget exceeded; narrow the declared scope')
            groups[group_key] = {'identity':dict(zip(identities,identity)), 'records':0,
                                'invalid_times':counter(), 'time_reversals':counter(),
                                'adjacent_equal_times':counter(), 'duplicate_keys':counter(),
                                'missing_keys':counter(), 'forward_gaps':counter(),
                                '_previous':None, '_keys':{}, '_bins':{}}
        g = groups[group_key]; g['records'] += 1
        if keys:
            values = [row[c] for c in keys]
            if any(absent(v) for v in values): add(g['missing_keys'], {'source_row':rowno})
            else:
                key = token(values)
                if key in g['_keys']:
                    add(g['duplicate_keys'], {'source_rows':[g['_keys'][key], rowno]})
                else:
                    key_count += 1
                    if key_count > limits['max_keys']: raise ValueError('Key budget exceeded; narrow the scope or raise max_keys explicitly')
                    g['_keys'][key] = rowno
        raw = number(row[timing['column']])
        value = raw*scale-origin if raw is not None else None
        if value is None or not math.isfinite(value):
            add(g['invalid_times'], {'source_row':rowno}); g['_previous'] = None; continue
        position = grid_position(value, width)
        if abs(position) > 2**52:
            raise ValueError('Time grid exceeds usable precision')
        index = math.floor(position)
        if index not in g['_bins']:
            bin_count += 1
            if bin_count > limits['max_bins']: raise ValueError('Density-bin budget exceeded; coarsen the window')
            g['_bins'][index] = 0
        g['_bins'][index] += 1
        previous = g['_previous']
        if previous is not None:
            dt = value-previous[0]; example = {'source_rows':[previous[1], rowno]}
            if dt < 0: add(g['time_reversals'], example)
            elif dt == 0: add(g['adjacent_equal_times'], example)
            elif dt > gap:
                finite_number(dt, 'gap duration')
                add(g['forward_gaps'], {**example, 'start_s':previous[0], 'end_s':value, 'duration_s':dt})
        g['_previous'] = (value,rowno)
    output = []
    for key in sorted(groups):
        g = groups[key]
        g['duplicate_keys']['status'] = 'conditional' if keys else 'unavailable'
        if not keys: g['duplicate_keys']['count'] = None
        g['forward_gaps']['status'] = 'unavailable' if g['invalid_times']['count'] or g['time_reversals']['count'] else 'conditional'
        if g['forward_gaps']['status'] == 'unavailable':
            g['forward_gaps'].update(count=None, examples=[], reason='Invalid or reversed timestamps prevent a complete ordered-gap assessment')
        g['density'] = [{'start_s':finite_number(i*width,'density start'),
                         'end_s':finite_number((i+1)*width,'density end'),'records':n} for i,n in sorted(g['_bins'].items())]
        for private in ['_previous','_keys','_bins']: del g[private]
        output.append(g)
    if sha256(path) != before: raise ValueError('Source changed during quality profiling')
    return {'schema_version':1, 'configuration':request, 'source':{'path':str(path),'sha256':before},
            'scanned_rows':scanned,'selected_rows':selected,'missing_identity':missing_identity,'groups':output,
            'scope':['Counts describe selected observed records, not capture completeness or packet loss.',
                     'Density lists occupied half-open bins; omitted bins have no selected valid-time records, not zero throughput.',
                     'Gap checks concern source order within declared identities; no leading/trailing exposure is inferred.',
                     'Duplicate keys are candidates under the declared key semantics; no observations are removed.',
                     'No identity columns means a source-level profile, not a verified device identity.',
                     'Rows with blank declared identities are counted separately and excluded from identity-level diagnostics.',
                     'Example lists are bounded; total counts remain complete within the scanned scope.']}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--request',required=True); p.add_argument('--output',required=True)
    a=p.parse_args(); request_path=Path(a.request).resolve(); request=read_json(request_path)
    # Source paths use cwd, matching build_windows. Prefer absolute raw paths.
    from common import ensure_output_safe
    inputs=[request_path, request['source']['path']]
    ensure_output_safe(a.output, inputs, '.json')
    write_json(a.output, profile(request), inputs)


if __name__ == '__main__': main()
