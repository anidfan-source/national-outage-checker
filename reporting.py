"""Portable CSV and JSON report builders for the Streamlit front end."""
import csv
from datetime import datetime, timezone
import io
import json


INCIDENT_COLUMNS = (
    'provider', 'incident', 'status', 'category', 'evidence_type', 'reported_at',
    'identified_at', 'last_fetched_at', 'estimated_restoration_at', 'local_area',
    'postcode_districts', 'reported_postcode_areas', 'telephone_codes',
    'customers_affected', 'location', 'stale', 'source_url', 'description',
    'attribution', 'filter_mode', 'filter_location', 'filter_provider',
    'filter_search', 'report_generated_at', 'collection_at',
)
SOURCE_COLUMNS = (
    'source', 'category', 'connection_state', 'scope', 'last_attempt_at',
    'last_success_at', 'source_updated_at', 'records_returned', 'coverage',
    'error', 'website', 'feed_endpoint', 'notes', 'attribution',
    'report_generated_at', 'collection_at',
)
LIMITATIONS = (
    'Provider reports, risk notices and passive network signals are not household diagnoses. '
    'Telephone, postcode and probe locations may be approximate. Feed history and geographic '
    'coverage are incomplete; no records does not mean no outages. Independent signals may overlap.'
)


def report(records, sources, filters, collection_at, backend_available=True):
    """Return the complete, filter-matched report payload without presentation limits."""
    generated_at = datetime.now(timezone.utc).isoformat()
    incidents = [{**item, 'stale': bool(item.get('stale') or not backend_available)} for item in records]
    health = [
        {**source, 'state': 'backend-offline' if not backend_available and source.get('kind') != 'portal'
         else source.get('state')}
        for source in sources
    ]
    by_category = {}
    for item in incidents:
        by_category[item.get('category')] = by_category.get(item.get('category'), 0) + 1
    source_states = {}
    for source in health:
        source_states[source.get('state')] = source_states.get(source.get('state'), 0) + 1
    return {
        'schemaVersion': 1,
        'generatedAt': generated_at,
        'collectedAt': collection_at,
        'backendAvailable': backend_available,
        'filters': filters,
        'summary': {
            'recordCount': len(incidents),
            'staleCount': sum(bool(item['stale']) for item in incidents),
            'networkEvidenceCount': sum(item.get('evidenceType') in ('network-signal', 'probe-evidence') for item in incidents),
            'byCategory': by_category,
            'sourceStates': source_states,
        },
        'limitations': LIMITATIONS,
        'locationAttribution': 'Ofcom telephone area codes; GeoNames postal data (CC BY 4.0), adapted into approximate associations.',
        'sources': health,
        'incidents': incidents,
    }


def _value(value):
    if value is None:
        return ''
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    value = str(value)
    # Spreadsheet applications can otherwise execute a formula supplied by an upstream feed.
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value

def _joined(values):
    return '; '.join(str(value) for value in (values or []) if value not in (None, ''))

def _write_csv(columns, rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore', lineterminator='\r\n')
    writer.writeheader()
    writer.writerows({key: _value(value) for key, value in row.items()} for row in rows)
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def csv_bytes(payload):
    """Return a compact, one-row-per-incident spreadsheet."""
    filters=payload.get('filters') or {}
    rows=[]
    for item in payload['incidents']:
        points=[f"{point.get('lat')},{point.get('lng')} ({point.get('method','unknown')})" for point in item.get('locationPoints',[]) if point.get('lat') is not None and point.get('lng') is not None]
        rows.append({
            'provider': item.get('provider'), 'incident': item.get('title'), 'category': item.get('category'),
            'evidence_type': item.get('evidenceType', 'provider-notice'),
            'status': item.get('status'), 'reported_at': item.get('date'), 'last_fetched_at': item.get('observedAt'),
            'identified_at': item.get('identifiedAt'), 'stale': item.get('stale'), 'local_area': item.get('region'),
            'reported_postcode_areas': _joined(item.get('reportedPostcodeAreas')),
            'postcode_districts': _joined(item.get('postcodeDistricts')),
            'telephone_codes': _joined(code.get('code') for code in item.get('telephoneAreas', [])),
            'location': _joined(points),
            'customers_affected': item.get('customersAffected'),
            'estimated_restoration_at': item.get('estimatedRestorationAt'), 'source_url': item.get('url'),
            'description': item.get('description'), 'attribution': item.get('attribution'),
            'filter_mode': filters.get('mode'), 'filter_location': filters.get('location'),
            'filter_provider': filters.get('provider'), 'filter_search': filters.get('search'),
            'report_generated_at': payload['generatedAt'], 'collection_at': payload['collectedAt'],
        })
    return _write_csv(INCIDENT_COLUMNS, rows)

def source_health_csv_bytes(payload):
    """Return a separate, one-row-per-source health spreadsheet."""
    rows=[]
    for source in payload['sources']:
        rows.append({
            'source': source.get('name'), 'category': source.get('category'), 'connection_state': source.get('state'),
            'scope': source.get('scope'), 'last_attempt_at': source.get('checkedAt'),
            'last_success_at': source.get('lastSuccess'), 'source_updated_at': source.get('sourceUpdatedAt'),
            'records_returned': source.get('count'), 'coverage': source.get('coverage'), 'error': source.get('error'),
            'website': source.get('website'), 'feed_endpoint': source.get('url'), 'notes': source.get('note'),
            'attribution': source.get('attribution'), 'report_generated_at': payload['generatedAt'],
            'collection_at': payload['collectedAt'],
        })
    return _write_csv(SOURCE_COLUMNS, rows)

