import unittest
from locations import CODES, distance_km, enrich, telephone_matches

class LocationTests(unittest.TestCase):
    def item(self, title='', description='', **extra):
        return enrich(dict(title=title, description=description, region='',lat=None,lng=None,**extra))

    def test_code_postcode_alignment(self):
        item=self.item('Outage in area code 0113')
        self.assertEqual(item['postcodeAreas'],['LS'])
        self.assertEqual(item['locationPoints'][0]['method'],'telephone-area')
        self.assertAlmostEqual(item['locationPoints'][0]['lat'],53.8,delta=.1)

    def test_international_codes(self):
        for text in ['Affected area code +44 113','Affected area code 0044 113','Affected area code +44 (0)113','Affected area code (0113)']:
            with self.subTest(text=text):self.assertEqual(self.item(text)['postcodeAreas'],['LS'])

    def test_multiple_codes_deduplicated(self):
        item=self.item('Affected area codes 0113, 0114 and 0113')
        self.assertEqual(item['postcodeAreas'],['LS','S'])
        self.assertEqual(len(item['locationPoints']),2)

    def test_support_numbers_not_incident_locations(self):
        for text in ['Outage. Contact 0113 1234567.', 'Outage, call 020 for updates', 'Fault helpline 0113', 'Outage. Tel: 0113', 'Affected phone number +44 113 123 4567', 'Outage reference 01131234567']:
            with self.subTest(text=text):self.assertEqual(self.item(text)['telephoneAreas'],[])

    def test_non_geographic_unknown_and_uncontextualized(self):
        for text in ['Area code 0800', 'Area code 07700','Area code 0300','Area code 01632','Area code 0207','Ticket 0113']:
            with self.subTest(text=text):self.assertEqual(telephone_matches(text),[])

    def test_shared_code_is_not_assigned_one_town(self):
        item=self.item('Area code 023 outage')
        self.assertEqual(item['postcodeAreas'],['PO','SO'])
        self.assertEqual(item['locationPoints'],[])
        self.assertEqual(CODES['028']['postcodeAreas'],['BT'])
        self.assertEqual(CODES['0191']['postcodeAreas'],['DH','NE','SR'])

    def test_full_postcode_takes_priority_over_phone_guess(self):
        item=self.item('Area code 0113 outage in LS1 1AA')
        self.assertEqual(item['postcodeDistricts'],['LS1'])
        self.assertEqual(item['locationPoints'][0]['method'],'postcode-district')

    def test_source_coordinate_preserved_and_conflict_flagged(self):
        item=enrich(dict(title='Affected area code 0113',description='',region='SW1A 1AA',lat=51.5,lng=-.1))
        self.assertEqual(item['locationPoints'],[dict(lat=51.5,lng=-.1,method='source',label='Source-supplied location')])
        self.assertTrue(item['locationConflict'])

    def test_cloud_product_not_postcode(self):
        self.assertEqual(self.item('AWS EC2 outage')['locationPoints'],[])
        self.assertEqual(self.item('Incident at postcode EC2')['postcodeAreas'],['EC'])

    def test_unlocated_remains_unlocated(self):
        self.assertEqual(self.item('Global network incident')['locationPoints'],[])

    def test_unmapped_code_keeps_place_without_guess(self):
        code=next(k for k,v in CODES.items() if not v['postcodeAreas'])
        item=self.item('Area code '+code)
        self.assertEqual(item['telephoneAreas'][0]['code'],code)
        self.assertEqual(item['locationPoints'],[])

    def test_distance_separates_distant_places_in_same_postcode_area(self):
        self.assertLess(distance_km(55.85,-4.42,55.84,-4.43),2)
        self.assertGreater(distance_km(55.85,-4.42,55.43,-5.61),80)

if __name__=='__main__':unittest.main()

