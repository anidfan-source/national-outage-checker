"""Streamlit front end. Run with: streamlit run streamlit_app.py"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.parse import urlsplit

import streamlit as st

import server
from reporting import LIMITATIONS, csv_bytes, report


st.set_page_config(page_title='UK Outage Viewer', page_icon='⚡', layout='wide')


@st.cache_data(ttl=server.INTERVAL, show_spinner='Collecting public outage feeds…')
def load_dashboard():
    """The Streamlit deployment collects directly and needs no companion HTTP server."""
    server.init_db()
    server.refresh()
    return server.snapshot()


def text(value):
    return str(value or '').casefold()


def selected_location(value, reference):
    query = value.strip().upper()
    if not query:
        return None, ''
    normalized = query.replace(' ', '').replace('(', '').replace(')', '').replace('-', '')
    if normalized.startswith('+44'):
        normalized = '0' + normalized[3:].lstrip('0')
    if normalized.startswith('0044'):
        normalized = '0' + normalized[4:].lstrip('0')
    code = next((entry for entry in reference.get('codes', []) if entry['code'] == normalized), None)
    if code:
        return {'code': normalized, 'areas': code['postcodeAreas']}, (
            f"{normalized} · {code['place']} → {', '.join(code['postcodeAreas']) or 'postcode association unavailable'} (approximate)"
        )
    import re
    match = re.match(r'^([A-Z]{1,2})(?:\d[A-Z\d]?(?:\d[A-Z]{2})?)?$', query.replace(' ', ''))
    if match:
        return {'code': None, 'areas': [match.group(1)]}, f"Postcode area {match.group(1)} · not a household match"
    return {'code': None, 'areas': []}, 'Enter a geographic code such as 0113, a postcode area such as LS, or a postcode.'


def location_match(item, selection):
    if not selection:
        return True
    if selection['code'] and any(code.get('code') == selection['code'] for code in item.get('telephoneAreas', [])):
        return True
    return any(area in selection['areas'] for area in item.get('postcodeAreas', []))


def filtered_incidents(data, categories, provider, location, query, mode, since):
    closed = {'resolved', 'completed', 'postmortem'}
    records = []
    for item in data['incidents']:
        if item.get('category') not in categories or (provider != 'All providers' and item.get('sourceId') != provider):
            continue
        searchable = ' '.join([text(item.get(key)) for key in ('title', 'provider', 'region', 'description')]
                              + [text(value) for value in item.get('postcodeAreas', [])]
                              + [text(entry.get('code')) + ' ' + text(entry.get('place')) for entry in item.get('telephoneAreas', [])])
        if query and query.casefold() not in searchable or not location_match(item, location):
            continue
        if mode == 'Live' and not (item.get('current') and item.get('status') not in closed):
            continue
        if mode == 'History':
            if not item.get('date'):
                continue
            try:
                if datetime.fromisoformat(item['date']) < since:
                    continue
            except ValueError:
                continue
        records.append(item)
    return sorted(records, key=lambda item: item.get('date') or item.get('observedAt') or '', reverse=True)


def file_name(extension):
    return 'uk-outage-report-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.' + extension


try:
    data = load_dashboard()
except Exception as error:
    st.error(f'Unable to collect feeds: {type(error).__name__}: {error}')
    st.stop()

st.title('UK Outage Viewer')
st.caption('Provider reports, power cuts and passive network evidence affecting home broadband. This is not a household connection diagnosis.')

with st.sidebar:
    st.header('Filters')
    category_labels = {'broadband': 'Broadband & mobile backup', 'electricity': 'Electricity',
                       'third-party': 'Cloud, DNS & apps', 'environment': 'Weather & flood risks',
                       'routing': 'Routing & internet exchanges'}
    categories = st.multiselect('Types', list(category_labels), default=list(category_labels), format_func=category_labels.get)
    provider_options = ['All providers'] + [source['id'] for source in data['sources']]
    provider_names = {source['id']: source['name'] for source in data['sources']}
    provider = st.selectbox('Provider', provider_options, format_func=lambda value: provider_names.get(value, value))
    location_query = st.text_input('Dialling code / postcode area', placeholder='0113, LS or LS1 1AA')
    location, location_message = selected_location(location_query, data['locationReference'])
    if location_message:
        st.caption(location_message)
    query = st.text_input('Search', placeholder='Provider, postcode or issue')
    mode = st.radio('View', ['Live', 'History'], horizontal=True)
    history_days = st.slider('History period (days)', 1, 365, 30, disabled=mode == 'Live')
    if st.button('Refresh feeds now', use_container_width=True):
        load_dashboard.clear()
        st.rerun()

now = datetime.now(timezone.utc)
since = now if mode == 'Live' else now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=history_days - 1)
records = filtered_incidents(data, categories, provider, location, query, mode, since)
source_by_id = {source['id']: source for source in data['sources']}

fresh = sum(source.get('state') == 'connected' for source in data['sources'] if source.get('kind') != 'portal')
stale_sources = sum(source.get('state') == 'stale' for source in data['sources'])
st.info(f"Last collection: {data.get('updatedAt') or 'not available'} · {fresh} automatic feeds fresh · {stale_sources} responding with stale data.")

metrics = st.columns(5)
for column, category in zip(metrics, category_labels):
    column.metric(category_labels[category], sum(item.get('category') == category for item in records))

filters = {
    'mode': mode.lower(), 'categories': categories, 'provider': None if provider == 'All providers' else provider,
    'location': location_query, 'locationInterpretation': location_message or None, 'search': query,
    'timeWindow': 'current feed records' if mode == 'Live' else f'last {history_days} calendar days',
    'from': None if mode == 'Live' else since.isoformat(), 'through': now.isoformat(),
}
payload = report(records, data['sources'], filters, data.get('updatedAt'))
left, right = st.columns(2)
left.download_button('Download CSV report', csv_bytes(payload), file_name('csv'), 'text/csv', use_container_width=True)
right.download_button('Download JSON report', json.dumps(payload, ensure_ascii=False, indent=2), file_name('json'), 'application/json', use_container_width=True)
st.caption(f"Exports contain all {len(records)} matching records plus source health. {LIMITATIONS}")

trend = Counter((item.get('date') or '')[:10] for item in records if item.get('date'))
if trend:
    st.subheader('Collected incident trend')
    st.bar_chart({day: trend[day] for day in sorted(trend)})

points = []
for item in records:
    for point in item.get('locationPoints', []):
        points.append({'lat': point['lat'], 'lon': point['lng'], 'provider': item.get('provider'),
                       'type': point.get('method'), 'title': item.get('title')})
if points:
    st.subheader('Incident locations')
    st.caption('Source coordinates take priority. Postcode, telephone and RIPE probe locations are approximate.')
    st.map(points, latitude='lat', longitude='lon', size=20)

st.subheader(f'Incidents and notices ({len(records)})')
if not records:
    st.info('No matching records. This does not confirm normal service; inspect connection health below.')
for item in records:
    source = source_by_id.get(item.get('sourceId'), {})
    label = f"{item.get('provider')} · {item.get('title')}"
    with st.expander(label):
        st.write(item.get('description') or 'No public description supplied.')
        st.caption(f"Status: {item.get('status')} · Reported: {item.get('date') or 'not supplied'} · Last fetched: {item.get('observedAt')}")
        if item.get('stale'):
            st.warning('This record is stale because its source is unavailable or its published data is old.')
        details = []
        if item.get('evidenceType'):
            details.append(f"Evidence: {item['evidenceType']}")
        if item.get('reportedPostcodeAreas'):
            details.append('Reported postcode areas: ' + ', '.join(item['reportedPostcodeAreas']))
        if item.get('telephoneAreas'):
            details.append('Telephone association (approximate): ' + '; '.join(f"{entry['code']} → {', '.join(entry['postcodeAreas'])}" for entry in item['telephoneAreas']))
        if item.get('customersAffected') is not None:
            details.append(f"Customers reported affected: {item['customersAffected']}")
        if item.get('estimatedRestorationAt'):
            details.append('Estimated restoration: ' + item['estimatedRestorationAt'])
        if details:
            st.caption(' · '.join(details))
        if item.get('url'):
            st.link_button('Source details', item['url'])

st.subheader('Data connections')
st.caption('Connected means the feed was fetched successfully, not that the provider is fault-free. Portal-only entries are links, not automated connections.')
for source in data['sources']:
    with st.expander(f"{source['name']} · {source.get('state', 'unknown')}"):
        st.write(source.get('note') or source.get('scope'))
        st.caption(f"{category_labels.get(source.get('category'), source.get('category'))} · {source.get('scope')}")
        st.caption(f"Last attempt: {source.get('checkedAt') or 'not attempted'} · Last success: {source.get('lastSuccess') or 'not available'}")
        if source.get('sourceUpdatedAt'):
            st.caption('Source updated: ' + source['sourceUpdatedAt'])
        if source.get('coverage'):
            st.caption(source['coverage'])
        if source.get('error'):
            st.error(source['error'])
        if source.get('website'):
            st.link_button('Provider / source', source['website'])
