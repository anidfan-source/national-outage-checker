#!/usr/bin/env python3
"""Local, standard-library feed aggregator. Run: python3 server.py."""
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from sources import SOURCES
from locations import enrich, reference_summary
from public_connectors import collect_public, outdated
from street_manager_open_data import collect_street_manager_open_data

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'outages.sqlite3'
INTERVAL = 300
LOCK = threading.Lock()
STATE = {'sources': [], 'updatedAt': None, 'refreshing': True}
SCOTTISH_WARNING_REGIONS = (
    'Orkney & Shetland', 'Highlands & Eilean Siar', 'Grampian', 'Strathclyde',
    'Central, Tayside & Fife', 'SW Scotland, Lothian Borders',
)

def now():
    return datetime.now(timezone.utc).isoformat()

def date(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        try:
            d = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            return None
    return d.replace(tzinfo=d.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()

def plain(value):
    return html.unescape(re.sub('<[^>]+>', ' ', str(value or ''))).strip()[:6000]

def weather_warning_region(title, description, fallback):
    """Keep Met Office Scottish warning areas visible without duplicating its UK feed."""
    evidence = f'{title}\n{description}'.casefold()
    matches = [region for region in SCOTTISH_WARNING_REGIONS if region.casefold() in evidence]
    return 'Scotland — ' + '; '.join(matches) if matches else fallback

def safe_url(value, fallback):
    return value if value and urllib.parse.urlsplit(value).scheme in ('https', 'http') else fallback

def flood_area_centroid(item):
    """Read the EA's published flood-area centroid without inferring a warning boundary."""
    area=item.get('floodArea') or {}
    if not isinstance(area, dict): area={}
    lat,lng=area.get('lat'),area.get('long')
    if lat is None or lng is None:
        code=item.get('floodAreaID')
        if code:
            try:
                raw=fetch('https://environment.data.gov.uk/flood-monitoring/id/floodAreas/'+urllib.parse.quote(str(code),safe=''))
                payload=json.loads(raw)
                area=payload.get('items',payload)
                if isinstance(area,list): area=area[0] if area else {}
                lat,lng=area.get('lat'),area.get('long')
            except Exception:
                return None,None
    return lat,lng

def fetch(url, headers=None):
    request_headers={'User-Agent': 'UK-Outage-Viewer/1.0', 'Accept': 'application/json, application/xml, text/xml, */*'}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(req, timeout=18) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError('Feed exceeds 8 MB limit')
    return raw

def event(source, key, title, started, status='unknown', description='', url=None, lat=None, lng=None, region=None):
    try:
        lat, lng = float(lat), float(lng)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            lat = lng = None
    except (ValueError, TypeError):
        lat = lng = None
    return dict(id=source['id'] + ':' + str(key), sourceId=source['id'], provider=source['name'],
                category=source['category'], title=plain(title), date=date(started), status=status,
                description=plain(description), url=safe_url(url, source['website']), lat=lat, lng=lng,
                region=plain(region or source['scope']), observedAt=now())

def timestamp_ms(value):
    try:
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None

def postcode_district(value):
    match = re.match(r'^\s*([A-Z]{1,2}\d[A-Z\d]?)\b', str(value or ''), re.I)
    return match.group(1).upper() if match else None

def parse(source, raw):
    kind = source['kind']
    if kind == 'gointernet':
        # The board has no documented API. Only parse the public active-incident section;
        # closed history is deliberately excluded from the live evidence view.
        active=raw.decode('utf-8','replace').split('Closed incidents',1)[0]
        titles=re.findall(r'Incident title.*?text-gray-950 dark:text-white\s*"\s*>\s*(.*?)\s*</div>',active,re.S)
        return [event(source, hashlib.sha256(plain(title).encode()).hexdigest(), plain(title), now(), 'reported',
                      'Public Go Internet status-board incident. Verify with the provider.', source['website']) for title in titles]
    if kind == 'rss':
        root = ET.fromstring(raw)
        if root.tag.split('}')[-1] not in ('rss', 'feed', 'RDF'):
            raise ValueError('Expected RSS or Atom feed')
        items = root.findall('.//item') + root.findall('{http://www.w3.org/2005/Atom}entry')
        def field(node, *names):
            for name in names:
                for child in node:
                    if child.tag.split('}')[-1] == name:
                        return child.attrib.get('href') or ''.join(child.itertext())
            return ''
        result = []
        for item in items:
            title = field(item, 'title')
            url = field(item, 'link')
            key = field(item, 'guid', 'id') or url or hashlib.sha256(title.encode()).hexdigest()
            description = field(item, 'description', 'summary', 'content')
            region = weather_warning_region(title, description, source['scope']) if source['id'] == 'metoffice' else source['scope']
            # Generic news feeds do not reliably encode active/resolved state.
            result.append(event(source, key, title, field(item, 'pubDate', 'published', 'updated', 'date'),
                                'notice', description, url, region=region))
        return result
    data = json.loads(raw)
    if kind == 'statuspage':
        if not isinstance(data.get('incidents'), list):
            raise ValueError('Missing incidents array')
        return [event(source, x['id'], x['name'], x.get('started_at') or x.get('created_at'), x.get('status', 'unknown'),
                      (x.get('incident_updates') or [{}])[0].get('body', ''), x.get('shortlink')) for x in data['incidents']]
    if kind == 'google':
        if not isinstance(data, list):
            raise ValueError('Expected Google incident list')
        return [event(source, x['id'], x.get('external_desc'), x.get('begin'), 'resolved' if x.get('end') else 'investigating',
                      (x.get('updates') or [{}])[0].get('text', ''),
                      'https://status.cloud.google.com/incidents/' + x['id']) for x in data]
    if kind == 'flood':
        if not isinstance(data.get('items'), list):
            raise ValueError('Missing flood items')
        records=[]
        for x in data['items']:
            lat,lng=flood_area_centroid(x)
            records.append(event(source, x.get('floodAreaID') or x['@id'], x.get('description'), x.get('timeRaised'),
                                 'resolved' if x.get('severityLevel') == 4 else 'warning', x.get('message'),
                                 source['website'], lat,lng,x.get('eaAreaName') or source['scope']))
        return records
    if kind == 'npg':
        if not isinstance(data.get('results'), list):
            raise ValueError('Missing power cut records')
        result = []
        for x in data['results']:
            started = date(x.get('loggedtime'))
            status = 'scheduled' if started and started > now() else 'reported'
            result.append(event(source, x.get('reference') or x['id'], x.get('natureofoutage') or 'Power cut', started,
                                status, f"{x.get('reason') or ''} {x.get('customerstagesequencemessage') or ''} Customers: {x.get('totalconfirmedpowercut', 'unknown')}. Estimated restoration: {x.get('estimatedtimetillresolution') or 'unknown'}.",
                                source['website'], x.get('lat'), x.get('lng'), ', '.join(x.get('postcode') or []) or x.get('area')))
        return result
    if kind == 'community':
        if data.get('ok') is not True or not isinstance(data.get('reports'), list):
            raise ValueError('Missing community reports array')
        result = []
        for item in data['reports']:
            if not item.get('id'):
                raise ValueError('Community report has no ID')
            district = postcode_district(item.get('postcode'))
            severity = str(item.get('severity') or 'routine').lower()
            count = item.get('affected_count')
            try:
                count = int(count) if count is not None else None
            except (TypeError, ValueError):
                count = None
            description = 'User-submitted report; unverified.'
            if count is not None:
                description += f' {count} people marked themselves as affected.'
            record = event(source, item['id'], 'Community telecoms report' + (f' · {severity}' if severity else ''),
                           timestamp_ms(item.get('submitted_at')), 'community-report', description,
                           item.get('map_url'), region=district or source['scope'])
            # Do not ingest free text, street address, photographs or household-level coordinates.
            record.update(evidenceType='community-report', reportStatus=item.get('status'),
                          affectedCount=count, locationMethod='postcode-district',
                          attribution='UK Utility Reporter public community reports')
            result.append(record)
        return result
    raise ValueError('Unknown adapter')

def collect(source):
    health = {**source, 'state': 'portal-only', 'checkedAt': None, 'error': None, 'count': 0}
    if source['kind'] == 'portal':
        return health, None
    health['checkedAt'] = now()
    try:
        if source['kind'] in ('ssen','spen','nged','ripe','ioda','radar'):
            records, details = collect_public(source, fetch, event, date)
            health.update(details)
        elif source['kind'] == 'street-manager-open-data':
            records, details = collect_street_manager_open_data(source, event, date)
            health.update(details)
        elif source['kind'] == 'npg':
            rows = []
            for offset in range(0, 10000, 100):
                data = json.loads(fetch(source['url'] + f'?limit=100&offset={offset}'))
                rows.extend(data['results'])
                if len(rows) >= data['total_count']:
                    break
            else:
                raise ValueError('Power feed exceeds pagination limit; refusing partial snapshot')
            records = parse(source, json.dumps({'results': rows}))
        elif source['kind'] == 'statuspage':
            records = parse(source, fetch(source['url']))
            # The history endpoint is capped; separately fetch all unresolved incidents.
            active = parse(source, fetch(source['url'].replace('/incidents.json', '/incidents/unresolved.json')))
            records = list({item['id']: item for item in records + active}.values())
        else:
            records = parse(source, fetch(source['url']))
        health.update(state='stale' if health.get('dataStale') else 'connected', count=len(records), lastSuccess=now())
        return health, records
    except Exception as exc:
        health.update(state='unavailable', error=f'{type(exc).__name__}: {exc}'[:250])
        return health, None

@contextmanager
def database():
    conn = sqlite3.connect(DB)
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def init_db():
    DB.parent.mkdir(exist_ok=True)
    with database() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, source TEXT, seen TEXT, current INTEGER, body TEXT)')

def refresh():
    global STATE
    with LOCK:
        STATE['refreshing'] = True
        previous = {s['id']: s for s in STATE['sources']}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(collect, SOURCES))
    with database() as conn:
        for health, records in results:
            if records is None:
                health['lastSuccess'] = previous.get(health['id'], {}).get('lastSuccess')
                continue
            conn.execute('UPDATE incidents SET current=0 WHERE source=?', (health['id'],))
            for item in records:
                # Keep `seen` as the first dashboard observation. Provider timestamps can be
                # ahead of the collecting clock, so replacing it would erase useful evidence.
                conn.execute('INSERT INTO incidents VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source=excluded.source, current=excluded.current, body=excluded.body',
                             (item['id'], health['id'], item['observedAt'], 1, json.dumps(item)))
        conn.execute('DELETE FROM incidents WHERE seen < ?', ((datetime.now(timezone.utc) - timedelta(days=366)).isoformat(),))
    with LOCK:
        STATE = dict(sources=[h for h, _ in results], updatedAt=now(), refreshing=False)

def snapshot():
    with LOCK:
        state = json.loads(json.dumps(STATE))
    health = {s['id']: s for s in state['sources']}
    with database() as conn:
        rows = conn.execute('SELECT source,seen,current,body FROM incidents').fetchall()
    state['incidents'] = [{**enrich(json.loads(body)), 'identifiedAt': seen, 'current': bool(current),
                           'stale': health.get(source, {}).get('state') != 'connected' or outdated(json.loads(body).get('sourceUpdatedAt'), date)} for source, seen, current, body in rows]
    state['locationReference'] = reference_summary()
    state['pollSeconds'] = INTERVAL
    return state

def worker():
    while True:
        try:
            refresh()
        except Exception as exc:
            print(f'Refresh failed: {exc}', flush=True)
            with LOCK:
                STATE['refreshing'] = False
        time.sleep(INTERVAL)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/dashboard':
            payload, mime = json.dumps(snapshot()).encode(), 'application/json'
        elif path in ('/', '/index.html', '/app.js', '/reports.js', '/styles.css'):
            name = 'index.html' if path == '/' else path[1:]
            payload = (ROOT / name).read_bytes()
            mime = {'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}[name.rsplit('.', 1)[1]]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

if __name__ == '__main__':
    init_db()
    STATE['sources'] = [{**s, 'state': 'portal-only' if s['kind'] == 'portal' else 'pending'} for s in SOURCES]
    port = int(os.environ.get('PORT', '8000'))
    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=worker, daemon=True).start()
    print(f'UK Outage Viewer: http://localhost:{port}', flush=True)
    httpd.serve_forever()

