"""Shared SIWC OAuth validation and terminal-stream reader. No diagnostic fixtures."""
from __future__ import annotations
import base64
import hashlib
import secrets
import time
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID
from ingest.ai_openai import GPT_MODEL, extract_payload

ISSUER = 'https://auth.openai.com'
DISCOVERY = ISSUER + '/.well-known/openid-configuration'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
JWKS = ISSUER + '/.well-known/jwks.json'
RESOURCE = 'https://api.openai.com/v1'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
APP_NAME = 'Machimoa local summary translation probe'


class ProbeError(Exception):
    """Fixed, non-secret authentication/stream diagnostics."""
    def __init__(self, code, *, diagnostic=None):
        self.code = code
        self.diagnostic = diagnostic
        super().__init__(code)


def validate_discovery(data):
    expected = dict(issuer=ISSUER, authorization_endpoint=AUTHORIZE,
                    token_endpoint=TOKEN, jwks_uri=JWKS)
    if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
        raise ProbeError('unexpected_oidc_metadata')


class AuthorizationAttempt:
    def __init__(self, host_id, redirect_uri, client_id=None, *, renewable=True, app_name=APP_NAME):
        try:
            if not isinstance(host_id, str) or not host_id.startswith('urn:uuid:'):
                raise ValueError()
            UUID(host_id.removeprefix('urn:uuid:'))
        except (TypeError, ValueError):
            raise ProbeError('invalid_host_id') from None
        if client_id is not None and (not isinstance(client_id, str) or
                not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}', client_id) or client_id=='dynamic_agent_client'):
            raise ProbeError('invalid_issued_client')
        uri = urlsplit(redirect_uri)
        if (uri.scheme != 'http' or uri.hostname != '127.0.0.1' or
                not uri.port or uri.path != '/auth/callback' or uri.query or uri.fragment or
                uri.username is not None or uri.password is not None):
            raise ProbeError('invalid_callback')
        self.redirect_uri = redirect_uri
        self.client_id = client_id
        self.state, self.nonce, self.verifier = (secrets.token_urlsafe(32) for _ in range(3))
        self.created = time.monotonic()
        self.consumed = False
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
        params = dict(client_id=client_id or 'dynamic_agent_client',
            ext_agent_host_id=host_id, response_type='code', redirect_uri=redirect_uri,
            scope=SCOPES if renewable else SCOPES.replace('offline_access ', ''),
            resource=RESOURCE, state=self.state, nonce=self.nonce,
            code_challenge_method='S256', code_challenge=challenge)
        if not client_id:
            params['agent_name_hint'] = app_name
        self.url = AUTHORIZE + '?' + urlencode(params)

    def consume(self, query):
        try:
            values = parse_qs(query, keep_blank_values=True, max_num_fields=12)
        except ValueError:
            raise ProbeError('invalid_callback') from None
        if any(len(v) != 1 for v in values.values()):
            raise ProbeError('invalid_callback')
        if (self.consumed or time.monotonic()-self.created > 600 or
                not secrets.compare_digest(values.get('state', [''])[0], self.state)):
            raise ProbeError('invalid_oauth_state')
        self.consumed = True
        if 'error' in values:
            raise ProbeError('authorization_not_granted')
        client = values.get('client_id', [self.client_id])[0]
        if (not isinstance(client, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}',client) or
                client=='dynamic_agent_client' or
                self.client_id is not None and client != self.client_id):
            raise ProbeError('invalid_issued_client')
        code = values.get('code', [''])[0]
        if not code or len(code) > 8192:
            raise ProbeError('missing_authorization_code')
        return dict(grant_type='authorization_code', client_id=client, code=code,
            code_verifier=self.verifier, redirect_uri=self.redirect_uri, resource=RESOURCE)


def verify_grant(data, *, client_id, nonce, keys):
    import jwt
    if not isinstance(data, dict) or data.get('token_type', '').lower() != 'bearer':
        raise ProbeError('invalid_token_response')
    if not isinstance(data.get('scope'), str) or not {'openid','resource.invoke','chatgpt.tokens.use.direct'}.issubset(data['scope'].split()):
        raise ProbeError('chatgpt_plan_permission_missing')
    def verify(encoded, audience):
        try:
            header = jwt.get_unverified_header(encoded)
            if header.get('alg') != 'RS256':
                raise ValueError()
            matched = [k for k in keys['keys'] if k.get('kid') == header.get('kid')]
            if len(matched) != 1:
                raise ValueError()
            key = jwt.PyJWK.from_dict(matched[0]).key
            claims = jwt.decode(encoded, key, algorithms=['RS256'], audience=audience,
                issuer=ISSUER, leeway=5, options={'require': ['sub','exp','iat']})
            if not isinstance(claims['sub'], str) or not claims['sub']:
                raise ValueError()
            return claims
        except Exception:
            raise ProbeError('identity_or_access_signature_invalid') from None
    identity = verify(data.get('id_token'), client_id)
    if not isinstance(identity.get('nonce'), str) or not secrets.compare_digest(identity['nonce'], nonce):
        raise ProbeError('identity_nonce_invalid')
    access = verify(data.get('access_token'), RESOURCE)
    if (access.get('sub') != identity['sub'] or access.get('client_id') != client_id or not isinstance(access.get('scope'), str) or
            not {'resource.invoke','chatgpt.tokens.use.direct'}.issubset(access['scope'].split())):
        raise ProbeError('access_grant_invalid')
    return data['access_token']


def model_available(data):
    if not isinstance(data, dict) or not isinstance(data.get('models'), list):
        raise ProbeError('unexpected_model_catalog')
    if not any(m.get('slug') == GPT_MODEL and m.get('visibility') == 'list'
               for m in data['models'] if isinstance(m, dict)):
        raise ProbeError('gpt_6_1_sol_not_in_account_catalog')


def get_field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def stream_failure_diagnostic(exc, *, phase, event_count, completed_seen):
    """Fixed categories only: never exception messages, URLs, headers or bodies."""
    kinds = {
        'APITimeoutError': 'timeout', 'ReadTimeout': 'timeout', 'ConnectTimeout': 'timeout',
        'WriteTimeout': 'timeout', 'PoolTimeout': 'timeout', 'TimeoutError': 'timeout',
        'APIConnectionError': 'connection', 'ConnectError': 'connection',
        'gaierror': 'dns', 'SSLError': 'tls', 'SSLCertVerificationError': 'tls',
        'ProxyError': 'proxy', 'ConnectionRefusedError': 'connection_refused',
        'ConnectionResetError': 'connection_reset',
        'ReadError': 'connection', 'WriteError': 'connection',
        'RemoteProtocolError': 'protocol', 'LocalProtocolError': 'protocol',
        'APIStatusError': 'http', 'ProbeError': 'stream_contract',
        'KeyError': 'local_key', 'TypeError': 'local_type', 'ValueError': 'local_value',
        'AttributeError': 'local_attribute', 'AssertionError': 'local_assertion',
        'RuntimeError': 'local_runtime',
    }
    def kind(error):
        return next((kinds[base.__name__] for base in type(error).mro()
                     if base.__name__ in kinds), 'unknown')
    status = getattr(exc, 'status_code', None)
    causes, seen, current = [], {id(exc)}, exc.__cause__
    while current is not None and id(current) not in seen and len(causes) < 4:
        seen.add(id(current)); causes.append(kind(current)); current = current.__cause__
    return dict(phase=phase, exceptionKind=kind(exc),
        causeKind=kind(exc.__cause__) if exc.__cause__ is not None else None,
        causeChain=causes,
        eventCount=event_count, completedSeen=completed_seen,
        httpStatus=status if type(status) is int and 100 <= status <= 599 else None)


def read_completed_stream(client, request, *, observe=None, on_completed=None, extractor=None, equivalent=None):
    """Only terminal JSON after completion; never join/accept partial deltas."""
    extract = extractor or extract_payload
    same = equivalent or (lambda left, right: left == right)
    completed, items = None, {}
    phase, event_count = 'create', 0
    try:
        with client.responses.create(**request) as stream:
            phase = 'read'
            for event in stream:
                event_count += 1
                if observe:
                    phase = 'observe'
                    observe(event)
                    phase = 'read'
                kind = get_field(event, 'type')
                if kind in {'response.failed', 'response.incomplete', 'error'}:
                    error = (get_field(get_field(event, 'response'), 'error') or
                             get_field(event, 'error') or (event if kind == 'error' else None))
                    code = get_field(error, 'code')
                    known = {'subscription_sharing_usage_limit_exceeded',
                        'subscription_sharing_usage_unavailable', 'subscription_sharing_user_not_eligible',
                        'subscription_sharing_unsupported_capability', 'subscription_sharing_route_not_supported'}
                    raise ProbeError(code if code in known else 'stream_not_completed')
                if kind == 'response.completed':
                    if completed is not None:
                        raise ProbeError('duplicate_completed_event')
                    completed = get_field(event, 'response')
                    if completed is None:
                        raise ProbeError('invalid_completed_output')
                if kind == 'response.output_item.done':
                    index = get_field(event, 'output_index')
                    if type(index) is not int or index < 0 or index in items:
                        raise ProbeError('invalid_terminal_output_item')
                    items[index] = get_field(event, 'item')
            phase = 'close'
    except ProbeError as exc:
        exc.diagnostic = stream_failure_diagnostic(exc, phase=phase,
            event_count=event_count, completed_seen=completed is not None)
        raise
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        diagnostic = stream_failure_diagnostic(exc, phase=phase,
            event_count=event_count, completed_seen=completed is not None)
        code = ('plan_timeout' if diagnostic['exceptionKind'] == 'timeout' else
                'plan_http_' + str(status) if type(status) is int and 100 <= status <= 599 else
                'plan_transport_unknown')
        raise ProbeError(code, diagnostic=diagnostic) from None
    if completed is None:
        error = ProbeError('stream_missing_completed')
        error.diagnostic = stream_failure_diagnostic(error, phase='validation',
            event_count=event_count, completed_seen=False)
        raise error
    if get_field(completed, 'model') != GPT_MODEL:
        raise ProbeError('unexpected_response_model')
    final = get_field(completed, 'output')
    if not isinstance(final, list):
        raise ProbeError('invalid_completed_output')
    terminal = [item for _, item in sorted(items.items())]
    if on_completed:
        on_completed(completed, terminal)
    if any(get_field(item, 'type') != 'reasoning' for item in final):
        payload = extract(completed)
        if terminal and not same(extract({'status':get_field(completed, 'status'), 'output':terminal}), payload):
            raise ProbeError('conflicting_terminal_output')
    else:
        # Plan responses may carry all assistant content in output_item.done.
        payload = extract({'status':get_field(completed, 'status'), 'output':terminal})
    return payload, completed
