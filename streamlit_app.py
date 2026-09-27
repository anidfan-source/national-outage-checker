"""Multi-page Streamlit front end. Run with: streamlit run streamlit_app.py"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
import re

import pydeck as pdk
import streamlit as st
import server
from historic_flood import fetch_historic_flood_warnings
from historic_weather import fetch_historic_weather_warnings
from reporting import LIMITATIONS, csv_bytes, report

st.set_page_config(page_title='UK Outage Viewer', page_icon='⚡', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
[data-testid="stMetric"] {background:#f7f9fc;border:1px solid #e4e9f1;border-radius:14px;padding:12px}
[data-testid="stMetric"] [data-testid="stMetricLabel"], [data-testid="stMetric"] [data-testid="stMetricValue"] {color:#101828!important}
[data-testid="stSidebar"] {background:#101828} [data-testid="stSidebar"] * {color:#f8fafc}
.eyebrow {color:#087f5b;font-weight:700;letter-spacing:.08em;font-size:.75rem;text-transform:uppercase}
</style>''', unsafe_allow_html=True)

CATEGORY_LABELS = {'broadband':'Broadband & mobile backup','electricity':'Power cuts','third-party':'Cloud, DNS & apps','environment':'Weather & flood risk','routing':'Routing & internet signals'}
CLOSED = {'resolved','completed','postmortem'}

def street_manager_configured():
    """Return True when the Street Manager Open Data receiver is configured."""
    try:
        cfg = st.secrets.get('street_manager', {})
        url = cfg.get('webhook_url')
        token = cfg.get('webhook_token')
    except Exception:
        url = token = None
    url = url or os.getenv('STREET_MANAGER_WEBHOOK_URL')
    token = token or os.getenv('STREET_MANAGER_WEBHOOK_TOKEN')
    return bool(url and token)

def configure_street_manager():
    """Expose the Open Data receiver configuration to the collector process."""
    try:
        cfg = st.secrets.get('street_manager', {})
        if cfg.get('webhook_url'): os.environ['STREET_MANAGER_WEBHOOK_URL'] = str(cfg['webhook_url']).rstrip('/')
        if cfg.get('webhook_token'): os.environ['STREET_MANAGER_WEBHOOK_TOKEN'] = str(cfg['webhook_token'])
    except Exception:
        pass

@st.cache_data(ttl=120, show_spinner='Refreshing public outage feeds…')
def load_dashboard():
    """Refresh the collectors and return a consistent dashboard snapshot."""
    server.init_db()
    server.refresh()
    return server.snapshot()

@st.cache_data(ttl=3600, show_spinner=False)
def load_historic_flood_warnings():
    return fetch_historic_flood_warnings()

@st.cache_data(ttl=3600, show_spinner=False)
def load_historic_weather_warnings():
    return fetch_historic_weather_warnings()

def text(value): return str(value or '').casefold()

def selected_location(value, reference):
    query=value.strip().upper()
    if not query: return None, ''
    normal=query.replace(' ','').replace('(','').replace(')','').replace('-','')
    if normal.startswith('+44'): normal='0'+normal[3:].lstrip('0')
    if normal.startswith('0044'): normal='0'+normal[4:].lstrip('0')
    code=next((entry for entry in reference.get('codes',[]) if entry['code']==normal),None)
    if code: return {'code':normal,'areas':code['postcodeAreas']}, f"{normal} · {code['place']} → {', '.join(code['postcodeAreas']) or 'postcode association unavailable'} (approximate)"
    match=re.match(r'^([A-Z]{1,2})(?:\d[A-Z\d]?(?:\d[A-Z]{2})?)?$',query.replace(' ',''))
    if match: return {'code':None,'areas':[match.group(1)]}, f'Postcode area {match.group(1)} · not a household match'
    return {'code':None,'areas':[]}, 'Enter 0113, LS, or a postcode.'

def location_match(item, selection):
    if not selection: return True
    if selection['code'] and any(code.get('code')==selection['code'] for code in item.get('telephoneAreas',[])): return True
    return any(area in selection['areas'] for area in item.get('postcodeAreas',[]))

def filtered_incidents(data, categories, provider, location, query, mode, since):
    records=[]
    for item in data['incidents']:
        if item.get('category') not in categories or (provider!='All providers' and item.get('sourceId')!=provider): continue
        searchable=' '.join([text(item.get(key)) for key in ('title','provider','region','description')]+[text(v) for v in item.get('postcodeAreas',[])]+[text(x.get('code'))+' '+text(x.get('place')) for x in item.get('telephoneAreas',[])])
        if (query and query.casefold() not in searchable) or not location_match(item,location): continue
        if mode=='Live' and not (item.get('current') and item.get('status') not in CLOSED): continue
        if mode=='History':
            try:
                if not item.get('date') or datetime.fromisoformat(item['date'])<since: continue
            except ValueError: continue
        records.append(item)
    return sorted(records,key=lambda x:x.get('date') or x.get('observedAt') or '',reverse=True)

def filename(extension): return 'uk-outage-report-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.'+extension

def filters(data, page_categories=None):
    names={source['id']:source['name'] for source in data['sources']}
    _,view_control,_=st.columns((1,2,1))
    with view_control:
        st.caption('SHOW INCIDENTS')
        mode=st.segmented_control('View mode',['Live','History'],default='Live',selection_mode='single',key='global_view_mode',label_visibility='collapsed') or 'Live'
    with st.sidebar:
        st.caption('NATIONAL OUTAGE CHECKER'); st.header('Explore incidents')
        location_query=st.text_input('Location',placeholder='0113, LS or LS1 1AA',help='Matches reported postcode areas and approximate dialling-code areas.')
        location,message=selected_location(location_query,data['locationReference'])
        if message: st.caption(message)
        query=st.text_input('Find a provider or issue',placeholder='Power cut, Zen, rain…')
        days=st.slider('History days',1,365,30,disabled=mode=='Live',help='Choose History above to search earlier notices.')
        available=page_categories or list(CATEGORY_LABELS)
        categories=st.multiselect('Evidence types',available,default=available,format_func=CATEGORY_LABELS.get)
        provider=st.selectbox('Provider',['All providers']+list(names),format_func=lambda x:names.get(x,x))
        if st.button('Refresh feeds',use_container_width=True,type='primary'): load_dashboard.clear(); st.rerun()
        st.divider(); st.caption('A match is related published evidence, not a diagnosis of an individual household line.')
    now=datetime.now(timezone.utc); since=now if mode=='Live' else now.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=days-1)
    incident_data=data
    if mode=='History' and 'environment' in categories:
        try:
            incident_data={**data,'incidents':data['incidents']+load_historic_flood_warnings()+load_historic_weather_warnings()}
        except Exception as error:
            st.sidebar.warning(f'Historic environmental archive unavailable: {type(error).__name__}')
    records=filtered_incidents(incident_data,categories,provider,location,query,mode,since)
    summary={'mode':mode.lower(),'categories':categories,'provider':None if provider=='All providers' else provider,'location':location_query,'locationInterpretation':message or None,'search':query,'timeWindow':'current feed records' if mode=='Live' else f'last {days} calendar days','from':None if mode=='Live' else since.isoformat(),'through':now.isoformat()}
    return records,summary

def header(data, eyebrow, title, description):
    fresh=sum(s.get('state')=='connected' for s in data['sources'] if s.get('kind')!='portal'); stale=sum(s.get('state')=='stale' for s in data['sources'])
    st.markdown(f'<div class="eyebrow">{eyebrow}</div>',unsafe_allow_html=True); st.title(title); st.caption(description)
    st.caption(f"Updated {data.get('updatedAt') or 'not available'} · {fresh} live feeds connected · {stale} stale source{'s' if stale!=1 else ''}")

def exports(records, data, summary):
    payload=report(records,data['sources'],summary,data.get('updatedAt')); a,b=st.columns(2)
    a.download_button('Export filtered CSV',csv_bytes(payload),filename('csv'),'text/csv',use_container_width=True)
    b.download_button('Export filtered JSON',json.dumps(payload,ensure_ascii=False,indent=2),filename('json'),'application/json',use_container_width=True)

def map_records(records):
    points=[{'lat':p['lat'],'lon':p['lng'],'provider':item.get('provider'),'type':p.get('method'),'title':item.get('title')} for item in records for p in item.get('locationPoints',[]) if 49.5 <= p['lat'] <= 61.5 and -8.8 <= p['lng'] <= 2.2]
    if points:
        chart=pdk.Deck(
            initial_view_state=pdk.ViewState(latitude=54.5,longitude=-3.4,zoom=5.1,min_zoom=4.5,max_zoom=12,pitch=0),
            layers=[pdk.Layer('ScatterplotLayer',data=points,get_position='[lon, lat]',get_radius=8500,get_fill_color='[18, 104, 166, 190]',pickable=True)],
            tooltip={'html':'<b>{provider}</b><br/>{title}<br/>{type}'},
            map_style='https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
        )
        st.pydeck_chart(chart,width='stretch')
    else: st.info('No mapped locations match these filters. Provider notices without coordinates are still listed below.')

def incident_list(records, title='Published evidence'):
    st.subheader(f'{title} ({len(records)})')
    if not records: st.info('No matching records. This does not confirm normal service; inspect Source health for connection status.'); return
    for item in records:
        with st.expander(f"{item.get('provider')} · {item.get('title')}"):
            st.write(item.get('description') or 'No public description supplied.')
            st.caption(f"Status: {item.get('status')} · Reported: {item.get('date') or 'not supplied'} · Last fetched: {item.get('observedAt')}")
            if item.get('stale'): st.warning('This record is stale because its source is unavailable or its published data is old.')
            details=[]
            if item.get('evidenceType'): details.append(f"Evidence: {item['evidenceType']}")
            if item.get('reportedPostcodeAreas'): details.append('Reported areas: '+', '.join(item['reportedPostcodeAreas']))
            if item.get('telephoneAreas'): details.append('Telephone association (approximate): '+'; '.join(f"{x['code']} → {', '.join(x['postcodeAreas'])}" for x in item['telephoneAreas']))
            if item.get('customersAffected') is not None: details.append(f"Customers affected: {item['customersAffected']}")
            if item.get('estimatedRestorationAt'): details.append('Estimated restoration: '+item['estimatedRestorationAt'])
            if details: st.caption(' · '.join(details))
            if item.get('url'): st.link_button('Open source',item['url'])

def correlated_view():
    header(DATA,'Overview','UK Outage Viewer','Start with a place, then compare direct provider notices with power, weather and passive network evidence.'); records,summary=filters(DATA)
    direct=sum(item.get('evidenceType')=='provider-report' or item.get('category')=='broadband' for item in records); risks=sum(item.get('category') in ('electricity','environment') for item in records); signals=sum(item.get('evidenceType') in ('network-signal','probe-evidence') for item in records)
    for col,label,value in zip(st.columns(4),('Matching evidence','Provider reports','Power & weather context','Network signals'),(len(records),direct,risks,signals)): col.metric(label,value)
    st.subheader('What may be related'); groups=defaultdict(list)
    for item in records:
        for area in (item.get('postcodeAreas') or [item.get('region') or 'Location not supplied'])[:3]: groups[area].append(item)
    overlaps=[(area,items) for area,items in groups.items() if len({x.get('category') for x in items})>1 or len({x.get('provider') for x in items})>1]
    if overlaps:
        for area,items in sorted(overlaps,key=lambda x:len(x[1]),reverse=True)[:6]: st.info(f"**{area}** · {len(items)} matching notices across {', '.join(sorted({CATEGORY_LABELS.get(x.get('category'),x.get('category')) for x in items}))}. Review source records before attributing a cause.")
    else: st.caption('No multi-source geographic overlap is visible in the selected records.')
    left,right=st.columns((3,2))
    with left: st.subheader('Map of available locations'); st.caption('Source coordinates are preferred. Postcode, telephone and probe locations are approximate.'); map_records(records)
    with right:
        trend=Counter((x.get('date') or '')[:10] for x in records if x.get('date')); st.subheader('Notice trend')
        if trend: st.bar_chart({day:trend[day] for day in sorted(trend)})
        else: st.caption('No dated records in this selection.')
        exports(records,DATA,summary)
    incident_list(records,'All matching evidence')

def category_view(key,title,description):
    header(DATA,CATEGORY_LABELS[key],title,description); records,summary=filters(DATA,[key])
    values=(len(records),len({x.get('provider') for x in records}),len({a for x in records for a in x.get('postcodeAreas',[])}))
    for col,label,value in zip(st.columns(3),('Matching notices','Providers represented','Postcode areas mentioned'),values): col.metric(label,value)
    left,right=st.columns((3,2))
    with left: st.subheader('Locations'); map_records(records)
    with right: exports(records,DATA,summary); st.caption(LIMITATIONS)
    incident_list(records)

def sources_view():
    header(DATA,'Data quality','Sources & connection health','See what is automated, stale or only a provider portal before relying on a result.'); records,summary=filters(DATA)
    if street_manager_configured():
        st.success('Street Manager Open Data receiver is configured securely. Streamlit pulls stored events without exposing the receiver token.')
    else:
        st.info('Street Manager Open Data is not configured. Add [street_manager] webhook_url/webhook_token to Streamlit secrets or set STREET_MANAGER_WEBHOOK_URL/STREET_MANAGER_WEBHOOK_TOKEN.')
    states=Counter(s.get('state','unknown') for s in DATA['sources'])
    for col,state in zip(st.columns(4),('connected','stale','unavailable','portal-only')): col.metric(state.replace('-',' ').title(),states.get(state,0))
    exports(records,DATA,summary)
    for source in sorted(DATA['sources'],key=lambda x:(x.get('category',''),x.get('name',''))):
        with st.expander(f"{source['name']} · {source.get('state','unknown')}"):
            st.write(source.get('note') or source.get('scope')); st.caption(f"{CATEGORY_LABELS.get(source.get('category'),source.get('category'))} · {source.get('scope')}")
            st.caption(f"Last attempt: {source.get('checkedAt') or 'not attempted'} · Last success: {source.get('lastSuccess') or 'not available'}")
            if source.get('sourceUpdatedAt'): st.caption('Source updated: '+source['sourceUpdatedAt'])
            if source.get('coverage'): st.caption(source['coverage'])
            if source.get('error'): st.error(source['error'])
            if source.get('website'): st.link_button('Open provider / source',source['website'])

def broadband_view(): category_view('broadband','Broadband & provider notices','Direct provider notices and connectivity reports that may affect a home connection.')
def power_view(): category_view('electricity','Power cuts & infrastructure','Power incidents can interrupt home routers, street cabinets and local network equipment.')
def weather_view():
    header(DATA,CATEGORY_LABELS['environment'],'Weather & flood impacts','Live official warnings provide impact context for faults and access disruptions.')
    records,summary=filters(DATA,['environment'])
    if summary['mode']=='history':
        st.info('Historical results include Environment Agency flood warnings and the supplied Met Office NSWWS 2026 metadata. Met Office metadata records the original issue date, warning classification, weather type and named regions; it does not include validity times or warning geometry.')
        st.link_button('Search the Met Office historic warning archive','https://www.metoffice.gov.uk/research/library-and-archive/publications/national-severe-weather-warning-service')
    values=(len(records),len({x.get('provider') for x in records}),len({a for x in records for a in x.get('postcodeAreas',[])}))
    for col,label,value in zip(st.columns(3),('Matching notices','Providers represented','Postcode areas mentioned'),values): col.metric(label,value)
    left,right=st.columns((3,2))
    with left: st.subheader('Locations'); map_records(records)
    with right: exports(records,DATA,summary); st.caption(LIMITATIONS)
    incident_list(records)
def routing_view(): category_view('routing','Internet routing signals','Passive evidence of wider connectivity changes. These signals are not confirmed ISP outages.')
def services_view(): category_view('third-party','Online services','Cloud, DNS and application issues that can resemble a home broadband problem.')

configure_street_manager()

try: DATA=load_dashboard()
except Exception as error: st.error(f'Unable to collect feeds: {type(error).__name__}: {error}'); st.stop()

navigation=st.navigation({'Explore':[st.Page(correlated_view,title='Correlated view',icon='🔎',default=True),st.Page(broadband_view,title='Broadband',icon='📶'),st.Page(power_view,title='Power',icon='⚡'),st.Page(weather_view,title='Weather & flood',icon='🌦️'),st.Page(routing_view,title='Network signals',icon='🌐'),st.Page(services_view,title='Services',icon='☁️')],'Trust':[st.Page(sources_view,title='Source health',icon='📊')]},position='sidebar')
navigation.run()
