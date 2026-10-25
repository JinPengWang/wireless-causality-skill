"""Stream XLSX tables; profile values without interpreting names as measurements."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from common import number, sha256, table_rows, write_json


def audit(path, max_rows=None):
    import openpyxl
    before = sha256(path)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = [(ws.title, ws.max_row, ws.max_column) for ws in workbook]
    workbook.close()
    result = {'path':str(Path(path).resolve()), 'sha256':before, 'sheets':[],
              'mode':'full' if max_rows is None else 'sample',
              'formula_policy':'cached values only; formula caches may be absent or stale'}
    for sheet, declared_rows, declared_cols in sheets:
        profile, count, issue = {}, 0, None
        try:
            for rowno, row in table_rows(path, sheet):
                if max_rows is not None and count >= max_rows:
                    break
                count += 1
                for name, value in row.items():
                    col = profile.setdefault(name, {'present':0,'numeric':0,'min':None,'max':None,
                                                     'examples':[], 'bounded_values':Counter()})
                    if value is None or value == '':
                        continue
                    col['present'] += 1
                    text = str(value)
                    if len(col['examples']) < 4 and text[:200] not in col['examples']:
                        col['examples'].append(text[:200])
                    if text in col['bounded_values'] or len(col['bounded_values']) < 64:
                        col['bounded_values'][text] += 1
                    n = number(value)
                    if n is not None:
                        col['numeric'] += 1
                        col['min'] = n if col['min'] is None else min(n, col['min'])
                        col['max'] = n if col['max'] is None else max(n, col['max'])
        except ValueError as exc:
            issue = str(exc)
        for col in profile.values():
            col['missing'] = count - col['present']
            col['first_64_values_counts'] = dict(col.pop('bounded_values'))
        result['sheets'].append({'sheet':sheet,'declared_rows':declared_rows,
                                'declared_columns':declared_cols,'rows_scanned':count,
                                'issue':issue,'columns':profile})
    if sha256(path) != before:
        raise RuntimeError('Source changed during audit')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', nargs='+', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--max-rows', type=int)
    a=p.parse_args()
    if a.max_rows is not None and a.max_rows < 1:
        p.error('--max-rows must be positive')
    if Path(a.output).suffix.lower() != '.json':
        p.error('Output must be a JSON file')
    if any(Path(x).suffix.lower() != '.xlsx' for x in a.input):
        p.error('This audit reads .xlsx only')
    if any(Path(x).resolve() == Path(a.output).resolve() for x in a.input):
        p.error('Output cannot overwrite a source')
    results=[]
    for path in a.input:
        r=audit(path,a.max_rows); results.append(r)
        print(Path(path).name, [(s['sheet'],s['rows_scanned']) for s in r['sheets']], flush=True)
    write_json(a.output, {'created_utc':datetime.now(timezone.utc).isoformat(),'workbooks':results})

if __name__ == '__main__':
    main()
