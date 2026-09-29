"""Roadworks collectors for Scotland (SRWR) and Wales (Traffic Wales)."""
import csv, hashlib, html, io, re, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET, zipfile

TELECOM_TERMS=(
    "telecom","broadband","fibre","fiber","openreach","bt","virgin media","cityfibre",
    "vodafone","hyperoptic","gigaclear","community fibre","talktalk","telefonica","o2",
)
SRWR_PAGE="https://downloads.srwr.scot/disruptions-export"
SRWR_CACHE_SECONDS=900
SRWR_CACHE={"expires":0.0,"records":None,"details":None}

def _clean(value):
    return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",str(value or "")))).strip()

def _norm(value):
    return re.sub(r"[^a-z0-9]+"," ",str(value or "").casefold()).strip()

def _pick(row,*names):
    norm={_norm(k).replace(" ","_"):v for k,v in row.items()}
    for name in names:
        value=norm.get(_norm(name).replace(" ","_"))
        if value not in (None,""): return value
    return None

def _telecom(row):
    text=_norm(" ".join(str(v or "") for v in row.values()))
    return any(term in text for term in TELECOM_TERMS)

def _download(url,accept="*/*",limit=20_000_000):
    req=urllib.request.Request(url,headers={"User-Agent":"UK-Outage-Viewer/1.0","Accept":accept})
    with urllib.request.urlopen(req,timeout=25) as response: raw=response.read(limit+1)
    if len(raw)>limit: raise ValueError("Roadworks feed exceeds download limit")
    return raw

def _srwr_zip_url():
    api=SRWR_PAGE.rstrip('/')+"/api/v1/files"
    payload=__import__('json').loads(_download(api,"application/json"))
    files=payload.get("files") if isinstance(payload,dict) else None
    if not isinstance(files,list) or not files or not files[0].get("name"):
        raise ValueError("SRWR disruptions export file list is empty")
    name=files[0]["name"]
    file_payload=__import__('json').loads(_download(SRWR_PAGE.rstrip('/')+"/api/v1/file/"+urllib.parse.quote(name),"application/json"))
    url=file_payload.get("url") if isinstance(file_payload,dict) else None
    if not url: raise ValueError("SRWR disruptions export download URL was not returned")
    return url

def _compact_source_fields(row,max_fields=40,max_chars=12000):
    values=[]
    for key,value in row.items():
        cleaned=_clean(value)
        if not cleaned: continue
        label=_clean(key)
        priority=bool(re.search(r"promoter|reference|description|location|street|town|status|start|end|date|permit|traffic|work|activity|coordinate|latitude|longitude|usrn",label,re.I))
        values.append((not priority,label,cleaned))
    values.sort(key=lambda item:(item[0],item[1].casefold()))
    result={}; used=0
    for _,label,value in values:
        if len(result)>=max_fields or used+len(value)>max_chars: break
        result[label]=value[:4000]
        used+=len(value)
    return result

def collect_srwr(source,make_event,parse_date):
    cached=SRWR_CACHE
    if cached["records"] is not None and cached["expires"]>time.monotonic():
        return cached["records"],cached["details"]
    raw=_download(_srwr_zip_url(),"application/zip",80_000_000)
    records=[]; scanned=0
    csv.field_size_limit(10_000_000)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".csv"): continue
            with archive.open(name) as fh:
                reader=csv.DictReader(io.TextIOWrapper(fh,encoding="utf-8-sig",errors="replace"))
                for row in reader:
                    scanned+=1
                    if not _telecom(row): continue
                    status=_pick(row,"works status","work status","status") or "roadworks"
                    if any(x in _norm(status) for x in ("cancelled","canceled","complete","completed")): continue
                    promoter=_pick(row,"promoter organisation","promoter","organisation","undertaker") or "Telecom roadworks"
                    ref=_pick(row,"promoter reference","works reference","work reference","reference") or hashlib.sha256(str(row).encode()).hexdigest()
                    start=_pick(row,"start","start date","proposed start","actual start")
                    end=_pick(row,"end","end date","proposed end","expected end")
                    street=_pick(row,"street","street name","location","location description","address")
                    town=_pick(row,"town","locality","area")
                    desc=_pick(row,"description","works description","work description","activity description") or ""
                    item=make_event(source,ref,f"Telecom road works · {promoter}",start,status,
                        ". ".join(x for x in (street,town,desc) if x),source["website"],region=town or street or "Scotland")
                    source_fields=_compact_source_fields(row)
                    item.update(evidenceType="roadworks-context",promoter=promoter,workReferenceNumber=ref,
                        locationDescription=" · ".join(x for x in (street,town) if x),
                        workDescription=desc, proposedStartAt=start,proposedEndAt=end,
                        sourceFields=source_fields,
                        attribution="Scottish Road Works Register (SRWR)")
                    records.append(item)
    details={"coverage":"Scotland SRWR Disruptions Export; telecom-related current road works only.","scannedCount":scanned,"retainedCount":len(records),"cacheSeconds":SRWR_CACHE_SECONDS}
    cached["records"]=records
    cached["details"]=details
    cached["expires"]=time.monotonic()+SRWR_CACHE_SECONDS
    return records,details

def collect_traffic_wales(source,make_event,parse_date):
    raw=_download(source["url"],"application/rss+xml, application/xml, text/xml")
    root=ET.fromstring(raw); records=[]
    for node in root.findall(".//item"):
        def field(name):
            child=node.find(name); return "".join(child.itertext()).strip() if child is not None else ""
        title=_clean(field("title")); desc=_clean(field("description"))
        link=field("link"); guid=field("guid") or link or hashlib.sha256(title.encode()).hexdigest()
        published=field("pubDate")
        combined=f"{title} {desc}"
        start=re.search(r"\bStart\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",combined,re.I)
        end=re.search(r"\bEnd\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",combined,re.I)
        item=make_event(source,guid,title,published,"roadworks",desc,link,region="Wales trunk-road network")
        item.update(evidenceType="roadworks-context",proposedStartAt=start.group(1) if start else None,
                    proposedEndAt=end.group(1) if end else None,attribution="Traffic Wales")
        records.append(item)
    return records,{"coverage":"Traffic Wales major roadworks on the Welsh motorway and trunk-road network.","scannedCount":len(records)}
