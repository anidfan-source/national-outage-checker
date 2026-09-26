"""Build approximate town-based associations, NOT telephone coverage boundaries.
Uses Ofcom's area-code table and GeoNames postal data. See reference/README.md.
"""
from collections import defaultdict
from datetime import date
import html
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OFCOM = 'https://www.ofcom.org.uk/phones-and-broadband/phone-numbers/telephone-area-codes-tool'
POSTAL = 'https://download.geonames.org/export/zip/GB.zip'

def download(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=30).read()

def normal(value):
    value = value.casefold().replace('saint ', 'st ').replace('&', 'and')
    return re.sub(r'[^a-z0-9]', '', value)

def build(ofcom, postal):
    places = defaultdict(list)
    districts = defaultdict(list)
    for line in postal.splitlines():
        parts = line.split('\t')
        if len(parts) < 11:
            continue
        row = dict(district=parts[1], place=parts[2], context=' '.join(parts[3:9]), lat=float(parts[9]), lng=float(parts[10]))
        places[normal(row['place'])].append(row)
        districts[row['district']].append(row)
    # Place-name aliases only: postcode associations still come from postal records.
    aliases = {'Tyneside':'Newcastle upon Tyne', 'Medway':'Chatham', 
               'Blandford':'Blandford Forum', 'Grays Thurrock':'Grays', 'Bishops Stortford':"Bishop's Stortford",
               'Kings Lynn':"King's Lynn", 'Isle of Wight':'Newport', 'Isles of Scilly':'Hugh Town'}
    qualifiers = {'Ashford (Kent)':'Kent', 'Bangor (Gwynedd)':'Wales', 'Alford (Lincs)':'Lincolnshire',
                  'Alford (Aberdeen)':'Scotland', 'Bangor (Co. Down)':'Northern Ireland',
                  'Newcastle (Co. Down)':'Northern Ireland', 'Isle of Wight':'Isle of Wight',
                  'Newport':'Wales', 'Richmond':'North Yorkshire', 'Whitchurch':'Shropshire',
                  'Saintfield':'Northern Ireland'}
    # Disambiguate common names using the postcode area of the Ofcom locality.
    area_hints = {'Leeds':'LS', 'Nottingham':'NG', 'Bolton':'BL', 'Cambridge':'CB',
        'Barnsley':'S', 'Canterbury':'CT', 'Chesterfield':'S', 'Chippenham':'SN',
        'Blackburn':'BB', 'Cromer':'NR', 'Basildon':'SS', 'Brighton':'BN', 'Bradford':'BD',
        'Crawley':'RH', 'Buxton':'SK', 'Dorchester':'DT', 'Eastbourne':'BN',
        'Bracknell':'RG', 'Ely':'CB', 'Dudley':'DY', 'Horsham':'RH', 'Alton':'GU',
        'Barry':'CF', 'Hungerford':'RG', 'Luton':'LU', 'Newport':'NP', 'Newmarket':'CB',
        'Bridgend':'CF', 'New Mills':'SK', 'Coleshill':'B', 'Brampton':'CA',
        'Romford':'RM', 'Redhill':'RH', 'Newquay':'TR', 'Whitchurch':'SY', 'Sunderland':'SR'}
    codes = {}
    for code, raw in re.findall(r'<th[^>]*>\s*(0[12]\d{1,5})\s*</th>\s*<td[^>]*>(.*?)</td>', ofcom, re.S):
        town = html.unescape(re.sub('<[^>]+>', '', raw)).strip()
        if 'cost of calling' in town:
            continue
        lookup = aliases.get(town, re.sub(r'\s*\([^)]*\)', '', town))
        if ' - ' in lookup:
            lookup = lookup.split(' - ')[-1]
        rows = places.get(normal(lookup), [])
        if code.startswith('028'):
            rows = [r for r in rows if r['district'].startswith('BT')]
        if town in qualifiers:
            rows = [r for r in rows if qualifiers[town].casefold() in r['context'].casefold()]
        if town in area_hints:
            rows = [r for r in rows if re.match('[A-Z]+',r['district'])[0] == area_hints[town]]
        # Refuse homonymous towns far apart. Never average unrelated places.
        if rows and (max(r['lat'] for r in rows)-min(r['lat'] for r in rows) > .45 or
                     max(r['lng'] for r in rows)-min(r['lng'] for r in rows) > .7):
            rows = []
        codes[code] = dict(code=code, place=town,
            postcodeAreas=sorted({re.match('[A-Z]+',r['district'])[0] for r in rows}),
            postcodeDistricts=sorted({r['district'] for r in rows}),
            lat=round(sum(r['lat'] for r in rows)/len(rows),5) if rows else None,
            lng=round(sum(r['lng'] for r in rows)/len(rows),5) if rows else None,
            method='town-name association' if rows else 'unmapped')
    # London's named postal districts use local neighbourhood names in GeoNames.
    # These are associations with London postal areas, not the full 020 footprint.
    codes['020']['postcodeAreas'] = ['E','EC','N','NW','SE','SW','W','WC']
    codes['020']['postcodeDistricts'] = sorted(k for k in districts if re.match('[A-Z]+',k)[0] in codes['020']['postcodeAreas'])
    # Codes whose Ofcom table uses finer number prefixes: retain all candidate places.
    for prefix in ['0191','023','028'] + sorted({c[:5] for c in codes if len(c)==6}):
        if prefix in codes:
            continue
        children = [v for k,v in codes.items() if k.startswith(prefix)]
        if not children:
            continue
        codes[prefix] = dict(code=prefix, place=' / '.join(sorted({r['place'] for r in children})),
            postcodeAreas=sorted({p for r in children for p in r['postcodeAreas']}),
            postcodeDistricts=sorted({p for r in children for p in r['postcodeDistricts']}),
            lat=None, lng=None, method='shared code; multiple places', children=[r['code'] for r in children])
    outcodes = {k:dict(lat=round(sum(r['lat'] for r in rows)/len(rows),5),
                      lng=round(sum(r['lng'] for r in rows)/len(rows),5)) for k,rows in districts.items()}
    if len(codes)<700 or len(outcodes)<2000:
        raise ValueError('Unexpected reference coverage; inspect upstream schema')
    return dict(generatedAt=date.today().isoformat(), sources=[OFCOM,POSTAL],
                method='Approximate association via named place, not a coverage crosswalk',
                codes=codes, districts=outcodes)

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--ofcom-html',type=Path)
    parser.add_argument('--postal-text',type=Path)
    args=parser.parse_args()
    ofcom=args.ofcom_html.read_text() if args.ofcom_html else download(OFCOM).decode()
    postal=args.postal_text.read_text() if args.postal_text else zipfile.ZipFile(io.BytesIO(download(POSTAL))).read('GB.txt').decode()
    data=build(ofcom,postal)
    (ROOT/'reference'/'uk_locations.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(len(data['codes']),'telephone prefixes;',sum(bool(x['postcodeAreas']) for x in data['codes'].values()),'with postcode associations;',len(data['districts']),'postcode districts')
