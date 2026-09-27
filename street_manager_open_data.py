"""Collector for the separately deployed Street Manager Open Data receiver."""
import json, os, urllib.request

def _value(row, *names):
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None

def collect_street_manager_open_data(source, make_event, parse_date):
    url = os.getenv("STREET_MANAGER_WEBHOOK_URL", "").rstrip("/")
    token = os.getenv("STREET_MANAGER_WEBHOOK_TOKEN", "")
    if not url or not token:
        raise RuntimeError("Street Manager Open Data receiver is not configured")
    request = urllib.request.Request(url + "/api/events?limit=5000", headers={
        "Accept": "application/json",
        "Authorization": "Bearer " + token,
        "User-Agent": "UK-Outage-Viewer/1.0",
    })
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("Street Manager Open Data response exceeds 8 MB limit")
    payload = json.loads(raw)
    rows = payload.get("events")
    if not isinstance(rows, list):
        raise ValueError("Street Manager Open Data response has no events array")

    records = []
    object_types = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        data = row.get("object_data") or {}
        object_type = str(row.get("object_type") or "STREET_WORKS").upper()
        object_types.add(object_type)
        work_reference = _value(data, "work_reference_number")
        object_reference = row.get("object_reference")
        event_reference = row.get("event_reference") or object_reference or row.get("event_time")
        identity = event_reference or work_reference
        if not identity:
            continue
        promoter = _value(data, "promoter_organisation", "promoter_organisation_name")
        street = _value(data, "street_name", "area_name", "town")
        category = _value(data, "work_category")
        traffic = _value(data, "traffic_management_type")
        status = _value(data, "work_status", "status") or row.get("event_type") or "roadworks-update"
        object_label = object_type.replace("_", " ").title()
        title = f"Street Manager {object_label} · " + str(row.get("event_type") or "update").replace("_", " ").title()
        if promoter:
            title += " · " + str(promoter)
        bits = [item for item in [
            f"Street: {street}" if street else None,
            f"Town: {data.get('town')}" if data.get("town") else None,
            f"Category: {category}" if category else None,
            f"Traffic management: {traffic}" if traffic else None,
        ] if item]
        item = make_event(
            source, identity, title, row.get("event_time"), status,
            f"Street Manager Open Data {object_label} event. " + ". ".join(bits),
            source["website"], region=street or data.get("town") or source["scope"],
        )
        item.update(
            evidenceType="roadworks-context",
            objectType=object_type,
            objectReference=object_reference,
            workReferenceNumber=work_reference,
            permitReferenceNumber=data.get("permit_reference_number"),
            promoter=promoter,
            workCategory=category,
            trafficManagementType=traffic,
            usrn=data.get("usrn"),
            eventType=row.get("event_type"),
            attribution="Department for Transport Street Manager Open Data",
        )
        records.append(item)
    return list({record["id"]: record for record in records}.values()), {
        "coverage": "Street Manager Open Data permit, activity and Section 58 notifications received by the configured webhook.",
        "scannedCount": len(rows),
        "objectTypes": sorted(object_types),
    }
