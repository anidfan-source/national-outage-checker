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
let map, activeLayer;
if (window.L) {
  map = L.map('map').setView([54.5, -3.5], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'}).addTo(map);
} else {
  $('map').textContent = 'Map library unavailable. Incidents and data connections remain available below.';
}
const closed = new Set(['resolved', 'completed', 'postmortem']);
const formatDate = value => value ? new Date(value).toLocaleString('en-GB') : 'Not supplied';
function selectedCategories() {
  return new Set([...document.querySelectorAll('input[type="checkbox"]:checked')].map(x => x.value));
}
function matches(item) {
  const query = $('search').value.trim().toLowerCase();
  return selectedCategories().has(item.category) && (!$('sourceFilter').value || (item.sourceId || item.id) === $('sourceFilter').value) &&
    (!query || [item.title, item.provider, item.name, item.region, item.description, item.note].join(' ').toLowerCase().includes(query));
}
function startDate() {
  const start = new Date();
  start.setDate(1);
  start.setHours(0, 0, 0, 0);
  start.setMonth(start.getMonth() - Number($('monthRange').value) + 1);
  return start;
}
function incidents() {
  return data.incidents.filter(item => matches(item) && (live ? item.current && !closed.has(item.status) :
    item.date && new Date(item.date) >= startDate() && new Date(item.date) <= new Date()))
    .sort((a,b) => (b.date || b.observedAt).localeCompare(a.date || a.observedAt));
}
function render() {
  const rows = incidents();
  $('totals').innerHTML = Object.entries(categories).map(([key, c]) => `<div class="stat-card"><span>${c.label}</span><strong>${rows.filter(x => x.category === key).length}</strong></div>`).join('');
  $('incidentSummary').textContent = `${rows.length} ${live ? 'current feed entries (including notices, planned work and stale reports)' : 'historical entries in selected months'}. Notices have unconfirmed current status. History grows from collected feeds; missing months do not imply zero outages.`;
  $('incidents').innerHTML = rows.slice(0, pageSize).map(item => `<article class="incident-card">
    <div class="card-meta"><span>${escapeHTML(item.provider)}</span><span class="badge ${item.stale || !apiAvailable ? 'unavailable' : ''}">${escapeHTML(item.status)}${item.stale || !apiAvailable ? ' · stale' : ''}</span></div>
    <h3><a href="${safeLink(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(item.title)}</a></h3>
    <p>${escapeHTML(item.description.slice(0, 700))}</p><small>${escapeHTML(item.region)} · Reported: ${escapeHTML(formatDate(item.date))} · Last fetched: ${escapeHTML(formatDate(item.observedAt))}</small>
  </article>`).join('') || '<p class="empty">No matching records available. Check connection coverage below; this does not confirm normal service.</p>';
  $('showMore').hidden = rows.length <= pageSize;
  const mapped = rows.filter(x => Number.isFinite(x.lat) && Number.isFinite(x.lng));
  $('mapStatus').textContent = `${mapped.length} entries have source coordinates; ${rows.length - mapped.length} have no point location and appear only in the list.`;
  if (map) {
    if (activeLayer) map.removeLayer(activeLayer);
    activeLayer = L.layerGroup(mapped.map(item => L.circleMarker([item.lat,item.lng], {
      radius: 8, color: categories[item.category].color, fillOpacity: item.stale || !apiAvailable ? 0.3 : 0.8,
    }).bindPopup(`<strong>${escapeHTML(item.provider)}</strong><p>${escapeHTML(item.title)}</p><p>${escapeHTML(item.region)}</p><p>${escapeHTML(item.status)}${item.stale || !apiAvailable ? ' · stale' : ''}</p><a href="${safeLink(item.url)}" target="_blank" rel="noopener noreferrer">Source details</a>`)));
    activeLayer.addTo(map);
  }
  renderTimeline();
  const feeds = data.sources.filter(x => x.kind !== 'portal');
  $('sourceSummary').textContent = `${apiAvailable ? feeds.filter(x => x.state === 'connected').length : 0} of ${feeds.length} automatic feeds connected · ${data.sources.length - feeds.length} portal/access-dependent sources. Refreshed every 5 minutes.`;
  $('sources').innerHTML = data.sources.filter(matches).map(source => `<article class="source-card">
    <div class="card-meta"><a href="${safeLink(source.website)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.name)}</a><span class="badge ${source.state}">${escapeHTML(!apiAvailable && source.kind !== 'portal' ? 'unknown / backend offline' : source.state)}</span></div>
    <p>${escapeHTML(source.note || source.scope)}</p><small>${escapeHTML(categories[source.category].label)} · ${escapeHTML(source.scope)}</small>
    ${source.kind !== 'portal' ? `<p class="feed-detail">Last attempt: ${escapeHTML(formatDate(source.checkedAt))} · Last success: ${escapeHTML(formatDate(source.lastSuccess))}${source.error ? `<br>${escapeHTML(source.error)}` : ''}</p><a class="feed-detail" href="${safeLink(source.url)}" target="_blank" rel="noopener noreferrer">Feed endpoint</a>` : ''}
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
  data.incidents.filter(matches).forEach(item => {
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
    const response = await fetch('/api/dashboard', {signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
document.querySelectorAll('input[type="checkbox"]').forEach(el => el.addEventListener('change', ()=>{pageSize=50;render();}));
['sourceFilter','viewMode'].forEach(id => $(id).addEventListener('change', ()=>{pageSize=50;render();}));
$('search').addEventListener('input', ()=>{pageSize=50;render();});
$('monthRange').addEventListener('input', ()=>{$('rangeValue').textContent=`${$('monthRange').value} months`;render();});
$('liveToggle').addEventListener('click', ()=>{
  live=!live; pageSize=50;
  $('liveToggle').textContent=live?'Live view · switch to history':'History view · switch to live';
  $('liveToggle').setAttribute('aria-pressed',String(live));render();
});
$('showMore').addEventListener('click', ()=>{pageSize+=50;render();});
load();
setInterval(load, 15000);
