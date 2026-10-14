"""Common SIWC credential lifecycle, independent of source, claims and inference.

Official flow: https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
Refresh intent is protected before sending: unknown rotation is never resent.
"""
import copy
import math
import re
import secrets
import time
from uuid import UUID

from ingest.chatgpt_plan_auth import PlanSession, _VERIFIED, _interactive_worker, fetch
from ingest.chatgpt_plan_protocol import (ProbeError, DISCOVERY, TOKEN, JWKS, RESOURCE,
    ISSUER, model_available, validate_discovery)

REAUTH = 'chatgpt_plan_reauthentication_required'
REQUIRED = {'resource.invoke','chatgpt.tokens.use.direct'}
TERMINAL_REFRESH = {'invalid_grant','invalid_refresh_token','token_expired',
    'refresh_token_expired','refresh_token_invalidated','refresh_token_reused'}


def _claims(encoded, audience, keys, *, expired=False):
    import jwt
    try:
        header = jwt.get_unverified_header(encoded)
        candidates = [k for k in keys['keys'] if k.get('kid') == header.get('kid')]
        if header.get('alg') != 'RS256' or len(candidates) != 1:
            raise ValueError()
        value = jwt.decode(encoded,jwt.PyJWK.from_dict(candidates[0]).key,
            algorithms=['RS256'],audience=audience,issuer=ISSUER,leeway=5,
            options={'require':['sub','exp','iat'],'verify_exp':not expired})
        if (not isinstance(value['sub'],str) or not value['sub'] or
                type(value['exp']) not in (int,float) or not math.isfinite(value['exp'])):
            raise ValueError()
        return value
    except Exception:
        raise ProbeError('identity_or_access_signature_invalid') from None


def validate_record(record, keys):
    """Protected original ID may expire; signed current access is checked separately.

    Issued client binds the workspace. Opaque OpenAI metadata is not interpreted.
    Expired access is only accepted here to decide renewal, never for inference.
    """
    try:
        if (set(record) != {'format','state','client_id','host_id','nonce','subject','grant'} or
                type(record['format']) is not int or record['format'] != 1 or record['state'] not in {'ready','refresh_pending','reauth'} or
                not isinstance(record['client_id'],str) or
                not re.fullmatch(r'[A-Za-z0-9_.-]{1,256}',record['client_id']) or
                record['client_id'] == 'dynamic_agent_client' or
                not record['host_id'].startswith('urn:uuid:') or
                not isinstance(record['nonce'],str) or not record['nonce'] or
                not isinstance(record['grant'],dict)):
            raise ValueError()
        UUID(record['host_id'].removeprefix('urn:uuid:'))
    except Exception:
        raise ProbeError('plan_saved_registration_invalid') from None
    grant = record['grant']
    if grant.get('token_type','').lower() != 'bearer' or not isinstance(grant.get('scope'),str):
        raise ProbeError('invalid_token_response')
    identity = _claims(grant.get('id_token'),record['client_id'],keys,expired=True)
    if not secrets.compare_digest(str(identity.get('nonce','')),record['nonce']):
        raise ProbeError('identity_nonce_invalid')
    access = _claims(grant.get('access_token'),RESOURCE,keys,expired=True)
    if (access['sub'] != identity['sub'] or access['sub'] != record['subject'] or
            access.get('client_id') != record['client_id']):
        raise ProbeError('access_grant_invalid')
    if (not REQUIRED.issubset(grant['scope'].split()) or
            not isinstance(access.get('scope'),str) or not REQUIRED.issubset(access['scope'].split())):
        raise ProbeError('chatgpt_plan_permission_missing')
    if not set(access['scope'].split()).issubset(grant['scope'].split()):
        raise ProbeError('access_grant_invalid')
    return access


class PlanSessionManager:
    def __init__(self, *, store=None, http_factory=None, login=None, clock=None):
        if store is None:
            from ingest.chatgpt_plan_store import WindowsPlanStore
            store = WindowsPlanStore()
        if http_factory is None:
            import requests
            http_factory = requests.Session
        self.store, self.http_factory = store, http_factory
        self.login, self.clock = login or _interactive_worker, clock or time.time

    def __repr__(self):
        return 'PlanSessionManager(credentials=redacted)'

    def acquire(self, *, expected=None, allow_login=True):
        # Lock covers load/check/rotation/save across threads and processes.
        with self.store.lock():
            record = self.store.load()
            if record is not None and not isinstance(record,dict):
                raise ProbeError('plan_saved_registration_invalid')
            if record is None or record.get('state') == 'reauth':
                if not allow_login:
                    raise ProbeError(REAUTH)
                registration = None if record is None else {
                    'host_id':record['host_id'],'client_id':record['client_id']}
                try:
                    session = self.login(registration)
                except ProbeError:
                    raise
                except Exception:
                    raise ProbeError('plan_auth_transport_unavailable') from None
                try:
                    if not isinstance(session,PlanSession) or not session._record:
                        raise ProbeError('unverified_plan_session')
                    record = {'format':1,'state':'ready',**copy.deepcopy(session._record)}
                    # Only renewable, explicitly consented sessions are persisted.
                    if not isinstance(record['grant'].get('refresh_token'),str) or not record['grant']['refresh_token']:
                        raise ProbeError('plan_renewable_session_required')
                    session.require_active()
                    with self.http_factory() as http:
                        validate_record(record,fetch(http,JWKS))
                    prior = self.store.load()
                    if prior is not None and (record['client_id'],record['host_id'],record['subject']) != (
                            prior['client_id'],prior['host_id'],prior['subject']):
                        raise ProbeError('plan_selected_account_changed')
                    self.store.save(record)
                    self._attach(session,record)
                    return session
                except ProbeError:
                    if isinstance(session,PlanSession):
                        session.clear()
                    raise
                except Exception:
                    if isinstance(session,PlanSession):
                        session.clear()
                    raise ProbeError('plan_auth_transport_unavailable') from None
            if record.get('state') == 'refresh_pending':
                raise ProbeError('plan_refresh_result_unknown')
            try:
                with self.http_factory() as http:
                    validate_discovery(fetch(http,DISCOVERY))
                    keys = fetch(http,JWKS)
                    try:
                        claims = validate_record(record,keys)
                    except ProbeError as exc:
                        if exc.code == 'chatgpt_plan_permission_missing':
                            self.store.save({**record,'state':'reauth','grant':{}})
                        raise
                    identity = (record['client_id'],record['host_id'],claims['sub'])
                    if expected is not None and expected != identity:
                        raise ProbeError('plan_selected_account_changed')
                    if self.clock()+250 >= claims['exp']:
                        record = self._refresh(record,http,keys)
                        claims = validate_record(record,keys)
                        if self.clock()+250 >= claims['exp']:
                            raise ProbeError(REAUTH)
                    # Catalog access checks current account eligibility without inference.
                    model_available(fetch(http,RESOURCE+'/models',headers={
                        'Authorization':'Bearer '+record['grant']['access_token']}))
            except ProbeError:
                raise
            except Exception:
                raise ProbeError('plan_auth_transport_unavailable') from None
            session = PlanSession(record['grant']['access_token'],claims['exp'],_VERIFIED)
            self._attach(session,record,identity)
            return session

    def _attach(self, session, record, identity=None):
        if identity is None:
            import jwt
            subject = jwt.decode(session._access,options={'verify_signature':False})['sub']
            identity = (record['client_id'],record['host_id'],subject)
        # Later stage renewal cannot launch a browser or switch selected account.
        session._renew = lambda:self.acquire(expected=identity,allow_login=False)

    def _refresh(self, record, http, keys):
        old = record['grant']
        refresh = old.get('refresh_token')
        if not isinstance(refresh,str) or not refresh:
            self.store.save({**record,'state':'reauth','grant':{}})
            raise ProbeError(REAUTH)
        earliest = old.get('earliest_refresh_at')
        if earliest is not None and (type(earliest) not in (int,float) or self.clock() < earliest):
            raise ProbeError('plan_refresh_not_yet_allowed')
        intent = {**record,'state':'refresh_pending'}
        self.store.save(intent)
        try:
            response = http.post(TOKEN,data={'grant_type':'refresh_token',
                'client_id':record['client_id'],'refresh_token':refresh,'resource':RESOURCE},
                timeout=30,allow_redirects=False)
            payload = response.json()
        except Exception:
            raise ProbeError('plan_refresh_result_unknown') from None
        if response.status_code != 200:
            code = payload.get('error') if isinstance(payload,dict) else None
            if isinstance(code,dict):
                code = code.get('code')
            if response.status_code in {400,401} and isinstance(code,str) and code in TERMINAL_REFRESH:
                self.store.save({**record,'state':'reauth','grant':{}})
                raise ProbeError(REAUTH)
            if code == 'invalid_client':
                raise ProbeError('plan_client_configuration_invalid')
            # Even an error must not resend a possibly rotated token automatically.
            raise ProbeError('plan_refresh_result_unknown')
        try:
            if (not isinstance(payload,dict) or not isinstance(payload.get('refresh_token'),str) or
                    not payload['refresh_token'] or not isinstance(payload.get('scope'),str) or
                    not set(payload['scope'].split()).issubset(old['scope'].split())):
                raise ProbeError('plan_refresh_grant_invalid')
            # Some refresh responses omit ID; keep the original verified identity.
            if payload.get('id_token'):
                fresh_id = _claims(payload['id_token'],record['client_id'],keys)
                original_id = _claims(old['id_token'],record['client_id'],keys,expired=True)
                if fresh_id['sub'] != original_id['sub']:
                    raise ProbeError('plan_selected_account_changed')
            grant = {**payload,'id_token':old['id_token']}
            next_record = {**record,'state':'ready','grant':grant}
            current = validate_record(record,keys)
            updated = validate_record(next_record,keys)
            if updated['sub'] != current['sub'] or updated['exp'] <= self.clock()+250:
                raise ProbeError('plan_refresh_grant_invalid')
            self.store.save(next_record)
            return next_record
        except ProbeError:
            # Intent stays pending: no inference, no stale refresh replay.
            raise
        except Exception:
            raise ProbeError('plan_refresh_result_unknown') from None
