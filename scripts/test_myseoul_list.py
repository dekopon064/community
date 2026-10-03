"""Synthetic minimal markup based on two observed responses; never saved HTML.

No network, DB, provider or credentials. Live empty/error results not captured.
"""
import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from ingest.http_client import HttpClient, HttpBudgetExhausted, HttpRequestFailed, HttpStatusError, ResponseTooLarge
from ingest.myseoul_list import LIST_DATA_URL, list_parameters, parse_list_html, read_list_page
from ingest.myseoul_collect import collect_myseoul, list_entries
from test_myseoul_collect import FakeRPC, key
from test_myseoul_program import CENTER, Response, detail, url
import run_myseoul_collect as cli


def listing(page=1, total=62, count=None, start=None, statuses=None):
    count = min(10, max(0, total-(page-1)*10)) if count is None else count
    start = (page-1)*10+1 if start is None else start
    cards = ''.join(
        f'<a class="item" href="javascript:;" onclick="goPrgmDetail(\'{i:032X}\', \'{CENTER}\'); return false;">'
        '<strong class="txt-22">합성 모집 안내</strong>'
        f'<span class="program-state cate-st4 cate2">{(statuses or {}).get(i,"신청중")}</span></a>'
        for i in range(start,start+count))
    paging = ''.join(f'<div class="paging {c}"><button class="on" aria-current="page">{page}</button></div>'
                     for c in ('w_flex_only','m_flex_only')) if count else ''
    return f"<script>$('#totalCnt').text('{total}');</script><div class=\"counseling-list\">{cards}</div>{paging}"


class ReaderTests(unittest.TestCase):
    def test_parameters_post_single_request_no_bootstrap_cookie_or_redirect(self):
        response=Response(listing(2));sender=Mock(return_value=response)
        http=HttpClient(budget=12,max_attempts=1,transport=sender)
        page=read_list_page(http,2)
        self.assertEqual((page.page,page.page_size,page.total,len(page.items)),(2,10,62,10))
        self.assertEqual(http.request_count,1);self.assertTrue(response.closed)
        args,kw=sender.call_args;self.assertEqual(args,(LIST_DATA_URL,))
        self.assertEqual(kw['data'],list_parameters(2));self.assertFalse(kw['allow_redirects']);self.assertTrue(kw['verify'])
        self.assertEqual(kw['headers'],{'Accept':'text/html'});self.assertNotIn('cookies',kw)
        self.assertTrue(all(v=='' for k,v in kw['data'].items() if k not in ('miv_pageNo','miv_pageSize')))

    def test_page_size_and_request_page_rejected_before_network(self):
        for page,size in [(0,10),(3,10),(True,10),(1,20),(1,True)]:
            sender=Mock();http=HttpClient(budget=12,max_attempts=1,transport=sender)
            with self.assertRaises(ValueError):read_list_page(http,page,size)
            sender.assert_not_called();self.assertEqual(http.request_count,0)

    def test_page_echo_total_count_empty_and_short(self):
        for total in (0,3,10):
            p=parse_list_html(listing(total=total),1)
            self.assertEqual(len(list_entries(p,1)),min(total,10))
        with self.assertRaisesRegex(ValueError,'page_mismatch'):parse_list_html(listing(2),1)
        for bad in [listing(count=9),listing().replace("text('62')","text('unknown')"),
                    listing().replace('aria-current="page"','aria-current="none"',1),
                    listing()[:-6],'<html><form>로그인</form></html>',
                    '<div class="counseling-list"></div>',listing().replace('counseling-list','changed')]:
            with self.subTest(bad=bad[:35]),self.assertRaises(ValueError):parse_list_html(bad,1)

    def test_identity_order_and_language_links_are_canonical_and_duplicate_blocked(self):
        html=listing(total=1).replace('href="javascript:;"',f'href="{url(program=f"{1:032X}",language="en")}"')
        p=parse_list_html(html,1);self.assertIn('lang=ko',p.items[0]['url'])
        for bad in [html.replace(CENTER,'BAD'),html.replace('goPrgmDetail','unknownHandler'),
                    html.replace('lang=en','lang=unknown'),html.replace('global.seoul.go.kr','external.example.org'),
                    listing(total=2).replace(f'{2:032X}',f'{1:032X}'),
                    listing(total=1).replace("return false;","return false; alert(1);")]:
            with self.subTest(bad=bad[:50]),self.assertRaises(ValueError):parse_list_html(bad,1)

    def test_actual_status_labels_only_and_no_title_based_closing(self):
        p=parse_list_html(listing(total=3,statuses={1:'신청마감',2:'.',3:'신청중 / 마감 확인 필요'}),1)
        self.assertEqual([e['state'] for e in list_entries(p,1)],['closed','unknown','unknown'])
        self.assertEqual(p.items[2]['status'],'신청중 / 마감 확인 필요')
        with self.assertRaisesRegex(ValueError,'status_invalid'):parse_list_html(listing(total=1).replace('program-state','changed'),1)

    def test_transport_timeout_status_redirect_encoding_and_nonhtml_no_retry(self):
        cases=[(requests.Timeout('DO_NOT_ECHO'),HttpRequestFailed,'timeout'),
               (requests.RequestException('DO_NOT_ECHO'),HttpRequestFailed,'request_failed'),
               (Response(status=403),HttpStatusError,'403'),(Response(status=429),HttpStatusError,'429'),
               (Response(status=503),HttpStatusError,'503'),(Response(status=302),HttpRequestFailed,'redirect_blocked'),
               (Response(content_type='application/json'),HttpRequestFailed,'non_html'),
               (Response(data=b'\xff'),HttpRequestFailed,'html_encoding_invalid')]
        for result,exc,code in cases:
            with self.subTest(code=code):
                sender=Mock(side_effect=result) if isinstance(result,Exception) else Mock(return_value=result)
                http=HttpClient(budget=12,max_attempts=1,transport=sender)
                with self.assertRaisesRegex(exc,code) as caught:read_list_page(http,1)
                self.assertNotIn('DO_NOT_ECHO',str(caught.exception));self.assertEqual(http.request_count,1);sender.assert_called_once()
                if not isinstance(result,Exception):self.assertTrue(result.closed)

    def test_size_header_body_budget_and_no_retry_configuration(self):
        for response in [Response('x'*101),Response(listing())]:
            response.headers['Content-Length']='101'
            http=HttpClient(budget=12,max_attempts=1,max_response_bytes=100,transport=Mock(return_value=response))
            with self.assertRaises(ResponseTooLarge):read_list_page(http,1)
            self.assertTrue(response.closed)
        http=HttpClient(budget=12,max_attempts=1,max_response_bytes=100,transport=Mock(return_value=Response('x'*101)))
        with self.assertRaises(ResponseTooLarge):read_list_page(http,1)
        for http,exc in [(HttpClient(budget=0,max_attempts=1),HttpBudgetExhausted),(HttpClient(budget=12,max_attempts=2),ValueError)]:
            with patch('requests.post') as sender,self.assertRaises(exc):read_list_page(http,1)
            sender.assert_not_called()

    def test_default_post_transport_is_single_public_post(self):
        with patch('requests.post',return_value=Response(listing(total=0))) as sender,patch('requests.get') as get:
            self.assertEqual(read_list_page(HttpClient(budget=12,max_attempts=1),1).total,0)
            sender.assert_called_once();get.assert_not_called()


class CoreAndCLITests(unittest.TestCase):
    def test_real_reader_adapter_to_core_budget_and_second_page_condition(self):
        for known,expected_requests in [(False,12),(True,1)]:
            rpc=FakeRPC();calls=[]
            if known:rpc.sources.update(key(n) for n in range(1,11))
            def transport(target,**kw):
                calls.append((target,kw))
                if target==LIST_DATA_URL:return Response(listing(page=int(kw['data']['miv_pageNo']),total=20))
                return Response(detail())
            result=collect_myseoul(HttpClient(budget=12,max_attempts=1,transport=transport),rpc)
            self.assertEqual(result['requests'],expected_requests)
            self.assertEqual(len([c for c in calls if c[0]==LIST_DATA_URL]),1 if known else 2)
            self.assertEqual(len(set((u,kw.get('data',{}).get('miv_pageNo')) for u,kw in calls)),len(calls))
            self.assertEqual(len(rpc.observed),0 if known else 10)

    def test_validation_only_zero_network_or_db_and_execute_config_guard(self):
        out=io.StringIO()
        with patch('requests.post') as post,patch('requests.get') as get,patch('ingest.supabase_store.create_ingest_client') as factory,contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(['--project-ref','abcdefghijklmnopqrst']),0)
            post.assert_not_called();get.assert_not_called();factory.assert_not_called()
        self.assertTrue(json.loads(out.getvalue())['public_list_reader_ready'])
        with patch.dict('os.environ',{'SUPABASE_URL':'https://other.example.org','SUPABASE_SERVICE_KEY':'synthetic'},clear=True),patch('ingest.supabase_store.create_ingest_client') as factory,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--project-ref','abcdefghijklmnopqrst','--execute']),1)
            factory.assert_not_called()

    def test_execute_wiring_only_with_fake_client_and_transport(self):
        rpc=FakeRPC()
        client=SimpleNamespace(rpc=lambda n,p:SimpleNamespace(execute=lambda:SimpleNamespace(data=rpc(n,p))))
        http=HttpClient(budget=12,max_attempts=1,transport=Mock(return_value=Response(listing(total=0))))
        with patch.dict('os.environ',{'SUPABASE_URL':'https://abcdefghijklmnopqrst.supabase.co','SUPABASE_SERVICE_KEY':'synthetic'},clear=True),patch('ingest.supabase_store.create_ingest_client',return_value=client) as factory,patch('ingest.http_client.HttpClient',return_value=http),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--project-ref','abcdefghijklmnopqrst','--execute']),0)
            factory.assert_called_once();self.assertEqual(http.request_count,1)
        self.assertEqual([n for n,_ in rpc.calls],['start_ingest_run','discover_myseoul_list_page','myseoul_pending_details','finish_myseoul_list_collection'])


if __name__=='__main__':unittest.main()
