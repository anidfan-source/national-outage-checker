/* Pure report builders shared by download buttons and browser tests. */
(function (root) {
  const COLUMNS = ['record_type', 'generated_at', 'collection_at', 'backend_available', 'filters', 'record_count',
    'id', 'provider', 'category', 'evidence_type', 'title', 'status', 'reported_at', 'last_fetched_at',
    'source_updated_at', 'stale', 'region', 'reported_postcode_areas', 'inferred_postcode_areas', 'telephone_codes',
    'location_methods', 'location_points', 'location_conflict', 'customers_affected', 'estimated_restoration_at',
    'source_url', 'description', 'source_state', 'source_error', 'last_success_at', 'attribution', 'limitations'];
  const LIMITATIONS = 'Provider reports, risk notices and passive network signals are not household diagnoses. Telephone/postcode/probe locations may be approximate. Feed history and geographic coverage are incomplete; no records does not mean no outages. Independent signals may overlap. See source health and attribution.';
  function buildReport({records, sources, filters, collectedAt, backendAvailable, generatedAt = new Date().toISOString()}) {
    const incidents = records.map(item => ({...item, stale: Boolean(item.stale || !backendAvailable)}));
    const health = sources.map(source => ({...source, state: !backendAvailable && source.kind !== 'portal' ? 'backend-offline' : source.state}));
    return {schemaVersion: 1, generatedAt, collectedAt: collectedAt || null, backendAvailable, filters,
      summary: {recordCount: incidents.length, staleCount: incidents.filter(x => x.stale).length,
        networkEvidenceCount: incidents.filter(x => ['network-signal','probe-evidence'].includes(x.evidenceType)).length,
        byCategory: incidents.reduce((totals,x) => {totals[x.category] = (totals[x.category] || 0) + 1; return totals;}, {}),
        sourceStates: health.reduce((totals,x) => {totals[x.state] = (totals[x.state] || 0) + 1; return totals;}, {})},
      limitations: LIMITATIONS, locationAttribution: 'Ofcom telephone area codes; GeoNames postal data (CC BY 4.0), adapted into approximate associations.',
      sources: health, incidents};
  }
  function csvCell(value) {
    let text = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    // Quoting alone does not stop spreadsheet formula execution.
    if (/^[\s\u0000-\u001f]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }
  function toCSV(report) {
    const common = {generated_at:report.generatedAt, collection_at:report.collectedAt, backend_available:report.backendAvailable};
    const rows = [{...common, record_type:'report', filters:report.filters, record_count:report.summary.recordCount,
      attribution:report.locationAttribution, limitations:report.limitations}];
    for (const item of report.incidents) rows.push({...common, record_type:'incident', id:item.id, provider:item.provider,
      category:item.category, evidence_type:item.evidenceType || 'provider-notice', title:item.title, status:item.status,
      reported_at:item.date, last_fetched_at:item.observedAt, source_updated_at:item.sourceUpdatedAt, stale:item.stale,
      region:item.region, reported_postcode_areas:item.reportedPostcodeAreas, inferred_postcode_areas:item.inferredPostcodeAreas,
      telephone_codes:(item.telephoneAreas || []).map(x => x.code), location_methods:(item.locationPoints || []).map(x => x.method),
      location_points:item.locationPoints, location_conflict:item.locationConflict, customers_affected:item.customersAffected,
      estimated_restoration_at:item.estimatedRestorationAt, source_url:item.url, description:item.description, attribution:item.attribution});
    for (const source of report.sources) rows.push({...common, record_type:'source', id:source.id, provider:source.name,
      category:source.category, source_state:source.state, source_error:source.error, last_success_at:source.lastSuccess,
      last_fetched_at:source.checkedAt, source_updated_at:source.sourceUpdatedAt, source_url:source.website,
      description:source.note, attribution:source.attribution});
    return '\ufeff' + [COLUMNS, ...rows.map(row => COLUMNS.map(column => row[column]))].map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
  }
  root.OutageReports = {buildReport, toCSV};
})(globalThis);
