"""Validated presentation settings shared by report and plotting tools."""
import math
import re
from pathlib import Path
from common import read_json

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'report'


def contrast(a, b):
    def luminance(color):
        channels = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
        linear = [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in channels]
        return sum(c*w for c, w in zip(linear, [.2126, .7152, .0722]))
    high, low = sorted([luminance(a), luminance(b)], reverse=True)
    return (high+.05)/(low+.05)


def load_theme(path=None):
    theme = read_json(ASSETS / 'theme.json')
    if path:
        overrides = read_json(path)
        if not isinstance(overrides, dict) or set(overrides) - set(theme):
            raise ValueError('Unknown report theme fields')
        theme.update(overrides)
    if type(theme['schema_version']) is not int or theme['schema_version'] != 1:
        raise ValueError('Theme schema_version must be 1')
    for key in ['text_color', 'heading_color', 'accent_color', 'muted_color', 'rule_color', 'background_color', 'soft_color']:
        if not isinstance(theme[key], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', theme[key]):
            raise ValueError('Use six-digit hexadecimal theme colors')
    colors = theme['series_colors']
    if not isinstance(colors, list) or not colors or any(not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in colors):
        raise ValueError('Provide a nonempty hexadecimal series palette')
    fonts = theme['font_families']
    if not isinstance(fonts, list) or not fonts or any(not isinstance(f, str) or not re.fullmatch(r'[\w -]+', f) for f in fonts):
        raise ValueError('Use plain font-family names')
    bounds = {'body_px': (14, 24), 'line_height': (1.3, 2), 'content_width_px': (640, 1100),
              'print_body_pt': (10, 14), 'print_margin_mm': (15, 30), 'table_columns': (2, 8),
              'plot_font_pt': (11, 18), 'plot_width_in': (6, 10),
              'plot_series_per_panel': (1, 8), 'plot_rows_per_page': (1, 4)}
    for key, (low, high) in bounds.items():
        value = theme[key]
        if type(value) not in {int, float} or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Theme parameter outside readable bounds: '+key)
    for key in ['table_columns', 'plot_series_per_panel', 'plot_rows_per_page']:
        if type(theme[key]) is not int:
            raise ValueError(key+' must be an integer')
    for foreground in ['text_color', 'heading_color', 'accent_color', 'muted_color']:
        for background in ['background_color', 'soft_color']:
            if contrast(theme[foreground], theme[background]) < 4.5:
                raise ValueError('Insufficient text contrast: '+foreground+' / '+background)
    return theme


def stylesheet(theme):
    colors = {'text': 'text_color', 'heading': 'heading_color', 'accent': 'accent_color',
              'muted': 'muted_color', 'rule': 'rule_color', 'background': 'background_color', 'soft': 'soft_color'}
    variables = ['--'+k+':'+theme[v] for k, v in colors.items()]
    variables += ['--font:'+','.join('"'+f+'"' for f in theme['font_families']),
                  '--body:'+str(theme['body_px'])+'px', '--leading:'+str(theme['line_height']),
                  '--width:'+str(theme['content_width_px'])+'px', '--print-body:'+str(theme['print_body_pt'])+'pt']
    return (':root {'+';'.join(variables)+'}\n@page {size:A4; margin:'+str(theme['print_margin_mm'])+'mm;'
            ' @bottom-center {content:counter(page); font-size:9pt; color:#536477;}}\n'+
            (ASSETS/'whitepaper.css').read_text(encoding='utf-8'))


def number_text(value, digits=4):
    if type(digits) is not int or not 1 <= digits <= 15:
        raise ValueError('significant_digits must be an integer from 1 to 15')
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError('A displayed numeric claim must have a finite value')
    return format(value, '.'+str(digits)+'g') if value else '0'


def presentation_options(report, presentation, checks, theme):
    p = {} if presentation is None else presentation
    if not isinstance(p, dict):
        raise ValueError('Presentation must be an object')
    version = p.get('schema_version', 1)
    if type(version) is not int or version not in (1, 2):
        raise ValueError('Presentation schema_version must be 1 or 2')
    allowed = {'schema_version', 'language', 'labels', 'summary_ids', 'item_titles', 'tables'}
    if version == 2:
        allowed.add('readings')
    if set(p) - allowed:
        raise ValueError('Unknown presentation fields')
    if 'language' in p and p['language'] != report.get('language', 'en'):
        raise ValueError('Presentation language must match the ledger')
    sections = {'phenomena': report['phenomena'],
                'findings': sorted(report['findings'], key=lambda item: (item['priority'], item['id']))}
    items = {item['id']: item for group in sections.values() for item in group}
    summary = p.get('summary_ids', [])
    if not isinstance(summary, list) or any(not isinstance(i, str) or i not in items for i in summary) or len(set(summary)) != len(summary):
        raise ValueError('summary_ids must select distinct existing evidence items')
    titles = p.get('item_titles', {})
    if not isinstance(titles, dict) or any(k not in items or not isinstance(v, str) or not v.strip() for k, v in titles.items()):
        raise ValueError('item_titles must map existing ids to nonempty titles')
    numeric = {c['id']: c for c in checks.get('claims', [])}
    tables, ids = [], set()
    if not isinstance(p.get('tables', []), list):
        raise ValueError('tables must be a list')
    for table in p.get('tables', []):
        required = {'id', 'owner', 'title', 'note', 'columns', 'rows'}
        if not isinstance(table, dict) or set(table) != required:
            raise ValueError('A presentation table requires id, owner, title, note, columns and rows')
        tid = table['id']
        if not isinstance(tid, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', tid) or tid in ids or table['owner'] not in items:
            raise ValueError('Table ids must be unique and owners must exist')
        ids.add(tid)
        for key in ['title', 'note']:
            if not isinstance(table[key], str) or not table[key].strip():
                raise ValueError('Table '+key+' is required')
        columns = table['columns']
        if not isinstance(columns, list) or len(columns) < 2:
            raise ValueError('Provide a row-label column and at least one data column')
        for col in columns:
            if not isinstance(col, dict) or set(col) - {'label', 'unit'} or not isinstance(col.get('label'), str) or not col['label'].strip():
                raise ValueError('Each column needs a label and an optional unit')
            if 'unit' in col and (not isinstance(col['unit'], str) or not col['unit'].strip()):
                raise ValueError('Column units must be nonempty strings')
        if not isinstance(table['rows'], list) or not table['rows']:
            raise ValueError('Table rows must be nonempty')
        rows = []
        for row in table['rows']:
            if not isinstance(row, list) or len(row) != len(columns) or not isinstance(row[0], str) or not row[0].strip():
                raise ValueError('Rows must match columns and begin with a nonempty row label')
            cells = []
            for index, cell in enumerate(row):
                if isinstance(cell, str):
                    cells.append({'text': cell, 'number': False})
                elif isinstance(cell, dict) and set(cell) <= {'claim_id', 'significant_digits'} and 'claim_id' in cell:
                    claim = numeric.get(cell['claim_id'])
                    if claim is None or cell['claim_id'] not in items[table['owner']].get('claim_ids', []):
                        raise ValueError('Numeric table cells must reference claims belonging to their owner')
                    if claim['status'] != 'passed' or columns[index].get('unit') != claim['unit']:
                        raise ValueError('Numeric table cells require passed claims and matching declared column units')
                    cells.append({'text': number_text(claim['asserted_value'], cell.get('significant_digits', 4)),
                                  'number': True, 'claim_id': claim['id'], 'raw': str(claim['asserted_value'])})
                else:
                    raise ValueError('Use text or a claim reference for each table cell')
            rows.append(cells)
        # Repeat the row-label column when splitting; never truncate or omit data.
        width = theme['table_columns'] - 1
        for offset in range(1, len(columns), width):
            selection = [0]+list(range(offset, min(offset+width, len(columns))))
            tables.append({**table, 'id': tid+'-'+str(offset), 'logical_id': tid,
                           'columns': [columns[i] for i in selection],
                           'rows': [[r[i] for i in selection] for r in rows],
                           'continued': offset > 1, 'last_part': offset + width >= len(columns)})
    # Order first by the owner's final location, then by stable order within the item.
    item_order = {identity: index for index, identity in enumerate(items)}
    tables.sort(key=lambda part: item_order[part['owner']])
    reference_numbers = {}
    for number, part in enumerate(tables, start=1):
        part['number'] = number
        reference_numbers.setdefault('table:'+part['logical_id'], number)
    readings = p.get('readings', {})
    if version == 2:
        figures = (figure for item in items.values() for figure in item['figures'])
        for number, figure in enumerate(figures, start=1):
            identity = figure.get('id')
            if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identity):
                raise ValueError('Presentation v2 requires a stable ASCII figure id on each ledger figure')
            key = 'figure:'+identity
            if key in reference_numbers:
                raise ValueError('Duplicate figure id: '+identity)
            reference_numbers[key] = number
        if not isinstance(readings, dict):
            raise ValueError('readings must map figure:<id> and table:<id> to prose')
        if readings.keys() != reference_numbers.keys():
            missing = sorted(reference_numbers.keys() - readings.keys())
            unknown = sorted(str(k) for k in readings.keys() - reference_numbers.keys())
            raise ValueError(f'Reading coverage mismatch; missing={missing}, unknown={unknown}')
        for key, reading in readings.items():
            if not isinstance(reading, str) or not reading.strip():
                raise ValueError('A nonempty plain-text reading is required for '+key)
    return {'summary_ids': summary, 'item_titles': titles, 'tables': tables, 'sections': sections,
            'readings': readings, 'reference_numbers': reference_numbers if version == 2 else None}
