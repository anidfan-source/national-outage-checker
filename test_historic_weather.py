import unittest

from historic_weather import fetch_historic_weather_warnings


class HistoricWeatherTests(unittest.TestCase):
    def test_bundled_metadata_becomes_historic_environment_records(self):
        records = fetch_historic_weather_warnings()
        self.assertEqual(len(records), 245)
        first = records[0]
        self.assertEqual(first['sourceId'], 'metoffice-historic')
        self.assertEqual(first['status'], 'historic-warning')
        self.assertFalse(first['current'])
        self.assertIn('Scotland', first['region'])
        self.assertIn('validity period or geometry', first['description'])


if __name__ == '__main__':
    unittest.main()
