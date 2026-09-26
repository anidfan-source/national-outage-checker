"""On-demand importer for the Environment Agency Historic Flood Warnings release."""
from datetime import datetime, timezone
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


DATASET_URL = ('https://environment.data.gov.uk/api/file/download?'
               'fileDataSetId=766cb094-b392-4bd6-a02e-f60e143f3213&fileName=Historic_Flood_Warnings.zip')
ODS_NS = {'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0'}


def fetch_historic_flood_warnings(fetch=None):
    """Return normalized historic EA warnings; the source is refreshed quarterly."""
    fetch = fetch or _fetch
    with zipfile.ZipFile(io.BytesIO(fetch(DATASET_URL))) as release:
        name = next(item for item in release.namelist() if item.lower().endswith('.ods'))
        workbook = release.read(name)
    with zipfile.ZipFile(io.BytesIO(workbook)) as sheet:
        root = ET.fromstring(sheet.read('content.xml'))
    rows = root.findall('.//table:table-row', ODS_NS)
    result = []
    for row in rows[1:]:
        cells = [''.join(cell.itertext()).strip() for cell in row.findall('table:table-cell', ODS_NS)]
        if len(cells) < 5 or not cells[0] or not cells[2]:
            continue
        try:
            started = datetime.strptime(cells[0], '%d/%m/%Y').replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
        area, code, name, warning_type = cells[1:5]
        result.append({
            'id': 'ea-historic:' + code + ':' + cells[0], 'sourceId': 'ea-historic',
            'provider': 'Environment Agency historic flood warnings', 'category': 'environment',
            'title': warning_type + ': ' + name, 'description': 'Historic Environment Agency flood warning or alert. This is environmental context, not evidence of a broadband fault.',
            'region': area or name, 'date': started, 'observedAt': datetime.now(timezone.utc).isoformat(),
            'status': 'historic', 'current': False, 'stale': False, 'url': DATASET_URL,
            'postcodeAreas': [], 'reportedPostcodeAreas': [], 'inferredPostcodeAreas': [],
            'telephoneAreas': [], 'locationPoints': [], 'evidenceType': 'historic-environment-context',
            'attribution': 'Environment Agency historic flood warnings, Open Government Licence v3.0',
        })
    return result


def _fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'National-Outage-Checker/1.0'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read(12_000_000)
