import csv
import io
import unittest

from reporting import csv_bytes, report


class ReportingTests(unittest.TestCase):
    def test_report_contains_full_data_and_marks_offline_records_stale(self):
        payload = report(
            [{'id': 'x', 'category': 'broadband', 'evidenceType': 'network-signal', 'stale': False}],
            [{'id': 'feed', 'kind': 'rss', 'state': 'connected'}], {'mode': 'live'}, '2026-01-01', False,
        )
        self.assertTrue(payload['incidents'][0]['stale'])
        self.assertEqual(payload['sources'][0]['state'], 'backend-offline')
        self.assertEqual(payload['summary']['networkEvidenceCount'], 1)

    def test_csv_escapes_spreadsheet_formulae_and_preserves_unicode_newlines(self):
        payload = report(
            [{'id': 'x', 'provider': 'P', 'category': 'broadband', 'title': '=SUM(1,1)',
              'description': 'Quoted "text", café\nand newline'}], [], {}, None,
        )
        output = csv_bytes(payload).decode('utf-8-sig')
        rows = list(csv.DictReader(io.StringIO(output)))
        incident = next(row for row in rows if row['record_type'] == 'incident')
        self.assertEqual(incident['title'], "'=SUM(1,1)")
        self.assertEqual(incident['description'], 'Quoted "text", café\nand newline')


if __name__ == '__main__':
    unittest.main()
