# Data source endpoints

This is the integration inventory for National Outage Checker. `sources.py` is
the executable source registry; this document makes the endpoint and access
requirements explicit. A provider page is not treated as an API endpoint.

## Public feeds connected by the application

| Source | Endpoint | Access | What it supplies |
| --- | --- | --- |
| Cloudflare | `https://www.cloudflarestatus.com/api/v2/incidents.json` | Public | Third-party incidents |
| Akamai | `https://www.akamaistatus.com/api/v2/incidents.json` | Public | Third-party incidents |
| Fastly | `https://status.fastly.com/api/v2/incidents.json` | Public when not rate-limited | Third-party incidents |
| Linode | `https://status.linode.com/api/v2/incidents.json` | Public | Third-party incidents |
| DigitalOcean | `https://status.digitalocean.com/api/v2/incidents.json` | Public | Third-party incidents |
| GitHub | `https://www.githubstatus.com/api/v2/incidents.json` | Public | Third-party incidents |
| Discord | `https://discordstatus.com/api/v2/incidents.json` | Public | Third-party incidents |
| Zoom | `https://status.zoom.us/api/v2/incidents.json` | Public | Third-party incidents |
| Dropbox | `https://status.dropbox.com/api/v2/incidents.json` | Public | Third-party incidents |
| Atlassian | `https://status.atlassian.com/api/v2/incidents.json` | Public | Third-party incidents |
| Google Cloud | `https://status.cloud.google.com/incidents.json` | Public | Cloud incidents |
| AWS | `https://status.aws.amazon.com/rss/all.rss` | Public | Cloud notices |
| Microsoft Azure | `https://status.azure.com/en-us/status/feed/` | Public | Cloud notices |
| Andrews & Arnold | `https://aastatus.net/atom.cgi` | Public | UK broadband notices |
| Zen faults | `https://status.zen.co.uk/rss/broadband-faults-rss.ashx` | Public | UK broadband fault notices |
| Zen maintenance | `https://status.zen.co.uk/rss/broadband-maintenance-rss.ashx` | Public | Planned UK broadband work |
| Northern Powergrid | `https://northernpowergrid.opendatasoft.com/api/explore/v2.1/catalog/datasets/live-power-cuts-data/records` | Public | Power cuts that may affect broadband equipment |
| Met Office warnings | `https://weather.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK` | Public | Live UK severe-weather notices and impact text |
| Environment Agency | `https://environment.data.gov.uk/flood-monitoring/id/floods` | Public | England flood warnings |
| SSEN Power Track | `https://external.distribution.prd.ssen.co.uk/opendataportal-prd/v4/api/getallfaults` | Public | Power cuts, coordinates and affected postcodes |
| National Grid Electricity Distribution | `https://connecteddata.nationalgrid.co.uk/api/3/action/datastore_search?resource_id=292f788f-4339-455b-8cc0-153e14509d4d` | Public | Power-cut records; upload time is checked for staleness |
| IODA | `https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events` | Public | UK-related network anomaly signals |
| RIPE Atlas | `https://atlas.ripe.net/api/v2/probes/` | Public | Disconnected public UK probes |

## Street Manager: roadworks source

Street Manager is the preferred source for England utility and highway works.
It requires a registered account, an organisation name, contact details and an
API endpoint during onboarding. Do not use a consumer map scrape as a substitute.

The service supplies work location coordinates, promoter organisation, timing,
status and traffic-management information. After credentials are issued, use:

| Operation | Route | Use in this project |
| --- | --- | --- |
| Work updates | `GET /works/updates` | Incrementally ingest changed works; retain only telecom promoters and nearby works. |
| Permit export | `POST /permits/csv` | Request a permit export where the account role permits it. |
| Forward-plan export | `POST /forward-plans/csv` | Retrieve planned works. |
| Retrieve generated export | `GET /csv/{csvId}` | Download the CSV returned by an export request. |

The routes above are documented against the Street Manager API host supplied at
onboarding. The documentation examples use the **sandbox** host
`https://api.sandbox.manage-roadworks.service.gov.uk`; do not point production
polling at it. Authentication is JWT-based and the production hostname and
permissions are provisioned to the account.

## Sources with an account, partner agreement or licensed feed

| Source | Endpoint or registration page | Constraint |
| --- | --- | --- |
| Ofcom Connected Nations broadband and mobile coverage | `https://api.ofcom.org.uk/` | Subscription key; per-postcode coverage correlation, not live faults. |
| thinkbroadband Availability API | `https://api.thinkbroadband.com/inquiry.php` | Commercial GUID and allow-listed server IP; aggregates operator availability. |
| Openreach APIs | `https://d2haref.openreach.co.uk/onboarding/api-page/` | Communications-provider B2B access. |
| CityFibre Ticketing API | `https://ticketing.docs.cityfibre.com/` | Partner authentication. |
| Street Manager | `https://www.gov.uk/guidance/find-and-use-roadworks-data` | Registered account and JWT. |
| National Highways Road and Lane Closures v2 | `https://developer.data.nationalhighways.co.uk/` | Developer subscription key; strategic-road closures only. |
| one.network | `https://uk.one.network/node/489` | Licensed data API/reports product. |

## Portal-only sources

The following are deliberately retained as provider links until a documented
endpoint and permission are available: Openreach, BT, EE, Plusnet, Sky, Virgin
Media, TalkTalk, Vodafone, O2, Three, CityFibre, Hyperoptic, Gigaclear, KCOM,
B4RN, Community Fibre, G.Network, toob, IDNet, Starlink, UK Power Networks,
SP Energy Networks, Electricity North West, NIE Networks, NESO, Quad9,
Microsoft 365, LINX, Cloudflare Radar, SEPA, Natural Resources Wales, Northern
Ireland flood information and one.network.

For all environment, roadworks and network signals, the application labels a
geographic overlap as context or correlation. It never represents it as proof
of a household broadband fault.
