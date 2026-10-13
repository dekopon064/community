"""Synthetic normalization -> existing observation RPC payload; no API or DB."""
import copy
import socket
import unittest
from unittest.mock import patch
from test_seoul_reservation import row
from ingest.connectors.seoul_reservation import normalize_seoul_item
from ingest.program_db import program_rpc_item, ProgramNewOnlyObservationAdapter

class SeoulImageDeliveryTests(unittest.TestCase):
    def test_imgurl_retained_in_normalized_and_new_only_payload_without_network(self):
        values = ['https://images.example.org/seoul.png', '', 'http://images.example.org/seoul.png', 'data:image/png;base64,ignored']
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            for value in values:
                with self.subTest(value=value):
                    source = row(IMGURL=value, USETGTINFO='성인')
                    unchanged = copy.deepcopy(source)
                    record = normalize_seoul_item(source)
                    item = program_rpc_item(record)
                    expected = value if value.startswith('https://') else None
                    self.assertEqual(item['normalized_payload']['source_image_url'], expected)
                    self.assertEqual(item['normalized_payload']['provider_fields']['IMGURL'], value)
                    self.assertEqual(source, unchanged)
                    calls = []
                    def rpc(name, args):
                        calls.append((name,args))
                        return [{'inputIndex':0,'externalKey':record.external_key,'outcome':'new_saved','revision':record.revision_hash,
                                 'id':'30000000-0000-4000-8000-000000000001','reviewWaiting':True,'aiWaiting':False}]
                    ProgramNewOnlyObservationAdapter(rpc).observe('synthetic-run',[record],None)
                    self.assertEqual(calls[0][0],'observe_seoul_program_new_only')
                    self.assertEqual(calls[0][1]['p_items'][0]['normalized_payload']['source_image_url'],expected)
                    self.assertEqual(calls[0][1]['p_items'][0]['jobs'],[])
    def test_image_changes_revision_but_does_not_reinterpret_facts(self):
        a=normalize_seoul_item(row(IMGURL='https://images.example.org/a.png'))
        b=normalize_seoul_item(row(IMGURL='https://images.example.org/b.png'))
        self.assertNotEqual(a.revision_hash,b.revision_hash)
        fa=program_rpc_item(a)['program_facts'];fb=program_rpc_item(b)['program_facts']
        self.assertEqual({k:v for k,v in fa.items() if k!='source_revision'},{k:v for k,v in fb.items() if k!='source_revision'})

if __name__=='__main__':unittest.main()
