"""Synthetic failures only. No network, credentials or RPC clients."""
import io
import json
import socket
import unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch
import requests
from ingest.connectors.seoul_reservation import SeoulReservationConnector
from ingest.http_client import HttpClient
from ingest.seoul_diagnostics import diagnose_read, failure_diagnostic
from ingest.seoul_workflow import process_seoul_collection
from test_seoul_reservation import Response, row, envelope, TEST_KEY

class SeoulDiagnosticTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)
    def read(self,response=None,error=None):
        calls=[]
        def transport(*args,**kwargs):
            calls.append(1)
            if error: raise error
            return response
        connector=SeoulReservationConnector(HttpClient(budget=1,max_attempts=1,transport=transport),api_key_provider=lambda:TEST_KEY)
        with redirect_stderr(io.StringIO()): result=diagnose_read(connector)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['request_count'],1)
        self.assertEqual(result['writes'],0);self.assertEqual(result['ai_calls'],0)
        self.assertNotIn(TEST_KEY,json.dumps(result))
        self.assertNotIn('openapi.seoul',json.dumps(result))
        return result,connector
    def test_single_read_success_and_scope(self):
        result,_=self.read(Response(envelope([row(sid=f'TEST{i}') for i in range(50)],500)))
        self.assertEqual(result['scanned'],50);self.assertEqual(result['culture_count'],50)
        self.assertEqual(result['coverage'],'bounded_page_only')
    def test_non_json_and_utf8_diagnostics(self):
        for raw,code in [(b'<html>not json</html>','invalid_json'),(b'\xff','invalid_utf8')]:
            result,_=self.read(Response(data=raw))
            self.assertEqual(result['diagnostic']['stage'],'json_decode')
            self.assertEqual(result['diagnostic']['error_code'],code)
            self.assertEqual(result['diagnostic']['http_status'],200)
            self.assertEqual(result['diagnostic']['response_bytes'],len(raw))
    def test_timeout_and_status_never_retry(self):
        result,_=self.read(error=requests.Timeout(TEST_KEY))
        self.assertEqual(result['diagnostic']['stage'],'http_request')
        self.assertEqual(result['diagnostic']['error_code'],'timeout')
        result,_=self.read(Response({},status=503))
        self.assertEqual(result['diagnostic']['http_status'],503)
        self.assertEqual(result['diagnostic']['stage'],'http_status')
    def test_api_code_not_untrusted_message(self):
        result,_=self.read(Response({'RESULT':{'CODE':'ERROR-301','MESSAGE':'secret server details https://example.test/private'}}))
        self.assertEqual(result['diagnostic']['api_code'],'ERROR-301')
        self.assertEqual(result['diagnostic']['stage'],'response_contract')
        self.assertNotIn('secret',json.dumps(result))
    def test_shape_and_row_failure_exact_index(self):
        result,_=self.read(Response(envelope([row()],50)))
        self.assertEqual(result['diagnostic']['error_code'],'seoul_page_shape_invalid')
        rows=[row(sid=f'TEST{i}') for i in range(50)];rows[7]['SVCURL']='https://other.test/'
        result,_=self.read(Response(envelope(rows)))
        self.assertEqual(result['status'],'read_complete')
        self.assertEqual(result['validation'],'incomplete')
        self.assertEqual(result['valid_target_count'],49)
        self.assertEqual(result['item_errors'],[{'row_index':7,'stage':'row_normalization','error_code':'seoul_link_invalid'}])
    def test_credential_echo_fails_before_rows(self):
        result,_=self.read(Response(envelope([row(SVCNM=TEST_KEY)])))
        self.assertEqual(result['diagnostic']['error_code'],'seoul_credential_in_response')
    def test_size_limit_is_not_relaxed(self):
        response=Response(data=b'{}',headers={'Content-Length':'8000001'})
        result,_=self.read(response)
        self.assertEqual(result['diagnostic']['error_code'],'response_too_large')
        self.assertTrue(response.closed)
    def test_missing_key_no_request(self):
        c=SeoulReservationConnector(HttpClient(budget=1,max_attempts=1,transport=lambda *_a,**_k:self.fail('request forbidden')),api_key_provider=lambda:'')
        result=diagnose_read(c)
        self.assertEqual(result['request_count'],0)
        self.assertEqual(result['diagnostic']['stage'],'configuration')
    def test_unknown_exception_text_never_exposed(self):
        c=SimpleNamespace(last_diagnostic={'stage':'row_normalization','row_index':2},http=None)
        result=failure_diagnostic(c,RuntimeError('https://example.test/'+TEST_KEY))
        self.assertEqual(result,{'stage':'row_normalization','error_code':'unexpected_error','row_index':2})
    def test_raw_diagnostic_fields_cannot_leak(self):
        c=SimpleNamespace(last_diagnostic={'stage':TEST_KEY,'row_index':TEST_KEY,'api_code':TEST_KEY,'url':TEST_KEY},http=None)
        self.assertEqual(failure_diagnostic(c,RuntimeError(TEST_KEY)),{'stage':'unknown','error_code':'unexpected_error'})
    def test_http_retries_preserve_existing_policy_and_clear_stale_status(self):
        calls=[]
        responses=iter([Response({},status=503),Response({'ok':True})])
        def transport(*_a,**_kw):calls.append(1);return next(responses)
        http=HttpClient(budget=3,transport=transport,sleep=lambda _:None)
        with redirect_stderr(io.StringIO()):http.get_json('https://example.test/synthetic')
        self.assertEqual(len(calls),2);self.assertEqual(http.max_attempts,3)
        self.assertEqual(http.last_diagnostic['stage'],'http_complete')
        self.assertEqual(http.last_diagnostic['http_status'],200)
        self.assertNotIn('error_code',http.last_diagnostic)
    def test_bad_key_and_duplicate_identity_still_block_entire_page(self):
        result,_=self.read(Response(envelope([row(sid='DUP')]*50)))
        self.assertEqual(result['diagnostic']['error_code'],'seoul_duplicate_id_in_page')
        rows=[row(sid=f'TEST{i}') for i in range(50)];rows[4]['SVCID']='bad identity'
        result,_=self.read(Response(envelope(rows)))
        self.assertEqual(result['diagnostic']['stage'],'row_identity')
        self.assertEqual(result['diagnostic']['row_index'],4)
        self.assertEqual(result['diagnostic']['error_code'],'seoul_id_invalid')
    def test_cli_read_has_no_store_and_execute_is_exclusive(self):
        from run_seoul_program_collection import main
        with patch('ingest.connectors.seoul_reservation.SeoulReservationConnector',return_value='fake'),\
             patch('ingest.seoul_diagnostics.diagnose_read',return_value={'status':'read_complete','writes':0}) as read,\
             patch('ingest.supabase_store.create_ingest_client',side_effect=AssertionError('DB forbidden')),\
             redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--diagnose-read']),0);read.assert_called_once_with('fake')
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['--diagnose-read','--execute'])
    def test_collection_failure_reports_stage_without_observation(self):
        events=[]
        store=SimpleNamespace(start_ingest_run=lambda *_a,**_k:SimpleNamespace(skipped=False,run_id='fake'),
                              finish_ingest_run=lambda *_a,**_k:events.append('finish'))
        adapter=SimpleNamespace(require_contract=lambda:None,observe=lambda *_a:self.fail('write forbidden'))
        c=SeoulReservationConnector(HttpClient(budget=1,max_attempts=1,transport=lambda *_a,**_k:Response(data=b'not json')),api_key_provider=lambda:TEST_KEY)
        result=process_seoul_collection(store,adapter,c)
        self.assertEqual(result['diagnostic']['stage'],'json_decode')
        self.assertEqual(result['diagnostic']['error_code'],'invalid_json')
        self.assertEqual(events,['finish']);self.assertEqual(result['new_saved'],0)

if __name__=='__main__':unittest.main()
