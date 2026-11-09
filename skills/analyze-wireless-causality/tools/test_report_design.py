"""Evidence-preservation and presentation-boundary regressions; synthetic only."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import sha256, write_json
from write_report import render
from report_design import load_theme, number_text, presentation_options
from report_writer import anchor, image_data
from check_report_layout import check, inspect_html
from plot_windows import plot


def fixture(root, language='en'):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    values = root/'measurements.json'
    write_json(values, {'values': [12.125, 18.375, .000000246]})
    config = root/'configuration.json'
    write_json(config, {'population': 'Synthetic intervals; no physical causal inference'})
    claims = []
    for i, value in enumerate([12.125, 18.375, .000000246]):
        claims.append({'id': 'C'+str(i+1), 'statement': 'Synthetic value '+str(i+1),
                       'operands': {'x': {'artifact': 'source', 'locator': {'type': 'json_pointer', 'pointer': '/values/'+str(i)},
                                          'unit': 'Mbit/s', 'unit_basis': 'Synthetic delivery rate'}},
                       'expression': 'x', 'value': value, 'unit': 'Mbit/s',
                       'tolerance': {'absolute': 1e-12, 'relative': 0}})
    item = {'id': 'P1', 'statement': 'The synthetic runs differ descriptively; device effects remain unidentified.',
            'status': 'observed', 'calculation': 'Direct values in the declared recording population.',
            'evidence': [{'path': values.name, 'sha256': sha256(values), 'locator': {'type': 'json_pointer', 'pointer': '/values'},
                          'supports': 'All three declared synthetic values'}],
            'figures': [], 'limitations': 'No randomized intervention or independent replication.', 'claim_ids': ['C1', 'C2', 'C3']}
    return {'schema_version': 3, 'analysis_status': 'completed', 'language': language,
            'title': 'Synthetic performance review', 'question': 'What do the available measurements establish?',
            'scope': 'Synthetic report contract only.', 'measurement_contract': 'Declared interval mean delivery in Mbit/s.',
            'phenomena': [item], 'findings': [], 'limitations': 'Causal effects are not identified.',
            'reproduce': 'Execute the synthetic report fixture.',
            'numeric_claims': {'schema_version': 1, 'artifacts': {'source': {'path': values.name, 'sha256': sha256(values)}}, 'claims': claims},
            'assessment': {'execution': {'status': 'completed', 'reason': 'Synthetic arithmetic executed'},
                           'data_capability': {'status': 'limited', 'reason': 'No causal design'},
                           'question_answer': {'status': 'partial', 'reason': 'Descriptive scope only'},
                           'delivery_quality': {'status': 'partial', 'reason': 'Awaiting actual visual review',
                                                'checks': [{'id': 'layout', 'status': 'not_checked', 'reason': 'Awaiting rendering'}]}},
            'claim_review': {'status': 'passed', 'reviewer': 'Synthetic fixture author', 'note': 'All fixture claims mapped', 'unmapped_statements': []},
            'provenance': {'skill_revision': 'synthetic-fixture', 'runtime': {'executable': 'fixture', 'python': 'fixture', 'packages': {}},
                           'commands': [['synthetic-fixture']], 'artifacts': [
                               {'role': 'source', 'path': values.name, 'sha256': sha256(values)},
                               {'role': 'configuration', 'path': config.name, 'sha256': sha256(config)},
                               {'role': 'tool', 'path': str(Path(__file__).resolve()), 'sha256': sha256(__file__)}]}}


def presentation():
    return {'schema_version': 1, 'language': 'en', 'summary_ids': ['P1'], 'item_titles': {'P1': 'Available comparison'},
            'tables': [{'id': 'T1', 'owner': 'P1', 'title': 'Observed delivery', 'note': 'Synthetic values only; no uncertainty estimate.',
                        'columns': [{'label': 'Run'}, {'label': 'Delivery', 'unit': 'Mbit/s'}],
                        'rows': [['A', {'claim_id': 'C1'}], ['B', {'claim_id': 'C2'}], ['C', {'claim_id': 'C3'}]]}]}


class ReportDesignTests(unittest.TestCase):
    def test_renderer_reuses_its_validated_numeric_result(self):
        import evidence_model
        with patch.object(evidence_model, 'verify_numeric_claims', wraps=evidence_model.verify_numeric_claims) as verify:
            self.export()
            self.assertEqual(verify.call_count, 1)

    def setUp(self):
        self.base = Path(tempfile.gettempdir())
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.root = Path(self.temp.name)
        self.report = fixture(self.root)

    def tearDown(self):
        if self.root.parent.resolve() != self.base.resolve():
            raise RuntimeError('Unexpected cleanup target')
        self.temp.cleanup()

    def export(self, fmt='html', options=None, basename='diagnosis'):
        path = self.root/(basename+'.'+('md' if fmt == 'markdown' else fmt))
        render(self.report, self.root, path, presentation=presentation() if options is None else options, output_format=fmt)
        return path

    def illustrated_presentation(self):
        item = self.report['phenomena'][0]
        item['statement'] = 'Compare {{figure:retry}} with {{table:T1}}.'
        for identity, caption in [('phase', 'Phase observations compared with {{figure:retry}}.'),
                                  ('retry', 'Retry observations.')]:
            path = self.root/(identity+'.svg')
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>'+identity+'</title></svg>', encoding='utf-8')
            item['figures'].append({'id': identity, 'path': path.name, 'sha256': sha256(path), 'caption': caption})
        options = presentation()
        options.update(schema_version=2, readings={
            'figure:phase': 'Sparse phase observations. Compare {{figure:retry}}.',
            'figure:retry': 'Interpret the <em>retry flag</em> within its observed population.',
            'table:T1': 'Read the full-run values separately from {{figure:phase}}.'})
        return options

    @staticmethod
    def visible_body(text, fmt):
        # Ignore link markup when checking the reader-visible target and sequence.
        if fmt == 'html':
            return re.sub(r'<[^>]+>', '', text.split('<main>', 1)[1].split('<h2 id="appendix">', 1)[0])
        return re.sub(r'\[([^\]]+)\]\(#[^)]+\)', r'\1', text.split('## Audit appendix', 1)[0])

    def test_references_and_neighboring_readings_follow_reordered_figures(self):
        options = self.illustrated_presentation()
        figures = self.report['phenomena'][0]['figures']
        for order, phase_num, retry_num in [('original', 1, 2), ('reordered', 2, 1)]:
            if order == 'reordered':
                figures.reverse()
            for fmt in ['html', 'markdown']:
                with self.subTest(order=order, fmt=fmt):
                    text = self.export(fmt, options, order).read_text(encoding='utf-8')
                    body = self.visible_body(text, fmt)
                    self.assertNotIn('{{', body)
                    self.assertIn(f'Compare Figure {retry_num} with Table 1.', body)
                    phase = f'Figure {phase_num}. Phase observations compared with Figure {retry_num}.'
                    retry = f'Figure {retry_num}. Retry observations.'
                    phase_reading = f'Sparse phase observations. Compare Figure {retry_num}.'
                    table_reading = f'Read the full-run values separately from Figure {phase_num}.'
                    landmarks = ['Table 1. Observed delivery', table_reading]
                    for identity in [figure['id'] for figure in figures]:
                        landmarks.extend([phase, phase_reading] if identity == 'phase' else [retry, 'Interpret the '])
                    positions = [body.index(mark) for mark in landmarks]
                    self.assertEqual(positions, sorted(positions))
                    self.assertNotIn('<em>retry flag</em>', text)
                    self.assertIn('retry flag', body)

    def test_split_table_has_one_reading_and_references_its_first_part(self):
        options = presentation()
        wide = options['tables'][0]
        following = dict(wide, id='peer', title='Peer summary')
        options['tables'].append(following)
        metrics = load_theme()['table_columns']
        wide['columns'] = [wide['columns'][0]]+[{'label': f'Rate {i}', 'unit': 'Mbit/s'} for i in range(metrics)]
        wide['rows'] = [['A']+[{'claim_id': 'C1'} for _ in range(metrics)]]
        options.update(schema_version=2, readings={'table:T1': 'Wide results share a denominator.',
                                                   'table:peer': 'Only the matched peer is shown.'})
        self.report['phenomena'][0]['statement'] = 'Consult {{table:T1}} and {{table:peer}}.'
        for fmt in ['html', 'markdown']:
            with self.subTest(fmt=fmt):
                body = self.visible_body(self.export(fmt, options).read_text(encoding='utf-8'), fmt)
                self.assertIn('Consult Table 1 and Table 3.', body)
                self.assertIn('Table 2. Observed delivery', body)
                reading = 'Wide results share a denominator.'
                self.assertEqual(body.count(reading), 1)
                self.assertLess(body.index('Table 1. Observed delivery'), body.index(reading))
                self.assertLess(body.index(reading), body.index('Table 3. Peer summary'))

    def test_invalid_visual_ids_readings_and_references_rejected(self):
        options = self.illustrated_presentation()
        readings = options['readings']
        item = self.report['phenomena'][0]
        figure = item['figures'][0]
        for missing in ['figure:phase', 'table:T1']:
            partial = {k: v for k, v in readings.items() if k != missing}
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.export(options={**options, 'readings': partial})
        for target, key, value in [
            (readings, 'table:T1', '  '),
            (readings, 'figure:absent', 'Orphan interpretation'),
            (readings, 'table:T1', 'See {{figure:absent}}.'),
            (item, 'statement', 'See {{table:absent}}.'),
            (figure, 'caption', 'See {{figure:absent}}.'),
        ]:
            with self.subTest(key=key, value=value), patch.dict(target, {key: value}), self.assertRaises(ValueError):
                self.export(options=options)
        anonymous = {k: v for k, v in figure.items() if k != 'id'}
        other = dict(item, id='P2', figures=[figure.copy()])
        with patch.dict(item, figures=[anonymous, item['figures'][1]]), self.assertRaises(ValueError):
            self.export(options=options)
        with patch.dict(self.report, phenomena=[item, other]), self.assertRaises(ValueError):
            self.export(options=options)
        self.assertFalse((self.root/'diagnosis.html').exists())

    def test_empty_visual_set_and_legacy_figures_without_ids(self):
        self.export(options={'schema_version': 2, 'readings': {}}, basename='no-visuals')
        self.illustrated_presentation()
        item = self.report['phenomena'][0]
        item['statement'] = 'Historical observations.'
        for figure in item['figures']:
            del figure['id']
            figure['caption'] = 'Historical observations.'
        for name, options in [('v1', presentation()), ('unspecified', {})]:
            with self.subTest(name=name):
                text = self.export(options=options, basename=name).read_text(encoding='utf-8')
                self.assertIn('Figure 2. Historical observations.', text)

    def test_numeric_audit_is_separate_but_all_claims_reachable(self):
        p = self.export()
        body = p.read_text(encoding='utf-8').split('<main>')[1].split('<h2 id="appendix">')[0]
        self.assertNotIn('sha256', body)
        self.assertNotIn('recomputed_value', body)
        for c in ['C1', 'C2', 'C3']:
            self.assertIn('#'+anchor('claim', c), body)
        self.assertEqual(inspect_html(p)[0]['errors'], [])

    def test_html_and_markdown_keep_counterevidence_and_scope(self):
        item = copy.deepcopy(self.report['phenomena'][0])
        item.update(id='H1', status='unresolved', claim_ids=[], priority=1, priority_reason='Investigate context first',
                    mechanism='Candidate path mechanism', support='Descriptive co-occurrence only',
                    prediction='A controlled contrast changes delivery', strongest_alternative='Offered load varies',
                    counterevidence='Direction reverses across observations', next_test='Measure offered load',
                    claim_type='mechanism_candidate', explains=['P1'])
        self.report['findings'] = [item]
        for fmt in ['html', 'markdown']:
            text = self.export(fmt).read_text(encoding='utf-8')
            body = text.split('<h2 id="appendix">')[0] if fmt == 'html' else text.split('## Audit appendix')[0]
            for key in ['counterevidence', 'strongest_alternative', 'limitations', 'next_test']:
                self.assertIn(item[key], body)

    def test_unselected_items_still_appear_in_body(self):
        p = self.export(options={'summary_ids': []})
        self.assertIn(self.report['phenomena'][0]['statement'], p.read_text(encoding='utf-8'))

    def test_unsafe_markup_is_literal(self):
        self.report['question'] = '<script>alert(1)</script> **not markup**'
        p = self.export()
        self.assertNotIn('<script>', p.read_text(encoding='utf-8'))
        self.assertEqual(inspect_html(p)[0]['errors'], [])

    def test_plain_text_cannot_create_markdown_headings_or_lists(self):
        self.report['phenomena'][0]['statement'] = '# retries is a counter label.\n- Retry denotes an observation.\n1. Sequence is a label.\n~~~\nLiteral &nbsp; counter name.'
        text = self.export('markdown').read_text(encoding='utf-8')
        self.assertEqual(sum(line.startswith('# ') for line in text.splitlines()), 1)
        self.assertNotIn('\n- Retry', text)
        self.assertNotIn('\n1. Sequence', text)
        self.assertNotIn('\n~~~\n', text)
        self.assertIn('&amp;nbsp;', text)

    def test_multiline_table_headers_preserve_table_structure(self):
        p = presentation()
        p['tables'][0]['columns'][1]['label'] = 'Mean\ndelivery'
        text = self.export('markdown', p).read_text(encoding='utf-8')
        self.assertIn('| Run | Mean delivery (Mbit/s) |', text)
        self.assertNotIn('| Run | Mean\n', text)

    def test_tiny_nonzero_value_stays_visible(self):
        self.assertNotEqual(number_text(.000000246, 2), '0')
        self.assertIn('2.46e-07', self.export().read_text(encoding='utf-8'))

    def test_duplicate_summary_and_unknown_title_rejected(self):
        for p in [{'summary_ids': ['P1', 'P1']}, {'item_titles': {'absent': 'Unknown'}}]:
            with self.assertRaises(ValueError):
                self.export(options=p)

    def test_wrong_table_unit_and_unlinked_claim_rejected(self):
        for mutation in ['unit', 'owner']:
            p = presentation()
            if mutation == 'unit':
                p['tables'][0]['columns'][1]['unit'] = 'byte'
            else:
                p['tables'][0]['rows'][0][1]['claim_id'] = 'absent'
            with self.assertRaises(ValueError):
                self.export(options=p)

    def test_wide_table_splits_without_losing_rows_or_columns(self):
        p = presentation()
        table = p['tables'][0]
        table['columns'] = [table['columns'][0]]+[{'label': 'Metric '+str(i), 'unit': 'Mbit/s'} for i in range(8)]
        table['rows'] = [['A']+[{'claim_id': 'C1'} for i in range(8)], ['B']+[{'claim_id': 'C2'} for i in range(8)]]
        text = self.export(options=p).read_text(encoding='utf-8')
        for i in range(8):
            self.assertEqual(text.split('<h2 id="appendix">')[0].count('Metric '+str(i)), 1)
        self.assertEqual(text.split('<h2 id="appendix">')[0].count('<td>A</td>'), 2)

    def test_language_matching_and_chinese_labels(self):
        self.report['language'] = 'zh-CN'
        with self.assertRaises(ValueError):
            self.export()
        text = self.export(options={'language': 'zh-CN', 'summary_ids': ['P1']}).read_text(encoding='utf-8')
        self.assertIn('执行摘要', text)
        self.assertIn('尚未检查', text)

    def test_theme_rejects_unsafe_font_and_invisible_text(self):
        for bad in [{'font_families': ['x; color:red']}, {'text_color': '#ffffff'}, {'table_columns': 2.5}]:
            path = self.root/'theme.json'
            write_json(path, bad)
            with self.assertRaises(ValueError):
                load_theme(path)

    def test_active_svg_is_rejected(self):
        path = self.root/'active.svg'
        for content in ['<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/image.png"/></svg>']:
            path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                image_data(path)

    def test_changed_input_during_export_fails_before_write(self):
        import evidence_model
        original = evidence_model.numerical_checks
        def changed(report, base):
            result = original(report, base)
            write_json(self.root/'configuration.json', {'changed': True})
            return result
        with patch.object(evidence_model, 'numerical_checks', side_effect=changed):
            with self.assertRaises(ValueError):
                self.export()
        self.assertFalse((self.root/'diagnosis.html').exists())

    def test_both_reader_formats_share_complete_audit_sidecar(self):
        self.export('html')
        audit = self.root/'diagnosis.audit.json'
        before = sha256(audit)
        self.export('markdown')
        self.assertEqual(sha256(audit), before)
        model = json.loads(audit.read_text(encoding='utf-8'))
        self.assertEqual(model['ledger'], self.report)
        self.assertEqual(len(model['numerical_checks']['claims']), 3)

    def test_existing_sidecar_is_not_overwritten_by_new_evidence(self):
        self.export()
        audit = self.root/'diagnosis.audit.json'
        before = sha256(audit)
        self.report['question'] = 'A different investigation'
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(sha256(audit), before)

    def test_json_export_cannot_replace_reader_audit_sidecar(self):
        self.export()
        path = self.root/'diagnosis.audit.json'
        before = sha256(path)
        with self.assertRaises(ValueError):
            render(self.report, self.root, path, output_format='json')
        self.assertEqual(sha256(path), before)

    def test_static_check_does_not_claim_visual_review(self):
        p = self.export()
        result = check(p, self.root/'checks.json', use_browser=False)
        self.assertEqual(result['automatic_status'], 'partial')
        self.assertEqual(result['visual_review']['status'], 'not_checked')

    def test_missing_browser_is_recorded_without_false_pdf_success(self):
        p = self.export()
        with patch('check_report_layout.find_browser', return_value=None):
            result = check(p, self.root/'checks.json', pdf=self.root/'diagnosis.pdf')
        self.assertEqual(result['pdf']['status'], 'unsupported')
        self.assertFalse((self.root/'diagnosis.pdf').exists())

    def test_checker_does_not_overwrite_linked_evidence(self):
        p = self.export()
        before = sha256(self.root/'measurements.json')
        with self.assertRaises(ValueError):
            check(p, self.root/'measurements.json', use_browser=False)
        self.assertEqual(sha256(self.root/'measurements.json'), before)

    def test_existing_pdf_is_never_mistaken_for_new_export(self):
        p = self.export()
        pdf = self.root/'old.pdf'
        pdf.write_bytes(b'%PDF-old')
        with self.assertRaises(ValueError):
            check(p, self.root/'checks.json', pdf=pdf, use_browser=False)

    def test_checker_protects_provenance_not_exposed_as_hyperlink(self):
        p = self.export()
        path = self.root/'configuration.json'
        before = sha256(path)
        with self.assertRaises(ValueError):
            check(p, path, use_browser=False)
        self.assertEqual(sha256(path), before)

    def test_cross_drive_link_falls_back_to_local_file_uri(self):
        from report_writer import Writer
        from check_report_layout import local_path
        writer = Writer(self.root/'r.html', 'html', 't', 'en', load_theme())
        with patch('report_writer.os.path.relpath', side_effect=ValueError('different drives')):
            link = writer.relative(self.root/'measurements.json')
        self.assertTrue(link.startswith('file:'))
        self.assertEqual(local_path(link, self.root), (self.root/'measurements.json').resolve())

    def test_language_alias_is_normalized_in_html_attribute(self):
        self.report['language'] = '中文'
        text = self.export(options={}).read_text(encoding='utf-8')
        self.assertIn('<html lang="zh-CN">', text)

    def test_legacy_chinese_marks_numeric_verification_not_checked(self):
        self.report['schema_version'] = 2
        self.report['language'] = 'zh-CN'
        self.report['analysis_status'] = 'partial'
        for field in ['assessment', 'numeric_claims', 'claim_review', 'provenance']:
            self.report.pop(field)
        self.report['phenomena'][0].pop('claim_ids')
        text = self.export(options={}).read_text(encoding='utf-8')
        self.assertIn('旧版 v2 账本未执行 v3 数值核验', text)
        self.assertNotIn('>partial<', text)

    def test_broken_anchor_and_external_image_fail_static_checks(self):
        p = self.export()
        text = p.read_text(encoding='utf-8').replace('</main>', '<a href="#absent">missing</a><img src="https://example.com/x.png" alt="x"></main>')
        p.write_text(text, encoding='utf-8')
        self.assertGreaterEqual(len(inspect_html(p)[0]['errors']), 2)

    def test_dense_distribution_retains_every_entity(self):
        rows = []
        for e in range(15):
            rows.append({'run_id': 'r'+str(e), 'entity': 'entity'+str(e), 'direction': 'receive', 'condition': 'synthetic',
                         'pair_id': 'unknown', 'metric': 'delivery', 'unit': 'Mbit/s', 'start_s': 0, 'end_s': 1,
                         'coverage': 1, 'value': e+1, 'definition': 'Synthetic interval mean delivery'})
        artifacts = plot(rows, self.root/'figures')
        self.assertEqual(len(artifacts), 3)
        self.assertEqual({e for a in artifacts for e in a['entities']}, {r['entity'] for r in rows})
        self.assertTrue(all(len(a['entities']) <= 6 for a in artifacts))

    def test_wrapped_legend_does_not_overlap_axis_labels(self):
        import matplotlib.figure
        rows = []
        for e in range(7):
            rows.append({'run_id': 'long'+str(e), 'entity': 'Device-'+str(e)+'-'+'LongPeerConfigurationLabel_'*3,
                         'direction': 'receive', 'condition': 'long-label scenario', 'pair_id': 'unknown',
                         'metric': 'delivery', 'unit': 'Mbit/s', 'start_s': 0, 'end_s': 1,
                         'coverage': 1, 'value': e+1, 'definition': 'Synthetic interval mean'})
        checked = []
        def inspect_canvas(fig, *args, **kwargs):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            for legend in fig.legends:
                bounds = legend.get_window_extent(renderer)
                for ax in fig.axes:
                    self.assertFalse(bounds.overlaps(ax.xaxis.label.get_window_extent(renderer)))
                self.assertGreaterEqual(bounds.x0, 0)
                self.assertLessEqual(bounds.x1, fig.bbox.width)
            checked.append(True)
        with patch.object(matplotlib.figure.Figure, 'savefig', inspect_canvas):
            artifacts = plot(rows, self.root/'long_figures', language='zh-CN')
        self.assertTrue(checked)
        self.assertEqual({e for a in artifacts for e in a['entities']}, {r['entity'] for r in rows})


if __name__ == '__main__':
    unittest.main()
