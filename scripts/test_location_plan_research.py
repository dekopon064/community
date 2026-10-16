"""Real common auth + research + official reader, signed fakes; no live I/O."""
import copy
import io
import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ingest.ai_provider import create_location_research_adapter, ProviderError
from ingest.ai_openai import GPT_MODEL
from ingest.ai_claude import SUMMARY_MAX_TOKENS
from ingest.chatgpt_plan_protocol import ProbeError,read_completed_stream
from ingest.ai_errors import AiJobError
from ingest.location_official import (official_url,page_text,read_official_page,
    OfficialReadError,PublicHTTPS,MAX_PAGE_BYTES)
from ingest.location_plan_research import ResearchFailure,extract_research
from location_research_worker import serve
from test_chatgpt_plan_probe import FakeClient
import test_chatgpt_plan_sessions as sessions_fixture

CHOICES={'11':['강동구','종로구'],'41':['하남시'],'28':['연수구']}
URL='https://parks.seoul.go.kr/synthetic?item=1&menu=2'
EVIDENCE={'place':'합성물빛공원 교육장 앞','url':URL,'excerpt':'합성물빛공원 교육장 앞 위치: 서울특별시 강동구 합성길',
          'province':'11','district':'강동구'}
ITEM={'id':'30000000-0000-4000-8000-000000000001','source':'seoul_reservation',
      'title':'합성 체험','description':'만나는 장소: 합성물빛공원 교육장 앞\n활동 장소: 합성산'}


def completed(answer=None):
    return {'model':GPT_MODEL,'status':'completed','output':[
        {'type':'reasoning','summary':[]},
        {'type':'web_search_call','id':'ws_synthetic','status':'completed','action':{'type':'search',
         'query':'합성 장소 공식 위치','sources':[{'type':'url','url':URL}]}},
        {'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text',
         'text':json.dumps(answer or {'status':'suggested','evidence':EVIDENCE},ensure_ascii=False),
         'annotations':[{'type':'url_citation','url':URL,'title':'합성 공식 시설 안내'}]}]}],
        'usage':{'input_tokens':90,'output_tokens':20,'total_tokens':110,'output_tokens_details':{'reasoning_tokens':7}}}


def events(value):
    return [{'type':'response.output_item.done','output_index':i,'item':copy.deepcopy(item)} for i,item in enumerate(value['output'])]+[
        {'type':'response.completed','response':copy.deepcopy(value)}]


class LocationResearchTests(unittest.TestCase):
    def setUp(self):
        self.owner=sessions_fixture.SessionTests('test_valid_repeated_and_restarted_process_reuse_without_login_refresh')
        self.owner.setUp()
        self.addCleanup(self.owner.doCleanups)
        self.reads=[]

    def adapter(self, values=None, fetcher=None, client=None, limit=3):
        client=client or FakeClient([events(v) for v in (values or [completed()])])
        def page(url):
            self.reads.append(url)
            return EVIDENCE['excerpt']+'\n안전 안내'
        a=create_location_research_adapter('chatgpt_plan',choices=CHOICES,instructions='합성 조사 지침',
            limit=limit,manager=self.owner.manager(),client=client,fetch_page=fetcher or page)
        self.addCleanup(a.close)
        return a,client

    def test_common_reuse_real_factory_pro_search_and_verified_page(self):
        a,client=self.adapter()
        before=copy.deepcopy(ITEM)
        self.assertEqual(a.investigate(ITEM),{'status':'suggested','evidence':EVIDENCE})
        self.assertEqual(ITEM,before)
        self.assertEqual(self.owner.login_calls,[])
        self.assertEqual(self.owner.posts(),[])
        self.assertEqual(self.owner.store.writes,[])
        self.assertEqual(self.reads,[URL])
        self.assertEqual(a.calls,1)
        request=client.calls[0]
        self.assertEqual(request['model'],GPT_MODEL)
        self.assertEqual(request['tools'][0]['type'],'web_search')
        self.assertEqual(request['tools'][0]['filters']['allowed_domains'],['go.kr'])
        self.assertEqual(request['include'],['web_search_call.action.sources'])
        self.assertEqual(request['tool_choice'],{'type':'web_search'})
        self.assertFalse(request['store'])
        self.assertTrue(request['stream'])
        self.assertEqual(len(request['input']),1)
        self.assertNotIn('id',json.loads(request['input'][0]['content']))
        for forbidden in ('max_output_tokens','max_tool_calls','truncation','previous_response_id','service_tier'):
            self.assertNotIn(forbidden,request)
        self.assertEqual(a.usage,[{'input_tokens':90,'output_tokens':20,'reasoning_tokens':7}])

    def test_close_then_new_process_uses_same_protected_registration(self):
        for _ in range(2):
            a,_=self.adapter()
            a.investigate(ITEM)
            a.close()
        self.assertEqual(self.owner.login_calls,[])
        self.assertEqual(self.owner.posts(),[])
        self.assertEqual(self.owner.store.writes,[])

    def test_fake_refresh_uses_existing_manager_not_new_login(self):
        self.owner.near_expiry()
        a,_=self.adapter()
        a.investigate(ITEM)
        self.assertEqual(len(self.owner.posts()),1)
        self.assertEqual(self.owner.login_calls,[])
        self.assertEqual([x['state'] for x in self.owner.store.writes],['refresh_pending','ready'])

    def test_missing_or_revoked_grant_does_not_open_login_or_gpt(self):
        for value in (None,{**self.owner.record,'state':'reauth','grant':{}}):
            self.owner.store.record=copy.deepcopy(value)
            with self.assertRaises(ProbeError):
                self.adapter()
            self.assertEqual(self.owner.login_calls,[])
        self.assertEqual(self.reads,[])

    def test_no_other_provider_or_api_key_fallback(self):
        for provider in ('openai','anthropic','',None):
            with self.assertRaises(ProviderError):
                create_location_research_adapter(provider,choices=CHOICES,instructions='x',limit=1)
        self.assertEqual(self.owner.login_calls,[])

    def test_search_proof_required_url_generated_from_memory_is_not_enough(self):
        value=completed()
        value['output'][1]['action']['sources']=[]
        value['output'][2]['content'][0]['annotations']=[]
        a,_=self.adapter([value])
        self.assertEqual(a.investigate(ITEM),{'status':'error','evidence':None})
        self.assertEqual(self.reads,[])

    def test_real_page_must_contain_the_quote_place_and_region(self):
        a,_=self.adapter(fetcher=lambda url:'공식 페이지에 있지만 장소와 위치가 없는 설명')
        self.assertEqual(a.investigate(ITEM),{'status':'error','evidence':None})
        self.assertEqual(a.calls,1)

    def test_hallucinated_region_place_and_unsupported_fields_remain_errors(self):
        for key,value in [('district','다른구'),('province','99'),('place','다른공원'),('excerpt','존재하지 않는 인용')]:
            e={**EVIDENCE,key:value}
            a,_=self.adapter([completed({'status':'suggested','evidence':e})])
            self.assertEqual(a.investigate(ITEM)['status'],'error')

    def test_ambiguous_and_no_evidence_are_kept_without_read_or_write(self):
        for status in ('no_evidence','ambiguous'):
            a,_=self.adapter([completed({'status':status,'evidence':None})])
            self.assertEqual(a.investigate(ITEM),{'status':status,'evidence':None})
        self.assertEqual(self.reads,[])

    def test_item_error_then_next_item_one_new_generation_each(self):
        invalid=completed();invalid['output'][2]['content'][0]['text']='{wrong JSON'
        a,client=self.adapter([invalid,completed()])
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.investigate({**ITEM,'source':'synthetic_future_source'})['status'],'suggested')
        self.assertEqual(len(client.calls),2)
        self.assertEqual(a.calls-len(a.usage),0) # Completed metadata survives invalid JSON.

    def test_bad_json_does_not_hide_common_usage_failure(self):
        value=completed();value['output'][2]['content'][0]['text']='invalid JSON';value['usage']=None
        a,client=self.adapter([value])
        with self.assertRaises(ResearchFailure) as caught:a.investigate(ITEM)
        self.assertEqual(caught.exception.code,'research_usage_unknown')
        with self.assertRaises(ResearchFailure):a.investigate(ITEM)
        self.assertEqual(len(client.calls),1)

    def test_unsupported_search_and_provider_errors_stop_without_fallback(self):
        for code in ('subscription_sharing_unsupported_capability','subscription_sharing_usage_limit_exceeded'):
            client=FakeClient([[{'type':'error','code':code}]])
            a,_=self.adapter(client=client)
            with self.assertRaises(ResearchFailure) as caught:a.investigate(ITEM)
            self.assertEqual(caught.exception.code,code)
            with self.assertRaises(ResearchFailure):a.investigate(ITEM)
            self.assertEqual(len(client.calls),1)

    def test_response_unknown_is_recorded_and_next_item_runs_without_replay(self):
        a,client=self.adapter(client=FakeClient([[{'type':'response.output_text.delta','delta':'partial'}],events(completed())]))
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.last_diagnostic['code'],'stream_missing_completed')
        self.assertEqual(a.last_diagnostic['responseState'],'unknown')
        self.assertEqual(a.last_diagnostic['eventCount'],1)
        self.assertEqual(a.investigate({**ITEM,'id':'next'})['status'],'suggested')
        self.assertEqual(len(client.calls),2)
        self.assertEqual(len(a.usage),1) # Unknown use stays unknown, never zero.

    def test_terminal_only_payload_supported_without_weakening_normal_parser(self):
        value=completed();stream=events(value);stream[-1]['response']['output']=[]
        a,_=self.adapter(client=FakeClient([stream]))
        self.assertEqual(a.investigate(ITEM)['status'],'suggested')
        with self.assertRaises(AiJobError):
            read_completed_stream(FakeClient([events(value)]),{})

    def test_request_auth_rejection_is_common_error_without_login_or_replay(self):
        class Denied(Exception):
            status_code=401
        client=FakeClient()
        def deny(**request):
            client.calls.append(request)
            raise Denied('synthetic-sensitive-message')
        client.responses.create=deny
        a,_=self.adapter(client=client)
        with self.assertRaises(ResearchFailure) as caught:a.investigate(ITEM)
        self.assertEqual(caught.exception.code,'plan_http_401')
        self.assertNotIn('sensitive',str(caught.exception))
        with self.assertRaises(ResearchFailure):a.investigate(ITEM)
        self.assertEqual(len(client.calls),1)
        self.assertEqual(self.owner.login_calls,[])
        self.assertEqual(self.owner.store.writes,[])

    def test_conflicting_terminal_payload_does_not_generate_a_proposal(self):
        value=completed();stream=events(value);stream[-1]['response']['output'][2]['content'][0]['text']=json.dumps({'status':'no_evidence','evidence':None})
        a,_=self.adapter(client=FakeClient([stream]))
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.last_diagnostic['code'],'conflicting_terminal_output')
        self.assertEqual(self.reads,[])

    def test_optional_sources_only_in_terminal_event_do_not_change_answer_equality(self):
        value=completed();stream=events(value)
        stream[-1]['response']['output'][1]['action']['sources']=[]
        stream[-1]['response']['output'][2]['content'][0]['annotations']=[]
        a,_=self.adapter(client=FakeClient([stream]))
        self.assertEqual(a.investigate(ITEM)['status'],'suggested')
        self.assertEqual(self.reads,[URL])

    def test_usage_or_output_bounds_stop_future_calls(self):
        for value in (None,SUMMARY_MAX_TOKENS+1):
            response=completed()
            if value is None:response['usage']=None
            else:response['usage']['output_tokens']=value;response['usage']['total_tokens']=90+value
            a,client=self.adapter([response])
            with self.assertRaises(ResearchFailure):a.investigate(ITEM)
            with self.assertRaises(ResearchFailure):a.investigate(ITEM)
            self.assertEqual(len(client.calls),1)

    def test_hosted_search_count_is_checked_after_completion_not_claimed_as_server_cap(self):
        response=completed()
        response['output'][1:1]=[dict(copy.deepcopy(response['output'][1]),id='ws_extra_'+str(i)) for i in range(3)]
        a,client=self.adapter([response])
        with self.assertRaises(ResearchFailure) as caught:a.investigate(ITEM)
        self.assertEqual(caught.exception.code,'research_output_or_tool_bound')
        self.assertEqual(len(client.calls),1)
        self.assertNotIn('max_tool_calls',client.calls[0])
        self.assertEqual(self.reads,[])

    def test_wrong_completion_model_and_credentials_never_retried(self):
        value=completed();value['model']='wrong-model'
        a,client=self.adapter([value])
        with self.assertRaises(ResearchFailure):a.investigate(ITEM)
        with self.assertRaises(ResearchFailure):a.investigate(ITEM)
        self.assertEqual(len(client.calls),1)
        bad=FakeClient();bad.auth_headers={'Authorization':'Bearer wrong'}
        with self.assertRaises(ResearchFailure):self.adapter(client=bad)

    def test_limit_and_credential_headers_checked(self):
        a,client=self.adapter(limit=1)
        a.investigate(ITEM)
        with self.assertRaises(ResearchFailure):a.investigate(ITEM)
        self.assertEqual(len(client.calls),1)
        bad=FakeClient();bad.default_headers={'Authorization':'Bearer synthetic-wrong'}
        with self.assertRaises(ResearchFailure):self.adapter(client=bad)
        self.assertEqual(bad.calls,[])

    def test_official_redirect_missing_page_and_isolated_outage_are_recorded(self):
        def missing(url):raise OfficialReadError('official_page_unverified')
        a,_=self.adapter(fetcher=missing)
        self.assertEqual(a.investigate(ITEM)['status'],'no_evidence')
        def unavailable(url):raise OfficialReadError('official_read_unavailable')
        a,client=self.adapter(fetcher=unavailable)
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.last_diagnostic['code'],'official_read_unavailable')
        self.assertEqual(a.investigate({**ITEM,'id':'next'})['status'],'error')
        self.assertEqual(len(client.calls),2)

    def test_pipe_path_uses_common_auth_and_emits_only_safe_proposals(self):
        def factory(provider,**kwargs):
            return create_location_research_adapter(provider,**kwargs,manager=self.owner.manager(),
                client=FakeClient([events(completed())]),fetch_page=lambda url:EVIDENCE['excerpt'])
        source=io.StringIO('\n'.join(map(json.dumps,[{'action':'ready','limit':1,'choices':CHOICES,'instructions':'현재 검토값으로 공식 장소 조사'},
            {'action':'investigate','item':ITEM},{'action':'close'}]))+'\n')
        out=io.StringIO()
        with patch.dict('os.environ',{'AI_PROVIDER':'chatgpt_plan'}):serve(source,out,factory=factory)
        values=[json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(values),3)
        self.assertTrue(all(x['ok'] for x in values))
        self.assertEqual(values[1]['answer']['evidence'],EVIDENCE)
        self.assertEqual(values[1]['stats']['requests'],1)
        for secret in ('synthetic-refresh','access_token','id_token','Authorization'):
            self.assertNotIn(secret,out.getvalue())


    def test_diagnostic_keeps_actual_text_sources_quote_checks_and_failure_stage(self):
        a,_=self.adapter(fetcher=lambda url:'다른 위치 문구')
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        d=a.last_diagnostic
        self.assertEqual((d['stage'],d['code']),('official_page','research_quote_not_in_page'))
        self.assertEqual(d['official']['pageText'],'다른 위치 문구')
        self.assertFalse(d['official']['checks']['quoteInPage'])
        self.assertIn(URL,d['sources'])
        self.assertEqual(json.loads(d['response']['output'][2]['content'][0]['text'])['evidence'],EVIDENCE)

    def test_distinct_item_diagnostics_survive_next_response(self):
        variants=[(None,'research_json_invalid'),({'status':'suggested','evidence':{**EVIDENCE,'place':'다른 장소'}},'research_place_not_in_description')]
        for answer,expected in variants:
            value=completed(answer)
            if answer is None:value['output'][2]['content'][0]['text']='{broken actual response'
            a,_=self.adapter([value,completed()])
            self.assertEqual(a.investigate(ITEM)['status'],'error')
            old=copy.deepcopy(a.last_diagnostic)
            self.assertEqual(old['code'],expected)
            self.assertEqual(a.investigate({**ITEM,'id':'next'})['status'],'suggested')
            self.assertEqual(old['code'],expected)

    def test_missing_search_source_has_specific_reason_without_official_read(self):
        value=completed();value['output'][1]['action']['sources']=[];value['output'][2]['content'][0]['annotations']=[]
        a,_=self.adapter([value])
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.last_diagnostic['code'],'research_url_not_in_search_sources')
        self.assertEqual(self.reads,[])

    def test_timeout_and_5xx_are_one_attempt_then_a_different_item(self):
        for exception in (TimeoutError('private timeout details'),type('Unavailable',(Exception,),{'status_code':503})('private server response')):
            client=FakeClient([[],events(completed())]);original=client.create
            def create(**request):
                if not client.calls:client.calls.append(request);raise exception
                return original(**request)
            client.responses.create=create
            a,_=self.adapter(client=client)
            self.assertEqual(a.investigate(ITEM)['status'],'error')
            self.assertIn(a.last_diagnostic['code'],('plan_timeout','plan_transport_unknown','plan_http_503'))
            self.assertNotIn('private',json.dumps(a.last_diagnostic))
            self.assertEqual(a.investigate({**ITEM,'id':'next'})['status'],'suggested')
            self.assertEqual(len(client.calls),2)

    def test_partial_output_is_kept_redacted_without_accepting_a_proposal(self):
        a,_=self.adapter(client=FakeClient([[{'type':'response.output_text.delta','delta':'partial Bearer synthetic-secret'}]]))
        self.assertEqual(a.investigate(ITEM)['status'],'error')
        self.assertEqual(a.last_diagnostic['partialText'],'partial Bearer [REDACTED]')

    def test_diagnostics_exclude_auth_metadata_and_reasoning_content(self):
        value=completed();value['headers']={'Authorization':'synthetic-header-secret'}
        value['output'][0]['encrypted_content']='synthetic-hidden-reasoning'
        value['output'][2]['content'][0]['text']='{"api_key":"synthetic-response-secret"}'
        a,_=self.adapter([value]);a.investigate(ITEM)
        logged=json.dumps(a.last_diagnostic)
        for secret in ('synthetic-header-secret','synthetic-hidden-reasoning','synthetic-response-secret'):
            self.assertNotIn(secret,logged)
        self.assertIn('[REDACTED]',logged)

    def test_diagnostic_capacity_failure_is_fatal(self):
        value=completed();value['output'][2]['content'][0]['text']='x'*600001
        a,client=self.adapter([value])
        with self.assertRaises(ResearchFailure) as caught:a.investigate(ITEM)
        self.assertEqual(caught.exception.code,'research_record_error')
        with self.assertRaises(ResearchFailure):a.investigate(ITEM)
        self.assertEqual(len(client.calls),1)

    def test_auth_and_quota_codes_inside_sse_are_fatal_not_item_errors(self):
        from ingest.location_plan_research import PROVIDER_STOPS
        for code in PROVIDER_STOPS:
            for kind in ('error','response.failed'):
                event={'type':kind,'error':{'code':code,'message':'private provider text'}}
                if kind=='response.failed':event={'type':kind,'response':{'error':event['error']}}
                a,client=self.adapter(client=FakeClient([[event],events(completed())]))
                with self.assertRaises(ResearchFailure) as caught:a.investigate(ITEM)
                self.assertEqual(caught.exception.code,code)
                self.assertEqual(a.last_diagnostic['providerCode'],code)
                self.assertNotIn('private',json.dumps(a.last_diagnostic))
                with self.assertRaises(ResearchFailure):a.investigate(ITEM)
                self.assertEqual(len(client.calls),1)


class OfficialReadTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        guard.start();self.addCleanup(guard.stop)

    def test_official_hosts_only_no_credentials_or_private_targets(self):
        self.assertEqual(official_url(URL),URL)
        for url in ('http://seoul.go.kr/x','https://127.0.0.1/x','https://seoul.go.kr.evil.test/',
                    'https://user:pass@seoul.go.kr/x','https://seoul.go.kr:443/x','https://seoul.go.kr/?token=secret'):
            with self.assertRaises(OfficialReadError):official_url(url)

    def test_visible_html_only_and_size_type_charset_bounds(self):
        body=('<script>서울 잘못된구 가짜주소</script><p>'+EVIDENCE['excerpt']+'</p>').encode()
        text=page_text(body,'text/html; charset=utf-8')
        self.assertIn(EVIDENCE['excerpt'],text)
        self.assertNotIn('잘못된구',text)
        for body,kind in ((b'x'*(MAX_PAGE_BYTES+1),'text/plain'),(b'{}','application/json'),(b'\xff','text/html; charset=utf-8')):
            with self.assertRaises(OfficialReadError):page_text(body,kind)

    def test_fake_read_one_get_no_auth_no_redirect_no_retry(self):
        calls=[]
        class Conn:
            def __init__(self,*args,**kwargs):calls.append(('init',args,kwargs))
            def request(self,*args,**kwargs):calls.append(('request',args,kwargs))
            def getresponse(self):return SimpleNamespace(status=200,getheader=lambda k,default=None:{'Content-Type':'text/html'}.get(k,default),read=lambda n:('<p>'+EVIDENCE['excerpt']+'</p>').encode())
            def close(self):calls.append(('close',))
        self.assertIn(EVIDENCE['excerpt'],read_official_page(URL,connection_factory=Conn))
        request=[c for c in calls if c[0]=='request'][0]
        self.assertEqual(request[1],('GET','/synthetic?item=1&menu=2'))
        self.assertNotIn('Authorization',request[2]['headers'])
        self.assertEqual(len([c for c in calls if c[0]=='request']),1)
        for status in (301,404,503):
            class Failure(Conn):
                def getresponse(self):return SimpleNamespace(status=status)
            with self.assertRaises(OfficialReadError):read_official_page(URL,connection_factory=Failure)

    def test_private_dns_answers_rejected_before_connect(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),patch('socket.create_connection') as connect:
            with self.assertRaises(OfficialReadError):PublicHTTPS('parks.seoul.go.kr').connect()
            connect.assert_not_called()

    def test_public_ip_is_pinned_and_tls_checks_original_hostname(self):
        import ssl
        context=ssl.create_default_context()
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch('socket.create_connection') as connect,patch.object(context,'wrap_socket') as tls:
            connection=PublicHTTPS('parks.seoul.go.kr',timeout=15,context=context)
            connection.connect()
            connect.assert_called_once_with(('8.8.8.8',443),timeout=15)
            tls.assert_called_once_with(connect.return_value,server_hostname='parks.seoul.go.kr')


if __name__=='__main__':unittest.main()
