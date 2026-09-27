"""Public power-cut reports and passive network evidence; no credentials required."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

MAX_PAGES = 20
PAGE_SIZE = 500
SPEN_PAGE_SIZE = 100


def epoch(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def provider_date(value, parse_date):
    """NGED omits zones. Preserve raw fields and explicitly record this assumption."""
    if not value:
        return None
    d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo('Europe/London'))
    return parse_date(d.isoformat())


def outdated(value, parse_date):
    timestamp = parse_date(value)
    return bool(timestamp and datetime.fromisoformat(timestamp) < datetime.now(timezone.utc) - timedelta(hours=1))


def get_pages(source, fetch):
    kind = source['kind']
    rows = []
    until = int(datetime.now(timezone.utc).timestamp())
    last = None
    for page in range(MAX_PAGES):
        if kind == 'nged':
            url = source['url'] + '&' + urlencode(dict(limit=PAGE_SIZE, offset=page*PAGE_SIZE, sort='_id asc'))
        elif kind == 'ripe':
            url = source['url'] + '?' + urlencode(dict(country_code='GB', status=2, is_public='true', page_size=PAGE_SIZE, page=page+1))
        else:
            url = source['url'] + '?' + urlencode({'relatedTo':'country/GB','from':until-86400,'until':until,
                                                   'format':'codf','limit':PAGE_SIZE,'page':page+1})
        data = json.loads(fetch(url))
        last = data
        if kind == 'nged':
            if data.get('success') is not True or not isinstance(data.get('result'), dict):
                raise ValueError('NGED API reported an error')
            result = data['result']
            batch, total = result.get('records'), result.get('total')
            if not isinstance(batch, list) or not isinstance(total, int) or result.get('total_was_estimated'):
                raise ValueError('NGED pagination schema is incomplete')
            done = len(rows) + len(batch) >= total
        elif kind == 'ripe':
            batch = data.get('results')
            if not isinstance(batch, list) or not isinstance(data.get('count'), int):
                raise ValueError('RIPE pagination schema is incomplete')
            done = not data.get('next')
            if done and len(rows) + len(batch) < data['count']:
                raise ValueError('RIPE returned a truncated snapshot')
        else:
            batch = data.get('data')
            if data.get('error') or not isinstance(batch, list):
                raise ValueError('IODA API reported an error or invalid data')
            done = len(batch) < PAGE_SIZE
        if not batch and not done:
            raise ValueError('Empty page before end of feed')
        rows.extend(batch)
        if done:
            if kind == 'nged':
                return {'success':True, 'result':{'records':rows}}
            if kind == 'ripe':
                return {'results':rows,'count':len(rows)}
            return {'data':rows,'error':None,'copyright':last.get('copyright'), 'windowUntil':until}
    raise ValueError('Pagination limit reached; refusing partial snapshot')


def get_spen_pages(source, fetch):
    """SPEN's Opendatasoft endpoint caps each authenticated page at 100 rows."""
    api_key = os.getenv('SPEN_API_KEY')
    if not api_key:
        raise RuntimeError('SPEN_API_KEY is not configured')
    rows = []
    total = None
    for page in range(MAX_PAGES):
        url = source['url'] + '?' + urlencode({'apikey': api_key, 'limit': SPEN_PAGE_SIZE, 'offset': page * SPEN_PAGE_SIZE})
        data = json.loads(fetch(url))
        batch = data.get('results')
        count = data.get('total_count')
        if not isinstance(batch, list) or not isinstance(count, int):
            raise ValueError('SPEN API returned an invalid outage snapshot')
        if total is None:
            total = count
        elif count != total:
            raise ValueError('SPEN outage total changed during pagination')
        rows.extend(batch)
        if len(rows) >= total:
            return {'results': rows[:total]}
        if not batch:
            raise ValueError('Empty SPEN page before end of feed')
    raise ValueError('SPEN pagination limit reached; refusing partial snapshot')


def collect_public(source, fetch, make_event, parse_date):
    if source['kind'] == 'spen':
        data = get_spen_pages(source, fetch)
    elif source['kind'] == 'radar':
        token = os.getenv('CLOUDFLARE_API_TOKEN')
        if not token:
            raise RuntimeError('CLOUDFLARE_API_TOKEN is not configured')
        url = source['url'] + '?' + urlencode({'location':'GB','dateRange':'7d','format':'json','limit':100})
        data = json.loads(fetch(url, headers={'Authorization': 'Bearer ' + token}))
    else:
        data = json.loads(fetch(source['url'])) if source['kind'] == 'ssen' else get_pages(source, fetch)
    records = normalize(source, data, make_event, parse_date)
    details = {}
    if source['kind'] == 'ssen':
        details['sourceUpdatedAt'] = parse_date(data.get('timestampUtc'))
    elif source['kind'] == 'spen':
        details['sourceUpdatedAt'] = max((x['sourceUpdatedAt'] for x in records if x.get('sourceUpdatedAt')), default=None)
    elif source['kind'] == 'nged':
        details['sourceUpdatedAt'] = max((x['sourceUpdatedAt'] for x in records if x.get('sourceUpdatedAt')), default=None)
    elif source['kind'] == 'ripe':
        details['scannedCount'] = data['count']
        details['coverage'] = 'Public UK disconnected probes; only disconnections starting within 24h are retained.'
    elif source['kind'] == 'ioda':
        details['attribution'] = data.get('copyright') or 'IODA / Georgia Tech'
        details['coverage'] = 'UK-related events overlapping the preceding 24h. Signals may overlap.'
    elif source['kind'] == 'radar':
        details['attribution'] = 'Cloudflare Radar, CC BY-NC 4.0'
        details['coverage'] = 'Cloudflare-verified UK outages published during the preceding seven days.'
    if details.get('sourceUpdatedAt'):
        details['dataStale'] = outdated(details['sourceUpdatedAt'], parse_date)
    return records, details


def normalize(source, data, make_event, parse_date):
    kind = source['kind']
    result = []
    current = datetime.now(timezone.utc)
    if kind == 'ssen':
        if data.get('errorMessage') or not isinstance(data.get('faults'), list):
            raise ValueError('Invalid SSEN fault snapshot')
        for x in data['faults']:
            if not x.get('reference'):
                raise ValueError('SSEN fault has no reference')
            location = x.get('location') or {}
            started = parse_date(x.get('loggedAtUtc'))
            # Do not interpret undocumented job codes as resolved or planned.
            item = make_event(source, x['reference'], x.get('title') or 'Power cut', started,
                'scheduled' if started and datetime.fromisoformat(started) > current else 'reported',
                x.get('message'), source['website'], location.get('latitude'), location.get('longitude'),
                ', '.join(x.get('affectedAreas') or []) or source['scope'])
            item.update(sourceUpdatedAt=parse_date(data.get('timestampUtc')), sourceStatus=x.get('jobStatus'),
                        sourceSubtype=x.get('jobSubType'), customersAffected=x.get('customerCount'),
                        estimatedRestorationAt=parse_date(x.get('estimatedRestorationTimeUtc')), evidenceType='provider-report',
                        attribution='SSEN Distribution, CC BY 4.0')
            result.append(item)
    elif kind == 'spen':
        if not isinstance(data.get('results'), list):
            raise ValueError('Invalid SPEN outage snapshot')
        for x in data['results']:
            if not x.get('fault_id'):
                raise ValueError('SPEN outage has no fault ID')
            started = parse_date(x.get('planned_outage_start_date') if x.get('planned') else x.get('date_of_reported_fault'))
            state = str(x.get('status') or '').casefold()
            status = 'resolved' if state in ('resolved', 'restored', 'completed', 'closed') else 'reported'
            if status != 'resolved' and x.get('planned') and started and datetime.fromisoformat(started) > current:
                status = 'scheduled'
            location = ' · '.join(str(value) for value in (x.get('post_code'), x.get('local_authority'), x.get('region')) if value) or source['scope']
            item = make_event(source, x['fault_id'], ('Planned power work' if x.get('planned') else 'Power cut') + ': ' + str(x.get('voltage') or 'Network incident'),
                started, status, 'Provider status: ' + str(x.get('status') or 'unknown'), source['website'],
                x.get('location_latitude'), x.get('location_longitude'), location)
            item.update(sourceUpdatedAt=parse_date(x.get('upload_date')), sourceStatus=x.get('status'),
                customersAffected=None, estimatedRestorationAt=parse_date(x.get('etr')), planned=bool(x.get('planned')),
                evidenceType='provider-report', attribution='SP Energy Networks National Energy Outage Data, CC BY 4.0',
                localAuthority=x.get('local_authority'), licenceArea=x.get('licence_area'))
            result.append(item)
    elif kind == 'nged':
        if data.get('success') is not True or not isinstance(data.get('result',{}).get('records'), list):
            raise ValueError('Invalid NGED snapshot')
        for x in data['result']['records']:
            if not x.get('Incident ID'):
                raise ValueError('NGED record has no incident ID')
            started = provider_date(x.get('Start Time'), parse_date)
            state = str(x.get('Status') or '').casefold()
            planned = str(x.get('Planned')).lower() == 'true'
            status = 'resolved' if state in ('resolved','restored','completed','closed') else 'reported'
            if status != 'resolved' and planned and started and datetime.fromisoformat(started) > current:
                status = 'scheduled'
            item = make_event(source, x['Incident ID'], ('Planned power work' if planned else 'Power cut') + ': ' + str(x.get('Category') or 'Network incident'),
                started, status, 'Provider status: ' + str(x.get('Status') or 'unknown'), source['website'],
                x.get('Location Latitude'), x.get('Location Longitude'), x.get('Postcodes') or x.get('Region'))
            item.update(sourceUpdatedAt=provider_date(x.get('Upload Date'), parse_date), sourceStatus=x.get('Status'),
                sourceTimestampRaw=x.get('Upload Date'), sourceStartRaw=x.get('Start Time'),
                timezoneAssumption='Europe/London for zone-less NGED timestamps',
                customersAffected=x.get('Confirmed Off'), estimatedRestorationAt=provider_date(x.get('ETR'), parse_date),
                planned=planned, evidenceType='provider-report', attribution='National Grid Electricity Distribution / NGED Open Data Licence')
            result.append(item)
    elif kind == 'ripe':
        if not isinstance(data.get('results'), list):
            raise ValueError('Invalid RIPE probe snapshot')
        for x in data['results']:
            if x.get('country_code') != 'GB' or x.get('is_public') is not True or x.get('status',{}).get('id') != 2:
                continue
            started = parse_date(x['status'].get('since')) or epoch(x.get('status_since'))
            if not started:
                continue
            since = datetime.fromisoformat(started)
            if not current-timedelta(hours=24) <= since <= current:
                continue
            coords = (x.get('geometry') or {}).get('coordinates') or []
            lng, lat = coords if len(coords) == 2 else (None, None)
            asns = sorted({a for a in [x.get('asn_v4'),x.get('asn_v6')] if isinstance(a,int)})
            item = make_event(source, f"{x['id']}:{started}", f"Probe {x['id']} disconnected", started,
                'probe-disconnected', 'Passive probe status, not a confirmed ISP outage. Possible causes include local power loss, maintenance or connectivity. Networks: ' + ', '.join(f'AS{a}' for a in asns),
                f"https://atlas.ripe.net/probes/{x['id']}/",lat,lng,'UK probe / approximate location')
            # Intentionally omit probe IPs, personal descriptions and network prefixes.
            item.update(evidenceType='probe-evidence', locationMethod='probe-location', asns=asns,
                        attribution='RIPE NCC / RIPE Atlas public probe data')
            result.append(item)
    elif kind == 'ioda':
        if data.get('error') or not isinstance(data.get('data'),list):
            raise ValueError('Invalid IODA snapshot')
        for x in data['data']:
            started = epoch(x.get('start'))
            if not started or not x.get('location') or not x.get('datasource'):
                raise ValueError('IODA event missing identity or start time')
            identity = '|'.join(str(x.get(k,'')) for k in ('location','start','datasource','method'))
            key = hashlib.sha256(identity.encode()).hexdigest()[:24]
            item = make_event(source,key,'Network signal: ' + str(x.get('location_name') or x['location']),
                started,'observed-signal','IODA anomaly signal in the last 24-hour query window; current resolution unconfirmed. Several detection methods may describe the same disruption.',
                source['website'],region=x.get('location_name') or source['scope'])
            item.update(evidenceType='network-signal', detectionMethod=x.get('method'), signalDatasource=x['datasource'],
                        signalScore=x.get('score'), signalDurationSeconds=x.get('duration'), sourceStatus=x.get('status'),
                        entity=x['location'], attribution=data.get('copyright') or 'IODA / Georgia Tech')
            result.append(item)
    elif kind == 'radar':
        annotations = (data.get('result') or {}).get('annotations')
        if data.get('success') is not True or not isinstance(annotations, list):
            raise ValueError('Invalid Cloudflare Radar outage snapshot')
        for x in annotations:
            locations = x.get('locations') or []
            if locations and 'GB' not in locations:
                continue
            started = parse_date(x.get('startDate'))
            if not started:
                raise ValueError('Cloudflare Radar outage has no start time')
            outage = x.get('outage') or {}
            identity = '|'.join(str(v) for v in (started, x.get('scope'), ','.join(map(str,x.get('asns') or []))))
            key = hashlib.sha256(identity.encode()).hexdigest()[:24]
            scope = x.get('scope') or 'United Kingdom'
            cause = str(outage.get('outageCause') or 'unknown cause').replace('_',' ').lower()
            outage_type = str(outage.get('outageType') or 'network').replace('_',' ').lower()
            item = make_event(source, key, 'Cloudflare Radar outage: ' + scope, started,
                'resolved' if x.get('endDate') else 'observed-signal',
                f'Cloudflare-verified {outage_type} outage; reported cause: {cause}. This is network-level evidence, not a household diagnosis.',
                x.get('linkedUrl') or source['website'], region=scope)
            item.update(evidenceType='network-signal', estimatedRestorationAt=parse_date(x.get('endDate')),
                asns=x.get('asns') or [], outageCause=outage.get('outageCause'), outageType=outage.get('outageType'),
                attribution='Cloudflare Radar, CC BY-NC 4.0')
            result.append(item)
    else:
        raise ValueError('Unsupported public connector')
    return list({r['id']:r for r in result}.values())

