from datetime import datetime, timezone, timedelta
import json
import unittest
from unittest.mock import patch
from public_connectors import normalize, get_pages, get_spen_pages, provider_date
from server import event, date, collect
from sources import SOURCES
from locations import enrich

class PublicConnectorTests(unittest.TestCase):
    def source(self, kind):
        return next(s for s in SOURCES if s['kind']==kind)

    def normalize(self,kind,data):
        return normalize(self.source(kind),data,event,date)

    def test_ssen_preserves_postcodes_and_published_time(self):
        rows=self.normalize('ssen',{'timestampUtc':'2026-09-26T12:00:00Z','faults':[{'reference':'A1','title':'Power cut','loggedAtUtc':'2026-09-26T11:00:00Z','location':{'latitude':54,'longitude':-2},'affectedAreas':['LS1 1AA'],'customerCount':4,'estimatedRestorationTimeUtc':'2026-09-26T14:00:00Z','jobStatus':'A'}]})
        self.assertEqual(rows[0]['region'],'LS1 1AA')
        self.assertEqual(rows[0]['customersAffected'],4)
        self.assertEqual(rows[0]['sourceUpdatedAt'],'2026-09-26T12:00:00+00:00')
        self.assertEqual(rows[0]['evidenceType'],'provider-report')
        self.assertEqual(rows[0]['lat'],54)

    def test_nged_dates_resolution_and_staleness(self):
        payload={'success':True,'result':{'records':[{'Incident ID':'a','Status':'Restored','Planned':'false','Upload Date':'2020-07-01T12:00:00','Start Time':'2020-07-01T10:00:00','Postcodes':'BS1 1AA','ETR':'2020-07-01T11:00:00'}]}}
        with patch('public_connectors.get_pages',return_value=payload):
            health,rows=collect(self.source('nged'))
        self.assertEqual(health['state'],'stale')
        self.assertEqual(rows[0]['status'],'resolved')
        self.assertEqual(rows[0]['date'],'2020-07-01T09:00:00+00:00')
        self.assertEqual(rows[0]['sourceStartRaw'],'2020-07-01T10:00:00')

    def test_spen_normalizes_live_outages(self):
        payload={'results':[{'fault_id':'sp-1','planned':False,'status':'Ongoing','date_of_reported_fault':'2026-09-27T12:00:00Z',
            'etr':'2026-09-27T15:00:00Z','upload_date':'2026-09-27T12:05:00Z','voltage':'LV','post_code':'G1',
            'local_authority':'Glasgow City','region':'Central Belt','location_latitude':55.86,'location_longitude':-4.25}]}
        rows=self.normalize('spen',payload)
        self.assertEqual(rows[0]['status'],'reported')
        self.assertEqual(rows[0]['region'],'G1 · Glasgow City · Central Belt')
        self.assertEqual(rows[0]['estimatedRestorationAt'],'2026-09-27T15:00:00+00:00')
        self.assertEqual(rows[0]['lat'],55.86)

    def test_spen_paginates_with_its_100_record_limit(self):
        source=self.source('spen')
        pages=[{'total_count':101,'results':[{'fault_id':'a'}]*100},{'total_count':101,'results':[{'fault_id':'b'}]}]
        with patch.dict('os.environ',{'SPEN_API_KEY':'test-key'}),patch('public_connectors.SPEN_PAGE_SIZE',100):
            data=get_spen_pages(source,lambda _:json.dumps(pages.pop(0)))
        self.assertEqual(len(data['results']),101)

    def test_nged_planned_future_and_missing_date(self):
        rows=self.normalize('nged',{'success':True,'result':{'records':[{'Incident ID':'a','Planned':'true','Start Time':'2099-01-01T10:00:00'},{'Incident ID':'b'}]}})
        self.assertEqual(rows[0]['status'],'scheduled')
        self.assertIsNone(rows[1]['date'])
        self.assertIsNone(rows[1]['sourceUpdatedAt'])

    def test_ripe_only_recent_public_uk_disconnections(self):
        since=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        good={'id':1,'country_code':'GB','is_public':True,'status':{'id':2,'since':since},'geometry':{'coordinates':[-2,54]},'asn_v4':123,'address_v4':'SECRET_IP','description':'PRIVATE_DESCRIPTION'}
        entries=[good,{**good,'id':2,'country_code':'US'},{**good,'id':3,'is_public':False},{**good,'id':4,'status':{'id':1,'since':since}},{**good,'id':5,'status':{'id':2,'since':'2020-01-01T00:00:00Z'}}]
        rows=self.normalize('ripe',{'results':entries})
        self.assertEqual(len(rows),1)
        self.assertNotIn('SECRET_IP',json.dumps(rows))
        self.assertNotIn('PRIVATE_DESCRIPTION',json.dumps(rows))
        self.assertEqual(enrich(rows[0])['locationPoints'][0]['method'],'probe-location')

    def test_ioda_identity_dedup_and_unconfirmed_state(self):
        record={'start':1750000000,'location':'asn/123','location_name':'Network','datasource':'bgp','method':'median','status':0,'duration':60,'score':12}
        rows=self.normalize('ioda',{'error':None,'data':[record,record,{**record,'datasource':'ping-slash24'}]})
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['status'],'observed-signal')
        self.assertIsNone(rows[0]['lat'])
        self.assertEqual(rows[0]['signalDurationSeconds'],60)

    def test_cloudflare_radar_outage(self):
        payload={'success':True,'result':{'annotations':[{'startDate':'2026-09-27T10:00:00Z','endDate':None,
            'locations':['GB'],'scope':'Northern England','asns':[1234],'linkedUrl':'https://example.com/report',
            'outage':{'outageCause':'POWER_OUTAGE','outageType':'REGIONAL'}}]}}
        rows=self.normalize('radar',payload)
        self.assertEqual(rows[0]['status'],'observed-signal')
        self.assertEqual(rows[0]['region'],'Northern England')
        self.assertEqual(rows[0]['asns'],[1234])
        self.assertEqual(rows[0]['outageCause'],'POWER_OUTAGE')

    def test_error_payloads_are_not_successful_empty_feeds(self):
        for kind,data in [('ssen',{'faults':[],'errorMessage':'failed'}),('nged',{'success':False}),('ripe',{}),('ioda',{'data':[],'error':'failed'}),('radar',{'success':False})]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.normalize(kind,data)

    def test_nged_pagination(self):
        pages=[{'success':True,'result':{'total':2,'records':[{'Incident ID':'a'}]}},{'success':True,'result':{'total':2,'records':[{'Incident ID':'b'}]}}]
        with patch('public_connectors.PAGE_SIZE',1),patch('server.fetch',side_effect=[json.dumps(x) for x in pages]) as fetch:
            data=get_pages(self.source('nged'),fetch)
        self.assertEqual(len(data['result']['records']),2)
        self.assertIn('offset=1',fetch.call_args_list[1].args[0])

    def test_pagination_limit_never_accepts_partial_data(self):
        payload=json.dumps({'results':[{}],'count':20,'next':'https://unexpected.example'})
        with patch('public_connectors.MAX_PAGES',1),self.assertRaises(ValueError):
            get_pages(self.source('ripe'),lambda url:payload)

    def test_ioda_scopes_to_uk_and_paginates(self):
        pages=[{'data':[{'a':1}],'error':None},{'data':[],'error':None}]
        with patch('public_connectors.PAGE_SIZE',1),patch('server.fetch',side_effect=[json.dumps(x) for x in pages]) as fetch:
            data=get_pages(self.source('ioda'),fetch)
        self.assertEqual(len(data['data']),1)
        self.assertIn('relatedTo=country%2FGB',fetch.call_args_list[0].args[0])
        self.assertIn('page=2',fetch.call_args_list[1].args[0])

    def test_ripe_truncated_snapshot_fails(self):
        with self.assertRaises(ValueError):get_pages(self.source('ripe'),lambda _:json.dumps({'results':[],'count':20,'next':None}))

    def test_community_reports_minimise_personal_location_data(self):
        source=next(s for s in SOURCES if s['kind']=='community')
        payload={'ok':True,'reports':[{'id':'abc','postcode':'LS1 1AA','address':'Private home',
            'description':'My router and account are down', 'lat':53.8,'lon':-1.5,
            'severity':'urgent','affected_count':3,'status':'reported','submitted_at':1760000000000}]}
        rows=__import__('server').parse(source,json.dumps(payload))
        self.assertEqual(rows[0]['region'],'LS1')
        self.assertEqual(rows[0]['evidenceType'],'community-report')
        self.assertNotIn('Private home',json.dumps(rows))
        self.assertNotIn('router and account',json.dumps(rows))
        self.assertIsNone(rows[0]['lat'])

if __name__=='__main__':unittest.main()

