"""Loopback-only, explicit administrator capabilities. No import/startup credential IO."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from uuid import UUID, uuid4
from ingest.pc_worker_sources import SOURCES,CATALOG

SCHEMA = 'machimoa-pc-worker-v3'
PORT = 14621


class ControlError(Exception):
    def __init__(self, code, status=403):
        self.code, self.status = code, status
        super().__init__(code)


def identity(value):
    if not isinstance(value, str) or str(UUID(value, version=4)) != value.lower():
        raise ValueError('invalid_identity')
    return value


def command(value):
    if (not isinstance(value, dict) or set(value) != {'source','kind','limit'}
        or not isinstance(value['source'],str) or value['source'] not in {*SOURCES,'all'}
        or not isinstance(value['kind'],str) or value['kind'] not in {'collect','ai'}
        or value['kind']=='ai' and value['source']!='all'
        or not (value['kind']=='ai' and value['limit']=='all') and
            (type(value['limit']) is not int or not 1<=value['limit']<=(1 if value['kind']=='collect' else 25))):
        raise ControlError('invalid_command',422)
    return dict(value)


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=')


class PcWorkerControl:
    def __init__(self, *, project, origin, key, execute, clock=time.time):
        parsed=urlsplit(origin)
        if (not re.fullmatch('[a-z0-9]{20}',project) or parsed.path or parsed.query or parsed.fragment
            or parsed.username or parsed.password or not parsed.hostname
            or parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost'})):
            raise ValueError('invalid_local_configuration')
        self.project,self.origin,self.key,self.execute,self.clock=project,origin,key,execute,clock
        self.instance,self.challenge=str(uuid4()),str(uuid4())
        self.sessions,self.connections,self.runs={},{},{}
        self.active=None
        self.lock=threading.RLock()
        self.thread=None

    def hello(self):
        return dict(schema=SCHEMA,instance=self.instance,challenge=self.challenge,project=self.project,catalog=CATALOG)

    def verify(self,ticket,operation):
        try:
            if not isinstance(ticket,str) or len(ticket)>8192:raise ValueError()
            prefix,payload,mac=ticket.split('.')
            if prefix!='pcw1' or not re.fullmatch('[A-Za-z0-9_-]+',payload+mac):raise ValueError()
            secret=self.key()
            if not isinstance(secret,str) or len(secret.strip())<24:raise ValueError()
            key=hmac.digest(secret.strip().encode(),b'machimoa.pc-worker.capability.v1','sha256')
            if not hmac.compare_digest(b64(hmac.digest(key,payload.encode(),'sha256')).decode(),mac):raise ValueError()
            value=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            if set(value)!={'schema','operation','command','requestId','instance','challenge','project','actor','origin','catalog','iat','exp'}:raise ValueError()
            if (value['schema']!=SCHEMA or value['operation']!=operation or value['instance']!=self.instance
                or value['challenge']!=self.challenge or value['project']!=self.project or value['origin']!=self.origin or value['catalog']!=CATALOG
                or type(value['iat']) is not int or type(value['exp']) is not int or value['exp']-value['iat']!=60
                or value['iat']>self.clock()+5 or self.clock()>=value['exp']):raise ValueError()
            identity(value['actor']);identity(value['requestId'])
            if operation=='run':value['command']=command(value['command'])
            elif value['command'] is not None:raise ValueError()
            return value
        except Exception:
            raise ControlError('invalid_capability') from None

    def connect(self,ticket):
        value=self.verify(ticket,'connect')
        with self.lock:
            # Bounded in-process state; restart makes all old tickets/sessions invalid.
            now=self.clock()
            self.sessions={k:v for k,v in self.sessions.items() if v[1]>now}
            self.connections={k:v for k,v in self.connections.items() if v in self.sessions}
            connection_id=(value['actor'],value['requestId'])
            token=self.connections.get(connection_id)
            if not token:
                if len(self.sessions)>=64:raise ControlError('connection_limit',409)
                token=secrets.token_urlsafe(32)
                self.sessions[token]=(value['actor'],now+1800)
                self.connections[connection_id]=token
            return dict(token=token,instance=self.instance,expiresAt=int(self.sessions[token][1]))

    def actor(self,token):
        with self.lock:
            session=self.sessions.get(token)
            if not session or session[1]<=self.clock():raise ControlError('connection_expired',401)
            return session[0]

    def status(self,token,request_id=None):
        actor=self.actor(token)
        with self.lock:
            own=[r for r in self.runs.values() if r['actor']==actor]
            if request_id is not None:
                try:identity(request_id)
                except Exception:raise ControlError('invalid_request_id',422) from None
                run=self.runs.get(request_id)
                if run and run['actor']!=actor:run=None
            else:run=own[-1] if own else None
            return dict(busy=self.active is not None,run=self.public(run))

    @staticmethod
    def public(run):
        return None if run is None else {k:run[k] for k in ('requestId','command','state','code','counts','sourceResults')}

    def submit(self,token,ticket):
        actor=self.actor(token);value=self.verify(ticket,'run')
        if value['actor']!=actor:raise ControlError('wrong_actor')
        with self.lock:
            prior=self.runs.get(value['requestId'])
            if prior:
                if prior['actor']!=actor or prior['command']!=value['command']:raise ControlError('request_conflict',409)
                return self.status(token,value['requestId'])
            if self.active:raise ControlError('worker_busy',409)
            # Never evict deduplication state and allow a replay. Restart explicitly at the bound.
            if len(self.runs)>=1000:raise ControlError('run_history_limit',409)
            run=dict(requestId=value['requestId'],actor=actor,command=value['command'],state='running',code='',counts={},sourceResults=[])
            self.runs[value['requestId']]=run;self.active=value['requestId']
            self.thread=threading.Thread(target=self._execute,args=(run,),daemon=False)
            self.thread.start()
            return self.status(token,value['requestId'])

    def report(self,counts):
        # Internal callback only: no endpoint can write progress or start work.
        if (not isinstance(counts,dict) or len(counts)>30
            or any(not re.fullmatch('[a-z_]{1,40}',k) or type(v) is not int or v<0 for k,v in counts.items())):
            raise ValueError('invalid_worker_progress')
        with self.lock:
            if self.active is None or self.runs[self.active]['state']!='running':
                raise ValueError('inactive_worker_progress')
            self.runs[self.active]['counts']=dict(counts)

    def _execute(self,run):
        try:
            result=self.execute(dict(run['command']))
            if (not isinstance(result,dict) or set(result) not in ({'state','code','counts'},{'state','code','counts','sourceResults'})
                or result['state'] not in {'completed','partial','failed','stopped','unknown','auth_required'}
                or result['code'] not in {'','completed','worker_failed','state_unknown','reauth_required','auth_unavailable','batch_stopped','contract_unavailable','common_failure','retry_registered','provider_not_reusable','queue_snapshot_changed','queue_snapshot_invalid','queue_snapshot_limit'}
                or not isinstance(result['counts'],dict) or len(result['counts'])>30
                or any(not re.fullmatch('[a-z_]{1,40}',k) or type(v) is not int or v<0 for k,v in result['counts'].items())):
                raise ValueError()
            sources=result.get('sourceResults',[])
            if not isinstance(sources,list) or len(sources)>len(SOURCES):raise ValueError()
            seen=set()
            for source in sources:
                if (not isinstance(source,dict) or set(source)!={'source','state','code','counts'}
                    or source['source'] not in SOURCES or source['source'] in seen
                    or source['state'] not in {'completed','partial','failed','stopped','unknown','auth_required'}
                    or source['code'] not in {'','completed','worker_failed','state_unknown','reauth_required','auth_unavailable','batch_stopped','contract_unavailable','common_failure','retry_registered','provider_not_reusable'}
                    or not isinstance(source['counts'],dict) or len(source['counts'])>30
                    or any(not re.fullmatch('[a-z_]{1,40}',k) or type(v) is not int or v<0 for k,v in source['counts'].items())):
                    raise ValueError()
                seen.add(source['source'])
            result={**result,'sourceResults':sources}
        except Exception:
            # No SDK exception strings, tokens, URLs or response bodies in public diagnostics.
            result=dict(state='unknown',code='state_unknown',counts={})
        with self.lock:
            if result['state']=='unknown' and not result['counts'] and run['counts']:
                result['counts']=dict(run['counts'])
            run.update(result)
            # An unknown write/claim/AI result is not permission to start another batch.
            # Keep this instance blocked; existing administrator history must be checked first.
            if result['state']!='unknown':self.active=None
        print(json.dumps({'pcWorker':self.public(run),'actor':run['actor']},ensure_ascii=False),flush=True)

    def wait(self):
        if self.thread:self.thread.join()


def handler(control):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(5)

        def log_message(self,*args):pass

        def reply(self,status,value,*,cors=False):
            data=json.dumps(value,separators=(',',':')).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Vary','Origin')
            self.send_header('X-Content-Type-Options','nosniff')
            if cors:
                self.send_header('Access-Control-Allow-Origin',control.origin)
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
                self.send_header('Access-Control-Allow-Private-Network','true')
            self.end_headers();self.wfile.write(data)

        def dispatch(self):
            allowed=False
            try:
                if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}' or self.headers.get('Origin')!=control.origin:
                    raise ControlError('wrong_origin')
                allowed=True
                url=urlsplit(self.path);query=parse_qs(url.query,keep_blank_values=True)
                if (url.path not in {'/hello','/connect','/run','/status'} or url.fragment
                    or query and (url.path!='/status' or set(query)!={'requestId'} or len(query['requestId'])!=1)):
                    raise ControlError('not_found',404)
                if self.command=='OPTIONS':
                    if self.headers.get('Access-Control-Request-Method') not in {'GET','POST'}:raise ControlError('invalid_preflight')
                    headers={h.strip().lower() for h in self.headers.get('Access-Control-Request-Headers','').split(',') if h.strip()}
                    if headers-{'authorization','content-type'}:raise ControlError('invalid_preflight')
                    return self.reply(200,{},cors=True)
                token=self.headers.get('Authorization','').removeprefix('Bearer ')
                if self.command=='GET' and url.path=='/hello':return self.reply(200,control.hello(),cors=True)
                if self.command=='GET' and url.path=='/status':return self.reply(200,control.status(token,query.get('requestId',[None])[0]),cors=True)
                if self.command!='POST' or url.path not in {'/connect','/run'}:raise ControlError('invalid_method',405)
                if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type')!='application/json':raise ControlError('invalid_body',422)
                length=self.headers.get('Content-Length','')
                if not length.isdigit() or not 0<int(length)<=12288:raise ControlError('invalid_body',422)
                try:
                    value=json.loads(self.rfile.read(int(length)))
                    if not isinstance(value,dict) or set(value)!={'ticket'}:raise ValueError()
                except Exception:raise ControlError('invalid_body',422) from None
                result=control.connect(value['ticket']) if self.path=='/connect' else control.submit(token,value['ticket'])
                self.reply(200,result,cors=True)
            except ControlError as error:self.reply(error.status,{'code':error.code},cors=allowed)
            except Exception:self.reply(503,{'code':'worker_unavailable'},cors=allowed)

        do_GET=dispatch
        do_POST=dispatch
        do_OPTIONS=dispatch
    return Handler


def serve(control,port=PORT):
    server=ThreadingHTTPServer(('127.0.0.1',port),handler(control))
    try:
        print(f'PC 연결 준비: http://127.0.0.1:{port} · 시작만으로 수집·인증·AI를 실행하지 않습니다.',flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print('새 요청을 중단합니다. 진행 중 작업은 정식 종료까지 기다립니다. 강제 취소하지 않습니다.',flush=True)
    finally:
        server.server_close();control.wait()
