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

def _is_telecom_record(data):
    fields=[
        _value(data,'promoter_organisation','promoter_organisation_name','promoter_name'),
        _value(data,'work_description','description','activity_type','work_type','work_category'),
    ]
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
    for name in names:
        if row.get(name) not in (None,""): return row[name]
    return None

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
        data=row.get("object_data") or {}
        wrn=_value(data,"work_reference_number") or row.get("object_reference")
        if not wrn: continue
        event_type=row.get("event_type")
        if _is_cancelled(data,event_type): continue
        if not _is_telecom_record(data): continue
        event_ref=row.get("event_reference") or row.get("object_reference") or row.get("event_time")
        promoter=_value(data,"promoter_organisation","promoter_organisation_name")
        street=_value(data,"street_name","area_name","town")
        category=_value(data,"work_category")
        traffic=_value(data,"traffic_management_type")
        status=_display_status(data,event_type)
        proposed_start=_value(data,"proposed_start_time","proposed_start_date","start_time","start_date")
        proposed_end=_value(data,"proposed_end_time","proposed_end_date","end_time","end_date")
        actual_start=_value(data,"actual_start_date_time")
        actual_end=_value(data,"actual_end_date_time")
        title="Telecom street works · "+str(event_type or "update").replace("_"," ").title()
        if promoter: title += " · "+str(promoter)
        bits=[x for x in [
            f"Street: {street}" if street else None,
            f"Town: {data.get('town')}" if data.get("town") else None,
            f"Category: {category}" if category else None,
            f"Traffic management: {traffic}" if traffic else None,
        ] if x]
        item=make_event(source,event_ref,title,row.get("event_time"),status,
                        "Street Manager Open Data Permit event. "+". ".join(bits),
                        source["website"],region=street or data.get("town") or source["scope"])
        item.update(evidenceType="roadworks-context",workReferenceNumber=wrn,
                    permitReferenceNumber=data.get("permit_reference_number"),
                    promoter=promoter,workCategory=category,trafficManagementType=traffic,
                    usrn=data.get("usrn"),eventType=event_type,
                    raisedAt=row.get("event_time"),
                    proposedStartAt=proposed_start,proposedEndAt=proposed_end,
                    actualStartAt=actual_start,actualEndAt=actual_end,
                    attribution="Department for Transport Street Manager Open Data")
        records.append(item)
    return list({r["id"]:r for r in records}.values()),{
        "coverage":"Street Manager Open Data Permit notifications received by the configured webhook.",
        "scannedCount":len(rows)}
