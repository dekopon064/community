"""Explicit local-only SIWC probe. No DB imports, API keys, workers or env files."""
from __future__ import annotations

import argparse
import importlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
import time
import sys
from urllib.parse import urlsplit
from ingest.ai_errors import AiJobError
from ingest.chatgpt_plan_auth import registration, fetch

from ingest.chatgpt_plan_probe import (AuthorizationAttempt, ChatGPTPlanProbe, ProbeError,
    DISCOVERY, TOKEN, JWKS, RESOURCE, validate_discovery, verify_grant, model_available,
    synthetic_context, DiagnosticClient, get_field)


def usage_summary(records):
    """Only aggregate counters, never provider attribution/message identifiers."""
    return [{'stage':record['stage'],'model':record['model'],'billing':record['billing'],
        'usage':{key:get_field(record['usage'],key) for key in ('input_tokens','output_tokens','total_tokens')},
        'reasoning_tokens':get_field(get_field(record['usage'],'output_tokens_details'),'reasoning_tokens')}
        for record in records]


def execute(*, diagnostic_session=False):
    if diagnostic_session and not sys.stdin.isatty():
        raise ProbeError('diagnostic_session_requires_terminal')
    import requests
    from openai import OpenAI
    from ingest.myseoul_ai import generate_myseoul_output
    path=Path(tempfile.gettempdir())/'machimoa-chatgpt-plan-probe'/'registration.json'
    record=registration(path)
    with requests.Session() as session:
        validate_discovery(fetch(session,DISCOVERY))
        result={}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,body):
                self.send_response(status)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
                self.end_headers();self.wfile.write(body.encode('utf-8'))
            def do_GET(self):
                if self.headers.get('Host')!=f'127.0.0.1:{server.server_port}':
                    self.reply(400,'Invalid host');return
                route=urlsplit(self.path)
                if route.path=='/':
                    self.reply(200,'<h1>마치모아 Pro 로컬 검증</h1><p>DB 연결 없이 합성 요약·번역을 최대 2회 실행합니다. API 키 전환은 없습니다.</p><p>토큰은 메모리에만 보관합니다.</p><a href="/auth/start">Continue with ChatGPT</a>')
                elif route.path=='/auth/start':
                    self.send_response(302);self.send_header('Location',attempt.url)
                    self.send_header('Cache-Control','no-store');self.end_headers()
                elif route.path=='/auth/callback':
                    try:
                        result['form']=attempt.consume(route.query)
                        self.reply(200,'<h1>인증 응답 수신</h1><p>이 창을 닫으셔도 됩니다. 검증 결과는 Codex에서 안내합니다.</p>')
                    except ProbeError as exc:
                        self.reply(400,'<h1>인증을 완료하지 못했습니다.</h1>')
                        if attempt.consumed:result['error']=exc.code
                else:self.reply(404,'Not found')
        with HTTPServer(('127.0.0.1',0),Handler) as server:
            server.timeout=1
            attempt=AuthorizationAttempt(record['host_id'],f'http://127.0.0.1:{server.server_port}/auth/callback',record.get('client_id'))
            print('ProbeReady http://127.0.0.1:'+str(server.server_port)+'/',flush=True)
            deadline=time.monotonic()+600
            while not result and time.monotonic()<deadline:
                server.handle_request()
        if 'error' in result:raise ProbeError(result['error'])
        if 'form' not in result:raise ProbeError('authorization_wait_expired')
        form=result.pop('form')
        response=session.post(TOKEN,data=form,timeout=30,allow_redirects=False)
        if response.status_code!=200:
            raise ProbeError('token_exchange_http_'+str(response.status_code))
        grant=response.json()
        access=verify_grant(grant,client_id=form['client_id'],nonce=attempt.nonce,keys=fetch(session,JWKS))
        record['client_id']=form['client_id']
        # Persist registration metadata only, never tokens, identity or codes.
        temporary=path.with_suffix('.new')
        temporary.write_text(json.dumps(record),encoding='utf-8');temporary.replace(path)
        form.clear();grant.clear()
        print('PlanPermissionVerified',flush=True)
        model_available(fetch(session,RESOURCE+'/models',headers={'Authorization':'Bearer '+access}))
        print('GPT61SolInAccountCatalog',flush=True)
    with OpenAI(api_key=access,base_url=RESOURCE,max_retries=0,timeout=120) as client:
        diagnostic=DiagnosticClient(client)
        while True:
            # Reload only local validation modules after an explicit operator command.
            for name in ('ingest.ai_openai','ingest.translation_validation','ingest.myseoul_content',
                         'ingest.myseoul_ai','ingest.chatgpt_plan_probe'):
                importlib.reload(importlib.import_module(name))
            module=importlib.import_module('ingest.chatgpt_plan_probe')
            probe=module.ChatGPTPlanProbe(diagnostic)
            try:
                output=importlib.import_module('ingest.myseoul_ai').generate_myseoul_output(
                    module.synthetic_context(),summarize_ko=probe.summarize_myseoul_ko,translate_ja=probe.translate_ja)
            except (module.ProbeError,AiJobError) as exc:
                # Only this launcher's synthetic data. Credentials/identity never logged.
                print(json.dumps({'status':'blocked','code':exc.code,'stage':probe.stage,
                    'generations':probe.calls,'network_generations':diagnostic.network_calls,
                    'db_connected':False,'fallback':False,
                    'stream_events':probe.stream_events,
                    'synthetic_responses':probe.diagnostic_responses,
                    'validated_synthetic_json':probe.validated_payloads},ensure_ascii=False),flush=True)
                if not diagnostic_session:return 1
                print('DiagnosticPaused: recheck (completed responses reused) / stop',flush=True)
                if input().strip()!='recheck':return 1
                continue
            usage=usage_summary(probe.usage)
            print(json.dumps({'status':'validated','generations':probe.calls,
                'network_generations':diagnostic.network_calls,'db_connected':False,
                'billing':'chatgpt_plan','output':output,'usage':usage},ensure_ascii=False),flush=True)
            break
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--diagnostic-session',action='store_true')
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps({'mode':'validation_only','network_calls':0,'db_connected':False,'api_key_fallback':False}))
        return 0
    try:return execute(diagnostic_session=args.diagnostic_session)
    except ProbeError as exc:
        print(json.dumps({'status':'blocked','code':exc.code,'fallback':False}),flush=True);return 1
    except Exception as exc:
        print(json.dumps({'status':'blocked','code':'local_validation_or_transport_failed','kind':type(exc).__name__,'fallback':False}),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
