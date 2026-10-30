"""Immutable report snapshot regressions, using synthetic evidence only."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import read_json, sha256, write_json
from check_report_layout import inspect_html
from evidence_model import validate_evidence
from snapshot_report import snapshot


SKILL = Path(__file__).resolve().parents[1]


def tree_hashes(root):
    return {str(path.relative_to(root)): sha256(path) for path in root.rglob('*') if path.is_file()}


class ReportSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.base = SKILL/'logs'/'snapshot_tests'
        self.base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.root = Path(self.temp.name)
        self.skill = self.root/'source_skill'
        (self.skill/'tools').mkdir(parents=True)
        for source in (SKILL/'tools').glob('*.py'):
            shutil.copyfile(source, self.skill/'tools'/source.name)
        shutil.copytree(SKILL/'assets'/'report', self.skill/'assets'/'report')
        self.data = self.root/'data'
        self.data.mkdir()
        write_json(self.data/'measurements.json', {'rate': 12.5})
        write_json(self.data/'configuration.json', {'population': 'synthetic only'})
        (self.data/'figure.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="10" height="10"/></svg>', encoding='utf-8')
        artifact = lambda name: {'path': name, 'sha256': sha256(self.data/name)}
        evidence = {**artifact('measurements.json'), 'locator': {'type': 'json_pointer', 'pointer': '/rate'},
                    'supports': 'The declared synthetic rate only'}
        self.report = {
            'schema_version': 3, 'analysis_status': 'completed', 'language': 'en',
            'title': 'Synthetic immutable report', 'question': 'What rate is recorded?',
            'scope': 'Synthetic contract only', 'measurement_contract': 'Declared Mbit/s',
            'phenomena': [{'id': 'P1', 'statement': 'The synthetic rate is 12.5 Mbit/s.', 'status': 'observed',
                           'calculation': 'Direct synthetic value', 'evidence': [evidence],
                           'figures': [{**artifact('figure.svg'), 'caption': 'Synthetic illustration only'}],
                           'limitations': 'No physical inference', 'claim_ids': ['C1']}],
            'findings': [], 'limitations': 'Synthetic fixture', 'reproduce': 'Historical command, retained verbatim',
            'numeric_claims': {'schema_version': 1, 'artifacts': {'source': artifact('measurements.json')},
                               'claims': [{'id': 'C1', 'statement': 'Synthetic rate',
                                           'operands': {'x': {'artifact': 'source', 'locator': {'type': 'json_pointer', 'pointer': '/rate'},
                                                              'unit': 'Mbit/s', 'unit_basis': 'Synthetic rate'}},
                                           'expression': 'x', 'value': 12.5, 'unit': 'Mbit/s',
                                           'tolerance': {'absolute': 0, 'relative': 0}}]},
            'assessment': {'execution': {'status': 'completed', 'reason': 'Synthetic calculation'},
                           'data_capability': {'status': 'limited', 'reason': 'Synthetic scope'},
                           'question_answer': {'status': 'partial', 'reason': 'Descriptive only'},
                           'delivery_quality': {'status': 'passed', 'reason': 'Historical recorded review only',
                                                'checks': [{'id': 'visual', 'status': 'passed', 'reason': 'Historical visual check'}]}},
            'claim_review': {'status': 'passed', 'reviewer': 'Fixture author', 'note': 'Mapped fixture', 'unmapped_statements': []},
            'provenance': {'skill_revision': 'fixture', 'runtime': {'executable': 'historical-python', 'python': 'fixture', 'packages': {}},
                           'commands': [['historical-analysis', '--example']], 'artifacts': [
                               {'role': 'source', **artifact('measurements.json')},
                               {'role': 'configuration', **artifact('configuration.json')},
                               *[{'role': 'tool', 'path': str(self.skill/'tools'/name), 'sha256': sha256(self.skill/'tools'/name)}
                                 for name in ['write_report.py', 'report_labels.py']]]}}
        self.ledger = self.data/'ledger.json'
        write_json(self.ledger, self.report)
        self.output = self.root/'bundle'

    def tearDown(self):
        if self.root.parent.resolve() != self.base.resolve():
            raise RuntimeError('Unexpected cleanup target')
        self.temp.cleanup()

    def export(self, skill, ledger, output):
        return subprocess.run([sys.executable, '-B', '-X', 'utf8', str(skill/'tools'/'write_report.py'),
                               '--ledger', str(ledger), '--output', str(output), '--format', 'html'],
                              capture_output=True, text=True, encoding='utf-8')

    def test_snapshot_reexports_after_original_tools_change_and_keeps_history(self):
        original_html = self.data/'original.html'
        before_export = self.export(self.skill, self.ledger, original_html)
        self.assertEqual(before_export.returncode, 0, before_export.stderr)
        originals = {**{str(p): sha256(p) for p in self.data.iterdir() if p.is_file()},
                     **{str(p): sha256(p) for p in self.skill.rglob('*') if p.is_file()}}
        manifest = snapshot(self.ledger, self.output, skill_root=self.skill)
        self.assertEqual({p: sha256(p) for p in originals}, originals)
        copied = read_json(self.output/'ledger.json')
        for field in ['assessment', 'claim_review', 'reproduce', 'question', 'scope']:
            self.assertEqual(copied[field], self.report[field])
        self.assertEqual(copied['numeric_claims']['claims'], self.report['numeric_claims']['claims'])
        self.assertEqual(copied['provenance']['commands'], self.report['provenance']['commands'])
        self.assertEqual(manifest['snapshot_operation']['visual_review'], 'not_checked')
        self.assertEqual(manifest['source_ledger']['sha256'], sha256(self.ledger))
        self.assertTrue(manifest['artifacts'])
        for entry in manifest['artifacts']:
            self.assertEqual(sha256(self.output/entry['snapshot_path']), entry['sha256'])
            self.assertTrue((self.output/entry['snapshot_path']).resolve().is_relative_to(self.output.resolve()))
        for name in ['write_report.py', 'report_labels.py']:
            path = self.skill/'tools'/name
            path.write_text(path.read_text(encoding='utf-8')+'\n# Later source edit\n', encoding='utf-8')
        self.assertNotEqual(self.export(self.skill, self.ledger, self.data/'stale.html').returncode, 0)
        archived_html = self.output/'report.html'
        result = subprocess.run(manifest['reexport_commands']['html'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(inspect_html(archived_html)[0]['errors'], [])
        self.assertEqual(inspect_html(original_html)[0]['errors'] != [], True)
        text = archived_html.read_text(encoding='utf-8')
        self.assertNotIn(str(self.skill), text)
        self.assertFalse((self.output/'skill'/'logs').exists())

    def test_changed_evidence_and_configuration_are_refused_without_output(self):
        for name in ['measurements.json', 'configuration.json', 'figure.svg']:
            with self.subTest(name=name):
                source = self.data/name
                original = source.read_bytes()
                source.write_bytes(original+b' ')
                before = tree_hashes(self.data)
                with self.assertRaisesRegex(ValueError, 'hash|changed|SHA256'):
                    snapshot(self.ledger, self.output, skill_root=self.skill)
                self.assertEqual(tree_hashes(self.data), before)
                self.assertFalse(self.output.exists())
                source.write_bytes(original)

    def test_historical_source_root_requires_exact_tool_bytes(self):
        historical = self.root/'historical_skill'
        shutil.copytree(self.skill, historical)
        source = self.skill/'tools'/'report_labels.py'
        source.write_text(source.read_text(encoding='utf-8')+'\n# Later labels\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            snapshot(self.ledger, self.output, skill_root=self.skill)
        before = tree_hashes(historical)
        snapshot(self.ledger, self.output, skill_root=self.skill, source_root=historical)
        self.assertEqual(tree_hashes(historical), before)
        self.assertEqual(sha256(self.output/'skill'/'tools'/'report_labels.py'), self.report['provenance']['artifacts'][-1]['sha256'])
        result = self.export(self.output/'skill', self.output/'ledger.json', self.output/'restored.html')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(inspect_html(self.output/'restored.html')[0]['errors'], [])
        bad = historical/'tools'/'report_labels.py'
        bad.write_text(bad.read_text(encoding='utf-8')+'\n# Wrong historic bytes\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            snapshot(self.ledger, self.root/'wrong_history', skill_root=self.skill, source_root=historical)
        self.assertFalse((self.root/'wrong_history').exists())

    def test_missing_historical_runtime_tool_can_use_exact_original(self):
        historical = self.root/'historical_skill'
        shutil.copytree(self.skill, historical)
        (historical/'tools'/'report_labels.py').unlink()
        snapshot(self.ledger, self.output, skill_root=self.skill, source_root=historical)
        self.assertEqual(sha256(self.output/'skill'/'tools'/'report_labels.py'), sha256(self.skill/'tools'/'report_labels.py'))

    def test_existing_output_and_source_overlap_are_refused_without_mutation(self):
        self.output.mkdir()
        (self.output/'keep.txt').write_text('retain', encoding='utf-8')
        before = tree_hashes(self.root)
        for target in [self.output, self.skill, self.skill/'tools'/'nested', self.skill/'assets'/'report'/'nested', self.data, self.root]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                snapshot(self.ledger, target, skill_root=self.skill)
        self.assertEqual(tree_hashes(self.root), before)

    def test_validation_result_path_follows_archived_evidence(self):
        item = copy.deepcopy(self.report['phenomena'][0])
        item.update(id='F1', status='validated_mechanism', priority=1, priority_reason='Synthetic ordering',
                    mechanism='Synthetic contract', support='Synthetic artifact', counterevidence='No physical inference',
                    next_test='Independent real measurement', prediction='Synthetic only', strongest_alternative='Fixture construction',
                    claim_type='intervention_effect', explains=['P1'], claim_ids=[],
                    validation={'result_path': 'measurements.json', 'design': 'Synthetic contract',
                                'independent_replication': 'None; synthetic test', 'reviewer_assessment': 'Synthetic contract',
                                'identification_scope': 'Synthetic scope only'})
        self.report['findings'] = [item]
        write_json(self.ledger, self.report)
        snapshot(self.ledger, self.output, skill_root=self.skill)
        copied = read_json(self.output/'ledger.json')
        self.assertEqual(copied['findings'][0]['validation']['result_path'], copied['findings'][0]['evidence'][0]['path'])

    def test_cli_records_actual_command_and_accepts_historical_source_flag(self):
        argv = [sys.executable, '-B', '-X', 'utf8', str(SKILL/'tools'/'snapshot_report.py'),
                '--ledger', str(self.ledger), '--output-dir', str(self.output),
                '--skill-root', str(self.skill), '--source-root', str(self.skill)]
        result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = read_json(self.output/'snapshot_manifest.json')
        self.assertEqual(manifest['snapshot_operation']['argv'], argv)
        self.assertEqual(manifest['snapshot_operation']['invocation'], 'cli')
        repeated = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(repeated.returncode, 0)

    def test_explicit_presentation_and_theme_remain_usable_after_original_config_changes(self):
        presentation = self.data/'presentation.json'
        theme = self.data/'theme.json'
        options = {'schema_version': 1, 'language': 'en', 'summary_ids': ['P1'],
                   'item_titles': {'P1': 'Selected archived heading'},
                   'tables': [{'id': 'T1', 'owner': 'P1', 'title': 'Archived table', 'note': 'Synthetic comparison',
                               'columns': [{'label': 'Run'}, {'label': 'Rate', 'unit': 'Mbit/s'}],
                               'rows': [['A', {'claim_id': 'C1'}]]}]}
        write_json(presentation, options)
        write_json(theme, {'body_px': 18})
        before = tree_hashes(self.data)
        manifest = snapshot(self.ledger, self.output, skill_root=self.skill,
                            presentation_path=presentation, theme_path=theme)
        self.assertEqual(tree_hashes(self.data), before)
        for config in manifest['explicit_configuration']:
            self.assertEqual(sha256(self.output/config['snapshot_path']), config['sha256'])
            self.assertEqual(config['historical_authentication'], 'not_established_by_snapshot')
        write_json(presentation, {'summary_ids': []})
        write_json(theme, {'body_px': 21})
        result = subprocess.run(manifest['reexport_commands']['html'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        audit = read_json(self.output/'report.audit.json')
        self.assertEqual(audit['presentation']['presentation'], options)
        self.assertEqual(audit['presentation']['theme']['body_px'], 18)
        self.assertEqual(inspect_html(self.output/'report.html')[0]['errors'], [])

    def test_source_drift_during_validation_refuses_publication(self):
        import snapshot_report
        original = snapshot_report.validate_evidence
        def changed(report, base):
            result = original(report, base)
            path = self.skill/'tools'/'report_labels.py'
            path.write_bytes(path.read_bytes()+b'\n# Concurrent edit\n')
            return result
        with patch.object(snapshot_report, 'validate_evidence', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during snapshot'):
                snapshot(self.ledger, self.output, skill_root=self.skill)
        self.assertFalse(self.output.exists())

    def test_one_resolved_file_can_be_both_located_evidence_and_provenance_tool(self):
        tool = self.skill/'tools'/'write_report.py'
        historical = self.root/'historical_skill'
        shutil.copytree(self.skill, historical)
        expected = sha256(tool)
        cases = [(False, str(tool)), (False, '../source_skill/tools/./write_report.py'),
                 (True, str(tool)), (True, '../source_skill/tools/./write_report.py')]
        for index, (recovered, path_text) in enumerate(cases):
            with self.subTest(path=path_text, recovered=recovered):
                if recovered and sha256(tool) == expected:
                    tool.write_bytes(tool.read_bytes()+b'\n# Later live renderer edit\n')
                report = copy.deepcopy(self.report)
                report['phenomena'][0]['evidence'].append({
                    'path': path_text, 'sha256': expected,
                    'locator': {'type': 'line_range', 'start': 1, 'end': 1},
                    'supports': 'The exact renderer implementation recorded by provenance'})
                finding = copy.deepcopy(report['phenomena'][0])
                finding.update(id='F1', status='validated_mechanism', priority=1, priority_reason='Synthetic ordering',
                               mechanism='Synthetic code contract', support='Exact implementation bytes',
                               counterevidence='No physical inference', next_test='Independent measurement',
                               prediction='Synthetic contract', strongest_alternative='Fixture construction',
                               claim_type='intervention_effect', explains=['P1'], claim_ids=[],
                               validation={'result_path': path_text, 'design': 'Synthetic contract',
                                           'independent_replication': 'Synthetic fixture only',
                                           'reviewer_assessment': 'Synthetic contract', 'identification_scope': 'Synthetic code only'})
                report['findings'] = [finding]
                write_json(self.ledger, report)
                if not recovered:
                    validate_evidence(report, self.data)
                output = self.root/('dual_role_'+str(index))
                manifest = snapshot(self.ledger, output, skill_root=self.skill,
                                    source_root=historical if recovered else None)
                copied = read_json(output/'ledger.json')
                evidence = copied['phenomena'][0]['evidence'][-1]
                provenance = next(a for a in copied['provenance']['artifacts']
                                  if a['role'] == 'tool' and a['sha256'] == expected)
                self.assertEqual(evidence['path'], 'skill/tools/write_report.py')
                self.assertEqual(evidence['path'], provenance['path'])
                self.assertEqual(evidence['sha256'], expected)
                self.assertEqual(evidence['locator'], {'type': 'line_range', 'start': 1, 'end': 1})
                self.assertEqual(copied['findings'][0]['validation']['result_path'], evidence['path'])
                validate_evidence(copied, output)
                result = subprocess.run(manifest['reexport_commands']['html'], capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(inspect_html(output/'report.html')[0]['errors'], [])
                if recovered:
                    report['phenomena'][0]['evidence'][-1]['sha256'] = sha256(tool)
                    write_json(self.ledger, report)
                    with self.assertRaisesRegex(ValueError, 'SHA256'):
                        snapshot(self.ledger, self.root/('bad_dual_'+str(index)),
                                 skill_root=self.skill, source_root=historical)
        # A historical copy cannot recover a changed non-tool configuration,
        # even when it has the same skill-relative path and expected old bytes.
        configuration = self.skill/'configuration.json'
        write_json(configuration, {'historical': True})
        shutil.copyfile(configuration, historical/'configuration.json')
        report = copy.deepcopy(self.report)
        report['provenance']['artifacts'][1].update(path=str(configuration), sha256=sha256(configuration))
        write_json(self.ledger, report)
        write_json(configuration, {'historical': False})
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            snapshot(self.ledger, self.root/'bad_configuration', skill_root=self.skill, source_root=historical)
        self.assertFalse((self.root/'bad_configuration').exists())


if __name__ == '__main__':
    unittest.main()
