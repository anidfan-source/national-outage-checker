"""Smoke test for the Streamlit layout without making upstream network calls."""
import unittest
from unittest.mock import patch
from pathlib import Path

from streamlit.testing.v1 import AppTest


FIXTURE = {
    'updatedAt': '2026-09-26T12:00:00+00:00',
    'locationReference': {'codes': [{'code': '0113', 'place': 'Leeds', 'postcodeAreas': ['LS']}]},
    'sources': [{'id': 'test', 'name': 'Test provider', 'category': 'broadband', 'kind': 'rss',
                 'state': 'connected', 'scope': 'UK', 'website': 'https://example.com', 'note': 'Test feed'}],
    'incidents': [{'id': 'test:1', 'sourceId': 'test', 'provider': 'Test provider', 'category': 'broadband',
                   'title': 'Test outage', 'description': 'Published test notice', 'region': 'LS1 1AA',
                   'date': '2026-09-26T11:00:00+00:00', 'observedAt': '2026-09-26T12:00:00+00:00',
                   'status': 'reported', 'current': True, 'stale': False, 'url': 'https://example.com/1',
                   'postcodeAreas': ['LS'], 'reportedPostcodeAreas': ['LS'], 'inferredPostcodeAreas': [],
                   'telephoneAreas': [], 'locationPoints': [{'lat': 53.8, 'lng': -1.5, 'method': 'source'}]}],
}


class StreamlitAppTests(unittest.TestCase):
    def test_page_renders_filters_map_and_downloads(self):
        with patch('server.init_db'), patch('server.refresh'), patch('server.snapshot', return_value=FIXTURE):
            app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'streamlit_app.py').run(timeout=10)
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, 'UK Outage Viewer')
        self.assertEqual(len(app.download_button), 2)
        self.assertTrue(any('Test outage' in expander.label for expander in app.expander))
        self.assertTrue(app.get('deck_gl_json_chart'))


if __name__ == '__main__':
    unittest.main()
