"""Validate evidence and figure integrity before rendering a Markdown diagnosis."""
import argparse
import os
import re
from pathlib import Path
from common import atomic_text, ensure_output_safe, read_json, sha256

STATUSES = {'candidate', 'supported_candidate', 'validated_mechanism', 'unresolved', 'refuted'}


def text_field(value, name):
    if not isinstance(value, str) or not value.strip() or value.strip().startswith(('REPLACE_', 'TODO', 'TBD')):
        raise ValueError('Supply a resolved nonempty ' + name)
    return value


def verify_locator(path, locator, cache=None):
    if not isinstance(locator, dict) or 'type' not in locator:
        raise ValueError('Use a structured evidence locator; see the version 2 template')
    kind = locator['type']
    if kind == 'whole_file':
        return 'verified_whole_file_only'
    if kind == 'description':
        text_field(locator.get('text'), 'locator description')
        return 'unverified_description'
    if kind == 'json_pointer':
        pointer = locator.get('pointer')
        if path.suffix.lower() != '.json' or not isinstance(pointer, str) or (pointer and not pointer.startswith('/')):
            raise ValueError('json_pointer requires a JSON artifact and an empty or slash-prefixed pointer')
        if cache is None:
            cache = {}
        if path not in cache:
            cache[path] = read_json(path)
        value = cache[path]
        for raw in pointer.split('/')[1:] if pointer else []:
            if re.search(r'~(?![01])', raw):
                raise ValueError('Invalid JSON pointer escape')
            token = raw.replace('~1', '/').replace('~0', '~')
            if isinstance(value, dict) and token in value:
                value = value[token]
            elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(value):
                value = value[int(token)]
            else:
                raise ValueError('Evidence JSON pointer does not resolve: ' + pointer)
        return 'verified_json_pointer'
    if kind == 'line_range':
        start, end = locator.get('start'), locator.get('end')
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise ValueError('line_range needs positive inclusive physical line numbers')
        with path.open(encoding='utf-8-sig') as stream:
            for count, _ in enumerate(stream, 1):
                if count >= end:
                    return 'verified_physical_line_range'
        raise ValueError('Evidence line range exceeds file length')
    raise ValueError('Unsupported locator type')


def verify_figure(path):
    if path.suffix.lower() == '.svg':
        import xml.etree.ElementTree as ET
        if ET.parse(path).getroot().tag.split('}')[-1] != 'svg':
            raise ValueError('Invalid SVG figure')
    elif path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
    else:
        raise ValueError('Use a supported image artifact')


def validate_evidence(report, base, cache=None):
    cache = {} if cache is None else cache
    base = Path(base)
    needed = {'schema_version', 'analysis_status', 'question', 'scope', 'measurement_contract',
              'phenomena', 'findings', 'limitations', 'reproduce'}
    if not isinstance(report, dict) or not needed <= report.keys():
        raise ValueError('Missing version 2 report sections; migrate with the current ledger template')
    if type(report['schema_version']) is not int or report['schema_version'] != 2:
        raise ValueError('Report ledger schema_version must be 2')
    if report['analysis_status'] not in {'completed', 'partial', 'blocked'}:
        raise ValueError('Unknown analysis_status')
    for key in ['question', 'scope', 'measurement_contract', 'limitations', 'reproduce']:
        text_field(report[key], key)
    if not isinstance(report['phenomena'], list) or not isinstance(report['findings'], list):
        raise ValueError('phenomena and findings must be lists')
    if report['analysis_status'] == 'completed' and not report['phenomena']:
        raise ValueError('A completed analysis requires observed phenomena')
    if report['analysis_status'] == 'blocked' and (report['phenomena'] or report['findings']):
        raise ValueError('A blocked report must not invent findings; document capabilities and missing evidence')
    if report['findings'] and not report['phenomena']:
        raise ValueError('Findings require an observed phenomenon')
    ids = set()
    for section in ['phenomena', 'findings']:
        for item in report[section]:
            required = {'id', 'statement', 'status', 'calculation', 'evidence', 'figures', 'limitations'}
            if not isinstance(item, dict) or not required <= item.keys():
                raise ValueError('Incomplete evidence item')
            if not isinstance(item['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', item['id']) or item['id'] in ids:
                raise ValueError('Use distinct Markdown-safe evidence ids')
            ids.add(item['id'])
            if item['status'] not in ({'observed'} if section == 'phenomena' else STATUSES):
                raise ValueError('Evidence status is incompatible with its report section')
            for key in ['statement', 'calculation', 'limitations']:
                text_field(item[key], key)
            if not isinstance(item['evidence'], list) or not item['evidence']:
                raise ValueError('Every item requires evidence artifacts')
            if not isinstance(item['figures'], list) or not 1 <= len(item['figures']) <= 2:
                raise ValueError('Use one or two readable figures per item')
            located = {}
            for evidence in item['evidence']:
                path = (base / evidence['path']).resolve()
                if not path.is_file() or sha256(path) != evidence.get('sha256'):
                    raise ValueError('Missing or changed evidence artifact')
                located[evidence['path']] = verify_locator(path, evidence.get('locator'), cache)
            for figure in item['figures']:
                path = (base / figure['path']).resolve()
                if not path.is_file() or sha256(path) != figure.get('sha256'):
                    raise ValueError('Missing or changed figure artifact; record its SHA256')
                text_field(figure.get('caption'), 'figure caption')
                verify_figure(path)
            if section == 'findings':
                explains = item.get('explains')
                if not isinstance(explains, list) or not explains or any(p not in {x['id'] for x in report['phenomena']} for p in explains):
                    raise ValueError('Each finding must explain declared phenomenon ids')
                for key in ['priority_reason', 'mechanism', 'support', 'counterevidence', 'next_test']:
                    text_field(item.get(key), key)
                if type(item.get('priority')) is not int or item['priority'] < 1:
                    raise ValueError('Priority must be a positive ordinal integer')
                if item['status'] == 'validated_mechanism':
                    validation = item.get('validation', {})
                    for key in ['design', 'independent_replication', 'reviewer_assessment']:
                        text_field(validation.get(key), 'validation ' + key)
                    status = located.get(validation.get('result_path'))
                    if status is None or status.startswith('unverified'):
                        raise ValueError('Validation result requires a hashed artifact with a machine-checkable locator')
    return report


def render(report, base, output, ledger_path=None):
    base, output = Path(base), Path(output)
    protected = [base / artifact['path'] for section in ['phenomena', 'findings']
                 for item in report.get(section, []) for kind in ['evidence', 'figures'] for artifact in item.get(kind, [])]
    if ledger_path:
        protected.append(ledger_path)
    ensure_output_safe(output, protected, '.md')
    cache = {}
    report = validate_evidence(report, base, cache)
    def link(path):
        relative = os.path.relpath(Path(path).resolve(), output.parent.resolve()).replace('\\', '/')
        if any(c in relative for c in [' ', '\n', '\r', '<', '>']):
            raise ValueError('Use Markdown-safe artifact paths')
        return relative
    lines = ['# Wireless performance diagnosis', '', report['question'], '',
             '**Analysis status:** ' + report['analysis_status'], '', '## Scope', '', report['scope'], '',
             '## Measurement contract', '', report['measurement_contract'], '', '## Observed phenomena', '']
    def item_text(item):
        rendered = [f"### {item['id']}: {item['statement']}", '', f"Evidence status: **{item['status']}**", '',
                    '**Calculation and selection:** ' + item['calculation'], '']
        for figure in item['figures']:
            rendered += [f"![{item['id']}]({link(base / figure['path'])})", '', figure['caption'], '']
        for key in ['priority_reason', 'mechanism', 'support', 'counterevidence', 'limitations', 'next_test']:
            if key in item:
                rendered += [f"**{key.replace('_', ' ').capitalize()}:** {item[key]}", '']
        if item.get('explains'):
            rendered += ['**Explains phenomena:** ' + ', '.join(item['explains']), '']
        if item['status'] == 'validated_mechanism':
            for key in ['design', 'independent_replication', 'reviewer_assessment', 'result_path']:
                rendered += [f"**Validation {key.replace('_', ' ')}:** {item['validation'][key]}", '']
        if ledger_path:
            rendered += [f"Evidence records: {item['id']} in [evidence ledger]({link(ledger_path)}).", '']
        for evidence in item['evidence']:
            verified = verify_locator((base / evidence['path']).resolve(), evidence['locator'], cache)
            rendered += [f"Evidence `{evidence['path']}`: {verified}; SHA256 `{evidence['sha256']}`.", '']
        return rendered
    for phenomenon in report['phenomena']:
        lines += item_text(phenomenon)
    lines += ['## Prioritized mechanisms and unresolved candidates', '',
              'Priority expresses investigation importance, not a probability of causation.', '']
    for finding in sorted(report['findings'], key=lambda x: (x['priority'], x['id'])):
        lines += item_text(finding)
    lines += ['## Limitations and missing evidence', '', report['limitations'], '',
              '## Reproduction', '', report['reproduce'], '']
    atomic_text(output, '\n'.join(lines))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    source = Path(a.ledger).resolve()
    render(read_json(source), source.parent, a.output, source)


if __name__ == '__main__':
    main()
