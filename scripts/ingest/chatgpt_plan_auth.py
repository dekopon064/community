"""Explicit local ChatGPT sign-in, verified access in memory, no inference or DB."""
from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from ingest.chatgpt_plan_protocol import (AuthorizationAttempt, ProbeError, DISCOVERY,
    TOKEN, JWKS, RESOURCE, verify_grant, validate_discovery, model_available)

_VERIFIED = object()


@dataclass(repr=False)
class PlanSession:
    """One selected account; no raw key constructor or silent refresh/fallback."""
    _access: str = field(repr=False)
    expires_at: float
    _verified: object = field(repr=False)

    def __post_init__(self):
        if self._verified is not _VERIFIED:
            raise ProbeError('unverified_plan_session')

    def __repr__(self):
        return 'PlanSession(credentials=redacted)'

    @classmethod
    def from_grant(cls, grant, *, client_id, nonce, keys, catalog):
        access = verify_grant(grant, client_id=client_id, nonce=nonce, keys=keys)
        model_available(catalog)
        import jwt
        # Signature/audience/issuer/subject/permission checked above.
        expiry = jwt.decode(access, options={'verify_signature':False})['exp']
        if type(expiry) not in {int, float}:
            raise ProbeError('invalid_access_expiry')
        session = cls(access, expiry, _VERIFIED)
        session.require_active()
        return session

    def require_active(self):
        # Leave enough time for both existing 120-second stages before a claim.
        if not self._access or time.time() + 250 >= self.expires_at:
            raise ProbeError('chatgpt_plan_reauthentication_required')

    def access_token(self):
        self.require_active()
        return self._access

    def clear(self):
        self._access = ''


def registration(path):
    """Persist opaque host/client registration only, never tokens or identity."""
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - {'host_id','client_id'}:
            raise ProbeError('unexpected_registration_file')
        UUID(data['host_id'].removeprefix('urn:uuid:'))
        return data
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'host_id':'urn:uuid:' + str(uuid4())}
    with path.open('x', encoding='utf-8') as file:
        json.dump(data, file)
    return data


def fetch(session, url, **kwargs):
    response = session.get(url, timeout=30, allow_redirects=False, **kwargs)
    if response.status_code != 200:
        raise ProbeError('official_get_http_' + str(response.status_code))
    return response.json()


def authenticate_worker():
    """Invoked only by explicit plan provider execution; never in dry-run."""
    if not sys.stdin.isatty():
        raise ProbeError('chatgpt_plan_login_requires_terminal')
    import requests
    path = Path(tempfile.gettempdir()) / 'machimoa-chatgpt-plan-probe' / 'registration.json'
    record = registration(path)
    with requests.Session() as http:
        validate_discovery(fetch(http, DISCOVERY))
        result = {}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def setup(self):
                super().setup()
                self.connection.settimeout(2)
            def reply(self, status, body):
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'none'; form-action 'self'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(body.encode('utf-8'))
            def do_GET(self):
                if self.headers.get('Host') != f'127.0.0.1:{server.server_port}':
                    self.reply(400, 'Invalid host')
                    return
                route = urlsplit(self.path)
                if route.path == '/':
                    self.reply(200, '<h1>마치모아 worker 로그인</h1><p>선택한 ChatGPT 계정의 구독 사용량으로 요약·번역합니다. 작업당 최대 2회 호출합니다. 유료 API 전환은 없습니다. 인증은 이 실행의 메모리에만 보관합니다.</p><a href="/auth/start">Continue with ChatGPT</a>')
                elif route.path == '/auth/start':
                    self.send_response(302)
                    self.send_header('Location', attempt.url)
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                elif route.path == '/auth/callback':
                    try:
                        result['form'] = attempt.consume(route.query)
                        self.reply(200, '<p>인증 응답을 받았습니다. 터미널에서 결과를 확인해 주세요.</p>')
                    except ProbeError as exc:
                        self.reply(400, '<p>인증을 완료하지 못했습니다.</p>')
                        if attempt.consumed:
                            result['error'] = exc.code
                else:
                    self.reply(404, 'Not found')
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            server.timeout = 1
            attempt = AuthorizationAttempt(record['host_id'],
                f'http://127.0.0.1:{server.server_port}/auth/callback', record.get('client_id'),
                renewable=False, app_name='Machimoa summary translation worker')
            print(f'ChatGPTWorkerLogin http://127.0.0.1:{server.server_port}/', flush=True)
            deadline = time.monotonic() + 600
            while not result and time.monotonic() < deadline:
                server.handle_request()
        if 'error' in result:
            raise ProbeError(result['error'])
        if 'form' not in result:
            raise ProbeError('authorization_wait_expired')
        form = result.pop('form')
        try:
            response = http.post(TOKEN, data=form, timeout=30, allow_redirects=False)
            if response.status_code != 200:
                raise ProbeError('token_exchange_http_' + str(response.status_code))
            grant = response.json()
            try:
                keys = fetch(http, JWKS)
                access = verify_grant(grant, client_id=form['client_id'], nonce=attempt.nonce, keys=keys)
                catalog = fetch(http, RESOURCE + '/models', headers={'Authorization':'Bearer ' + access})
                selected = PlanSession.from_grant(grant, client_id=form['client_id'],
                    nonce=attempt.nonce, keys=keys, catalog=catalog)
                try:
                    record['client_id'] = form['client_id']
                    temporary = path.with_suffix('.new')
                    temporary.write_text(json.dumps(record), encoding='utf-8')
                    temporary.replace(path)
                except Exception:
                    selected.clear()
                    raise
                return selected
            finally:
                grant.clear()
        finally:
            form.clear()
