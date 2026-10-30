"""Real XLSX and CLI regressions for audit completion and sampling boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import BadZipFile, ZipFile

import openpyxl

from audit_workbooks import audit
from common import sha256


class AuditStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_root = Path(__file__).resolve().parents[1]
        cls.test_base = cls.skill_root / 'logs' / 'audit_tests'
        cls.test_base.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='regression_', dir=cls.test_base)
        cls.run_root = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        if cls.run_root.resolve().parent != cls.test_base.resolve():
            raise RuntimeError('Unexpected test cleanup path')
        cls.temporary.cleanup()

    def setUp(self):
        self.root = self.run_root / self._testMethodName
        self.root.mkdir()

    def workbook(self, sheets=None, name='source.xlsx'):
        path = self.root / name
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for title, headers, rows in sheets or [('Data', ['metric', 'label'], [[11, 'a'], [22, 'b']])]:
            ws = wb.create_sheet(title)
            ws.append(headers)
            for row in rows:
                ws.append(row)
        wb.save(path)
        wb.close()
        return path

    def malformed_numeric(self):
        """The ZIP remains valid; only the third worksheet row cannot be decoded."""
        path = self.workbook()
        with ZipFile(path) as source:
            entries = [(entry, source.read(entry.filename)) for entry in source.infolist()]
        with ZipFile(path, 'w') as target:
            for entry, data in entries:
                if entry.filename == 'xl/worksheets/sheet1.xml':
                    self.assertIn(b'<c r="A3" t="n"><v>22</v></c>', data)
                    data = data.replace(b'<c r="A3" t="n"><v>22</v></c>',
                                        b'<c r="A3" t="n"><v>broken-number</v></c>')
                target.writestr(entry, data)
        return path

    def cli(self, inputs, output=None, extra=()):
        output = output or self.root / 'audit.json'
        command = [sys.executable, '-B', '-X', 'utf8',
                   str(self.skill_root / 'tools' / 'audit_workbooks.py'),
                   '--input', *map(str, inputs), '--output', str(output), *extra]
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                   cwd=self.skill_root)
        (self.root / 'cli.stdout.txt').write_text(completed.stdout, encoding='utf-8')
        (self.root / 'cli.stderr.txt').write_text(completed.stderr, encoding='utf-8')
        (self.root / 'cli.exit.txt').write_text(str(completed.returncode), encoding='utf-8')
        return completed, output

    def test_normal_full_audit_completed(self):
        path = self.workbook()
        before = sha256(path)
        result = audit(path)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['mode'], 'full')
        self.assertTrue(result['full_scan_completed'])
        sheet = result['sheets'][0]
        self.assertEqual(sheet['status'], 'completed')
        self.assertEqual(sheet['rows_scanned'], 2)
        self.assertEqual(sheet['columns']['metric']['max'], 22)
        self.assertEqual(sheet['scan']['boundary'], 'end_of_sheet')
        self.assertEqual(sheet['scan']['last_source_row'], 3)
        self.assertTrue(sheet['scan']['full_sheet_scanned'])
        self.assertEqual(sha256(path), before)

    def test_header_only_sheet_is_completed(self):
        result = audit(self.workbook([('Empty data', ['metric'], [])]))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['sheets'][0]['rows_scanned'], 0)
        self.assertTrue(result['full_scan_completed'])

    def test_blank_header_is_failed(self):
        result = audit(self.workbook([('Bad', ['metric', None], [[1, 2]])]))
        self.assertEqual(result['status'], 'failed')
        sheet = result['sheets'][0]
        self.assertEqual(sheet['status'], 'failed')
        self.assertIn('Blank or duplicate headers', sheet['issue'])
        self.assertEqual(sheet['rows_scanned'], 0)
        self.assertEqual(sheet['scan']['boundary'], 'read_error')
        self.assertFalse(result['full_scan_completed'])

    def test_duplicate_header_is_failed(self):
        result = audit(self.workbook([('Bad', ['metric', 'metric'], [[1, 2]])]))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['sheets'][0]['status'], 'failed')
        self.assertIn('Blank or duplicate headers', result['sheets'][0]['issue'])

    def test_real_numeric_xml_error_retains_partial_values(self):
        result = audit(self.malformed_numeric())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['mode'], 'full')
        sheet = result['sheets'][0]
        self.assertEqual(sheet['status'], 'partial')
        self.assertIn('broken-number', sheet['issue'])
        self.assertEqual(sheet['rows_scanned'], 1)
        self.assertEqual(sheet['columns']['metric']['max'], 11)
        self.assertEqual(sheet['columns']['label']['examples'], ['a'])
        self.assertEqual(sheet['scan']['last_source_row'], 2)
        self.assertFalse(sheet['scan']['full_sheet_scanned'])
        self.assertFalse(result['full_scan_completed'])

    def test_mixed_sheets_continue_after_failure(self):
        result = audit(self.workbook([('Bad', ['a', 'a'], [[1, 2]]),
                                      ('Good', ['metric'], [[7], [9]])]))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([s['status'] for s in result['sheets']], ['failed', 'completed'])
        self.assertEqual(result['sheets'][1]['columns']['metric']['max'], 9)

    def test_selected_sheet_records_narrow_scope(self):
        result = audit(self.workbook([('Bad', ['a', 'a'], [[1, 2]]),
                                      ('Good', ['metric'], [[7], [9]])]), sheet='Good')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['sheet_selection'], 'Good')
        self.assertEqual(result['scan_scope'], 'selected_sheet')
        self.assertTrue(result['full_scan_completed'])
        self.assertEqual([s['sheet'] for s in result['sheets']], ['Good'])

    def test_sample_limit_does_not_read_following_bad_row(self):
        result = audit(self.malformed_numeric(), max_rows=1)
        self.assertIsNone(result['sheets'][0]['issue'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['mode'], 'sample')
        sheet = result['sheets'][0]
        self.assertEqual(sheet['status'], 'completed')
        self.assertIsNone(sheet['issue'])
        self.assertEqual(sheet['rows_scanned'], 1)
        self.assertEqual(sheet['scan']['max_rows'], 1)
        self.assertEqual(sheet['scan']['boundary'], 'max_rows')
        self.assertFalse(sheet['scan']['full_sheet_scanned'])
        self.assertFalse(result['full_scan_completed'])

    def test_sample_exhausting_sheet_preserves_requested_mode(self):
        result = audit(self.workbook(), max_rows=5)
        self.assertEqual(result['mode'], 'sample')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['sheets'][0]['scan']['boundary'], 'end_of_sheet')
        self.assertTrue(result['full_scan_completed'])

    def test_cli_completed_exits_zero(self):
        completed, output = self.cli([self.workbook()])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['mode'], 'full')
        self.assertTrue(result['full_scan_completed'])

    def test_cli_partial_nonzero_preserves_json_and_values(self):
        completed, output = self.cli([self.malformed_numeric()])
        self.assertNotEqual(completed.returncode, 0)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['full_scan_completed'])
        sheet = result['workbooks'][0]['sheets'][0]
        self.assertEqual(sheet['rows_scanned'], 1)
        self.assertEqual(sheet['columns']['metric']['min'], 11)

    def test_cli_non_value_reader_error_retains_partial_json(self):
        path = self.workbook()
        with ZipFile(path) as source:
            entries = [(entry, source.read(entry.filename)) for entry in source.infolist()]
        with ZipFile(path, 'w') as target:
            for entry, data in entries:
                if entry.filename == 'xl/worksheets/sheet1.xml':
                    data = data.replace(b'<c r="A3" t="n"><v>22</v></c>',
                                        b'<c r="A3" t="s"><v>9999</v></c>')
                target.writestr(entry, data)
        completed, output = self.cli([path])
        self.assertNotEqual(completed.returncode, 0)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'partial')
        sheet = result['workbooks'][0]['sheets'][0]
        self.assertEqual(sheet['issue_type'], 'IndexError')
        self.assertEqual(sheet['rows_scanned'], 1)
        self.assertEqual(sheet['columns']['metric']['min'], 11)

    def test_cli_failed_nonzero_preserves_json(self):
        path = self.workbook([('Bad', ['a', 'a'], [[1, 2]])])
        completed, output = self.cli([path])
        self.assertNotEqual(completed.returncode, 0)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['workbooks'][0]['sheets'][0]['status'], 'failed')

    def test_cli_mixed_workbooks_retains_all_diagnostics(self):
        bad = self.workbook([('Bad', ['a', 'a'], [[1, 2]])], 'bad.xlsx')
        good = self.workbook(name='good.xlsx')
        completed, output = self.cli([bad, good])
        self.assertNotEqual(completed.returncode, 0)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([w['status'] for w in result['workbooks']], ['failed', 'completed'])
        self.assertEqual(result['workbooks'][1]['sheets'][0]['rows_scanned'], 2)

    def test_cli_successful_sample_is_not_error(self):
        completed, output = self.cli([self.malformed_numeric()], extra=('--max-rows', '1'))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['mode'], 'sample')
        self.assertFalse(result['full_scan_completed'])

    def test_invalid_arguments_still_raise(self):
        path = self.workbook()
        for kwargs in ({'max_rows': 0}, {'header_row': 0}, {'sheet': 'Absent'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                audit(path, **kwargs)

    def test_invalid_container_not_swallowed(self):
        path = self.root / 'invalid.xlsx'
        path.write_text('This is not an XLSX ZIP.', encoding='utf-8')
        with self.assertRaises(BadZipFile):
            audit(path)
        completed, output = self.cli([path])
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(output.exists())

    def test_output_safety_still_rejects_source_overwrite(self):
        path = self.workbook()
        before = sha256(path)
        completed, _ = self.cli([path], output=path)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(sha256(path), before)


if __name__ == '__main__':
    unittest.main()
