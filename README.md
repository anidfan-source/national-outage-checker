# UK Outage Viewer

A local dashboard combining provider incident feeds with power outages and environmental risk notices. The former sample records have been removed. No credentials or Python packages are required for the configured public feeds.

## Run

```sh
python3 -m pip install -r requirements.txt
python3 -m streamlit run streamlit_app.py
```

This is the recommended local dashboard. It collects feeds directly and stores the normalized history in `data/outages.sqlite3`; no companion HTTP server is required. The sidebar can refresh feeds, filter records and download CSV or JSON reports.

The original browser implementation remains available:

```sh
python3 server.py
```

Open the Streamlit URL it prints (normally http://localhost:8501). Use `PORT=8001 python3 server.py` for the original local browser version if port 8000 is occupied. A static `python3 -m http.server` cannot provide the live API. The server binds only to localhost; production deployment needs an appropriate server/reverse proxy and operational monitoring.

## Coverage

The registry in `sources.py` contains 59 sources:

- **24 automatic feeds:** provider, service, power, environment and passive-network signals, plus a privacy-minimised UK community telecoms report feed.
- **35 portal/access-dependent sources:** major UK fixed and mobile broadband providers, fibre altnets, satellite broadband, remaining electricity distribution operators, NESO, DNS, peering/routing measurement services, devolved flood agencies, streetworks data and the Downtech/Outages.co.uk manual reference.

Portal-only entries are explicitly **not connected**. Their notes explain the next access or adapter requirement. Some links lead to provider help/home pages rather than a public feed. Availability is checked for automatic feeds on every collection; HTTP errors, timeouts and invalid responses appear in the source directory. There is no claim of exhaustive coverage: new providers appear, private line faults require customer information and many services have no public outage API.

At initial verification, 17 of 19 feeds responded successfully; Fastly returned HTTP 403 and the Environment Agency HTTP 503. This is a test snapshot, not an availability guarantee.

## How data is handled

- A background collector polls every five minutes, with eight concurrent workers, per-request timeouts and response-size limits. The browser checks the local API every 15 seconds.
- Statuspage history and unresolved incidents are combined by provider incident ID. Public feeds only provide limited history. Statuspage scheduled-maintenance endpoints are not yet ingested; Zen maintenance is connected separately.
- RSS/Atom items remain **notices**, because generic feeds do not reliably expose current resolution state. Check their source before treating them as active faults. Weather notices are risk context, not a confirmed broadband outage.
- Northern Powergrid records are paginated. Future work is marked scheduled. Its published coordinates appear on the map. Estimated restoration times are estimates, not resolution evidence.
- Global incidents remain unlocated unless their text supplies geographic evidence; no assumed UK impact. Flood warnings currently appear in the list without flood-area geometry.
- UK Utility Reporter community reports retain only the report status, postcode district and affected-count estimate. Reporter descriptions, street addresses, images and precise source coordinates are not collected. They are unverified evidence, never a confirmed outage.
- SQLite stores normalized records in `data/outages.sqlite3`. Records are upserted by source and incident ID; absent feed records remain in history but leave the current view. Disappearance is not labelled resolution. Records not observed for 366 days are pruned. This stores latest incident state, not an audit log of every update.
- Failed feeds retain their previous records with a **stale** label. A successful empty feed is different from an unavailable feed. On restart, persisted data remains stale until its source reconnects. Last-success timestamps are held in memory; record observation timestamps persist.
- Live view shows current non-resolved entries including notices and planned work. History filters apply to incident start/publication dates. Undated notices remain in live view but cannot be charted. The chart always shows collected history, respecting category/provider/search filters; daily mode covers 30 days and monthly mode covers the selected number of months.
- Telephone area codes and postcodes in incident text enrich locations and postcode-area search. No postcode-to-household correlation, account-based line diagnostics or automatic causality claims are implemented.
- The Streamlit app caches a collection for five minutes. **Refresh feeds now** clears this cache and collects again. Streamlit report downloads contain every matching incident, not only the expanded on-screen results, along with the active filters and full source health. CSV output prefixes spreadsheet-formula-like values to prevent execution in spreadsheet programs.

## Sources and attribution

- [Met Office RSS guidance](https://weather.metoffice.gov.uk/guides/rss) and [terms](https://www.metoffice.gov.uk/policies/tandc).
- [Environment Agency flood-monitoring API](https://environment.data.gov.uk/flood-monitoring/doc/reference): contains Environment Agency flood and river level data from the real-time data API (beta), under the Open Government Licence.
- [Northern Powergrid live power-cut dataset](https://northernpowergrid.opendatasoft.com/explore/dataset/live-power-cuts-data/): consult publisher metadata for coverage, licensing and limitations.
- [UK Power Networks open-data portal](https://ukpowernetworks.opendatasoft.com/): its National Energy Outage dataset requires registered access. This is listed as a future integration, not fetched anonymously.
- Each source card links to its provider and, for automatic connections, the feed endpoint. Incident titles link back to the source. Map tiles are attributed to OpenStreetMap contributors. Leaflet and map tiles require internet access; incident lists remain usable if Leaflet fails.

## Extend

Add a source in `sources.py` using `feed(...)`. Existing adapters support Statuspage JSON, Google Cloud JSON, RSS/Atom, Northern Powergrid and Environment Agency flood data. For another schema add a validated adapter in `server.parse`, with fixture tests. Provider links alone must use `kind='portal'`. Do not add invented endpoints or label a portal as a live connection. Tokens should be held server-side; authentication is not implemented for portal entries.

## Verify

```sh
python3 -m unittest -v
```

Tests cover parsing, dates, unresolved incident collection, stale retention, archive deduplication, future power work, schema rejection and unsafe source URLs. Live network health is visible at `/api/dashboard`; the API has no caller-supplied upstream URL and static serving is restricted to the four frontend files.

## Telephone area codes and postcode areas

The **Dialling code / postcode area** filter accepts e.g. `0113`, `+44 113`, `LS`, or `LS1 1AA`. Postcodes filter at area level (LS), not household level. Code filters also include incidents whose reported postcode areas overlap the code’s approximate associations. The filter applies to incidents, totals, map and timeline, leaving the source directory available.

A bundled Ofcom/GeoNames reference contains 771 geographic codes/prefixes, 684 with town-based postcode associations, and 3,002 postcode district points. For example, 0113 → Leeds → LS. These are incomplete approximate associations, **not coverage boundaries**. Extended prefixes distinguish shared code localities; unresolved shared codes retain multiple candidates without a map point.

Only standalone codes in incident context are used; contact/support numbers and non-geographic numbers are ignored. Existing source coordinates take priority, then published postcode district points, then inferred telephone locality points. Approximate points have hollow dashed markers. The incident list shows evidence and conflicting associations. Multiple locations remain one incident in totals. This also enriches previously collected history at read time.

See [reference methodology, attribution and limitations](reference/README.md). The offline reference needs no runtime geocoder or credentials. Regenerate with `python3 scripts/build_location_reference.py` and review its diff before adopting new data.
