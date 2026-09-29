import csv
import io
import unittest
import zipfile
from unittest.mock import patch

from national_roadworks import SRWR_CACHE, collect_srwr
from server import date, event
from sources import SOURCES


class SrwrLocationTests(unittest.TestCase):
    def test_current_activity_fields_provide_location_and_completed_files_are_ignored(self):
        current_headers = [
            "ActivityReference", "ActivityStatus", "WorksPromoterName", "Location",
            "Description", "Street", "Locality", "Town", "StartDateTimeUTC",
            "EndDateTimeUTC", "Latitude", "Longitude",
        ]
        current_row = [
            "BT-123", "Works in progress", "Openreach", "Both sides outside number 10",
            "Fibre installation", "High Street", "Old Town", "Edinburgh",
            "2026-09-29T08:00:00Z", "2026-09-30T18:00:00Z", "55.9517", "-3.18829",
        ]
        completed_headers = ["ActivityReference", "NoticeTypeName"]
        completed_row = ["BT-OLD", "Works Closed"]
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            for name, headers, row in (
                ("CurrentActivities.csv", current_headers, current_row),
                ("CompletedActivities.csv", completed_headers, completed_row),
            ):
                text = io.StringIO()
                writer = csv.writer(text)
                writer.writerow(headers)
                writer.writerow(row)
                archive.writestr(name, text.getvalue())

        SRWR_CACHE.update(expires=0.0, records=None, details=None)
        source = next(item for item in SOURCES if item["id"] == "srwr")
        with patch("national_roadworks._srwr_zip_url", return_value="https://example.test/export.zip"), \
             patch("national_roadworks._download", return_value=payload.getvalue()):
            records, details = collect_srwr(source, event, date)

        self.assertEqual(details["scannedCount"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["workReferenceNumber"], "BT-123")
        self.assertEqual(records[0]["locationDescription"], "Both sides outside number 10 · High Street · Old Town · Edinburgh")
        self.assertEqual(records[0]["lat"], 55.9517)
        self.assertEqual(records[0]["lng"], -3.18829)


if __name__ == "__main__":
    unittest.main()
