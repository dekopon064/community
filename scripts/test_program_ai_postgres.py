"""Real local PostgreSQL concurrency test. Explicit network-none Docker only.

No environment file, URL, API, real provider, or production credentials.
Synthetic pre-P0 schema mirrors the existing PGlite bootstrap; not production.
"""
import concurrent.futures
import hashlib
import json
import pathlib
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKER, CONTAINER = sys.argv[1:3]
if not re.fullmatch(r"machimoa-program-ai-[a-f0-9]{8}", CONTAINER):
    raise SystemExit("Explicit isolated test container required")
inspect = json.loads(subprocess.check_output([DOCKER, "inspect", CONTAINER], text=True))[0]


def isolated(info):
    host = info["HostConfig"]
    return (host["NetworkMode"] == "none" and not host["PortBindings"] and not host["Binds"]
            and not host.get("Mounts") and not info.get("Mounts")
            and info["Config"]["Labels"].get("machimoa.purpose") == "isolated-program-ai-concurrency")


if not isolated(inspect):
    raise SystemExit("Isolation verification failed")
if '--isolation-check' in sys.argv:
    # Independent-review correction only: no SQL connection/test replay.
    mutations = [('HostConfig','Binds',['host-data:/data']),
                 ('HostConfig','Mounts',[{'Type':'bind','Source':'host-data','Target':'/data'}]),
                 ('HostConfig','Mounts',[{'Type':'volume','Source':'existing-volume','Target':'/data'}]),
                 (None,'Mounts',[{'Type':'bind','Source':'host-socket','Destination':'/var/run/postgresql'}])]
    for parent,key,value in mutations:
        wrong=json.loads(json.dumps(inspect))
        (wrong[parent] if parent else wrong)[key]=value
        assert not isolated(wrong), 'Non-isolated mount accepted'
    print('Isolation correction checks passed: 5. Actual container plus synthetic bind/volume/socket rejection; no SQL replay.')
    raise SystemExit(0)
DB = "machimoa_ai_concurrency"
ACTOR = "00000000-0000-4000-8000-000000000001"
WORKER = "ingest-program-worker"
checks = []


class SqlError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("Local SQL error: " + code)


class Session:
    def __init__(self):
        self.name = "program_test_" + uuid.uuid4().hex[:12]
        self.out = queue.Queue()
        self.errors = []
        self.p = subprocess.Popen([DOCKER, "exec", "-i", CONTAINER, "psql", "-X", "-qAt",
                                   "-U", "postgres", "-d", DB, "-v", "ON_ERROR_STOP=1",
                                   "-v", "VERBOSITY=sqlstate"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", bufsize=1)
        def read_out():
            for line in self.p.stdout:
                self.out.put(line.strip())
            self.out.put(None)
        def read_err():
            self.errors.extend(self.p.stderr.readlines())
        self.reader = threading.Thread(target=read_out, daemon=True)
        self.err_reader = threading.Thread(target=read_err, daemon=True)
        self.reader.start(); self.err_reader.start()
        self.exec("SET application_name=" + lit(self.name) + "; SET statement_timeout='6s'; SET lock_timeout='4s';")

    def exec(self, sql):
        marker = "END_" + uuid.uuid4().hex
        self.p.stdin.write(sql.rstrip().rstrip(";") + ";\nSELECT '" + marker + "';\n")
        self.p.stdin.flush()
        lines = []
        while True:
            try:
                line = self.out.get(timeout=12)
            except queue.Empty:
                raise SqlError("client_timeout") from None
            if line is None:
                self.p.wait(timeout=3); self.err_reader.join(timeout=1)
                matched = re.search(r"ERROR:\s+([A-Z0-9]{5})", "".join(self.errors))
                raise SqlError(matched[1] if matched else "psql_exit")
            if line == marker:
                return lines
            if line:
                lines.append(line)

    def value(self, expression):
        lines = self.exec("SELECT to_jsonb(" + expression + ")::text")
        return json.loads(lines[-1])

    def close(self):
        if self.p.poll() is None:
            try:
                self.p.stdin.write("\\q\n"); self.p.stdin.flush(); self.p.wait(timeout=3)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.p.terminate()


def lit(value):
    if value is None: return "NULL"
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, (int, float)): return str(value)
    if isinstance(value, (dict, list)): value = json.dumps(value, ensure_ascii=False)
    return "'" + str(value).replace("'", "''") + "'"


def rpc_sql(name, args):
    return "public." + name + "(" + ",".join(lit(a) for a in args) + ")"


def rpc(name, args):
    with_conn = Session()
    try:
        with_conn.exec("SET ROLE service_role")
        return with_conn.value(rpc_sql(name, args))
    finally: with_conn.close()


def rpc_as(role, name, args):
    session = Session()
    try:
        session.exec("SET ROLE " + role)
        return session.value(rpc_sql(name, args))
    finally: session.close()


def expect_error(fn, code, label):
    try: fn()
    except SqlError as e:
        assert e.code == code, (label, e.code)
    else: raise AssertionError(label + " unexpectedly succeeded")
    checks.append(label)


def check(condition, label):
    assert condition, label
    checks.append(label)


def packet(context):
    return json.loads(subprocess.check_output([sys.executable, "-X", "utf8", "test_program_ai.py", "--packet"],
                     cwd=ROOT / "scripts", input=json.dumps(context, ensure_ascii=False), text=True, encoding="utf-8"))


def finish_args(p):
    return [p[k] for k in ("p_job_id", "p_revision", "p_facts_version", "p_claimed_at", "p_lease_until", "p_worker_id", "p_output")]


def wait_locked(session):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        if db.value("exists(select 1 from pg_stat_activity where application_name=" + lit(session.name)
                    + " and wait_event_type='Lock')"):
            return
        time.sleep(.025)
    raise AssertionError("Expected independent session lock wait not observed")


def queued_count(id):
    return db.value("(select count(*) from machimoa_review.curation_candidates c join machimoa_review.source_items s"
                    " on c.source='seoul_reservation' and c.source_item_id=s.external_key where s.id=" + lit(id) + ")")


db = Session()
pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
samples = json.loads(subprocess.check_output([sys.executable, "-X", "utf8", "test_program_db.py", "--fixtures"],
                     cwd=ROOT / "scripts", text=True, encoding="utf-8"))
run = None


def seed(label, fixture="personal", change=None):
    item = json.loads(json.dumps(next(x["item"] for x in samples["storageFixtures"] if x["name"] == fixture)))
    item["external_key"] = label
    item["revision_hash"] = hashlib.sha256(label.encode()).hexdigest()
    item["normalized_payload"]["provider_fields"]["SVCID"] = label
    item["normalized_payload"]["source_url"] = item["program_facts"]["official_url"] = (
        "https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=" + label)
    if change: change(item)
    id = rpc("observe_seoul_program", [run, [item], None])[0]["id"]
    return id, item["revision_hash"]


def claim(id, revision):
    return rpc("claim_seoul_program_ai", [id, revision, WORKER, 600])


def extra_tests():
    # Real adapter -> real PostgreSQL RPC callable, with synthetic providers only.
    from ingest.program_ai import ProgramAIAdapter, process_seoul_program_job
    from test_program_ai import providers
    id, rev = seed("adapter_live", "family_paid")
    base = db.value("(select jsonb_build_object('title',s.min_fields->>'title','facts',f.facts) from machimoa_review.source_items s join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=s.revision_hash where s.id="+lit(id)+")")
    ko, ja, calls = providers(base)
    def live_rpc(name, args):
        session=Session()
        try:
            session.exec("SET ROLE service_role")
            expression="public."+name+"("+",".join(k+"=>"+lit(v) for k,v in args.items())+")"
            return session.value(expression)
        finally:session.close()
    result=process_seoul_program_job(ProgramAIAdapter(live_rpc),source_item_id=id,revision=rev,summarize_ko=ko,translate_ja=ja)
    check(result.completed==1 and len(calls)==1 and queued_count(id)==1,"actual Python adapter / PostgreSQL roundtrip, fake provider")

    # Observation's own active-claim guard rolls back the whole new revision.
    id,rev=seed("observe_race")
    item=json.loads(json.dumps(next(x['item'] for x in samples['storageFixtures'] if x['name']=='personal')))
    item['external_key']='observe_race';item['revision_hash']=hashlib.sha256(b'observe_revision_two').hexdigest()
    item['normalized_payload']['provider_fields']['SVCID']='observe_race'
    a,b=Session(),Session()
    try:
        a.exec("BEGIN;SET LOCAL ROLE service_role")
        a.value(rpc_sql('claim_seoul_program_ai',[id,rev,WORKER,600]))
        b.exec('SET ROLE service_role')
        future=pool.submit(b.value,rpc_sql('observe_seoul_program',[run,[item],None]));wait_locked(b);a.exec('COMMIT')
        expect_error(lambda:future.result(timeout=8),'PT409','actual observation waits then rejects active claim')
        check(db.value('(select revision_hash from machimoa_review.source_items where id='+lit(id)+')')==rev,'observation revision rollback')
    finally:a.close();b.close()

    # Two administrators resolving the same review cannot silently overwrite.
    def missing_url(item):
        item['program_facts']['official_url']='';item['normalized_payload']['source_url']=None;item['has_source_url']=False
    id,rev=seed('admin_save_race',change=missing_url)
    detail=rpc('admin_program_detail',[id]);url='https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=admin_save_race'
    expr='public.admin_program_save('+','.join(lit(v) for v in [id,rev,detail['version'],{'official_url':url}])+",ARRAY[]::text[],"+lit('합성 공식 링크 보완')+','+lit(ACTOR)+')'
    a,b=Session(),Session()
    try:
        a.exec('BEGIN;SET LOCAL ROLE service_role');saved=a.value(expr)
        b.exec('SET ROLE service_role');future=pool.submit(b.value,expr);wait_locked(b);a.exec('COMMIT')
        expect_error(lambda:future.result(timeout=8),'PT409','concurrent actual admin save version conflict')
        check(saved['factsVersion']==2 and saved['aiStatus']=='queued','actual save re-evaluates / queues without provider')
        check(len(saved['history'])==1 and saved['history'][0]['actor']==ACTOR,'actual save actor and event once')
    finally:a.close();b.close()

    # First fenced failure wins; an old completion cannot follow queued retry.
    id,rev=seed('failure_finish_race');c=claim(id,rev)[0];p=packet(c)
    a,b=Session(),Session()
    try:
        a.exec('BEGIN;SET LOCAL ROLE service_role')
        retried=a.value(rpc_sql('fail_seoul_program_ai',[c['jobId'],c['claimedAt'],c['leaseUntil'],WORKER,'ai_http_429']))
        b.exec('SET ROLE service_role');future=pool.submit(b.value,rpc_sql('finish_seoul_program_ai',finish_args(p)))
        wait_locked(b);a.exec('COMMIT')
        expect_error(lambda:future.result(timeout=8),'PT409','completion blocked after concurrent fenced failure')
        check(retried=='queued' and queued_count(id)==0,'retry leaves no candidate')
    finally:a.close();b.close()

    # Permission disable winner, distinct from approval-status change.
    race_finish_change('disabled_extra',lambda id,rev:"UPDATE machimoa_review.ingest_sources SET enabled=false WHERE source_id='seoul_reservation'",True)

    # Complete first, then a facts writer: the saved input stays versioned and
    # the later current facts make the candidate unpublishable.
    id,rev=seed('finish_first');c=claim(id,rev)[0];p=packet(c)
    a,b=Session(),Session()
    try:
        a.exec('BEGIN;SET LOCAL ROLE service_role');r=a.value(rpc_sql('finish_seoul_program_ai',finish_args(p)))
        future=pool.submit(b.exec,'UPDATE machimoa_review.source_item_program_facts SET facts_version=facts_version+1 WHERE source_item_id='+lit(id))
        wait_locked(b);a.exec('COMMIT');future.result(timeout=8)
        d=rpc('admin_review_detail',['candidates',r['candidateId']])
        check(d['programInfo']['inputChanged'] and not d['programInfo']['canPublish'],'completion-first then facts writer blocks publication')
    finally:a.close();b.close()

    # Deliberate reversed *test-only* row locks verify deadlock detection and
    # victim rollback; this does not demonstrate a product-path deadlock.
    left,lrev=seed('deadlock_left');right,rrev=seed('deadlock_right')
    a,b=Session(),Session()
    try:
        a.exec("SET deadlock_timeout='100ms';BEGIN;SELECT id FROM machimoa_review.source_items WHERE id="+lit(left)+' FOR UPDATE')
        b.exec("SET deadlock_timeout='100ms';BEGIN;SELECT id FROM machimoa_review.source_items WHERE id="+lit(right)+' FOR UPDATE')
        fa=pool.submit(a.exec,'SELECT id FROM machimoa_review.source_items WHERE id='+lit(right)+' FOR UPDATE')
        wait_locked(a)
        fb=pool.submit(b.exec,'SELECT id FROM machimoa_review.source_items WHERE id='+lit(left)+' FOR UPDATE')
        codes=[]
        for future in [fa,fb]:
            try:future.result(timeout=8);codes.append('ok')
            except SqlError as e:codes.append(e.code)
        check(sorted(codes)==['40P01','ok'],'controlled reversed test locks detect deadlock / rollback victim')
    finally:a.close();b.close()
    check(db.value('(select count(*) from public.curations)')==2,'extra tests did not publish')


def race_finish_change(label, change, gate=False):
    id, rev = seed(label)
    c = claim(id, rev)[0]; p = packet(c)
    a, b = Session(), Session()
    try:
        a.exec("BEGIN; SELECT " + ("source_id FROM machimoa_review.ingest_sources WHERE source_id='seoul_reservation'" if gate
                else "id FROM machimoa_review.source_items WHERE id=" + lit(id)) + " FOR UPDATE")
        b.exec("SET ROLE service_role")
        future = pool.submit(b.value, rpc_sql("finish_seoul_program_ai", finish_args(p)))
        wait_locked(b)
        a.exec(change(id, rev) + ";COMMIT")
        expect_error(lambda: future.result(timeout=8), "PT409", label + ": old completion blocked after waiting")
        check(queued_count(id) == 0, label + ": no partial candidate")
    finally: a.close(); b.close()
    if gate:
        db.exec("UPDATE machimoa_review.ingest_sources SET enabled=true,permission_status='approved_noncommercial' WHERE source_id='seoul_reservation'")


try:
    if '--extra' in sys.argv:
        check(db.value("to_regnamespace('machimoa_review') is not null"),'existing isolated test schema only')
        run=db.value("(select run_id from public.start_ingest_run('seoul_reservation',3600))")
        if run is None:raise AssertionError('Previous synthetic ingest lease still active; no forced replacement')
        extra_tests()
        print(json.dumps({'checks':len(checks),'passed':checks,'postgrest':'not tested'},ensure_ascii=False,indent=2))
        raise SystemExit(0)
    # Explicit fresh database only: refuses to run in an existing test schema.
    check(db.value("to_regnamespace('machimoa_review') is null"), "fresh dedicated database")
    db.exec("CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;"
            "CREATE TABLE public.curations(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),slug text NOT NULL UNIQUE,"
            "category text,title text NOT NULL,summary text,content text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());"
            "ALTER TABLE public.curations ENABLE ROW LEVEL SECURITY;"
            "INSERT INTO public.curations(slug,title,summary,content) VALUES('baseline-one','one','one','one'),('baseline-two','two','two','two')")
    files = sorted(p for p in (ROOT / "supabase/migrations").glob("*.sql") if
                   "20260827022301" <= p.name < "20260903" or "20260913" <= p.name <= "20261001000001_seoul_program_ai.sql")
    defs_expr = "(select jsonb_agg(jsonb_build_object('name',p.proname,'def',pg_get_functiondef(p.oid),'acl',p.proacl::text) order by p.proname) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_review' and p.proname in ('claim_processing_jobs','enqueue_curation_candidate','publish_curation_candidate','fail_processing_job','complete_processing_job'))"
    legacy = None
    for path in files:
        if path.name == "20261001000001_seoul_program_ai.sql": legacy = db.value(defs_expr)
        db.exec(path.read_text(encoding="utf-8"))
        if path.name.startswith("20260827022301"):
            db.exec("INSERT INTO machimoa_review.curation_candidates(source,source_item_id,source_revision_hash,slug,title,summary,content,raw_payload,ai_status) SELECT 'youthcenter','baseline-'||n,repeat('a',64),'baseline-candidate-'||n,'title','summary','content','{}','success' FROM generate_series(1,4)n")
    check(db.value(defs_expr) == legacy, "legacy function bodies and ACL unchanged")
    for role in ["anon", "authenticated", "service_role"]:
        for name in ["claim_seoul_program_ai", "finish_seoul_program_ai", "fail_seoul_program_ai"]:
            allowed = db.value("(select has_function_privilege(" + lit(role) + ",p.oid,'execute') from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname=" + lit(name) + ")")
            check(allowed == (role == "service_role"), role + ": " + name + " ACL")
    for role in ["anon", "authenticated"]:
        expect_error(lambda r=role: rpc_as(r, "claim_seoul_program_ai", [str(uuid.uuid4()), "a"*64, WORKER, 600]), "42501", role + ": actual invocation denied")
    db.exec("UPDATE machimoa_review.ingest_sources SET enabled=true,permission_status='approved_noncommercial' WHERE source_id='seoul_reservation'")
    run = db.value("(select run_id from public.start_ingest_run('seoul_reservation',120))")

    # Hold the first RPC transaction open; the second independent session skips it.
    id, rev = seed("concurrent_claim", "family_paid")
    a, b = Session(), Session()
    try:
        a.exec("BEGIN;SET LOCAL ROLE service_role")
        c = a.value(rpc_sql("claim_seoul_program_ai", [id, rev, WORKER, 600]))[0]
        b.exec("SET ROLE service_role")
        check(b.value(rpc_sql("claim_seoul_program_ai", [id, rev, WORKER, 600])) == [], "simultaneous claim skips locked target")
        a.exec("COMMIT")
    finally: a.close(); b.close()
    check(claim(id, rev) == [], "active lease prevents second claim")
    wrong, wrev = seed("wrong_source")
    db.exec("UPDATE machimoa_review.source_items SET source_id='youthcenter_content' WHERE id=" + lit(wrong))
    check(claim(wrong, wrev) == [], "wrong source never acquired")
    other, orev = seed("not_target")
    check(claim(id, rev) == [] and db.value("(select status from machimoa_review.processing_jobs where source_item_id=" + lit(other) + " and processing_stage='ai_enrichment')") == "queued", "non-target queue untouched")

    old = packet(c)
    db.exec("UPDATE machimoa_review.processing_jobs SET claim_lease_until=clock_timestamp()-interval '1 second' WHERE id=" + lit(c["jobId"]))
    expect_error(lambda: rpc("finish_seoul_program_ai", finish_args(old)), "PT409", "expired completion blocked")
    new_c = claim(id, rev)[0]
    check(new_c["claimedAt"] != c["claimedAt"], "same worker reacquisition has different fence")
    expect_error(lambda: rpc("finish_seoul_program_ai", finish_args(old)), "PT409", "past completion blocked after reacquisition")
    expect_error(lambda: rpc("fail_seoul_program_ai", [c["jobId"], c["claimedAt"], c["leaseUntil"], WORKER, "ai_schema_error"]), "PT409", "past failure blocked after reacquisition")
    p = packet(new_c)
    a, b = Session(), Session()
    try:
        a.exec("BEGIN;SET LOCAL ROLE service_role")
        first = a.value(rpc_sql("finish_seoul_program_ai", finish_args(p)))
        b.exec("SET ROLE service_role")
        future = pool.submit(b.value, rpc_sql("finish_seoul_program_ai", finish_args(p)))
        wait_locked(b); a.exec("COMMIT")
        second = future.result(timeout=8)
        check(first["outcome"] == "inserted" and second["outcome"] == "duplicate" and first["candidateId"] == second["candidateId"], "concurrent duplicate finish idempotent")
        check(queued_count(id) == 1, "exactly one candidate after duplicate finish")
    finally: a.close(); b.close()
    candidate = first["candidateId"]
    check(db.value("(select status from machimoa_review.processing_jobs where id=" + lit(c["jobId"]) + ")") == "completed", "atomic job completed")
    check(db.value("(select count(*) from machimoa_review.program_candidate_inputs where candidate_id=" + lit(candidate) + ")") == 1, "atomic input history once")

    race_finish_change("facts_race", lambda id,rev: "UPDATE machimoa_review.source_item_program_facts SET facts_version=facts_version+1 WHERE source_item_id="+lit(id))
    race_finish_change("revision_race", lambda id,rev: "UPDATE machimoa_review.source_items SET revision_hash=repeat('b',64) WHERE id="+lit(id))
    race_finish_change("closed_race", lambda id,rev: "UPDATE machimoa_review.source_item_program_facts SET facts=jsonb_set(facts,'{source_status}','\"reservation_closed\"') WHERE source_item_id="+lit(id))
    race_finish_change("exclude_race", lambda id,rev: "UPDATE machimoa_review.source_item_program_facts SET manual_excluded=true,facts_version=facts_version+1 WHERE source_item_id="+lit(id))
    race_finish_change("permission_race", lambda id,rev: "UPDATE machimoa_review.ingest_sources SET permission_status='testing_only' WHERE source_id='seoul_reservation'", True)

    # Trigger failure demonstrates all three writes rolling back in actual PG.
    rid, rrev = seed("atomic_abort"); rc = claim(rid, rrev)[0]; rp = packet(rc)
    db.exec("CREATE FUNCTION machimoa_review.synthetic_abort() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION USING ERRCODE='PT999',MESSAGE='synthetic_abort';END$$; CREATE TRIGGER synthetic_abort BEFORE INSERT ON machimoa_review.program_candidate_inputs FOR EACH ROW EXECUTE FUNCTION machimoa_review.synthetic_abort()")
    expect_error(lambda: rpc("finish_seoul_program_ai", finish_args(rp)), "PT999", "injected input history failure")
    check(queued_count(rid) == 0 and db.value("(select status from machimoa_review.processing_jobs where id="+lit(rc["jobId"])+")") == "claimed", "candidate and job rollback together")
    db.exec("DROP TRIGGER synthetic_abort ON machimoa_review.program_candidate_inputs;DROP FUNCTION machimoa_review.synthetic_abort()")

    # Candidate snapshot token becomes stale after a concurrent facts writer.
    for action in ["save", "reject", "publish"]:
        detail = rpc("admin_review_detail", ["candidates", candidate])
        a, b = Session(), Session()
        try:
            a.exec("BEGIN;SELECT id FROM machimoa_review.source_items WHERE id="+lit(id)+" FOR UPDATE")
            b.exec("SET ROLE service_role")
            args = [candidate, detail["revision"], detail["version"]]
            if action == "save": args += [dict(detail["content"], titleJa="合成編集"), ACTOR]
            elif action == "reject": args += ["合成検証", ACTOR]
            else: args += [ACTOR]
            name = {"save":"admin_review_save_candidate", "reject":"admin_review_reject", "publish":"admin_review_publish"}[action]
            future = pool.submit(b.value, rpc_sql(name, args)); wait_locked(b)
            a.exec("UPDATE machimoa_review.source_item_program_facts SET facts_version=facts_version+1 WHERE source_item_id="+lit(id)+";COMMIT")
            expect_error(lambda: future.result(timeout=8), "PT409", "candidate "+action+" stale snapshot after facts race")
        finally: a.close(); b.close()
    changed = rpc("admin_review_detail", ["candidates", candidate])
    check(changed["programInfo"]["inputChanged"] and not changed["programInfo"]["canPublish"], "facts changed publication unavailable")
    expect_error(lambda: rpc("admin_review_publish", [candidate,changed["revision"],changed["version"],ACTOR]), "PT409", "fresh snapshot still blocked by old input")
    check(rpc("admin_review_reject", [candidate,changed["revision"],changed["version"],"合成入力変更",ACTOR])["status"] == "rejected", "fresh rejection permitted after input change")

    # Gate-closed expired attempt is recoverable without authorizing execution.
    eid, erev = seed("expired_closed"); ec=claim(eid,erev)[0]; ep=packet(ec)
    db.exec("UPDATE machimoa_review.processing_jobs SET claim_lease_until=clock_timestamp()-interval '1 second' WHERE id="+lit(ec["jobId"])+";UPDATE machimoa_review.source_item_program_facts SET facts=jsonb_set(facts,'{source_status}','\"reservation_closed\"') WHERE source_item_id="+lit(eid))
    check(claim(eid,erev) == [], "closed expired gate refuses claim")
    db.exec("SELECT machimoa_review.program_refresh("+lit(eid)+")")
    check(db.value("(select status from machimoa_review.processing_jobs where id="+lit(ec["jobId"])+")") == "cancelled", "closed expired refresh no longer blocked")
    expect_error(lambda:rpc("finish_seoul_program_ai",finish_args(ep)),"PT409","closed expired past response blocked")

    # Controlled blocking exercises bounded lock timeout without changing data.
    tid, trev = seed("lock_timeout"); tc=claim(tid,trev)[0]; tp=packet(tc)
    a,b=Session(),Session()
    try:
        a.exec("BEGIN;SELECT id FROM machimoa_review.source_items WHERE id="+lit(tid)+" FOR UPDATE")
        b.exec("SET lock_timeout='250ms';SET ROLE service_role")
        future=pool.submit(b.value,rpc_sql("finish_seoul_program_ai",finish_args(tp)));wait_locked(b)
        expect_error(lambda:future.result(timeout=4),"55P03","bounded lock timeout safe failure")
        a.exec("COMMIT");check(queued_count(tid)==0,"timeout leaves no candidate")
    finally:a.close();b.close()
    check(db.value(defs_expr)==legacy,"legacy bodies and ACL unchanged after tests")
    check(db.value("(select count(*) from public.curations)")==2,"no publication during guard tests")
    print(json.dumps({"checks":len(checks),"passed":checks,"transport":"local container psql, independent PG sessions", "postgrest":"not tested"},ensure_ascii=False,indent=2))
finally:
    pool.shutdown(wait=True,cancel_futures=True);db.close()
