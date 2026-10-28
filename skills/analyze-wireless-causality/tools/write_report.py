"""Validate evidence, then export JSON or a whitepaper in Markdown/offline HTML."""
import argparse
import json
import sys
import hashlib
from pathlib import Path
from common import atomic_text, ensure_output_safe, read_json, sha256
from evidence_model import validate_evidence, verify_locator, verify_figure, protected_artifacts, numerical_checks
from report_design import ASSETS, load_theme, presentation_options
from report_labels import EN, ZH, labels
from report_writer import Writer, anchor


def render(report, base, output, ledger_path=None, presentation=None, output_format='markdown', theme_path=None):
    base, output = Path(base), Path(output)
    suffix = {'markdown': '.md', 'html': '.html', 'json': '.json'}
    if output_format not in suffix:
        raise ValueError('Supported formats are markdown, html and json; PDF uses the browser exporter')
    if output.name.lower().endswith('.audit.json'):
        raise ValueError('The .audit.json suffix is reserved for protected reader audit sidecars')
    resources = [Path(__file__), Path(__file__).with_name('report_writer.py'),
                 Path(__file__).with_name('report_design.py'), Path(__file__).with_name('report_labels.py'),
                 ASSETS/'theme.json', ASSETS/'whitepaper.css']
    if theme_path:
        resources.append(Path(theme_path))
    protected = protected_artifacts(report, base, ledger_path)+resources
    ensure_output_safe(output, protected, suffix[output_format])
    hashes = {str(Path(p).resolve()): sha256(p) for p in protected if Path(p).is_file()}
    report = validate_evidence(report, base)
    checks = numerical_checks(report, base)
    model = {'schema_version': 1, 'ledger_base': str(base.resolve()), 'ledger': report,
             'numerical_checks': checks, 'semantic_truth_verified_by_software': False}
    audit_path, audit_text = None, None
    if output_format == 'json':
        text = json.dumps(model, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    else:
        label = labels(report, presentation)
        theme = load_theme(theme_path)
        settings = presentation_options(report, presentation, checks, theme)
        audit_path = output.with_name(output.stem+'.audit.json')
        ensure_output_safe(audit_path, protected+[output], '.json')
        presentation_trace = {'renderer': 'whitepaper-v1', 'python': sys.version.split()[0],
                              'theme': theme, 'presentation': presentation,
                              'resources': {str(p): hashes[str(p.resolve())] for p in resources},
                              'visual_review': 'not_certified_by_renderer'}
        audit_text = json.dumps({**model, 'presentation': presentation_trace}, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
        if audit_path.exists() and audit_path.read_text(encoding='utf-8-sig') != audit_text:
            raise ValueError('Use a fresh report basename; existing audit sidecars are not overwritten')
        writer = Writer(output, output_format, report.get('title', label['title']), report.get('language', 'en'), theme)
        writer.sources = [{'path': writer.relative(path), 'sha256': digest} for path, digest in hashes.items()]
        writer.sources.append({'path': writer.relative(audit_path), 'sha256': hashlib.sha256(audit_text.encode('utf-8')).hexdigest()})
        def state(value):
            return label.get('status_'+value, value)
        def item_links(item):
            pairs = [(item['id'], '#'+anchor('audit', item['id']))]
            pairs += [(c, '#'+anchor('claim', c)) for c in item.get('claim_ids', [])]
            writer.references(label['evidence'], pairs)
        all_items = report['phenomena']+sorted(report['findings'], key=lambda x: (x['priority'], x['id']))
        by_id = {i['id']: i for i in all_items}
        writer.container('header', 'report-header')
        writer.paragraph(label['title'], 'eyebrow')
        writer.heading(1, report.get('title', label['title']))
        writer.paragraph(report['question'], 'lead')
        writer.field(label['analysis_status'], state(report['analysis_status']))
        writer.container('header', 'report-header', False)
        writer.heading(2, label['summary'], 'summary')
        writer.container('section', 'summary')
        if not settings['summary_ids']:
            writer.paragraph(label['summary_empty'])
        for identity in settings['summary_ids']:
            item = by_id[identity]
            writer.field(state(item['status']), item['statement'])
            writer.field(label['limitations'], item['limitations'], 'meta')
            writer.references(label['detail'], [(identity, '#'+anchor('item', identity))])
        writer.container('section', 'summary', False)
        writer.field(label['scope_limit'], report['limitations'], 'caveat')
        writer.container('nav', 'contents')
        writer.references(label['contents'], [(label[k], '#'+k) for k in ['scope', 'phenomena', 'findings', 'assessment', 'appendix']])
        writer.container('nav', 'contents', False)
        writer.heading(2, label['scope'], 'scope')
        writer.paragraph(report['scope'])
        writer.field(label['measurement_contract'], report['measurement_contract'])
        figures, tables = 0, 0
        for section in ['phenomena', 'findings']:
            writer.heading(2, label[section], section)
            if section == 'findings':
                writer.paragraph(label['priority_note'], 'meta')
            items = report['phenomena'] if section == 'phenomena' else sorted(report['findings'], key=lambda x: (x['priority'], x['id']))
            if not items:
                writer.paragraph(label['no_items'])
            for item in items:
                writer.heading(3, item['id']+' · '+settings['item_titles'].get(item['id'], label[section]), anchor('item', item['id']))
                writer.paragraph(item['statement'], 'lead')
                writer.field(label['status'], state(item['status']), 'meta')
                if item.get('claim_type'):
                    writer.field(label['claim_type'], state(item['claim_type']), 'meta')
                item_links(item)
                for table in (t for t in settings['tables'] if t['owner'] == item['id']):
                    tables += 1
                    caption = label['table']+' '+str(tables)+'. '+table['title']+(' ('+label['continued']+')' if table['continued'] else '')
                    headers = [c['label']+(' ('+c['unit']+')' if c.get('unit') else '') for c in table['columns']]
                    writer.table(headers, table['rows'], caption)
                    writer.paragraph(table['note'], 'meta')
                for figure in item['figures']:
                    figures += 1
                    writer.figure(base/figure['path'], figure['caption'], figures, label['figure'])
                writer.field(label['calculation'], item['calculation'])
                for key in ['priority_reason', 'mechanism', 'prediction', 'support', 'strongest_alternative', 'counterevidence', 'limitations', 'next_test']:
                    if key in item:
                        writer.field(label[key], item[key], 'caveat' if key in {'limitations', 'counterevidence'} else None)
                if item.get('explains'):
                    writer.references(label['explains'], [(p, '#'+anchor('item', p)) for p in item['explains']])
                for key, value in item.get('validation', {}).items():
                    writer.field(label['validation']+' — '+label.get(key, key), str(value))
        writer.heading(2, label['assessment'], 'assessment')
        writer.paragraph(label['recorded_assessment'], 'meta assessment-note')
        if report.get('assessment'):
            writer.table([label['dimension'], label['status'], label['detail']],
                         [[label[k], state(v['status']), v['reason']] for k, v in report['assessment'].items()])
        else:
            writer.field(label['analysis_status'], state(report['analysis_status']))
        writer.container('section', 'audit')
        writer.heading(2, label['appendix'], 'appendix')
        writer.paragraph(label['verification_note'], 'meta')
        writer.paragraph(label['display_note'], 'meta')
        writer.references(label['full_audit'], [(audit_path.name, writer.relative(audit_path))])
        writer.heading(3, label['evidence'])
        for item in all_items:
            writer.container('article', 'audit-item')
            writer.heading(3, item['id'], anchor('audit', item['id']))
            writer.references(label['detail'], [(item['id'], '#'+anchor('item', item['id']))])
            if ledger_path:
                writer.references(label['ledger'], [(Path(ledger_path).name, writer.relative(ledger_path))])
            for evidence in item['evidence']:
                writer.references(label['evidence'], [(evidence['path'], writer.relative(base/evidence['path']))])
                if evidence.get('supports'):
                    writer.field(label['supports'], evidence['supports'])
                writer.code(json.dumps({'locator': evidence['locator'], 'sha256': evidence['sha256'],
                                        'location_status': verify_locator((base/evidence['path']).resolve(), evidence['locator'])}, ensure_ascii=False))
            writer.container('article', 'audit-item', False)
        writer.heading(3, label['numerical_claims'])
        if report['schema_version'] == 2:
            writer.field(label['status'], state('not_checked')+' — '+label['legacy_numeric'])
        claims = {c['id']: c for c in report.get('numeric_claims', {}).get('claims', [])}
        for index, check in enumerate(checks.get('claims', [])):
            writer.heading(3, check['id'], anchor('claim', check['id']))
            writer.paragraph(claims.get(check['id'], {}).get('statement', check['id']))
            writer.field(label['status'], state(check['status']))
            if 'recomputed_value' in check:
                writer.field(label['calculation'], f"{label['asserted']}: {check['asserted_value']:.15g}; "
                             f"{label['computed']}: {check['recomputed_value']:.15g}; "
                             f"{label['unit']}: {check['unit']}; {label['tolerance']}: {check['allowed_error']:.15g}")
                writer.code(check['expression'])
            if check.get('reason'):
                writer.paragraph(check['reason'])
            for name, operand in check.get('operands', {}).items():
                source = report['numeric_claims']['artifacts'][operand['artifact']]
                writer.references(name+' ('+operand['unit']+')', [(source['path'], writer.relative(base/source['path']))])
                writer.code(json.dumps(operand['locator'], ensure_ascii=False))
            writer.references(label['full_audit'], [(check['id']+' /numerical_checks/claims/'+str(index), writer.relative(audit_path))])
        if report.get('assessment'):
            writer.heading(3, label['delivery_checks'])
            for check in report['assessment']['delivery_quality']['checks']:
                writer.field(check['id']+' — '+state(check['status']), check['reason'])
        writer.heading(3, label['reproduce'])
        writer.paragraph(report['reproduce'])
        if report.get('claim_review'):
            review = report['claim_review']
            writer.heading(3, label['claim_review'])
            writer.field(label['status'], state(review['status']))
            writer.paragraph(review['note'])
            if review.get('reviewer'):
                writer.field(label['reviewer_assessment'], review['reviewer'])
            if review.get('unmapped_statements'):
                writer.code(json.dumps(review['unmapped_statements'], ensure_ascii=False))
        if report.get('provenance'):
            trace = report['provenance']
            writer.heading(3, label['provenance'])
            writer.field(label['version'], trace['skill_revision'])
            writer.field(label['runtime'], trace['runtime']['executable']+' / Python '+trace['runtime']['python'])
            writer.references(label['full_audit'], [('/ledger/provenance', writer.relative(audit_path))])
        writer.heading(3, label['render_provenance'])
        writer.code(json.dumps({'renderer': 'whitepaper-v1', 'ledger_schema': report['schema_version'],
                                'analysis_status': report['analysis_status'], 'format': output_format,
                                'visual_review': 'not_certified_by_renderer'}, ensure_ascii=False))
        writer.references(label['full_audit'], [('/presentation', writer.relative(audit_path))])
        writer.container('section', 'audit', False)
        writer.container('footer', 'report-footer')
        writer.paragraph(label['verification_note'], 'meta')
        writer.container('footer', 'report-footer', False)
        text = writer.finish()
    for path, digest in hashes.items():
        if sha256(path) != digest:
            raise ValueError('An input or rendering resource changed during export: '+path)
    if audit_path is not None and not audit_path.exists():
        atomic_text(audit_path, audit_text)
    if audit_path is not None and sha256(audit_path) != hashlib.sha256(audit_text.encode('utf-8')).hexdigest():
        raise ValueError('Audit sidecar changed during export')
    atomic_text(output, text)
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--format', choices=['markdown', 'html', 'json'], default='markdown')
    parser.add_argument('--presentation', help='Optional summary/table/title/language presentation JSON')
    parser.add_argument('--theme', help='Optional validated theme overrides JSON')
    args = parser.parse_args()
    source = Path(args.ledger).resolve()
    if args.presentation:
        ensure_output_safe(args.output, [args.presentation])
    render(read_json(source), source.parent, args.output, source,
           read_json(args.presentation) if args.presentation else None, args.format, args.theme)


if __name__ == '__main__':
    main()
