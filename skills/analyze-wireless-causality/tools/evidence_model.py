"""Validate presentation-independent investigation ledgers and evidence scope."""
import argparse
import os
import re
from pathlib import Path
from common import read_json, sha256
from verify_claims import verify as verify_numeric_claims, select

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
    if kind in {'table_rows', 'table_cell'}:
        select(path, locator, {} if cache is None else cache)
        return 'verified_table_rows_and_field'
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
    if type(report['schema_version']) is not int or report['schema_version'] not in {2, 3}:
        raise ValueError('Report ledger schema_version must be 2 or 3')
    if report['analysis_status'] not in {'completed', 'partial', 'blocked'}:
        raise ValueError('Unknown analysis_status')
    for key in ['question', 'scope', 'measurement_contract', 'limitations', 'reproduce']:
        text_field(report[key], key)
    if not isinstance(report['phenomena'], list) or not isinstance(report['findings'], list):
        raise ValueError('phenomena and findings must be lists')
    if report['schema_version'] == 2 and report['analysis_status'] == 'completed' and not report['phenomena']:
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
            if not isinstance(item['figures'], list):
                raise ValueError('figures must be a list; an empty list is valid')
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
    if report['schema_version'] == 3:
        validate_v3(report, base, cache)
    return report



def protected_artifacts(report, base, ledger_path=None):
    paths = [Path(base)/a['path'] for section in ['phenomena', 'findings'] for item in report.get(section, [])
             for kind in ['evidence', 'figures'] for a in item.get(kind, [])]
    paths += [Path(base)/a['path'] for a in report.get('numeric_claims', {}).get('artifacts', {}).values()]
    paths += [Path(base)/a['path'] for a in report.get('provenance', {}).get('artifacts', [])]
    if ledger_path is not None:
        paths.append(Path(ledger_path))
    return paths


def numerical_checks(report, base):
    if report['schema_version'] == 2:
        return {'status': 'not_checked', 'reason': 'Legacy v2 ledger has no machine-readable atomic numerical claims'}
    return verify_numeric_claims(report['numeric_claims'], base)


def validate_v3(report, base, cache):
    for key in ['language', 'title']:
        text_field(report.get(key), key)
    assessment = report.get('assessment', {})
    statuses = {
        'execution': {'completed', 'partial', 'blocked'},
        'data_capability': {'sufficient', 'limited', 'unsupported'},
        'question_answer': {'answered', 'partial', 'unanswered'},
        'delivery_quality': {'passed', 'partial', 'not_checked'}
    }
    for dimension, allowed in statuses.items():
        record = assessment.get(dimension, {})
        if record.get('status') not in allowed:
            raise ValueError('Declare a separate ' + dimension + ' status')
        text_field(record.get('reason'), dimension + ' reason')
    if report['analysis_status'] != assessment['execution']['status']:
        raise ValueError('analysis_status and execution status disagree')
    quality = assessment['delivery_quality']
    if not isinstance(quality.get('checks'), list):
        raise ValueError('List actual delivery checks, including unfinished checks')
    for check in quality['checks']:
        text_field(check.get('id'), 'delivery check id')
        text_field(check.get('reason'), 'delivery check reason')
        if check.get('status') not in {'passed', 'failed', 'not_checked', 'not_applicable'}:
            raise ValueError('Invalid delivery check status')
    if quality['status'] == 'passed' and (not any(c['status'] == 'passed' for c in quality['checks']) or any(c['status'] not in {'passed', 'not_applicable'} for c in quality['checks'])):
        raise ValueError('Unfinished/failed checks cannot yield passed delivery quality')
    review = report.get('claim_review', {})
    if review.get('status') not in {'passed', 'partial', 'not_checked'} or not isinstance(review.get('unmapped_statements'), list):
        raise ValueError('Record the manual completeness and semantic review of claim mappings')
    text_field(review.get('note'), 'claim review note')
    if review['status'] == 'passed':
        text_field(review.get('reviewer'), 'claim mapping reviewer')
        if review['unmapped_statements']:
            raise ValueError('Unmapped statements cannot be marked passed')
    checks = numerical_checks(report, base)
    if any(c['status'] in {'failed', 'mismatch'} for c in checks['claims']) or any(a['integrity'] == 'failed' for a in checks['artifacts'].values()):
        raise ValueError('Numerical evidence check failed; run verify_claims.py for individual results')
    if quality['status'] == 'passed' and (review['status'] != 'passed' or any(c['status'] != 'passed' for c in checks['claims'])):
        raise ValueError('Unfinished claim checks cannot yield passed delivery quality')
    all_claims = {c['id'] for c in checks['claims']}
    referenced = set()
    for section in ['phenomena', 'findings']:
        for item in report[section]:
            claim_ids = item.get('claim_ids')
            if not isinstance(claim_ids, list) or any(c not in all_claims for c in claim_ids):
                raise ValueError('Link every item to declared atomic claim ids, or an empty list for qualitative statements')
            referenced.update(claim_ids)
            for evidence in item['evidence']:
                text_field(evidence.get('supports'), 'specific supported part of the statement')
            if section == 'findings':
                for key in ['prediction', 'strongest_alternative']:
                    text_field(item.get(key), key)
                if item.get('claim_type') not in {'association', 'incremental_prediction', 'mechanism_candidate', 'intervention_effect'}:
                    raise ValueError('Distinguish association, prediction, candidate and intervention effect')
                if item['claim_type'] == 'intervention_effect' or item['status'] == 'validated_mechanism':
                    validation = item.get('validation', {})
                    for key in ['design', 'independent_replication', 'reviewer_assessment', 'identification_scope']:
                        text_field(validation.get(key), 'validation ' + key)
                    linked = [a for a in item['evidence'] if a['path'] == validation.get('result_path')]
                    if not linked or not any(a['locator']['type'] in {'json_pointer', 'line_range', 'table_rows', 'table_cell'} for a in linked):
                        raise ValueError('Scoped effect/validated mechanism needs a specific located result')
    if referenced != all_claims:
        raise ValueError('Every numerical claim must be linked to its supported report item')
    trace = report.get('provenance', {})
    text_field(trace.get('skill_revision'), 'skill revision or working-tree hash')
    runtime = trace.get('runtime', {})
    for key in ['executable', 'python']:
        text_field(runtime.get(key), 'runtime ' + key)
    if not isinstance(runtime.get('packages'), dict):
        raise ValueError('Record dependency versions (null when unavailable)')
    if not isinstance(trace.get('commands'), list) or not trace['commands'] or any(not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command) for command in trace['commands']):
        raise ValueError('Record executed commands as argv lists')
    artifacts = trace.get('artifacts')
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError('Record hashed source/configuration/tool artifacts')
    if not {'source', 'configuration', 'tool'} <= {a.get('role') for a in artifacts}:
        raise ValueError('Provenance must include source, configuration and tool roles')
    for artifact in artifacts:
        path = (Path(base)/artifact['path']).resolve()
        if not path.is_file() or sha256(path) != artifact.get('sha256'):
            raise ValueError('Missing or changed provenance artifact')
