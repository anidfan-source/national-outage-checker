import io
import json
import os
import unittest
from unittest.mock import patch

from server import date, event
from sources import SOURCES
from street_manager_open_data import collect_street_manager_open_data
from street_manager_webhook import TOPICS, OBJECT_TYPES


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class StreetManagerOpenDataTests(unittest.TestCase):
    def source(self):
        return next(source for source in SOURCES if source["id"] == "street-manager")

    @patch.dict(os.environ, {
        "STREET_MANAGER_WEBHOOK_URL": "https://receiver.example",
        "STREET_MANAGER_WEBHOOK_TOKEN": "secret",
    }, clear=False)
    @patch("street_manager_open_data.urllib.request.urlopen")
    def test_all_open_data_object_types_are_normalized(self, urlopen):
        rows = [
            {
                "event_reference": 1, "event_type": "PERMIT_GRANTED",
                "object_type": "PERMIT", "object_reference": "WR1-01",
                "event_time": "2026-09-26T10:00:00Z",
                "object_data": {"work_reference_number": "WR1", "street_name": "High Street"},
            },
            {
                "event_reference": 2, "event_type": "ACTIVITY_CREATED",
                "object_type": "ACTIVITY", "object_reference": "A1",
                "event_time": "2026-09-26T10:01:00Z",
                "object_data": {"street_name": "Station Road"},
            },
            {
                "event_reference": 3, "event_type": "SECTION_58_CREATED",
                "object_type": "SECTION_58", "object_reference": "S58-1",
                "event_time": "2026-09-26T10:02:00Z",
                "object_data": {"area_name": "Market Square"},
            },
        ]
        urlopen.return_value = Response({"ok": True, "events": rows})
        records, details = collect_street_manager_open_data(self.source(), event, date)
        self.assertEqual(len(records), 3)
        self.assertEqual({row["objectType"] for row in records}, {"PERMIT", "ACTIVITY", "SECTION_58"})
        self.assertEqual(details["scannedCount"], 3)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_receiver_has_official_production_topics(self):
        self.assertEqual(set(TOPICS), {"permit", "activity", "section-58"})
        self.assertIn("PERMIT", OBJECT_TYPES["permit"])
        self.assertIn("ACTIVITY", OBJECT_TYPES["activity"])
        self.assertIn("SECTION_58", OBJECT_TYPES["section-58"])


if __name__ == "__main__":
    unittest.main()
