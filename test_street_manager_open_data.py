import json
import os
import unittest
from unittest.mock import patch

from server import event, date
from sources import SOURCES
from street_manager_open_data import collect_street_manager_open_data

STREET_MANAGER_SOURCE = next(item for item in SOURCES if item["id"] == "street-manager")


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=None):
        return self.payload


class StreetManagerOpenDataTests(unittest.TestCase):
    def test_extracts_nested_location_and_coordinates(self):
        payload = {
            "events": [{
                "object_reference": "WR-1",
                "event_reference": "EV-1",
                "event_time": "2026-09-29T10:00:00Z",
                "event_type": "WORK_STARTED",
                "object_data": {
                    "WorkReferenceNumber": "WR-1",
                    "WorksPromoterName": "Openreach",
                    "WorkStatus": "In Progress",
                    "DetailedLocation": "Outside 10 High Street",
                    "StreetName": "High Street",
                    "Locality": "Old Town",
                    "Town": "Leeds",
                    "Latitude": "53.8008",
                    "Longitude": "-1.5491",
                    "ProposedStartDate": "2026-09-29T08:00:00Z",
                    "ProposedEndDate": "2026-09-30T18:00:00Z",
                    "TrafficManagementType": "Lane closure",
                    "Description": "Fibre installation",
                },
            }, {
                "object_reference": "WR-2",
                "event_type": "WORK_STARTED",
                "object_data": {
                    "WorkReferenceNumber": "WR-2",
                    "PromoterName": "Water utility",
                    "Description": "Water main repair",
                },
            }],
        }
        with patch.dict(os.environ, {
            "STREET_MANAGER_WEBHOOK_URL": "https://receiver.example",
            "STREET_MANAGER_WEBHOOK_TOKEN": "test-token",
        }, clear=False), patch(
            "street_manager_open_data.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            records, details = collect_street_manager_open_data(
                STREET_MANAGER_SOURCE, event, date
            )

        self.assertEqual(details["scannedCount"], 2)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["workReferenceNumber"], "WR-1")
        self.assertEqual(record["lat"], 53.8008)
        self.assertEqual(record["lng"], -1.5491)
        self.assertEqual(record["locationSource"], "source-coordinates")
        self.assertIn("Outside 10 High Street", record["locationDescription"])
        self.assertIn("Leeds", record["locationDescription"])
        self.assertEqual(record["proposedStartAt"], "2026-09-29T08:00:00Z")
        self.assertEqual(record["promoter"], "Openreach")
        self.assertEqual(record["street"], "High Street")
        self.assertEqual(record["trafficManagementType"], "Lane closure")
        self.assertNotIn("proposedEndAt", record)
        self.assertNotIn("actualEndAt", record)

    def test_reads_outer_fields_and_geojson_coordinates(self):
        payload = {"events": [{
            "objectReference": "WR-3",
            "eventType": "WORK_STARTED",
            "eventTime": "2026-09-29T11:00:00Z",
            "promoterName": "CityFibre",
            "description": "Fibre installation",
            "detailedLocation": "Junction of A Road and B Road",
            "town": "Bristol",
            "location": {"coordinates": [-2.5879, 51.4545]},
        }]}
        with patch.dict(os.environ, {
            "STREET_MANAGER_WEBHOOK_URL": "https://receiver.example",
            "STREET_MANAGER_WEBHOOK_TOKEN": "test-token",
        }, clear=False), patch(
            "street_manager_open_data.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            records, _ = collect_street_manager_open_data(
                STREET_MANAGER_SOURCE, event, date
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["lat"], 51.4545)
        self.assertEqual(records[0]["lng"], -2.5879)
        self.assertIn("Junction of A Road and B Road", records[0]["description"])


if __name__ == "__main__":
    unittest.main()
