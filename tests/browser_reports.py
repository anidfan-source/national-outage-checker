"""Optional browser regression checks. Run with Playwright installed and server on :8000."""
import csv
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from locations import enrich
from playwright.sync_api import sync_playwright

payload=json.load(urllib.request.urlopen('http://localhost:8000/api/dashboard'))
now=datetime.now(timezone.utc).isoformat()
rows=[]
for i in range(61):
    rows.append(enrich(dict(id=str(i),sourceId='ssen',provider='Test provider',category='electricity',
        title=' =HYPERLINK("https://example.com","formula")' if i==0 else 'Power cut',
        description='Quoted "text", comma\nand newline — café',region='LS1 1AA',lat=None,lng=None,
        date=now,observedAt=now,status='reported',current=True,stale=False,evidenceType='provider-report',url='https://example.com')))
rows.append({**rows[1],'id':'old','date':(datetime.now(timezone.utc)-timedelta(days=60)).isoformat()})
payload['incidents']=rows
payload['updatedAt']=now
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    offline=[False]
    page.route('**/api/dashboard',lambda route:route.abort() if offline[0] else route.fulfill(json=payload))
    page.goto('http://localhost:8000',wait_until='networkidle')
    assert page.locator('.incident-card').count()==50
    page.fill('#locationFilter','0113')
    with page.expect_download() as download:page.click('#exportJson')
    report=json.loads(Path(download.value.path()).read_text())
    assert report['summary']['recordCount']==62
    assert len(report['incidents'])==62
    assert report['filters']['location']=='0113'
    assert len(report['sources'])==len(payload['sources'])
    assert report['incidents'][0]['locationPoints'][0]['method']=='postcode-district'
    with page.expect_download() as download:page.click('#exportCsv')
    raw=Path(download.value.path()).read_text(encoding='utf-8-sig')
    csv_rows=list(csv.DictReader(io.StringIO(raw)))
    incident_rows=[r for r in csv_rows if r['record_type']=='incident']
    assert len(incident_rows)==62
    assert next(r for r in incident_rows if r['id']=='0')['title'].startswith("' =")
    assert incident_rows[1]['description']=='Quoted "text", comma\nand newline — café'
    assert len([r for r in csv_rows if r['record_type']=='source'])==len(payload['sources'])
    page.click('#liveToggle')
    page.select_option('#viewMode','day')
    with page.expect_download() as download:page.click('#exportJson')
    report=json.loads(Path(download.value.path()).read_text())
    assert report['summary']['recordCount']==61
    assert report['filters']['timeWindow']=='last 30 calendar days'
    page.fill('#search','nonexistent-result')
    with page.expect_download() as download:page.click('#exportCsv')
    empty=list(csv.DictReader(io.StringIO(Path(download.value.path()).read_text(encoding='utf-8-sig'))))
    assert empty[0]['record_count']=='0'
    assert not any(r['record_type']=='incident' for r in empty)
    page.fill('#search','')
    offline[0]=True
    page.evaluate('load()')
    with page.expect_download() as download:page.click('#exportJson')
    report=json.loads(Path(download.value.path()).read_text())
    assert report['backendAvailable'] is False
    assert all(x['stale'] for x in report['incidents'])
    assert any(x['state']=='backend-offline' for x in report['sources'])
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    print('PASS: CSV/JSON downloads, full pagination, filter parity, daily history, formula escaping, Unicode/newlines, zero results, offline state, mobile layout')
    browser.close()
