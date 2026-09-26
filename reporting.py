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
    if is…3063 tokens truncated…) for x in data['incidents']]
    if kind == 'google':
        if not isinstance(data, list):
            raise ValueError('Expected Google incident list')
        return [event(source, x['id'], x.get('external_desc'), x.get('begin'), 'resolved' if x.get('end') else 'investigating',
                      (x.get('updates') or [{}])[0].get('text', ''),
                      'https://status.cloud.google.com/incidents/' + x['id']) for x in data]
    if kind == 'flood':
        if not isinstance(data.get('items'), list):
            raise ValueError('Missing flood items')
        return [event(source, x.get('floodAreaID') or x['@id'], x.get('description'), x.get('timeRaised'),
                      'resolved' if x.get('severityLevel') == 4 else 'warning', x.get('message'),
                      source['website'], region=x.get('eaAreaName') or source['scope']) for x in data['items']]
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
    raise ValueError('Unknown adapter')

def collect(source):
    health = {**source, 'state': 'portal-only', 'checkedAt': None, 'error': None, 'count': 0}
    if source['kind'] == 'portal':
        return health, None
    health['checkedAt'] = now()
    try:
        if source['kind'] in ('ssen','nged','ripe','ioda'):
            records, details = collect_public(source, fetch, event, date)
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
                conn.execute('INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?)',
                             (item['id'], health['id'], item['observedAt'], 1, json.dumps(item)))
        conn.execute('DELETE FROM incidents WHERE seen < ?', ((datetime.now(timezone.utc) - timedelta(days=366)).isoformat(),))
    with LOCK:
        STATE = dict(sources=[h for h, _ in results], updatedAt=now(), refreshing=False)

def snapshot():
    with LOCK:
        state = json.loads(json.dumps(STATE))
    health = {s['id']: s for s in state['sources']}
    with database() as conn:
        rows = conn.execute('SELECT source,current,body FROM incidents').fetchall()
    state['incidents'] = [{**enrich(json.loads(body)), 'current': bool(current),
                           'stale': health.get(source, {}).get('state') != 'connected' or outdated(json.loads(body).get('sourceUpdatedAt'), date)} for source, current, body in rows]
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
