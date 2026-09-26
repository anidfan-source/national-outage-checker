"""Explicit source registry; portal entries are never presented as connected feeds."""
SOURCES = []

def feed(id, name, category, kind, url, website=None, scope='Global / UK impact unconfirmed', note=''):
    SOURCES.append(dict(id=id, name=name, category=category, kind=kind, url=url,
                        website=website or url, scope=scope, note=note))

for id, name, host in [
    ('cloudflare', 'Cloudflare / 1.1.1.1', 'www.cloudflarestatus.com'),
    ('akamai', 'Akamai CDN', 'www.akamaistatus.com'),
    ('fastly', 'Fastly CDN', 'status.fastly.com'),
    ('linode', 'Akamai Connected Cloud / Linode', 'status.linode.com'),
    ('digitalocean', 'DigitalOcean', 'status.digitalocean.com'),
    ('github', 'GitHub', 'www.githubstatus.com'),
    ('discord', 'Discord', 'discordstatus.com'),
    ('zoom', 'Zoom', 'status.zoom.us'),
    ('dropbox', 'Dropbox', 'status.dropbox.com'),
    ('atlassian', 'Atlassian', 'status.atlassian.com'),
]:
    feed(id, name, 'third-party', 'statuspage', f'https://{host}/api/v2/incidents.json', f'https://{host}',
         note='Service disruption may affect websites or apps; does not establish a home line fault.')
feed('gcp', 'Google Cloud', 'third-party', 'google', 'https://status.cloud.google.com/incidents.json', 'https://status.cloud.google.com')
feed('aws', 'Amazon Web Services', 'third-party', 'rss', 'https://status.aws.amazon.com/rss/all.rss', 'https://health.aws.amazon.com/health/status')
feed('azure', 'Microsoft Azure', 'third-party', 'rss', 'https://status.azure.com/en-us/status/feed/', 'https://azure.status.microsoft/en-us/status/')
feed('aa', 'Andrews & Arnold', 'broadband', 'rss', 'https://aastatus.net/atom.cgi', 'https://aastatus.net', 'UK provider / location unspecified')
feed('zen', 'Zen Broadband faults', 'broadband', 'rss', 'https://status.zen.co.uk/rss/broadband-faults-rss.ashx', 'https://status.zen.co.uk', 'UK provider / location unspecified')
feed('zen-maintenance', 'Zen Broadband maintenance', 'broadband', 'rss', 'https://status.zen.co.uk/rss/broadband-maintenance-rss.ashx', 'https://status.zen.co.uk', 'UK provider / location unspecified', 'Planned work notices; check provider for current status.')
feed('npg', 'Northern Powergrid', 'electricity', 'npg', 'https://northernpowergrid.opendatasoft.com/api/explore/v2.1/catalog/datasets/live-power-cuts-data/records', 'https://northernpowergrid.opendatasoft.com/explore/dataset/live-power-cuts-data/', 'North East England, Yorkshire and northern Lincolnshire', 'Source coordinates; power loss can interrupt routers and network equipment.')
feed('metoffice', 'Met Office weather warnings', 'environment', 'rss', 'https://weather.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK', 'https://weather.metoffice.gov.uk/warnings-and-advice', 'UK', 'Risk context, not proof of a broadband outage. Verify warning validity at source.')
feed('metoffice-historic', 'Met Office historic weather-warning archive', 'environment', 'portal', None, 'https://www.metoffice.gov.uk/research/library-and-archive/publications/national-severe-weather-warning-service', 'UK, March 2011 onwards', 'The supplied NSWWS Metadata 2026 workbook is bundled for History views. It records original issue date, classification, weather element and named regions; it has no validity period or geometry. The live Met Office API has no historic-warning endpoint.')
feed('ea', 'Environment Agency flood warnings', 'environment', 'flood', 'https://environment.data.gov.uk/flood-monitoring/id/floods', 'https://check-for-flooding.service.gov.uk/', 'England', 'Environment Agency flood and river level data: Open Government Licence. Risk context, not a confirmed broadband fault.')
feed('ea-rainfall', 'Environment Agency rainfall telemetry', 'environment', 'portal', None, 'https://environment.data.gov.uk/flood-monitoring/doc/rainfall', 'England', 'Public OGL real-time rainfall telemetry; no registration required. Adapter pending. Use as environmental correlation only, not proof of a broadband outage.')
feed('ea-levels', 'Environment Agency river levels and flows', 'environment', 'portal', None, 'https://environment.data.gov.uk/flood-monitoring/doc/reference', 'England', 'Public OGL real-time level/flow telemetry; no registration required. Adapter pending. Use as environmental correlation only.')
feed('ea-tides', 'Environment Agency tide gauges', 'environment', 'portal', None, 'https://environment.data.gov.uk/flood-monitoring/doc/tidegauge', 'England coastal locations', 'Public OGL near-real-time tide-gauge data; no registration required. Adapter pending. Use as environmental correlation only.')
feed('ea-historic', 'Environment Agency historic flood warnings', 'environment', 'portal', None, 'https://www.data.gov.uk/dataset/d4fb2591-f4dd-4e7f-9aaf-49af94437b36/historic-flood-warnings2', 'England, 2006 onwards', 'Quarterly historical download. Loaded only for environmental History views; a flood warning is risk context, not proof of a broadband fault.')
feed('uk-utility-reporter', 'UK Utility Reporter community telecoms reports', 'broadband', 'community', 'https://www.ukutilityreporter.co.uk/api/reports?type=telecoms&limit=500', 'https://www.ukutilityreporter.co.uk/', 'UK', 'Public, user-submitted telecoms reports. The collector keeps only the report state, postcode district and affected-count estimate; it does not retain reporter text, address, photos or source coordinates. Treat as unverified community evidence.')

# These require a location, customer session, licensed access or a bespoke adapter.
for id, name, category, website, note in [
 ('openreach','Openreach','broadband','https://www.openreach.com/','Wholesale access network; customer line diagnostics through your ISP.'),
 ('bt','BT','broadband','https://www.bt.com/help/check-service-status','Address/account service checker.'),
 ('ee','EE','broadband','https://ee.co.uk/help','Broadband and mobile backup; address/account checker.'),
 ('plusnet','Plusnet','broadband','https://www.plus.net/help/','Customer service status and line diagnostics.'),
 ('sky','Sky Broadband','broadband','https://www.sky.com/help/servicestatus','Customer service checker.'),
 ('virgin','Virgin Media','broadband','https://www.virginmedia.com/help/service-status','Postcode/account service checker.'),
 ('talktalk','TalkTalk','broadband','https://community.talktalk.co.uk/','Service centre and customer line testing.'),
 ('vodafone','Vodafone','broadband','https://www.vodafone.co.uk/network/status-checker','Location checker; fixed broadband and mobile backup.'),
 ('o2','O2 mobile backup','broadband','https://status.o2.co.uk/','Location-based mobile network status.'),
 ('three','Three / 5G home broadband','broadband','https://www.three.co.uk/support/network-and-coverage/network-support','Location-based mobile and fixed wireless status.'),
 ('cityfibre','CityFibre','broadband','https://cityfibre.com/','Wholesale fault details via retail ISP.'),
 ('hyperoptic','Hyperoptic','broadband','https://www.hyperoptic.com/help/','Building/customer-specific status.'),
 ('gigaclear','Gigaclear','broadband','https://gigaclear.com/','Local fibre network; provider checker.'),
 ('kcom','KCOM','broadband','https://www.kcom.com/','Hull and East Yorkshire; provider service status.'),
 ('b4rn','B4RN','broadband','https://b4rn.org.uk/','Rural fibre network; provider status.'),
 ('communityfibre','Community Fibre','broadband','https://communityfibre.co.uk/','Provider help and network status.'),
 ('gnetwork','G.Network','broadband','https://www.g.network/','Provider help and network status.'),
 ('toob','toob','broadband','https://www.toob.co.uk/','Provider help and network status.'),
 ('idnet','IDNet','broadband','https://status.idnet.com/','Public status portal; feed adapter not verified.'),
 ('starlink','Starlink satellite broadband','broadband','https://www.starlink.com/support','Customer terminal/app diagnostics; no connected public outage feed.'),
 ('ukpn','UK Power Networks','electricity','https://ukpowernetworks.opendatasoft.com/explore/dataset/ukpn-national-energy-outage/','Open Data registration/access required for National Energy Outage data; adapter pending.'),
 ('ssen','SSEN Distribution','electricity','https://powertrack.ssen.co.uk/powertrack','Northern Scotland and southern England; outage map.'),
 ('spen','SP Energy Networks','electricity','https://www.spenergynetworks.co.uk/pages/power_cuts.aspx','Central/southern Scotland, Merseyside and north Wales; outage portal.'),
 ('nged','National Grid Electricity Distribution','electricity','https://powercuts.nationalgrid.co.uk/','Midlands, South West England and south Wales; formerly Western Power Distribution.'),
 ('enwl','Electricity North West','electricity','https://www.enwl.co.uk/power-cuts/','North West England; outage portal.'),
 ('nie','NIE Networks','electricity','https://powercheck.nienetworks.co.uk/','Northern Ireland; outage portal.'),
 ('neso','NESO','electricity','https://www.neso.energy/data-portal','Grid context; not a household power-cut feed.'),
 ('quad9','Quad9 DNS','third-party','https://status.quad9.net/','DNS resolver status; bespoke feed adapter needed.'),
 ('m365','Microsoft 365','third-party','https://status.cloud.microsoft/','Public status and tenant-specific authenticated service health.'),
 ('linx','LINX internet exchange','routing','https://www.linx.net/','Peering and exchange context; member incident access may be required.'),
 ('ripe','RIPE Atlas / RIS','routing','https://atlas.ripe.net/','Measurement and routing APIs require target ASNs/probes and interpretation; not connected.'),
 ('ioda','IODA internet outages','routing','https://ioda.inetintel.cc.gatech.edu/','Regional/ASN outage signals; custom adapter and UK network mapping needed.'),
 ('radar','Cloudflare Radar','routing','https://radar.cloudflare.com/','Traffic anomaly context; API token and custom adapter needed.'),
 ('sepa','SEPA flood warnings','environment','https://floodline.sepa.org.uk/floodupdates/','Scotland flood risk portal; adapter pending.'),
 ('nrw','Natural Resources Wales floods','environment','https://flood-warning.naturalresources.wales/','Wales flood risk portal; adapter pending.'),
 ('ni-flood','Northern Ireland flood information','environment','https://www.nidirect.gov.uk/articles/check-risk-flooding-your-area','Northern Ireland flood risk information; adapter pending.'),
 ('street-manager','Street Manager v7 roadworks','environment','https://www.gov.uk/guidance/find-and-use-roadworks-data','England roadworks data. Connected when API-user credentials are configured; the collector polls v7 /works/updates. Street Manager UI credentials are not API credentials.'),
 ('ofcom-connected-nations','Ofcom Connected Nations coverage','broadband','https://www.ofcom.org.uk/phones-and-broadband/coverage-and-speeds/connected-nations','Coverage/resilience enrichment rather than live faults. Use downloadable/open datasets where licensing permits; API access may require a subscription key.'),
 ('one-network','one.network roadworks','environment','https://one.network/','Streetworks and cable-damage risk; licensed data integration needed.'),
 ('downtech','Downtech / Outages.co.uk community reports','broadband','https://outages.co.uk/','Downtech operates the UK Outages.co.uk crowd-reporting site. No documented data API or feed was found, so this is a manual reference rather than an automated source.'),
]:
    feed(id,name,category,'portal',None,website,'See provider coverage',note)

# Verified public APIs replace the portal placeholders, retaining stable source IDs.
PUBLIC_CONNECTORS = {
    'ssen': dict(kind='ssen', url='https://external.distribution.prd.ssen.co.uk/opendataportal-prd/v4/api/getallfaults',
        scope='Northern Scotland and central southern England',
        note='SSEN Power Track open data (CC BY 4.0). Published fault coordinates and affected postcodes; estimates are not restoration confirmation.'),
    'nged': dict(kind='nged', url='https://connecteddata.nationalgrid.co.uk/api/3/action/datastore_search?resource_id=292f788f-4339-455b-8cc0-153e14509d4d',
        scope='Midlands, South West England and south Wales',
        note='NGED Connected Data Portal / NGED Open Data Licence. Source upload time is checked; old snapshots remain stale even when the API responds.'),
    'ioda': dict(kind='ioda', url='https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events',
        scope='UK-related networks and regions; last 24 hours',
        note='IODA / Georgia Tech network anomaly signals. Signals can overlap and do not confirm an individual broadband fault.'),
    'street-manager': dict(kind='street-manager-open-data', url=None,
        scope='England Street Manager Permit events received from the DfT Open Data feed',
        note='Street Manager Open Data Permit notifications via a verified AWS SNS webhook. Roadworks are correlation evidence/context and do not establish broadband causality.'),
    'ripe': dict(name='RIPE Atlas UK probe evidence', kind='ripe', url='https://atlas.ripe.net/api/v2/probes/',
        scope='Public UK probes disconnected within the last 24 hours',
        note='RIPE NCC Atlas public probe status. Disconnection may be local power, probe maintenance or connectivity; approximate probe locations are not household fault locations. No active tests are launched.'),
}
for source in SOURCES:
    if source['id'] in PUBLIC_CONNECTORS:
        source.update(PUBLIC_CONNECTORS[source['id']])
