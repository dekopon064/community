"""No network/DB tests of OAuth validation and subscription-only request handling."""
import copy
import json
import socket
import time
import unittest
from types import SimpleNamespace
from urllib.parse import urlencode,parse_qs,urlsplit
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from ingest.chatgpt_plan_probe import (AuthorizationAttempt,ProbeError,verify_grant,
    model_available,probe_request,ChatGPTPlanProbe,validate_discovery,
    ISSUER,RESOURCE,AUTHORIZE,TOKEN,JWKS,SCOPES,DiagnosticClient)
from ingest.ai_openai import GPT_MODEL
from ingest.ai_errors import AiJobError
from test_ingest_ai_openai import response,SUMMARY_JSON,TRANSLATION_JSON


class FakeStream:
    def __init__(self,events):self.events=events
    def __enter__(self):return iter(self.events)
    def __exit__(self,*args):pass


class FakeClient:
    max_retries=0
    def __init__(self,events=None):
        self.calls=[]
        self.events=events or [[{'type':'response.completed','response':response(SUMMARY_JSON)}],
                              [{'type':'response.completed','response':response(TRANSLATION_JSON)}]]
        self.responses=SimpleNamespace(create=self.create)
    def create(self,**request):
        self.calls.append(request)
        return FakeStream(self.events[len(self.calls)-1])


class ProProbeTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        p.start();self.addCleanup(p.stop)

    def attempt(self,client=None):
        return AuthorizationAttempt('urn:uuid:00000000-0000-4000-8000-000000000001',
            'http://127.0.0.1:1455/auth/callback',client)

    def test_registration_pkce_issued_client_and_one_time_state(self):
        a=self.attempt();params=parse_qs(urlsplit(a.url).query)
        self.assertEqual(params['client_id'],['dynamic_agent_client'])
        self.assertEqual(params['resource'],[RESOURCE])
        self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertNotIn(a.verifier,a.url)
        with self.assertRaises(ProbeError):a.consume(urlencode({'state':'wrong','code':'secret'}))
        form=a.consume(urlencode({'state':a.state,'code':'secret','client_id':'oaiapp_synthetic'}))
        self.assertEqual(form['redirect_uri'],a.redirect_uri)
        self.assertEqual(form['client_id'],'oaiapp_synthetic')
        self.assertEqual(form['code_verifier'],a.verifier)
        with self.assertRaises(ProbeError):a.consume(urlencode({'state':a.state,'code':'secret'}))

    def test_expired_duplicate_denied_and_mismatched_client(self):
        for case in ('expired','duplicate','denied','client'):
            a=self.attempt('oaiapp_existing')
            q={'state':a.state,'code':'secret','client_id':'oaiapp_existing'}
            if case=='expired':a.created-=601
            if case=='denied':q['error']='access_denied'
            if case=='client':q['client_id']='oaiapp_other'
            query=urlencode(q)
            if case=='duplicate':query+='&state=other'
            with self.assertRaises(ProbeError):a.consume(query)
        with self.assertRaises(ProbeError):AuthorizationAttempt('urn:uuid:x','http://localhost:1455/auth/callback')

    def grant(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));public['kid']='synthetic'
        common={'iss':ISSUER,'sub':'synthetic-subject','iat':int(time.time()),'exp':int(time.time())+60}
        id_claims={**common,'aud':'oaiapp_synthetic','nonce':'nonce'}
        access_claims={**common,'aud':RESOURCE,'client_id':'oaiapp_synthetic','scope':SCOPES}
        encode=lambda claims:jwt.encode(claims,key,algorithm='RS256',headers={'kid':'synthetic'})
        grant={'token_type':'Bearer','scope':SCOPES,'id_token':encode(id_claims),'access_token':encode(access_claims)}
        return grant,{'keys':[public]},encode,id_claims,access_claims

    def test_signed_grant_nonce_audience_issuer_expiry_scope_and_client(self):
        grant,keys,encode,idclaims,accessclaims=self.grant()
        args=dict(client_id='oaiapp_synthetic',nonce='nonce',keys=keys)
        self.assertEqual(verify_grant(grant,**args),grant['access_token'])
        for field,value in [('nonce','wrong'),('aud','wrong'),('iss','https://wrong.invalid'),('exp',1)]:
            altered=copy.deepcopy(grant);altered['id_token']=encode({**idclaims,field:value})
            with self.assertRaises(ProbeError):verify_grant(altered,**args)
        for field,value in [('aud','wrong'),('scope','openid'),('client_id','oaiapp_other'),('sub','other-subject')]:
            altered=copy.deepcopy(grant);altered['access_token']=encode({**accessclaims,field:value})
            with self.assertRaises(ProbeError):verify_grant(altered,**args)
        altered=copy.deepcopy(grant);altered['scope']='openid'
        with self.assertRaises(ProbeError):verify_grant(altered,**args)
        alien,*_=self.grant()
        with self.assertRaises(ProbeError):verify_grant(alien,**args)

    def test_official_metadata_and_account_model_required(self):
        data=dict(issuer=ISSUER,authorization_endpoint=AUTHORIZE,token_endpoint=TOKEN,jwks_uri=JWKS)
        validate_discovery(data)
        with self.assertRaises(ProbeError):validate_discovery({**data,'jwks_uri':'https://evil.invalid'})
        model_available({'models':[{'slug':GPT_MODEL,'visibility':'list'}]})
        with self.assertRaises(ProbeError):model_available({'models':[{'slug':'other','visibility':'list'}]})

    def test_requests_have_no_paid_api_options_and_exact_json_schemas(self):
        for stage in ('summary','translation'):
            req=probe_request(stage,'synthetic')
            self.assertEqual(req['model'],GPT_MODEL)
            self.assertTrue(req['stream']);self.assertFalse(req['store'])
            self.assertTrue(req['text']['format']['strict'])
            self.assertFalse({'max_output_tokens','truncation','service_tier','tools','previous_response_id','api_key'} & req.keys())
        client=FakeClient();probe=ChatGPTPlanProbe(client)
        self.assertEqual(probe.summarize_myseoul_ko('synthetic',None)[2],GPT_MODEL)
        self.assertEqual(probe.stage,'korean_body_assembly_validation')
        self.assertEqual(set(probe.validated_payloads),{'summary'})
        self.assertEqual(probe.translate_ja('합성','한국어 요약입니다.')[3],GPT_MODEL)
        self.assertEqual(probe.stage,'candidate_body_validation')
        self.assertEqual(set(probe.validated_payloads),{'summary','translation'})
        self.assertEqual(len(client.calls),2)
        self.assertEqual(probe.usage[0]['billing'],'chatgpt_plan')
        with self.assertRaises(ProbeError):probe.translate_ja('합성','한국어 요약입니다.')

    def test_partial_stream_failure_usage_limit_and_incomplete_never_accept_json(self):
        bad=[[],[{'type':'response.output_text.delta','delta':SUMMARY_JSON}],
             [{'type':'response.incomplete','response':response(SUMMARY_JSON,status='incomplete')}],
             [{'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded'}}}]]
        for events in bad:
            client=FakeClient([events]);probe=ChatGPTPlanProbe(client)
            with self.assertRaises(ProbeError):probe.summarize_myseoul_ko('synthetic',None)
            with self.assertRaises(ProbeError):probe.translate_ja('합성','본문')
            self.assertEqual(len(client.calls),1)

    def test_invalid_json_extra_fields_and_numeric_role_swap_rejected(self):
        for value in ['```json\n'+SUMMARY_JSON+'\n```',json.dumps({**json.loads(SUMMARY_JSON),'review':'extra'})]:
            client=FakeClient([[{'type':'response.completed','response':response(value)}]])
            with self.assertRaises(AiJobError):ChatGPTPlanProbe(client).summarize_myseoul_ko('synthetic',None)
        client=FakeClient();probe=ChatGPTPlanProbe(client);probe.summarize_myseoul_ko('synthetic',None)
        wrong=json.dumps({'title_ja':'合成','content_ja':'受講料: 2,000ウォン; 材料費: 10,000ウォン'})
        client.events[1]=[{'type':'response.completed','response':response(wrong)}]
        with self.assertRaises(AiJobError):probe.translate_ja('합성','수강료: 10,000원; 재료비: 2,000원')
        self.assertEqual(len(client.calls),2)

    def test_installed_sdk_streams_exact_json_without_network_or_retry(self):
        import httpx
        from openai import OpenAI
        requests=[]
        def handle(request):
            payload=json.loads(request.content);requests.append(payload)
            text=SUMMARY_JSON if len(requests)==1 else TRANSLATION_JSON
            completed=response(text)
            done={'type':'response.output_item.done','output_index':1,'item':completed['output'][1]}
            event={'type':'response.completed','response':{**completed,'output':[]}}
            return httpx.Response(200,headers={'Content-Type':'text/event-stream'},
                text='event: response.output_item.done\ndata: '+json.dumps(done)+'\n\n'
                     'event: response.completed\ndata: '+json.dumps(event)+'\n\ndata: [DONE]\n\n')
        with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
            with OpenAI(api_key='synthetic-oauth-not-a-key',max_retries=0,http_client=transport) as client:
                probe=ChatGPTPlanProbe(client)
                probe.summarize_myseoul_ko('synthetic',None)
                probe.translate_ja('합성','한국어 요약입니다.')
        self.assertEqual(len(requests),2)
        self.assertTrue(all(r['stream'] and not r['store'] for r in requests))

    def test_diagnostic_replay_never_exceeds_two_actual_generation_requests(self):
        client=FakeClient();cached=DiagnosticClient(client)
        for request in ({'input':'summary'},{'input':'summary'},{'input':'translation'},{'input':'translation'}):
            with cached.responses.create(**request) as events:list(events)
        self.assertEqual(cached.network_calls,2)
        self.assertEqual(len(client.calls),2)
        with self.assertRaises(ProbeError):
            with cached.responses.create(input='different'):pass
        self.assertEqual(len(client.calls),2)

    def test_terminal_message_json_survives_empty_completed_envelope(self):
        full=response(SUMMARY_JSON);message=full['output'][1]
        empty={**full,'output':[]}
        done={'type':'response.output_item.done','output_index':1,'item':message}
        complete={'type':'response.completed','response':empty}
        client=FakeClient([[done,complete]])
        probe=ChatGPTPlanProbe(DiagnosticClient(client))
        self.assertEqual(probe.summarize_myseoul_ko('synthetic',None)[0],json.loads(SUMMARY_JSON)['content_ko'])
        self.assertEqual(probe.stream_events['summary']['response.output_item.done'],1)
        for events in ([done], [done,done,complete],
                       [done,{'type':'response.incomplete','response':empty}]):
            with self.assertRaises(ProbeError):
                ChatGPTPlanProbe(FakeClient([events])).summarize_myseoul_ko('synthetic',None)
        with self.assertRaises(AiJobError):
            ChatGPTPlanProbe(FakeClient([[complete]])).summarize_myseoul_ko('synthetic',None)

    def test_conflicting_final_and_terminal_json_is_rejected(self):
        done={'type':'response.output_item.done','output_index':1,
              'item':response(SUMMARY_JSON)['output'][1]}
        altered=json.dumps({**json.loads(SUMMARY_JSON),'content_ko':'different'})
        final={'type':'response.completed','response':response(altered)}
        with self.assertRaises(ProbeError):
            ChatGPTPlanProbe(FakeClient([[done,final]])).summarize_myseoul_ko('synthetic',None)

    def test_noninteractive_diagnostic_session_stops_before_auth_or_model(self):
        import run_chatgpt_plan_probe as runner
        with patch.object(runner.sys.stdin,'isatty',return_value=False):
            with self.assertRaises(ProbeError) as raised:
                runner.execute(diagnostic_session=True)
        self.assertEqual(raised.exception.code,'diagnostic_session_requires_terminal')

    def test_usage_diagnostics_omit_response_identifiers_and_attribution(self):
        from run_chatgpt_plan_probe import usage_summary
        records=[{'stage':'summary','model':GPT_MODEL,'billing':'chatgpt_plan',
            'usage':{**response(SUMMARY_JSON)['usage'],'total_tokens':110,
                     'attribution':{'items':{'private-message-id':{}}}}}]
        value=json.dumps(usage_summary(records))
        self.assertNotIn('private-message-id',value)
        self.assertNotIn('attribution',value)
        self.assertIn('reasoning_tokens',value)

    def test_unknown_or_partial_response_cannot_be_resent_by_recheck(self):
        for events in ([],[{'type':'response.output_text.delta','delta':SUMMARY_JSON}],
                       [{'type':'response.failed','response':{'error':{'code':'unknown'}}}]):
            client=FakeClient([events]);diagnostic=DiagnosticClient(client)
            with diagnostic.responses.create(input='synthetic') as stream:list(stream)
            with self.assertRaises(ProbeError):
                with diagnostic.responses.create(input='synthetic'):pass
            self.assertEqual(len(client.calls),1)


if __name__=='__main__':unittest.main()
