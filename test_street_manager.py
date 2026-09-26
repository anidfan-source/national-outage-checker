import json
import os
import unittest
from unittest.mock import patch
from sources import SOURCES
from server import event,date
from street_manager import collect_street_manager

class StreetManagerTests(unittest.TestCase):
    def source(self):
        return next(s for s in SOURCES if s['id']=='street-manager')

    @patch.dict(os.environ,{'STREET_MANAGER_USERNAME':'api@example.test','STREET_MANAGER_PASSWORD':'secret','STREET_MANAGER_BASE_URL':'https://example.test'},clear=False)
    @patch('street_manager._request')
    def test_auth_and_updates_are_normalized(self,request):
        request.side_effect=[
            {'idToken':'jwt','organisationReference':'ORG'},
            {'rows':[{'work_reference_number':'WR1','update_id':7,'event_date':'2026-09-26T10:00:00Z','promoter_organisation_name':'Telecom Co','street_name':'High Street','work_status':'planned','work_category':'standard'}],'next_update':None}
        ]
        rows,details=collect_street_manager(self.source(),event,date)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['workReferenceNumber'],'WR1')
        self.assertEqual(rows[0]['evidenceType'],'roadworks-context')
        self.assertEqual(rows[0]['region'],'High Street')
        self.assertEqual(details['organisationReference'],'ORG')
        self.assertEqual(request.call_args_list[1].kwargs['token'],'jwt')

if __name__=='__main__': unittest.main()
