"""Shared strict I/O. Source files are never written by these tools."""
import hashlib
import json
import math
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def require_keys(obj, required, allowed, context):
    if not isinstance(obj, dict):
        raise ValueError(context + ' must be an object')
    missing, unknown = set(required) - obj.keys(), obj.keys() - set(allowed)
    if missing or unknown:
        raise ValueError(f'{context}: missing={sorted(missing)} unknown={sorted(unknown)}')


def table_rows(path, sheet=None, header_row=1):
    """Yield (source row, mapping); preserve exact headers and reject duplicates."""
    import csv
    path = Path(path)
    if path.suffix.lower() == '.xlsx':
        import openpyxl
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        if sheet is None and len(workbook.sheetnames) != 1:
            workbook.close()
            raise ValueError('Select an explicit sheet for a multi-sheet workbook')
        try:
            ws = workbook[sheet] if sheet else workbook[workbook.sheetnames[0]]
            rows = ws.iter_rows(min_row=header_row, values_only=True)
            headers = next(rows)
            names = [str(h).strip() if h is not None else '' for h in headers]
            if not all(names) or len(set(names)) != len(names):
                raise ValueError('Blank or duplicate headers: provide a reviewed header mapping')
            for rowno, row in enumerate(rows, header_row + 1):
                if any(v is not None for v in row):
                    yield rowno, dict(zip(names, row))
        finally:
            workbook.close()
    elif path.suffix.lower() in {'.csv', '.tsv'}:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = csv.reader(stream, delimiter='\t' if path.suffix.lower() == '.tsv' else ',')
            for _ in range(header_row - 1):
                next(rows)
            names = [h.strip() for h in next(rows)]
            if not all(names) or len(set(names)) != len(names):
                raise ValueError('Blank or duplicate headers')
            for rowno, row in enumerate(rows, header_row + 1):
                if len(row) != len(names):
                    raise ValueError(f'Column count mismatch at row {rowno}')
                yield rowno, dict(zip(names, row))
    else:
        raise ValueError('Supported tables: .xlsx, .csv, .tsv; add a tested reader for other formats')
