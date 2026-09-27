import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import server

class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(id='test', name='Test', kind='statuspage', category='broadband', scope='UK', website='https://example.com', url='https://example.com/api/v2/incidents.json')

    def test_statuspage_normalization(self):
        rows = server.parse(self.source, json.dumps({'incidents':[{'id':'1','name':'<b>Fault</b>','created_at':'2026-09-01T12:00:00Z','status':'resolved','shortlink':'javascript:bad','incident_updates':[{'body':'A &amp; B'}]}]}))
        self.assertEqual(rows[0]['title'], 'Fault')
        self.assertEqual(rows[0]['description'], 'A & B')
        self.assertEqual(rows[0]['status'], 'resolved')
        self.assertEqual(rows[0]['url'], self.source['website'])
        self.assertIsNone(rows[0]['lat'])

    def test_html_response_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            server.parse(self.source, '<html>Blocked</html>')
        with self.assertRaises(ValueError):
            server.parse({**self.source,'kind':'rss'}, '<html/>')

    def test_rss_does_not_invent_active_state_or_date(self):
        rows = server.parse({**self.source,'kind':'rss'}, '<rss><channel><item><guid>x</guid><title>Resolved notice</title></item></channel></rss>')
        self.assertEqual(rows[0]['status'],'notice')
        self.assertIsNone(rows[0]['date'])

    def test_met_office_warning_keeps_scottish_region(self):
        source = {**self.source, 'id':'metoffice', 'kind':'rss'}
        xml = '<rss><channel><item><guid>x</guid><title>Yellow warning for Strathclyde</title><description>Heavy rain</description></item></channel></rss>'
        rows = server.parse(source, xml)
        self.assertEqual(rows[0]['region'], 'Scotland — Strathclyde')

    def test_atom(self):
        rows = server.parse({**self.source,'kind':'rss'}, '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>42</id><title>Notice</title><updated>2026-09-01T00:00:00Z</updated><link href="https://example.com/42"/><summary>Details</summary></entry></feed>')
        self.assertEqual(rows[0]['id'],'test:42')
        self.assertEqual(rows[0]['url'],'https://example.com/42')

    def test_future_power_work_is_scheduled(self):
        rows = server.parse({**self.source,'kind':'npg'}, json.dumps({'results':[{'id':4,'reference':'work','loggedtime':'2099-01-01','lat':54,'lng':-2,'postcode':['AB1']}]}))
        self.assertEqual(rows[0]['status'],'scheduled')
        self.assertEqual(rows[0]['lat'],54)
        self.assertEqual(rows[0]['region'],'AB1')

    def test_flood_removed_warning(self):
        rows = server.parse({**self.source,'kind':'flood'}, json.dumps({'items':[{'@id':'f1','severityLevel':4}]}))
        self.assertEqual(rows[0]['status'],'resolved')

    def test_google_resolution(self):
        rows = server.parse({**self.source,'kind':'google'}, json.dumps([{'id':'g','end':'2026-09-01'}]))
        self.assertEqual(rows[0]['status'],'resolved')

    def test_failure_health(self):
        with patch('server.fetch',side_effect=TimeoutError('timeout')):
            health, rows = server.collect(self.source)
        self.assertEqual(health['state'],'unavailable')
        self.assertIsNone(rows)

    def test_unresolved_not_lost_to_history_cap(self):
        with patch('server.fetch',side_effect=[b'{"incidents":[]}', b'{"incidents":[{"id":"old","name":"Still active"}]}']):
            health, rows = server.collect(self.source)
        self.assertEqual(health['state'],'connected')
        self.assertEqual(len(rows),1)

    def test_archive_dedup_and_stale_retention(self):
        with tempfile.TemporaryDirectory() as tmp, patch('server.DB',Path(tmp)/'test.db'), patch('server.SOURCES',[self.source]), patch('server.STATE',{'sources':[], 'updatedAt':None, 'refreshing':False}):
            server.init_db()
            item = server.event(self.source,'1','Fault','2026-09-01')
            health = {**self.source,'state':'connected','lastSuccess':server.now()}
            with patch('server.collect',return_value=(health,[item])):
                server.refresh(); server.refresh()
            self.assertEqual(len(server.snapshot()['incidents']),1)
            with patch('server.collect',return_value=({**health,'state':'unavailable'},None)):
                server.refresh()
            self.assertTrue(server.snapshot()['incidents'][0]['stale'])
            self.assertTrue(server.snapshot()['incidents'][0]['current'])
            with patch('server.collect',return_value=(health,[])):
                server.refresh()
            self.assertFalse(server.snapshot()['incidents'][0]['current'])

if __name__ == '__main__':
    unittest.main()
