"""Street Manager v7 polling connector."""
from datetime import datetime, timedelta, timezone
import json, os, urllib.error, urllib.parse, urllib.request
MAX_PAGES=20
PAGE_SIZE=250

def _request(url, method='GET', body=None, token=None):
    headers={'Accept':'application/json','User-Agent':'UK-Outage-Viewer/1.0'}
    data=None
    if body is not None:
        data=json.dumps(body).encode('utf-8'); headers['Content-Type']='application/json'
    if token: headers['token']=token
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=18) as response: raw=response.read(8_000_001)
    except urllib.error.HTTPError as exc:
        error_message=''
        try:
            payload=json.loads(exc.read(16384).decode('utf-8','replace'))
            if isinstance(payload,dict):
                error_message=str(payload.get('message') or payload.get('error_description') or payload.get('error') or '')[:300]
        except Exception:
            pass
        if exc.code==401: raise RuntimeError('Street Manager authentication/access failed (401). Confirm this is an API user, not a web UI user.') from None
        if exc.code==423: raise RuntimeError('Street Manager account temporarily locked (423). Wait at least five minutes before retrying.') from None
        if exc.code==400:
            detail=f': {error_message}' if error_message else ''
            raise RuntimeError(f'Street Manager rejected the request (400){detail}') from None
        raise RuntimeError(f'Street Manager HTTP {exc.code}'+(f': {error_message}' if error_message else '')) from None
    if len(raw)>8_000_000: raise ValueError('Street Manager response exceeds 8 MB limit')
    return json.loads(raw)

def authenticate():
    username=os.getenv('STREET_MANAGER_USERNAME'); password=os.getenv('STREET_MANAGER_PASSWORD')
    if not username or not password: raise RuntimeError('Street Manager credentials are not configured')
    base=os.getenv('STREET_MANAGER_BASE_URL','https://api.manage-roadworks.service.gov.uk').rstrip('/')
    version=os.getenv('STREET_MANAGER_API_VERSION','v7').strip().lower()
    if version not in ('v6','v7','latest'): raise RuntimeError('STREET_MANAGER_API_VERSION must be v6, v7 or latest')
    result=_request(base+f'/{version}/work/authenticate','POST',{'username':username,'password':password})
    token=result.get('idToken') or result.get('id_token')
    if not token: raise ValueError('Street Manager authentication returned no ID token')
    return base,version,token,result.get('organisationReference') or result.get('organisation_reference')

def _value(row,*names):
    for name in names:
        if row.get(name) not in (None,''): return row[name]
    return None

def collect_street_manager(source,make_event,parse_date):
    base,version,token,organisation=authenticate()
    end=datetime.now(timezone.utc); start=end-timedelta(hours=11,minutes=59)
    params={'start_date':start.isoformat().replace('+00:00','Z'),'end_date':end.isoformat().replace('+00:00','Z'),'page_size':PAGE_SIZE}
    rows=[]; next_update=None
    for _ in range(MAX_PAGES):
        if next_update is not None: params={'update_id':next_update,'page_size':PAGE_SIZE}
        payload=_request(base+f'/{version}/event/works/updates?'+urllib.parse.urlencode(params),token=token)
        batch=payload.get('rows')
        if not isinstance(batch,list): raise ValueError('Street Manager updates response has no rows array')
        rows.extend(batch); next_update=payload.get('next_update')
        if next_update is None: break
    else: raise ValueError('Street Manager pagination limit reached; refusing partial snapshot')
    records=[]
    for row in rows:
        wrn=_value(row,'work_reference_number','workReferenceNumber'); update_id=_value(row,'update_id','updateId')
        if not wrn: continue
        when=_value(row,'event_date','eventDate','last_updated_date','lastUpdatedDate','created_date','createdDate')
        promoter=_value(row,'promoter_organisation_name','promoterOrganisationName','promoter_name','promoterName')
        street=_value(row,'street_name','streetName','street_descriptor','streetDescriptor')
        status=_value(row,'work_status','workStatus','status') or 'roadworks-update'
        category=_value(row,'work_category','workCategory'); traffic=_value(row,'traffic_management_type','trafficManagementType')
        title='Street works update'+(f' · {promoter}' if promoter else '')
        bits=[x for x in [f'Location: {street}' if street else None,f'Category: {category}' if category else None,f'Traffic management: {traffic}' if traffic else None] if x]
        desc='Street Manager v7 work update.'+(' '+'. '.join(bits)+'.' if bits else '')
        item=make_event(source,f'{wrn}:{update_id or when or "update"}',title,when,status,desc,source['website'],region=street or source['scope'])
        item.update(evidenceType='roadworks-context',workReferenceNumber=wrn,streetManagerUpdateId=update_id,promoter=promoter,workCategory=category,trafficManagementType=traffic,attribution='Department for Transport Street Manager')
        records.append(item)
    return list({r['id']:r for r in records}.values()),{'coverage':'Street Manager v7 work changes visible to the configured API user; preceding 12 hours.','organisationReference':organisation,'apiVersion':version,'scannedCount':len(rows)}
