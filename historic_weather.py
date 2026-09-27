"""Bundled Met Office NSWWS metadata for historic environmental context."""
from datetime import datetime, timezone
import json
from pathlib import Path
from locations import named_place_point

ARCHIVE_URL = 'https://www.metoffice.gov.uk/research/library-and-archive/publications/national-severe-weather-warning-service'
DATA_FILE = Path(__file__).resolve().parent / 'reference' / 'nswws_metadata_2026.json'


def fetch_historic_weather_warnings(since=None):
    """Build only the selected date window from the bundled historic metadata index."""
    rows = json.loads(DATA_FILE.read_text(encoding='utf-8'))
    if not isinstance(rows, list):
        raise ValueError('Historic weather metadata must be a list')
    observed = datetime.now(timezone.utc).isoformat()
    records = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Historic weather metadata row is invalid')
        warning_id, issued, classification, element, region = (row.get(key) for key in ('id', 'date', 'classification', 'element', 'region'))
        if not all(isinstance(value, str) and value.strip() for value in (warning_id, issued, classification, element, region)):
            raise ValueError('Historic weather metadata row is incomplete')
        issued_at = datetime.fromisoformat(issued).replace(tzinfo=timezone.utc).isoformat()
        if since and issued_at < since:
            continue
        point=named_place_point(region)
        records.append({
            'id': 'metoffice-historic:' + warning_id,
            'sourceId': 'metoffice-historic',
            'provider': 'Met Office historic weather-warning archive',
            'category': 'environment',
            'title': f'{classification} {element} weather warning',
            'date': issued_at,
            'status': 'historic-warning',
            'description': 'Historic warning metadata. The supplied workbook records its original issue date, classification, weather element and named regions; it does not supply the warning validity period or geometry.',
            'url': ARCHIVE_URL,
            'lat': None,
            'lng': None,
            'region': region,
            'observedAt': observed,
            'current': False,
            'stale': False,
            'evidenceType': 'historic-warning-metadata',
            'locationPoints': [point] if point else [], 'attribution': 'Met Office NSWWS Metadata 2026 workbook; Crown Copyright',
        })
    return records
