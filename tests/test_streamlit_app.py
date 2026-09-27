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
    def test_app_builds_navigation_without_errors(self):
        with patch('server.init_db'), patch('server.refresh'), patch('server.snapshot', return_value=FIXTURE):
            app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'streamlit_app.py').run(timeout=10)
        self.assertFalse(app.exception)
        # AppTest does not execute callable pages registered with st.navigation.
        # Verify that the selected page is explicitly run so production is not blank.
        source = (Path(__file__).resolve().parents[1] / 'streamlit_app.py').read_text(encoding='utf-8')
        self.assertIn('navigation.run()', source)
        self.assertIn('Country, county or local-authority match', source)
        self.assertIn('maxBounds', source)
        self.assertIn('CATEGORY_COLORS', source)
        self.assertIn('NOT_ONGOING', source)
        self.assertIn('approximate town/city match', source)
        self.assertIn('HeatmapLayer', source)
        self.assertIn('trends_view', source)
        self.assertIn('lock_map_selection', source)
        self.assertIn("on_select='rerun'", source)
        self.assertIn('map_area_pending', source)


if __name__ == '__main__':
    unittest.main()
