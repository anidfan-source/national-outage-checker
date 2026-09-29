const categories = {
  broadband: { label: 'Broadband & mobile backup', color: '#ffba00' },
  electricity: { label: 'Electricity', color: '#ff5f6d' },
  'third-party': { label: 'Cloud, DNS & apps', color: '#8b7dff' },
  environment: { label: 'Weather & flood risks', color: '#6fe0c2' },
  routing: { label: 'Routing & internet exchanges', color: '#49a7ff' },
};
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const safeLink = value => /^https?:\/\//i.test(value || '') ? escapeHTML(value) : '#';
$('extraFilters').innerHTML = ['environment', 'routing'].map(key => `<label class="checkbox-row"><input type="checkbox" value="${key}" checked><span>${categories[key].label}</span></label>`).join('');
let data = { incidents: [], sources: [] };
let live = true;
let pageSize = 50;
let apiAvailable = false;
let dashboardETag = null;
let map, activeLayer;
if (window.L) {
  map = L.map('map').setView([54.5, -3.5], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
} else {
  $('map').textContent = 'Map library unavailable. Incidents and data connections remain available below.';
}
const closed = new Set(['resolved', 'completed', 'postmortem']);
const formatDate = value => value ? new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/London', day: '2-digit', month: 'short', year: 'numeric',
  hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short'
}).format(new Date(value)) : 'Not supplied';
function selectedCategories() {
  return new Set([...document.querySelectorAll('input[type="checkbox"]:checked')].map(x => x.value));
}
function locationSelection() {
  const query = $('locationFilter').value.trim().toUpperCase();
  if (!query) return null;
  const codes = data.locationReference?.codes || [];
  const code = query.replace(/[\s()-]/g, '').replace(/^(?:\+44|0044)0?/, '0');
  const telephone = codes.find(x => x.code === code);
  if (telephone) return {code, areas: telephone.postcodeAreas, label: `${code} · ${telephone.place} → ${telephone.postcodeAreas.join(', ') || 'postcode association unavailable'} (approximate)`};
  const postal = query.match(/^([A-Z]{1,2})(?:\d[A-Z\d]?(?:\s*\d[A-Z]{2})?)?$/);
  if (postal) return {areas:[postal[1]], label:`Postcode area ${postal[1]} · includes approximate telephone associations, not a household match`};
  return {areas:[], label:'Enter a geographic dialling code (0113), postcode area (LS), district or postcode.'};
}
function locationMatches(item) {
  const selection = locationSelection();
  return !selection || (item.telephoneAreas || []).some(x => x.code === selection.code) ||
    (item.postcodeAreas || []).some(x => selection.areas.includes(x));
}
function locationDetails(item) {
  const phones = (item.telephoneAreas || []).map(x => `${x.code} ${x.place} → ${x.postcodeAreas.join(', ') || 'postcode association unavailable'}`);
  const parts = [];
  if (item.reportedPostcodeAreas?.length) parts.push(`Reported postcode areas: ${item.reportedPostcodeAreas.join(', ')}`);
  if (phones.length) parts.push(`Telephone associations (approximate): ${phones.join('; ')}`);
  if (item.locationConflict) parts.push('Postcode and telephone evidence differ; source location takes priority.');
  if (item.evidenceType) parts.push(`Evidence: ${item.evidenceType.replaceAll('-', ' ')}`);
  if (item.sourceUpdatedAt) parts.push(`Source updated: ${formatDate(item.sourceUpdatedAt)}`);
  if (item.customersAffected != null) parts.push(`Customers reported affected: ${item.customersAffected}`);
  if (item.estimatedRestorationAt) parts.push(`Estimated restoration: ${formatDate(item.estimatedRestorationAt)}`);
  if ((item.locationPoints || []).some(x => x.method === 'postcode-district')) parts.push('Map shows approximate postcode district centres.');
  return parts.map(x => `<p class="location-detail">${escapeHTML(x)}</p>`).join('');
}
function matches(item) {
  const query = $('search').value.trim().toLowerCase();
  return selectedCategories().has(item.category) && (!$('sourceFilter').value || (item.sourceId || item.id) === $('sourceFilter').value) &&
    (!query || [item.title, item.provider, item.name, item.region, item.description, item.note, ...(item.postcodeAreas || []), ...(item.telephoneAreas || []).flatMap(x => [x.code, x.place])].join(' ').toLowerCase().includes(query));
}
function startDate() {
  const start = new Date();
  if ($('viewMode').value === 'day') {
    start.setHours(0, 0, 0, 0);
    start.setDate(start.getDate() - 29);
    return start;
  }
  start.setDate(1);
  start.setHours(0, 0, 0, 0);
  start.setMonth(start.getMonth() - Number($('monthRange').value) + 1);
  return start;
}
function incidents() {
  return data.incidents.filter(item => matches(item) && locationMatches(item) && (live ? item.current && !closed.has(item.status) :
    item.date && new Date(item.date) >= startDate() && new Date(item.date) <= new Date()))
    .sort((a,b) => (b.date || b.observedAt).localeCompare(a.date || a.observedAt));
}
function render() {
  const rows = incidents();
  $('locationHelp').textContent = locationSelection()?.label || 'Match incidents by dialling code or postcode area. Telephone associations are approximate.';
  $('locationCoverage').textContent = data.locationReference ? `${data.locationReference.mappedCount} of ${data.locationReference.codeCount} telephone prefixes have postcode associations. Hollow dashed markers indicate approximate locations. Reference: Ofcom + GeoNames.` : 'Location reference loading…';
  $('totals').innerHTML = Object.entries(categories).map(([key, c]) => `<div class="stat-card"><span>${c.label}</span><strong>${rows.filter(x => x.category === key).length}</strong></div>`).join('');
  $('incidentSummary').textContent = `${rows.length} ${live ? 'current feed entries (including notices, planned work and stale reports)' : 'historical entries in the selected time window'}. Notices and network signals do not confirm household outages. History grows from collected feeds; missing months do not imply zero outages.`;
  $('incidents').innerHTML = rows.slice(0, pageSize).map(item => `<article class="incident-card">
    <div class="card-meta"><span>${escapeHTML(item.provider)}</span><span class="badge ${item.stale || !apiAvailable ? 'unavailable' : ''}">${escapeHTML(item.status)}${item.stale || !apiAvailable ? ' · stale' : ''}</span></div>
    <h3><a href="${safeLink(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(item.title)}</a></h3>
    ${locationDetails(item)}<p>${escapeHTML(item.description.slice(0, 700))}</p><small>${escapeHTML(item.region)} · Reported: ${escapeHTML(formatDate(item.date))} · Last fetched: ${escapeHTML(formatDate(item.observedAt))}</small>
  </article>`).join('') || '<p class="empty">No matching records available. Check connection coverage below; this does not confirm normal service.</p>';
  $('exportCsv').disabled = $('exportJson').disabled = !data.updatedAt;
  $('showMore').hidden = rows.length <= pageSize;
  const mapped = rows.filter(x => x.locationPoints?.length);
  const exact = mapped.filter(x => x.locationPoints.some(p => p.method === 'source')).length;
  const points = mapped.flatMap(item => item.locationPoints.map(point => ({item,point})));
  $('mapStatus').textContent = `${exact} incidents have source coordinates; ${mapped.length-exact} have approximate locations; ${rows.length-mapped.length} remain unlocated. ${points.length} markers represent ${mapped.length} incidents.`;
  if (map) {
    if (activeLayer) map.removeLayer(activeLayer);
    activeLayer = L.layerGroup(points.map(({item,point}) => L.circleMarker([point.lat,point.lng], {
      radius: point.method === 'source' ? 8 : 11, color: categories[item.category].color,
      dashArray: point.method === 'source' ? null : '4 3',
      fillOpacity: point.method !== 'source' ? 0.08 : item.stale || !apiAvailable ? 0.3 : 0.8,
    }).bindPopup(`<strong>${escapeHTML(item.provider)}</strong><p>${escapeHTML(item.title)}</p><p>${escapeHTML(point.label)}</p>${locationDetails(item)}<p>${escapeHTML(item.status)}${item.stale || !apiAvailable ? ' · stale' : ''}</p><a href="${safeLink(item.url)}" target="_blank" rel="noopener noreferrer">Source details</a>`)));
    activeLayer.addTo(map);
  }
  renderTimeline();
  const feeds = data.sources.filter(x => x.kind !== 'portal');
  $('sourceSummary').textContent = `${apiAvailable ? feeds.filter(x => x.state === 'connected').length : 0} of ${feeds.length} automatic feeds fresh · ${feeds.filter(x => x.state === 'stale').length} responding with stale data · ${data.sources.length - feeds.length} portal/access-dependent sources. Refreshed every 5 minutes.`;
  $('sources').innerHTML = data.sources.filter(matches).map(source => `<article class="source-card">
    <div class="card-meta"><a href="${safeLink(source.website)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.name)}</a><span class="badge ${source.state}">${escapeHTML(!apiAvailable && source.kind !== 'portal' ? 'unknown / backend offline' : source.state)}</span></div>
    <p>${escapeHTML(source.note || source.scope)}</p><small>${escapeHTML(categories[source.category].label)} · ${escapeHTML(source.scope)}</small>
    ${source.kind !== 'portal' ? `<p class="feed-detail">Last attempt: ${escapeHTML(formatDate(source.checkedAt))} · Last success: ${escapeHTML(formatDate(source.lastSuccess))}${source.sourceUpdatedAt ? `<br>Source updated: ${escapeHTML(formatDate(source.sourceUpdatedAt))}` : ''}${source.coverage ? `<br>${escapeHTML(source.coverage)}` : ''}${source.error ? `<br>${escapeHTML(source.error)}` : ''}</p><a class="feed-detail" href="${safeLink(source.url)}" target="_blank" rel="noopener noreferrer">Feed endpoint</a>` : ''}
  </article>`).join('');
}
function renderTimeline() {
  const daily = $('viewMode').value === 'day';
  const start = daily ? new Date() : startDate();
  start.setHours(0,0,0,0);
  if (daily) start.setDate(start.getDate() - 29);
  const count = daily ? 30 : Number($('monthRange').value);
  const buckets = Array.from({length: count}, (_,i) => {
    const d = new Date(start);
    if (daily) d.setDate(d.getDate()+i); else d.setMonth(d.getMonth()+i);
    const end = new Date(d);
    if (daily) end.setDate(end.getDate()+1); else end.setMonth(end.getMonth()+1);
    return {start:d, end, label:d.toLocaleDateString('en-GB', daily ? {day:'numeric', month:'short'} : {month:'short', year:'2-digit'}), count:0};
  });
  data.incidents.filter(item => matches(item) && locationMatches(item)).forEach(item => {
    if (!item.date || new Date(item.date) > new Date()) return;
    const bucket = buckets.find(b => new Date(item.date) >= b.start && new Date(item.date) < b.end);
    if (bucket) bucket.count++;
  });
  const max = Math.max(1,...buckets.map(b=>b.count));
  $('trendTitle').textContent = `${daily ? '30-day' : count + '-month'} collected incident history`;
  $('timeline').innerHTML = buckets.map(b=>`<div class="timeline-bar" style="height:${Math.max(2,b.count/max*90)}%" title="${escapeHTML(b.label)}: ${b.count} collected entries"><span>${escapeHTML(b.label)}</span></div>`).join('');
}
async function load() {
  try {
    const headers = dashboardETag ? {'If-None-Match': dashboardETag} : {};
    const response = await fetch('/api/dashboard', {headers, cache: 'no-cache', signal: AbortSignal.timeout(15000)});
    if (response.status === 304) return;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    dashboardETag = response.headers.get('ETag') || dashboardETag;
    data = await response.json();
    apiAvailable = true;
    const selected = $('sourceFilter').value;
    $('sourceFilter').innerHTML = '<option value="">All providers</option>' + data.sources.map(s=>`<option value="${escapeHTML(s.id)}">${escapeHTML(s.name)}</option>`).join('');
    $('sourceFilter').value = selected;
    $('connectionStatus').textContent = data.refreshing ? 'Fetching provider feeds…' : `Last collection: ${formatDate(data.updatedAt)}`;
    render();
  } catch (error) {
    apiAvailable = false;
    $('connectionStatus').textContent = 'Live data unavailable. Start python3 server.py and open http://localhost:8000. Any retained data is stale.';
    render();
  }
}
function exportReport(format) {
  const report = OutageReports.buildReport({
    records: incidents(), sources: data.sources, collectedAt: data.updatedAt, backendAvailable: apiAvailable,
    filters: {mode:live ? 'live' : 'history', categories:[...selectedCategories()], provider:$('sourceFilter').value || null,
      location:$('locationFilter').value.trim(), locationInterpretation:locationSelection()?.label || null,
      search:$('search').value.trim(), timeWindow:live ? 'current feed records' : $('viewMode').value === 'day' ? 'last 30 calendar days' : `${$('monthRange').value} calendar months`,
      from:live ? null : startDate().toISOString(), through:new Date().toISOString(),
      chartMode:$('viewMode').value, chartMonths:Number($('monthRange').value)}
  });
  const body = format === 'csv' ? OutageReports.toCSV(report) : JSON.stringify(report,null,2);
  const blob = new Blob([body], {type:format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = `uk-outage-report-${report.generatedAt.replace(/[:.]/g,'-')}.${format}`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  $('exportStatus').textContent = `Downloaded ${report.summary.recordCount} matching records and ${report.sources.length} source health entries${apiAvailable ? '.' : ' (retained data marked stale).'} `;
}
$('exportCsv').addEventListener('click',()=>exportReport('csv'));
$('exportJson').addEventListener('click',()=>exportReport('json'));
document.querySelectorAll('input[type="checkbox"]').forEach(el => el.addEventListener('change', ()=>{pageSize=50;render();}));
['sourceFilter','viewMode'].forEach(id => $(id).addEventListener('change', ()=>{pageSize=50;render();}));
$('locationFilter').addEventListener('input', ()=>{pageSize=50;render();});
$('search').addEventListener('input', ()=>{pageSize=50;render();});
$('monthRange').addEventListener('input', ()=>{$('rangeValue').textContent=`${$('monthRange').value} months`;render();});
$('liveToggle').addEventListener('click', ()=>{
  live=!live; pageSize=50;
  $('liveToggle').textContent=live?'Live view · switch to history':'History view · switch to live';
  $('liveToggle').setAttribute('aria-pressed',String(live));render();
});
$('showMore').addEventListener('click', ()=>{pageSize+=50;render();});
load();
setInterval(load, 60000);

