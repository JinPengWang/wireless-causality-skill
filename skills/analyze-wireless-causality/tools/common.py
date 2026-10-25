"""Shared validated I/O, measurement identities and normalized-window checks."""
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON constant: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      object_pairs_hook=pairs, parse_constant=invalid,
                      parse_float=lambda value: finite_number(value, 'JSON number'))


def ensure_output_safe(path, inputs=(), suffix=None):
    output = Path(path).resolve()
    if suffix and output.suffix.lower() != suffix:
        raise ValueError('Output must use ' + suffix)
    if output.is_dir():
        raise ValueError('Output is a directory')
    for source in inputs:
        source = Path(source).resolve()
        if output == source or (output.exists() and source.exists() and os.path.samefile(output, source)):
            raise ValueError('Output must not overwrite an input or evidence artifact: ' + str(source))
    return output


def source_paths(payload):
    paths = [s['path'] for s in payload.get('sources', []) if isinstance(s, dict) and 'path' in s]
    paths.extend(w['source_path'] for w in payload.get('windows', []) if w.get('source_path'))
    return sorted(set(paths))


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='write_', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_json(path, value, inputs=()):
    output = ensure_output_safe(path, inputs, '.json')
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    atomic_text(output, text)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def finite_number(value, label, positive=False):
    n = number(value)
    if n is None or (positive and n <= 0):
        raise ValueError(label + ' must be finite' + (' and positive' if positive else ''))
    return n


def require_keys(obj, required, allowed, context):
    if not isinstance(obj, dict):
        raise ValueError(context + ' must be an object')
    missing, unknown = set(required) - obj.keys(), obj.keys() - set(allowed)
    if missing or unknown:
        raise ValueError(f'{context}: missing={sorted(missing)} unknown={sorted(unknown)}')


def known_identity(value):
    return isinstance(value, str) and value.strip().casefold() not in {
        '', 'unknown', 'unpaired', 'unavailable', 'unspecified', 'none', 'null', 'n/a', 'na'}


def measurement_signature(row):
    kind = row.get('kind', 'external_interval_mean')
    if kind not in {'external_interval_mean','interval_mean','interval_amount','ratio','event_mean','event_fraction','event_sum','event_count'}:
        raise ValueError('Unknown measurement aggregation kind')
    definition = row.get('definition')
    identity = row.get('measurement_id')
    if identity is not None and (not isinstance(identity, str) or not known_identity(identity) or identity.strip().startswith(('REPLACE_', 'TODO'))):
        raise ValueError('measurement_id must be a nonempty string')
    if not isinstance(definition, str) or not definition.strip():
        raise ValueError('A normalized metric requires a measurement definition')
    families = {'interval_mean': 'duration_mean', 'external_interval_mean': 'duration_mean',
                'interval_amount': 'exposure_rate', 'event_sum': 'exposure_rate', 'event_count': 'exposure_rate',
                'ratio': 'pooled_observation_mean', 'event_mean': 'pooled_observation_mean',
                'event_fraction': 'pooled_observation_mean'}
    return (families[kind] if identity else kind, row['unit'], identity.strip() if identity else definition.strip())


def validate_windows(windows):
    """Validate adapter outputs before statistics; return normalized copies."""
    if not isinstance(windows, list) or not windows:
        raise ValueError('Provide a nonempty list of normalized windows')
    required = {'run_id', 'entity', 'direction', 'condition', 'pair_id', 'metric', 'unit',
                'start_s', 'end_s', 'coverage', 'value'}
    result = []
    metadata = {}
    series = {}
    for original in windows:
        if not isinstance(original, dict) or not required <= original.keys():
            raise ValueError('Incomplete normalized window')
        row = dict(original)
        for key in required - {'start_s', 'end_s', 'coverage', 'value'}:
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError('Nonempty string required: ' + key)
        for key in ['start_s', 'end_s', 'coverage']:
            row[key] = finite_number(row[key], key)
        if row['end_s'] <= row['start_s'] or not 0 <= row['coverage'] <= 1 + 1e-8:
            raise ValueError('Invalid window duration or coverage')
        row['coverage'] = min(row['coverage'], 1.)
        if math.isclose(row['coverage'], 1., rel_tol=1e-9, abs_tol=1e-12):
            row['coverage'] = 1.
        if row['value'] is not None:
            row['value'] = finite_number(row['value'], 'window value')
            if row['coverage'] == 0:
                raise ValueError('A measured value needs positive observation coverage')
        signature = measurement_signature(row)
        for key in ['aggregation_numerator', 'aggregation_denominator', 'scale']:
            if key in row:
                row[key] = finite_number(row[key], key)
        if row.get('kind') in {'ratio', 'event_mean', 'event_fraction'} and not {'aggregation_numerator', 'aggregation_denominator', 'scale'} <= row.keys():
            raise ValueError('Count/observation measurements require aggregation primitives')
        if row.get('kind') in {'ratio', 'event_fraction'} and (row['scale'] <= 0 or not 0 <= row['aggregation_numerator'] <= row['aggregation_denominator']):
            raise ValueError('Invalid normalized fraction primitives')
        if row.get('kind') == 'event_count' and row.get('aggregation_numerator', 0) < 0:
            raise ValueError('Negative event count')
        if row.get('aggregation_denominator', 0) < 0:
            raise ValueError('Negative aggregation denominator')
        if 'aggregation_denominator' in row and row['value'] is not None:
            if not {'aggregation_numerator', 'scale'} <= row.keys() or row['aggregation_denominator'] <= 0:
                raise ValueError('Incomplete aggregation primitives')
            expected = row['aggregation_numerator'] / row['aggregation_denominator'] * row['scale']
            if not math.isclose(row['value'], expected, rel_tol=1e-8, abs_tol=1e-10):
                raise ValueError('Value disagrees with retained aggregation primitives')
        meta = tuple(row[k] for k in ['entity', 'direction', 'condition', 'pair_id'])
        if row['run_id'] in metadata and metadata[row['run_id']] != meta:
            raise ValueError('Conflicting metadata within a run')
        metadata[row['run_id']] = meta
        key = (row['run_id'], row['metric'])
        if key in series and series[key][0] != signature:
            raise ValueError('Conflicting measurement definitions within a run/metric')
        series.setdefault(key, (signature, []))[1].append(row)
        result.append(row)
    for _, rows in series.values():
        rows.sort(key=lambda r: r['start_s'])
        if any(b['start_s'] < a['end_s'] - 1e-9 for a, b in zip(rows, rows[1:])):
            raise ValueError('Overlapping normalized windows')
    return result


def table_rows(path, sheet=None, header_row=1, required_columns=()):
    """Yield source row and stripped, unique headers; check headers before filtering."""
    if type(header_row) is not int or header_row < 1:
        raise ValueError('header_row must be a positive integer')
    path = Path(path)
    def checked(headers):
        names = [str(h).strip() if h is not None else '' for h in headers]
        if not names or not all(names) or len(set(names)) != len(names):
            raise ValueError('Blank or duplicate headers: provide a reviewed header mapping')
        missing = set(required_columns) - set(names)
        if missing:
            raise ValueError('Mapped column is absent: ' + ', '.join(sorted(missing)))
        return names
    if path.suffix.lower() == '.xlsx':
        import openpyxl
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet is None and len(workbook.sheetnames) != 1:
                raise ValueError('Select an explicit sheet for a multi-sheet workbook')
            if sheet is not None and sheet not in workbook.sheetnames:
                raise ValueError('Selected sheet is absent')
            ws = workbook[sheet] if sheet is not None else workbook[workbook.sheetnames[0]]
            rows = ws.iter_rows(min_row=header_row, values_only=True)
            names = checked(next(rows, ()))
            for rowno, row in enumerate(rows, header_row + 1):
                if any(v is not None for v in row):
                    yield rowno, dict(zip(names, row))
        finally:
            workbook.close()
    elif path.suffix.lower() in {'.csv', '.tsv'}:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = csv.reader(stream, delimiter='\t' if path.suffix.lower() == '.tsv' else ',')
            for _ in range(header_row - 1):
                next(rows, None)
            names = checked(next(rows, ()))
            for rowno, row in enumerate(rows, header_row + 1):
                if not row:
                    continue
                if len(row) != len(names):
                    raise ValueError(f'Column count mismatch at row {rowno}')
                yield rowno, dict(zip(names, row))
    else:
        raise ValueError('Supported tables: .xlsx, .csv, .tsv; add a tested reader for other formats')
