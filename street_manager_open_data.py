"""Collector for the separately deployed Street Manager Open Data receiver."""
import json, os, re, urllib.request

TELECOM_TERMS=(
    'telecom','telecommunications','broadband','fibre','fiber','internet','network','cable',
    'openreach','bt','virgin media','virginmedia','cityfibre','city fibre','vodafone','voneus',
    'hyperoptic','gigaclear','community fibre','communityfibre','zzoomm','giganet','toob',
    'talktalk','sky','o2','telefonica','three','ee','mobile','isp'
)
CANCELLED_TERMS=('cancelled','canceled','permit_cancelled','permit_canceled')
ACTIVE_TERMS=('in progress','in_progress','in-progress','started','active','works started','work started')

def _normalise(value):
    return re.sub(r'[^a-z0-9]+',' ',str(value or '').casefold()).strip()

def _key(value):
    spaced=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',str(value or ''))
    return re.sub(r'[^a-z0-9]+','_',spaced.casefold()).strip('_')

def _row_data(row):
    data=row.get('object_data') or row
    if isinstance(data,str):
        try: data=json.loads(data)
        except (TypeError,ValueError): data={}
    return data if isinstance(data,dict) else row

def _is_telecom_record(data):
    fields=[
        _value(data,'promoter_organisation','promoter_organisation_name','promoter_name','organisation_name','promoter'),
        _value(data,'work_description','works_description','description','activity_type','work_type','work_category','activity_description'),
    ]
    if not any(fields):
        fields=[value for value in data.values() if isinstance(value,(str,int,float))]
    haystack=' '.join(_normalise(value) for value in fields if value)
    return any(term in haystack for term in TELECOM_TERMS)

def _is_cancelled(data,event_type):
    values=[_value(data,'work_status','permit_status','status','permit_event'),event_type]
    haystack=' '.join(_normalise(value) for value in values if value)
    return any(_normalise(term) in haystack for term in CANCELLED_TERMS)

def _display_status(data,event_type):
    raw=_value(data,'work_status','permit_status','status') or event_type or 'roadworks-update'
    normal=_normalise(raw)
    if any(_normalise(term) in normal for term in ACTIVE_TERMS): return 'in progress'
    return raw

def _value(row,*names):
    if not isinstance(row,dict): return None
    by_key={_key(k):v for k,v in row.items()}
    for name in names:
        value=by_key.get(_key(name))
        if value not in (None,""): return value
    return None

def _first_value(data,row,*names):
    return _value(data,*names) or _value(row,*names)

def _text(value):
    if isinstance(value,(dict,list,tuple)): return None
    text=str(value or '').strip()
    return text or None

def _coordinates(data,row):
    lat=_first_value(data,row,'latitude','lat','location_latitude','start_latitude','latitude_value')
    lng=_first_value(data,row,'longitude','lng','lon','location_longitude','start_longitude','longitude_value')
    if lat not in (None,'') and lng not in (None,''):
        try:
            lat,lng=float(lat),float(lng)
            if -90 <= lat <= 90 and -180 <= lng <= 180: return lat,lng
        except (TypeError,ValueError): pass
    for container_name in ('location','coordinates','geometry','point','site_location','work_location'):
        container=_value(data,container_name) or _value(row,container_name)
        if isinstance(container,dict):
            nested_lat=_value(container,'latitude','lat')
            nested_lng=_value(container,'longitude','lng','lon')
            if nested_lat not in (None,'') and nested_lng not in (None,''):
                try:
                    nested_lat,nested_lng=float(nested_lat),float(nested_lng)
                    if -90 <= nested_lat <= 90 and -180 <= nested_lng <= 180:
                        return nested_lat,nested_lng
                except (TypeError,ValueError): pass
            pair=_value(container,'coordinates')
            if isinstance(pair,(list,tuple)) and len(pair) >= 2:
                try:
                    first,second=float(pair[0]),float(pair[1])
                    if -180 <= first <= 180 and -90 <= second <= 90: return second,first
                    if -90 <= first <= 90 and -180 <= second <= 180: return first,second
                except (TypeError,ValueError): pass
        elif isinstance(container,(list,tuple)) and len(container) >= 2:
            try:
                first,second=float(container[0]),float(container[1])
                if -180 <= first <= 180 and -90 <= second <= 90: return second,first
                if -90 <= first <= 90 and -180 <= second <= 180: return first,second
            except (TypeError,ValueError): pass
    return None,None

def collect_street_manager_open_data(source,make_event,parse_date):
    url=os.getenv("STREET_MANAGER_WEBHOOK_URL","").rstrip("/")
    token=os.getenv("STREET_MANAGER_WEBHOOK_TOKEN","")
    if not url or not token:
        raise RuntimeError("Street Manager Open Data receiver is not configured")
    req=urllib.request.Request(url+"/api/events?limit=5000",headers={
        "Accept":"application/json","Authorization":"Bearer "+token,
        "User-Agent":"UK-Outage-Viewer/1.0"})
    with urllib.request.urlopen(req,timeout=18) as response:
        raw=response.read(8_000_001)
    if len(raw)>8_000_000: raise ValueError("Street Manager Open Data response exceeds 8 MB limit")
    payload=json.loads(raw)
    rows=payload.get("events")
    if not isinstance(rows,list): raise ValueError("Street Manager Open Data response has no events array")
    records=[]
    for row in rows:
        data=_row_data(row)
        wrn=_first_value(data,row,"work_reference_number","work_reference","works_reference","reference","activity_reference","object_reference")
        if not wrn: continue
        event_type=_first_value(row,data,"event_type","event_name","permit_event")
        if _is_cancelled(data,event_type): continue
        if not _is_telecom_record(data): continue
        event_ref=_first_value(row,data,"event_reference","event_id","object_reference","event_time")
        promoter=_first_value(data,row,"promoter_organisation","promoter_organisation_name","works_promoter_name","promoter_name","organisation_name","promoter")
        detailed_location=_first_value(data,row,"detailed_location","location_description","location","site_location","works_location","location_text","road_name","address")
        street=_first_value(data,row,"street_name","street","road_name")
        locality=_first_value(data,row,"locality","area_name","district","place")
        town=_first_value(data,row,"town","town_name","city")
        category=_first_value(data,row,"work_category","work_type","activity_type")
        traffic=_first_value(data,row,"traffic_management_type","traffic_management","traffic_management_description")
        status=_display_status(data,event_type)
        proposed_start=_first_value(data,row,"proposed_start_time","proposed_start_date","start_time","start_date")
        proposed_end=_first_value(data,row,"proposed_end_time","proposed_end_date","end_time","end_date")
        actual_start=_first_value(data,row,"actual_start_date_time","actual_start","work_start_date")
        actual_end=_first_value(data,row,"actual_end_date_time","actual_end","work_end_date")
        description=_first_value(data,row,"work_description","works_description","description","activity_description")
        lat,lng=_coordinates(data,row)
        title="Telecom street works · "+str(event_type or "update").replace("_"," ").title()
        if promoter: title += " · "+str(promoter)
        location_parts=[]
        for value in (detailed_location,street,locality,town):
            value=_text(value)
            if value and value not in location_parts: location_parts.append(value)
        bits=[x for x in [
            f"Location: {detailed_location}" if _text(detailed_location) else None,
            f"Street: {street}" if _text(street) else None,
            f"Locality: {locality}" if _text(locality) else None,
            f"Town: {town}" if _text(town) else None,
            f"Category: {category}" if category else None,
            f"Traffic management: {traffic}" if traffic else None,
            f"Description: {description}" if description else None,
        ] if x]
        event_time=_first_value(row,data,"event_time","event_timestamp","created_at")
        item=make_event(source,event_ref,title,event_time,status,
                        "Street Manager Open Data Permit event. "+". ".join(bits),
                        source["website"],lat=lat,lng=lng,
                        region=town or locality or street or detailed_location or source["scope"])
        item.update(evidenceType="roadworks-context",workReferenceNumber=wrn,
                    locationDescription=" · ".join(location_parts),
                    permitReferenceNumber=_first_value(data,row,"permit_reference_number","permit_reference"),
                    promoter=promoter,workCategory=category,trafficManagementType=traffic,
                    usrn=_first_value(data,row,"usrn","usrn_reference"),eventType=event_type,
                    street=street,locality=locality,town=town,
                    latitude=lat,longitude=lng,
                    locationSource="source-coordinates" if lat is not None and lng is not None else "source-text",
                    raisedAt=event_time,
                    proposedStartAt=proposed_start,proposedEndAt=proposed_end,
                    actualStartAt=actual_start,actualEndAt=actual_end,
                    attribution="Department for Transport Street Manager Open Data")
        records.append(item)
    return list({r["id"]:r for r in records}.values()),{
        "coverage":"Street Manager Open Data Permit notifications received by the configured webhook.",
        "scannedCount":len(rows)}
