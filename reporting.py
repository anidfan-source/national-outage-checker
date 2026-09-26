"""Portable CSV and JSON report builders for the Streamlit front end."""
import csv
from datetime import datetime, timezone
import io
import json


COLUMNS = (
    'record_type', 'generated_at', 'collection_at', 'backend_available',
    'filters', 'record_count', 'id', 'provider', 'category', 'evidence_type',
    'title', 'status', 'reported_at', 'last_fetched_at', 'source_updated_at',
    'stale', 'region', 'reported_postcode_areas', 'inferred_postcode_areas',
    'telephone_codes', 'location_methods', 'location_points', 'location_conflict',
    'customers_affected', 'estimated_restoration_at', 'source_url', 'description',
    'source_state', 'source_error', 'last_success_at', 'attribution', 'limitations',
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


def csv_bytes(payload):
    """Return UTF-8 BOM CSV containing the report header, incidents and source health."""
    rows = [{
        'record_type': 'report', 'generated_at': payload['generatedAt'],
        'collection_at': payload['collectedAt'], 'backend_available': payload['backendAvailable'],
        'filters': payload['filters'], 'record_count': payload['summary']['recordCount'],
        'attribution': payload['locationAttribution'], 'limitations': payload['limitations'],
    }]
    for item in payload['incidents']:
        rows.append({
            'record_type': 'incident', 'generated_at': payload['generatedAt'],
            'collection_at': payload['collectedAt'], 'backend_available': payload['backendAvailable'],
            'id': item.get('id'), 'provider': item.get('provider'), 'category': item.get('category'),
            'evidence_type': item.get('evidenceType', 'provider-notice'), 'title': item.get('title'),
            'status': item.get('status'), 'reported_at': item.get('date'), 'last_fetched_at': item.get('observedAt'),
            'source_updated_at': item.get('sourceUpdatedAt'), 'stale': item.get('stale'), 'region': item.get('region'),
            'reported_postcode_areas': item.get('reportedPostcodeAreas'),
            'inferred_postcode_areas': item.get('inferredPostcodeAreas'),
            'telephone_codes': [code.get('code') for code in item.get('telephoneAreas', [])],
            'location_methods': [point.get('method') for point in item.get('locationPoints', [])],
            'location_points': item.get('locationPoints'), 'location_conflict': item.get('locationConflict'),
            'customers_affected': item.get('customersAffected'),
            'estimated_restoration_at': item.get('estimatedRestorationAt'), 'source_url': item.get('url'),
            'description': item.get('description'), 'attribution': item.get('attribution'),
            'limitations': payload['limitations'],
        })
    for source in payload['sources']:
        rows.append({
            'record_type': 'source', 'generated_at': payload['generatedAt'],
            'collection_at': payload['collectedAt'], 'backend_available': payload['backendAvailable'],
            'id': source.get('id'), 'provider': source.get('name'), 'category': source.get('category'),
            'source_state': source.get('state'), 'source_error': source.get('error'),
            'last_success_at': source.get('lastSuccess'), 'last_fetched_at': source.get('checkedAt'),
            'source_updated_at': source.get('sourceUpdatedAt'), 'source_url': source.get('website'),
            'description': source.get('note'), 'attribution': source.get('attribution'),
            'limitations': payload['limitations'],
        })
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=COLUMNS, extrasaction='ignore', lineterminator='\r\n')
    writer.writeheader()
    writer.writerows({key: _value(value) for key, value in row.items()} for row in rows)
    return ('\ufeff' + output.getvalue()).encode('utf-8')
