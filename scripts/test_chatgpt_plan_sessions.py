"""Signed synthetic grants, fake protected store/HTTP/Pro/RPC; no real credentials."""
import copy
import io
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch, Mock

from ingest.chatgpt_plan_auth import PlanSession, authenticate_worker
from ingest.chatgpt_plan_sessions import PlanSessionManager, REAUTH
from ingest.chatgpt_plan_store import WindowsPlanStore, WindowsProtection as NativeProtection
from ingest.chatgpt_plan_protocol import ProbeError, DISCOVERY, JWKS, TOKEN, RESOURCE, ISSUER, AUTHORIZE, SCOPES
from ingest.ai_provider import create_provider_adapter, close_provider_adapter
from ingest.ai_openai import GPT_MODEL
from ingest.ai_chatgpt_plan import PlanCommonFailure
from ingest.rpc_errors import RpcAmbiguous
import test_chatgpt_plan_probe as probe_fixture
from test_chatgpt_plan_probe import FakeClient
from test_ingest_ai_chatgpt_plan import streamed
from test_ingest_ai_openai import SUMMARY_JSON, TRANSLATION_JSON, response


HOST = 'urn:uuid:00000000-0000-4000-8000-000000000002'


class FakeStore:
    def __init__(self, record=None):
        self.record = copy.deepcopy(record)
        self.mutex = threading.RLock()
        self.writes = []
        self.error = None
    def lock(self):
        return self.mutex
    def load(self):
        if self.error:
            raise ProbeError(self.error)
        return copy.deepcopy(self.record)
    def save(self, record):
        if self.error:
            raise ProbeError(self.error)
        self.record = copy.deepcopy(record)
        self.writes.append(copy.deepcopy(record))


class SessionTests(unittest.TestCase):
    def setUp(self):
        for method in ('connect','connect_ex'):
            guard = patch.object(socket.socket,method,side_effect=AssertionError('network forbidden'))
            guard.start(); self.addCleanup(guard.stop)
        guard = patch('ingest.chatgpt_plan_store.WindowsProtection',side_effect=AssertionError('real credential access forbidden'))
        guard.start(); self.addCleanup(guard.stop)
        grant, self.keys, self.encode, self.identity, self.access = probe_fixture.ProProbeTests().grant()
        self.now = time.time()
        grant['id_token'] = self.encode({**self.identity,'exp':int(self.now)+3600})
        grant['access_token'] = self.encode({**self.access,'exp':int(self.now)+3600})
        grant['refresh_token'] = 'synthetic-refresh-original'
        self.record = dict(format=1,state='ready',client_id='oaiapp_synthetic',host_id=HOST,
            nonce='nonce',subject=self.access['sub'],grant=grant)
        self.store = FakeStore(self.record)
        self.calls, self.login_calls = [], []
        self.refresh_error, self.get_error, self.refresh_patch = None, None, {}
        self.refresh_exception = False
        self.clock = lambda:self.now
        owner = self
        class HTTP:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def get(self,url,**kwargs):
                owner.calls.append(('GET',url,copy.deepcopy(kwargs)))
                if kwargs.get('allow_redirects') is not False or kwargs.get('timeout') != 30:
                    raise AssertionError('transport contract')
                if url == DISCOVERY:
                    data = dict(issuer=ISSUER,authorization_endpoint=AUTHORIZE,token_endpoint=TOKEN,jwks_uri=JWKS)
                elif url == JWKS:data = owner.keys
                elif url == RESOURCE+'/models':
                    data = {'models':[{'slug':GPT_MODEL,'visibility':'list'}]}
                    if owner.get_error:return SimpleNamespace(status_code=owner.get_error,json=lambda:{})
                    if kwargs['headers']['Authorization'] != 'Bearer '+owner.store.record['grant']['access_token']:
                        raise AssertionError('old credential used')
                else:raise AssertionError('unexpected network')
                return SimpleNamespace(status_code=200,json=lambda:copy.deepcopy(data))
            def post(self,url,**kwargs):
                owner.calls.append(('POST',url,copy.deepcopy(kwargs)))
                if (url != TOKEN or kwargs.get('allow_redirects') is not False or
                        set(kwargs['data']) != {'grant_type','client_id','refresh_token','resource'}):
                    raise AssertionError('refresh contract')
                if owner.store.record['state'] != 'refresh_pending':raise AssertionError('missing intent')
                if owner.refresh_exception:raise RuntimeError('synthetic-secret-token-response')
                if owner.refresh_error:
                    status, code = owner.refresh_error
                    return SimpleNamespace(status_code=status,json=lambda:{'error':code})
                grant = copy.deepcopy(owner.record['grant'])
                grant['access_token'] = owner.encode({**owner.access,'exp':int(owner.now)+3600,'jti':'synthetic-rotated'})
                grant['refresh_token'] = 'synthetic-refresh-rotated'
                grant.pop('id_token',None)
                grant.update(owner.refresh_patch)
                return SimpleNamespace(status_code=200,json=lambda:copy.deepcopy(grant))
        self.http = HTTP

    def manager(self,store=None):
        def login(registration):
            self.login_calls.append(copy.deepcopy(registration))
            grant = copy.deepcopy(self.record['grant'])
            session = PlanSession.from_grant(grant,client_id=self.record['client_id'],
                nonce='nonce',keys=self.keys,catalog={'models':[{'slug':GPT_MODEL,'visibility':'list'}]})
            session._record['host_id'] = HOST
            return session
        return PlanSessionManager(store=store or self.store,http_factory=self.http,
            login=login,clock=self.clock)

    def near_expiry(self):
        self.store.record['grant']['access_token'] = self.encode({**self.access,'exp':int(self.now)+200})

    def assert_code(self,call,code):
        with self.assertRaises(ProbeError) as raised:call()
        self.assertEqual(raised.exception.code,code)
        return raised.exception

    def posts(self):return [c for c in self.calls if c[0]=='POST']

    def test_valid_repeated_and_restarted_process_reuse_without_login_refresh(self):
        for _ in range(3):
            session = authenticate_worker(manager=self.manager())
            self.assertEqual(session.access_token(),self.record['grant']['access_token'])
            session.clear()
        self.assertEqual(self.login_calls,[])
        self.assertEqual(self.posts(),[])
        self.assertEqual(self.store.writes,[])

    def test_valid_saved_credentials_need_no_tty_or_browser(self):
        with patch('sys.stdin.isatty',return_value=False):
            self.assertIsInstance(authenticate_worker(manager=self.manager()),PlanSession)
        self.assertEqual(self.login_calls,[])

    def test_missing_store_logs_in_once_persists_then_close_keeps_registration(self):
        self.store.record = None
        session = self.manager().acquire()
        self.assertEqual(self.login_calls,[None])
        self.assertEqual(self.store.record['state'],'ready')
        session.clear()
        self.manager().acquire().clear()
        self.assertEqual(len(self.login_calls),1)

    def test_near_expiry_rotates_once_and_saves_latest_before_catalog(self):
        self.near_expiry()
        session = self.manager().acquire()
        self.assertEqual(len(self.posts()),1)
        self.assertEqual([r['state'] for r in self.store.writes],['refresh_pending','ready'])
        self.assertEqual(self.store.record['grant']['refresh_token'],'synthetic-refresh-rotated')
        self.assertEqual(session.access_token(),self.store.record['grant']['access_token'])
        self.assertNotIn('scope',self.posts()[0][2]['data'])
        self.manager().acquire().clear()
        self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.login_calls,[])

    def test_expired_id_is_not_an_expired_access_or_reason_for_login(self):
        self.store.record['grant']['id_token'] = self.encode({**self.identity,'exp':int(self.now)-60})
        self.manager().acquire().clear()
        self.assertEqual(self.login_calls,[])

    def test_expired_access_renews_and_missing_refresh_requires_auth(self):
        self.store.record['grant']['access_token'] = self.encode({**self.access,'exp':int(self.now)-60})
        self.manager().acquire().clear()
        self.assertEqual(len(self.posts()),1)
        self.near_expiry(); self.store.record['grant'].pop('refresh_token')
        self.assert_code(self.manager().acquire,REAUTH)
        self.assertEqual(len(self.posts()),1)

    def test_terminal_refresh_marks_reauth_without_changing_client_or_host(self):
        self.near_expiry(); self.refresh_error = (400,'invalid_grant')
        self.assert_code(self.manager().acquire,REAUTH)
        self.assertEqual(self.store.record['state'],'reauth')
        self.assertEqual(self.store.record['grant'],{})
        self.assertEqual(self.store.record['client_id'],self.record['client_id'])
        self.assertEqual(self.store.record['host_id'],HOST)
        self.assertEqual(self.login_calls,[])
        self.manager().acquire().clear()
        self.assertEqual(self.login_calls,[{'client_id':self.record['client_id'],'host_id':HOST}])

    def test_missing_permissions_and_invalid_identity_do_not_make_model_requests(self):
        for change in ({'scope':'openid'}, {'sub':'different'}, {'client_id':'other'},
                       {'aud':'other'}, {'iss':'https://invalid.example'}):
            self.store = FakeStore(self.record)
            self.store.record['grant']['access_token'] = self.encode({**self.access,**change,'exp':int(self.now)+3600})
            with self.assertRaises(ProbeError):self.manager().acquire()
            self.assertFalse(any(c[1].endswith('/models') for c in self.calls))
        self.assertEqual(self.login_calls,[])

    def test_account_binding_prevents_client_host_or_subject_switch(self):
        manager = self.manager()
        expected = (self.record['client_id'],HOST,self.record['subject'])
        self.store.record['host_id'] = 'urn:uuid:00000000-0000-4000-8000-000000000003'
        self.assert_code(lambda:manager.acquire(expected=expected,allow_login=False),'plan_selected_account_changed')
        self.assertEqual(self.login_calls,[])

    def test_refresh_scope_expansion_account_switch_and_bad_signatures_stop(self):
        for extra in ({'scope':SCOPES+' new.permission'},
                      {'access_token':self.encode({**self.access,'sub':'other','exp':int(self.now)+3600})},
                      {'access_token':'unsigned-synthetic'}, {'refresh_token':''}):
            self.store = FakeStore(self.record); self.near_expiry(); self.refresh_patch = extra
            with self.assertRaises(ProbeError):self.manager().acquire()
            self.assertEqual(self.store.record['state'],'refresh_pending')
            self.assert_code(self.manager().acquire,'plan_refresh_result_unknown')
        self.assertEqual(len(self.posts()),4)
        self.assertEqual(self.login_calls,[])

    def test_refresh_unknown_never_replays_after_restart(self):
        self.near_expiry(); self.refresh_exception = True
        error = self.assert_code(self.manager().acquire,'plan_refresh_result_unknown')
        self.assertNotIn('secret',repr(error))
        self.assert_code(self.manager().acquire,'plan_refresh_result_unknown')
        self.assertEqual(len(self.posts()),1)
        self.assertEqual(self.store.record['state'],'refresh_pending')

    def test_refresh_http_usage_service_and_invalid_client_do_not_login_or_resend(self):
        for result in [(503,'unavailable'),(429,'usage_limit'),(400,'invalid_client')]:
            self.store = FakeStore(self.record); self.near_expiry(); self.refresh_error = result
            with self.assertRaises(ProbeError):self.manager().acquire()
            self.assert_code(self.manager().acquire,'plan_refresh_result_unknown')
        self.assertEqual(len(self.posts()),3)
        self.assertEqual(self.login_calls,[])

    def test_catalog_failure_preserves_tokens_and_does_not_oauth_loop(self):
        for status in (401,403,429,503):
            self.get_error = status
            self.assert_code(self.manager().acquire,'official_get_http_'+str(status))
            self.assertEqual(self.store.record,self.record)
        self.assertEqual(self.login_calls,[])
        self.assertEqual(self.posts(),[])

    def test_refresh_earliest_time_is_respected(self):
        self.near_expiry(); self.store.record['grant']['earliest_refresh_at'] = self.now+100
        self.assert_code(self.manager().acquire,'plan_refresh_not_yet_allowed')
        self.assertEqual(self.posts(),[])

    def test_concurrent_acquisition_reads_latest_rotated_credentials(self):
        self.near_expiry(); manager = self.manager()
        errors, sessions = [], []
        def run():
            try:sessions.append(manager.acquire())
            except Exception as e:errors.append(type(e).__name__)
        workers = [threading.Thread(target=run) for _ in range(3)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(timeout=5)
        self.assertEqual(errors,[])
        self.assertEqual(len(sessions),3)
        self.assertEqual(len(self.posts()),1)
        self.assertEqual({s.access_token() for s in sessions},{self.store.record['grant']['access_token']})

    def test_store_denied_corrupt_or_inflight_never_falls_back_to_login(self):
        for state in ('refresh_pending','corrupt'):
            self.store.record['state'] = state
            with self.assertRaises(ProbeError):self.manager().acquire()
        self.store.error = 'plan_secure_store_unavailable'
        self.assert_code(self.manager().acquire,'plan_secure_store_unavailable')
        self.assertEqual(self.login_calls,[])

    def test_later_stage_renewal_updates_sdk_token_without_repeating_summary(self):
        session = self.manager().acquire()
        client = streamed([response(SUMMARY_JSON),response(TRANSLATION_JSON)])
        client.api_key = session.access_token()
        adapter = create_provider_adapter('chatgpt_plan',None,plan_session=session,client=client)
        adapter.summarize_ko('synthetic',None)
        self.near_expiry(); session.expires_at = time.time()+100
        adapter.translate_ja('합성','한국어 요약입니다.')
        self.assertEqual(len(client.calls),2)
        self.assertEqual(client.api_key,self.store.record['grant']['access_token'])
        self.assertEqual(len(self.posts()),1)
        adapter.close()

    def test_renewal_unknown_blocks_batch_before_next_generation(self):
        session = self.manager().acquire()
        client = FakeClient()
        adapter = create_provider_adapter('chatgpt_plan',None,plan_session=session,client=client)
        self.near_expiry(); session.expires_at = time.time()+100; self.refresh_exception = True
        with self.assertRaises(PlanCommonFailure) as error:adapter.summarize_ko('synthetic',None)
        self.assertEqual(error.exception.failure_scope,'batch')
        self.assertEqual(error.exception.diagnostic['code'],'plan_refresh_result_unknown')
        self.assertEqual(client.calls,[])
        with self.assertRaises(RpcAmbiguous):adapter.summarize_ko('synthetic',None)
        self.assertEqual(len(self.posts()),1)
        adapter.close()

    def test_actual_no_retry_queue_stops_next_claim_on_shared_refresh_unknown(self):
        import test_seoul_batch_failures as batch
        from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
        fixture = batch.BatchFailureTests()
        def provider(**kwargs):
            result = ChatGPTPlanAdapter(**kwargs)
            self.near_expiry(); result._session.expires_at=time.time()+100
            self.refresh_exception=True
            return result
        try:
            with patch.object(batch,'verified_session',side_effect=lambda:self.manager().acquire()), \
                 patch.object(batch,'ChatGPTPlanAdapter',side_effect=provider):
                counts,client,events,claims,terminal,outputs,_ = fixture.batch(['success','success'])
            self.assertEqual(claims,[0]); self.assertEqual(client.calls,[])
            self.assertEqual(terminal,[]); self.assertEqual(outputs,[])
            self.assertTrue(counts['batch_stopped']); self.assertEqual(counts['unprocessed'],1)
            self.assertEqual(counts['automatic_retries'],0)
            self.assertEqual(counts['state_unknown'],1)
            self.assertEqual(counts['items'][0]['failureScope'],'batch')
            self.assertEqual(self.store.record['state'],'refresh_pending')
            self.assertEqual(len(self.posts()),1)
        finally:fixture.doCleanups()

    def test_provider_http_failure_does_not_refresh_or_resend(self):
        for code in ('subscription_sharing_usage_limit_exceeded','plan_http_401'):
            session = self.manager().acquire()
            client = FakeClient([[{'type':'error','code':code}]])
            adapter = create_provider_adapter('chatgpt_plan',None,plan_session=session,client=client)
            with self.assertRaises(Exception):adapter.summarize_ko('synthetic',None)
            with self.assertRaises(RpcAmbiguous):adapter.summarize_ko('synthetic',None)
            self.assertEqual(len(client.calls),1)
            adapter.close()
        self.assertEqual(self.posts(),[])
        self.assertEqual(self.login_calls,[])

    def test_actual_launchers_prepare_shared_auth_before_rpc_or_claim(self):
        import run_myseoul_program_ai as myseoul
        import run_seoul_program_ai as seoul
        import run_reclassified_content_ai as classified
        from ingest.ai_worker import AiWorkerResult
        args = SimpleNamespace(project_ref='a'*20,source_item_id='00000000-0000-4000-8000-000000000001',
            revision='a'*64,classification_version=1,no_retry=True,max_jobs=1,queue_pages=1)
        for cli, entry, module, worker in [
            (seoul,'execute_target','ingest.program_ai','process_seoul_program_job'),
            (seoul,'execute_queue','ingest.seoul_workflow','process_seoul_queue'),
            (myseoul,'execute_target','ingest.myseoul_ai','process_myseoul_job'),
            (classified,'execute_target','ingest.reclassification_ai','process_reclassified_job')]:
            events = []
            owned_client = FakeClient()
            owned_client.close = lambda:None
            def auth():
                session = authenticate_worker(manager=self.manager())
                events.append('verified-auth'); return session
            def db(*args):
                self.assertEqual(events,['verified-auth']); events.append('fake-rpc'); return object()
            with patch.dict('os.environ',{'AI_PROVIDER':'chatgpt_plan','SUPABASE_URL':'https://'+'a'*20+'.supabase.co',
                                         'SUPABASE_SERVICE_KEY':'synthetic'},clear=True):
                with patch('ingest.chatgpt_plan_auth.authenticate_worker',side_effect=auth), \
                     patch('openai.OpenAI',return_value=owned_client), \
                     patch('ingest.supabase_store.create_ingest_client',side_effect=db), \
                     patch(module+'.'+worker,return_value=AiWorkerResult(status='processed')) as run:
                    getattr(cli,entry)(args)
            self.assertEqual(events,['verified-auth','fake-rpc'])
            self.assertEqual(run.call_count,1)
        self.assertEqual(self.login_calls,[])
        self.assertEqual(self.posts(),[])

    def test_auth_failure_in_actual_launcher_never_constructs_rpc_or_claim(self):
        import run_seoul_program_ai as seoul
        args = SimpleNamespace(project_ref='a'*20,source_item_id='00000000-0000-4000-8000-000000000001',
            revision='a'*64,no_retry=True)
        self.store.record['state'] = 'refresh_pending'
        with patch.dict('os.environ',{'AI_PROVIDER':'chatgpt_plan','SUPABASE_URL':'https://'+'a'*20+'.supabase.co',
                                     'SUPABASE_SERVICE_KEY':'synthetic'},clear=True):
            with patch('ingest.chatgpt_plan_auth.authenticate_worker',side_effect=lambda:self.manager().acquire()), \
                 patch('ingest.supabase_store.create_ingest_client') as db:
                self.assert_code(lambda:seoul.execute_target(args),'plan_refresh_result_unknown')
        db.assert_not_called()

    def test_shared_reuse_reaches_real_general_and_reclassified_fake_candidates(self):
        import test_seoul_date_hours_replay as replay
        for classified in (False,True):
            fixture = replay.DateHoursReplayTests()
            try:
                with patch.object(replay,'verified_session',side_effect=lambda:self.manager().acquire()):
                    result, events, outputs, calls = fixture.replay(1,classified)
                self.assertEqual((result.completed,result.failed,result.state_unknown),(1,0,0))
                self.assertEqual(len(calls),2)
                self.assertEqual(sum(n.startswith('finish_') for n,_ in events),1)
                self.assertIn(outputs[0]['contentKo'],calls[1]['input'][0]['content'])
            finally:fixture.doCleanups()
        self.assertEqual(self.login_calls,[])
        self.assertEqual(self.posts(),[])

    def test_shared_reuse_reaches_real_myseoul_fenced_fake_candidate(self):
        import test_myseoul_gpt_pipeline as fixture
        context = fixture.native_packet(); before = copy.deepcopy(context)
        recorded = fixture.native_client(context)
        client = streamed(recorded.responses.results)
        def factory(**kwargs):
            return create_provider_adapter('chatgpt_plan',None,client=client,plan_session=self.manager().acquire())
        result, events, adapter = fixture.GPTPipelineTests().native_run(context,recorded,adapter_factory=factory)
        try:
            self.assertEqual((result.completed,result.failed,result.state_unknown),(1,0,0))
            self.assertEqual(context,before)
            self.assertEqual(len(client.calls),2)
            self.assertEqual(sum(n.startswith('finish_') for n,_ in events),1)
        finally:adapter.close()
        self.assertEqual(self.login_calls,[])

    def test_rotated_response_store_failure_keeps_pending_and_never_replays(self):
        self.near_expiry()
        original = self.store.save
        def save(record):
            if record['state']=='ready':raise ProbeError('plan_secure_store_unavailable')
            original(record)
        with patch.object(self.store,'save',side_effect=save):
            self.assert_code(self.manager().acquire,'plan_secure_store_unavailable')
        self.assertEqual(self.store.record['state'],'refresh_pending')
        self.assert_code(self.manager().acquire,'plan_refresh_result_unknown')
        self.assertEqual(len(self.posts()),1)

    def test_refresh_bound_client_and_scope_cannot_change_through_signed_access(self):
        self.near_expiry()
        self.refresh_patch = {'access_token':self.encode({**self.access,'scope':SCOPES+' new.permission',
                                                         'exp':int(self.now)+3600})}
        self.assert_code(self.manager().acquire,'access_grant_invalid')
        self.assertEqual(self.store.record['state'],'refresh_pending')

    def test_nonfinite_or_missing_expiry_is_not_a_permanent_valid_session(self):
        for exp in (float('inf'),float('nan'),None):
            self.store.record['grant']['access_token'] = self.encode({**self.access,'exp':exp})
            self.assert_code(self.manager().acquire,'identity_or_access_signature_invalid')

    def test_default_bearer_override_cannot_retain_old_token_after_rotation(self):
        session = self.manager().acquire()
        client = FakeClient()
        client.default_headers = {'Authorization':'Bearer '+session.access_token()}
        adapter = create_provider_adapter('chatgpt_plan',None,plan_session=session,client=client)
        self.near_expiry(); session.expires_at=time.time()+100
        with self.assertRaises(PlanCommonFailure):adapter.summarize_ko('synthetic',None)
        self.assertEqual(client.calls,[])
        self.assertEqual(len(self.posts()),1)
        adapter.close()

    def test_synthetic_future_source_uses_same_factory_without_source_auth(self):
        session = self.manager().acquire(); client = FakeClient()
        adapter = create_provider_adapter('chatgpt_plan',None,plan_session=session,client=client)
        adapter.summarize_ko('synthetic future source',None)
        adapter.translate_ja('합성','한국어 요약입니다.')
        self.assertEqual(len(client.calls),2)
        close_provider_adapter(adapter)
        self.manager().acquire().clear()
        self.assertEqual(self.login_calls,[])

    def test_fake_protected_disk_roundtrip_atomic_replace_without_plaintext(self):
        from cryptography.fernet import Fernet
        cipher = Fernet(Fernet.generate_key())
        class Protection:
            @contextmanager
            def lock(self,key):yield
            def protect(self,raw):return cipher.encrypt(raw)
            def unprotect(self,raw):return cipher.decrypt(raw)
        cache = Path(__file__).parent/'__pycache__'
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            path = Path(temporary)/'synthetic.bin'
            store = WindowsPlanStore(path=path,protection=Protection())
            self.assertIsNone(store.load())
            with store.lock():store.save(self.record)
            self.assertNotIn(self.record['grant']['access_token'].encode(),path.read_bytes())
            self.assertNotIn(b'synthetic-refresh',path.read_bytes())
            self.assertEqual(store.load(),self.record)
            self.assertEqual(list(Path(temporary).glob('*.new')),[])
            other = WindowsPlanStore(path=path,protection=Protection())
            self.assertEqual(other.load(),self.record)
            path.write_bytes(b'damaged synthetic ciphertext')
            self.assert_code(store.load,'plan_secure_store_unavailable')

    def test_windows_native_boundary_uses_user_dpapi_no_ui_and_bounded_mutex(self):
        import ctypes
        from cryptography.fernet import Fernet
        cipher = Fernet(Fernet.generate_key()); outputs = []; flags = []
        kernel = SimpleNamespace(LocalFree=Mock(return_value=None),CreateMutexW=Mock(return_value=17),
            WaitForSingleObject=Mock(return_value=0),ReleaseMutex=Mock(),CloseHandle=Mock())
        native = None
        def transform(source,description,entropy,reserved,prompt,flag,target,*,decrypt):
            self.assertEqual((description,entropy,reserved,prompt),(None,None,None,None))
            flags.append(flag)
            src = ctypes.cast(source,ctypes.POINTER(native.Blob)).contents
            raw = ctypes.string_at(src.data,src.size)
            value = cipher.decrypt(raw) if decrypt else cipher.encrypt(raw)
            buffer = (ctypes.c_ubyte*len(value)).from_buffer_copy(value); outputs.append(buffer)
            out = ctypes.cast(target,ctypes.POINTER(native.Blob)).contents
            out.size=len(value); out.data=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte))
            return True
        crypt = SimpleNamespace(CryptProtectData=Mock(side_effect=lambda *a:transform(*a,decrypt=False)),
            CryptUnprotectData=Mock(side_effect=lambda *a:transform(*a,decrypt=True)))
        with patch('ingest.chatgpt_plan_store.ctypes.WinDLL',side_effect=lambda name,**kw:kernel if name=='kernel32' else crypt):
            native = NativeProtection()
        protected = native.protect(b'synthetic-access-and-refresh')
        self.assertNotIn(b'synthetic-access',protected)
        self.assertEqual(native.unprotect(protected),b'synthetic-access-and-refresh')
        self.assertEqual(flags,[1,1])
        self.assertTrue(all(bytes(buffer)==bytes(len(buffer)) for buffer in outputs))
        self.assertEqual(kernel.LocalFree.call_count,2)
        with native.lock('synthetic-key'):pass
        kernel.WaitForSingleObject.assert_called_with(17,30000)
        kernel.ReleaseMutex.assert_called_once()
        kernel.CloseHandle.assert_called_once()
        kernel.WaitForSingleObject.return_value=0x80
        self.assert_code(lambda: self._take_lock(native),'plan_auth_lock_unavailable')
        self.assertEqual(kernel.ReleaseMutex.call_count,2)
        self.assertEqual(kernel.CloseHandle.call_count,2)

    @staticmethod
    def _take_lock(native):
        with native.lock('synthetic-key'):pass

    def test_diagnostics_repr_and_metadata_never_expose_tokens(self):
        with redirect_stdout(io.StringIO()) as output:
            session = self.manager().acquire()
        value = output.getvalue()+repr(session)+repr(self.manager())
        for secret in self.record['grant'].values():
            if isinstance(secret,str) and len(secret)>50:self.assertNotIn(secret,value)
        self.assertEqual(output.getvalue(),'')

    def test_common_entry_requests_reauth_only_for_confirmed_auth_conditions(self):
        for code, expected in [(REAUTH,True),('chatgpt_plan_permission_missing',True),
                ('plan_refresh_result_unknown',False),('official_get_http_429',False),
                ('plan_auth_transport_unavailable',False)]:
            manager = SimpleNamespace(acquire=Mock(side_effect=ProbeError(code)))
            with redirect_stderr(io.StringIO()) as output:
                self.assert_code(lambda:authenticate_worker(manager=manager),code)
            self.assertEqual('재인증이 필요합니다' in output.getvalue(),expected)
            for value in self.record['grant'].values():
                if isinstance(value,str) and len(value)>50:self.assertNotIn(value,output.getvalue())


if __name__ == '__main__':unittest.main()
