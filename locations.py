"""Conservative, offline incident location enrichment from geographic evidence."""
import json
from pathlib import Path
import re
import math
import urllib.parse
import urllib.request

REFERENCE = json.loads((Path(__file__).resolve().parent/'reference'/'uk_locations.json').read_text())
CODES = REFERENCE['codes']
DISTRICTS = REFERENCE['districts']
# Only explicit geographic codes, not arbitrary full phone/contact numbers.
CODE = re.compile(r'(?<![\w+])(?:0[12]\d{1,5}|(?:\+44|0044)[ \t]*(?:\(0\)[ \t]*)?[12]\d{1,4})(?!\w)')
POSTCODE = re.compile(r'(?<![A-Z0-9])([A-Z]{1,2}\d[A-Z\d]?)(?:\s*(\d[A-Z]{2}))?(?![A-Z0-9])', re.I)
CONTEXT = re.compile(r'\b(area\s*codes?|dial(?:l?ing)?\s*codes?|STD|prefix(?:es)?|exchanges?|affected|outage|fault|incident|disruption)\b', re.I)
CONTACT = re.compile(r'\b(call|contact|helpline|helpdesk|support\s*(?:on|number|line)|fax)\b', re.I)
FULL_POSTCODE = re.compile(r'^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$', re.I)

def lookup_postcode(value):
    """Resolve one full UK postcode to its ONS geography via the open Postcodes.io API."""
    compact=re.sub(r'\s+','',str(value or '')).upper()
    match=FULL_POSTCODE.fullmatch(compact)
    if not match:
        return None
    url='https://api.postcodes.io/postcodes/'+urllib.parse.quote(compact,safe='')
    request=urllib.request.Request(url,headers={'User-Agent':'UK-Outage-Viewer/1.0','Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=8) as response:
        payload=json.loads(response.read(1_000_001))
    result=payload.get('result')
    if payload.get('status') != 200 or not isinstance(result,dict):
        return None
    return {key:result.get(key) for key in ('postcode','outcode','latitude','longitude','admin_district','admin_county','admin_ward','parish','region','country')}

def distance_km(lat1,lng1,lat2,lng2):
    """Great-circle distance used only to match already-published approximate points."""
    try:
        a,b,c,d=map(math.radians,map(float,(lat1,lng1,lat2,lng2)))
    except (TypeError,ValueError):
        return None
    value=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(value)))

def normal_code(value):
    value = re.sub(r'[\s()-]', '', value)
    if value.startswith('+44'):
        value = '0' + value[3:].removeprefix('0')
    elif value.startswith('0044'):
        value = '0' + value[4:].removeprefix('0')
    return value

def telephone_matches(text):
    result = {}
    # Newlines and sentence boundaries isolate contact footers from incident evidence.
    for clause in re.split(r'[\n;.!?]+', text):
        if not CONTEXT.search(clause) or CONTACT.search(clause) or re.search(r'\btel(?:ephone)?\s*:', clause, re.I):
            continue
        for match in CODE.finditer(clause):
            code = normal_code(match.group())
            # Reject a complete phone number split into groups after the prefix.
            suffix = clause[match.end():]
            if re.match(r'[\s)-]*\d', suffix):
                continue
            if code in CODES:
                result[code] = CODES[code]
    return list(result.values())

def enrich(item):
    # Do not search source URLs, IDs, provider names or generic source notes.
    text = '\n'.join(str(item.get(k) or '') for k in ('title','description','region'))
    phones = telephone_matches(text)
    postcode_districts = set()
    for field in ('title','description','region'):
        for clause in re.split(r'[\n;.!?]+', str(item.get(field) or '')):
            if CONTACT.search(clause):
                continue
            for match in POSTCODE.finditer(clause):
                district = match.group(1).upper()
                # Bare EC2 could be an AWS product. Require postal context or a region field.
                if district in DISTRICTS and (match.group(2) or field == 'region' or re.search(r'\bpost\s*codes?\b', clause, re.I)):
                    postcode_districts.add(district)
    postcode_districts = sorted(postcode_districts)
    reported_areas = sorted({re.match('[A-Z]+',p)[0] for p in postcode_districts})
    inferred_areas = sorted({p for phone in phones for p in phone['postcodeAreas']})
    areas = sorted(set(reported_areas + inferred_areas))
    points = []
    if item.get('lat') is not None and item.get('lng') is not None:
        points.append(dict(lat=item['lat'], lng=item['lng'], method=item.get('locationMethod', 'source'),
                           label='Approximate RIPE Atlas probe location' if item.get('locationMethod') == 'probe-location' else 'Source-supplied location'))
    elif postcode_districts:
        for district in postcode_districts:
            points.append(dict(**DISTRICTS[district], method='postcode-district',
                               label=f'Approximate postcode district: {district}'))
    else:
        seen = set()
        for phone in phones:
            # Shared parent codes keep all candidates as text; never pick a town.
            if phone['lat'] is not None and (phone['lat'],phone['lng']) not in seen:
                points.append(dict(lat=phone['lat'],lng=phone['lng'],method='telephone-area',
                    label=f"Approximate telephone locality: {phone['code']} {phone['place']}"))
                seen.add((phone['lat'],phone['lng']))
    # Conflicting evidence remains visible; it never moves a source-supplied marker.
    conflict = bool(reported_areas and inferred_areas and not set(reported_areas).intersection(inferred_areas))
    return {**item, 'telephoneAreas':phones, 'postcodeAreas':areas,
            'reportedPostcodeAreas':reported_areas, 'inferredPostcodeAreas':inferred_areas,
            'postcodeDistricts':postcode_districts, 'locationPoints':points,
            'locationConflict':conflict}

def reference_summary():
    return dict(generatedAt=REFERENCE['generatedAt'], codeCount=len(CODES),
                mappedCount=sum(bool(x['postcodeAreas']) for x in CODES.values()),
                codes=[dict(code=x['code'],place=x['place'],postcodeAreas=x['postcodeAreas']) for x in CODES.values()])

def named_place_point(*values):
    """Return a conservative point only when an explicit reference place appears in text."""
    evidence=' '.join(str(value or '') for value in values).casefold()
    candidates=[]
    for item in CODES.values():
        place=str(item.get('place') or '')
        if len(place) < 4 or item.get('lat') is None or item.get('lng') is None:
            continue
        if re.search(r'(?<![a-z])'+re.escape(place.casefold())+r'(?![a-z])', evidence):
            candidates.append(item)
    if not candidates:
        return None
    best=max(candidates,key=lambda item:len(item['place']))
    return dict(lat=best['lat'],lng=best['lng'],method='named-place',label=f"Approximate named place: {best['place']}")

