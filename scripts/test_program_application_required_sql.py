"""Synthetic-only dedicated database in the verified network-none container."""
import argparse,copy,json,re,subprocess
from pathlib import Path
from uuid import uuid4
from test_myseoul_db import fixtures
parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--definition-format-only',action='store_true');args=parser.parse_args()
assert args.database.startswith('review_program_dates_') and args.database.replace('_','').isalnum()
container='machimoa-program-ai-5689d361'
def docker(parts,body=None):
    r=subprocess.run(['docker',*parts],input=body.encode() if body else None,capture_output=True)
    if r.returncode:raise RuntimeError(r.stderr.decode())
    return r.stdout.decode().strip()
meta=json.loads(docker(['inspect',container]))[0]
assert meta['State']['Running'] and meta['HostConfig']['NetworkMode']=='none' and not meta['HostConfig']['PortBindings'] and not meta['Mounts'] and meta['Config']['Labels']['machimoa.purpose']=='isolated-program-ai-concurrency'
assert json.loads(docker(['context','inspect']))[0]['Endpoints']['docker']['Host']=='npipe:////./pipe/dockerDesktopLinuxEngine'
def sql(q):return docker(['exec','-i',container,'psql','-X','-U','postgres','-d',args.database,'-qAt','-v','ON_ERROR_STOP=1','-v','VERBOSITY=verbose'],q)
def lit(x):return 'NULL' if x is None else str(x).lower() if isinstance(x,bool) else str(x) if isinstance(x,int) else "'"+(x if isinstance(x,str) else json.dumps(x,ensure_ascii=False)).replace("'","''")+"'"
def scalar(q):return json.loads(sql('select to_jsonb('+q+');') or 'null')
def rpc(name,x):return json.loads(sql('begin;set local role service_role;select public.'+name+'('+','.join(map(lit,x))+');commit;'))
checks=0
def ok(v):
    global checks
    assert v;checks+=1
def deny(q,code):
    global checks
    try:sql(q)
    except RuntimeError as e:assert code in str(e),str(e);checks+=1
    else:raise AssertionError('expected '+code)
def reject(name,x,code='PT422'):deny('begin;set local role service_role;select public.'+name+'('+','.join(map(lit,x))+');commit;',code)
root=Path(__file__).resolve().parents[1]
up=(root/'supabase/migrations/20261010075650_program_application_required.sql').read_text(encoding='utf8')
down=(root/'supabase/rollback/20261010075650_program_application_required_down.sql').read_text(encoding='utf8')
if args.definition_format_only:
    guard=re.search(r'do \$\$ begin[\s\S]*?end \$\$;',up).group()
    names=[n for n in dict.fromkeys(re.findall(r"to_regprocedure\('([^']+)'\)",guard)) if n!='machimoa_review.program_dates_dirty()']
    def crlf_definitions(signatures):
        for name in signatures:
            definition=scalar('pg_get_functiondef('+lit(name)+'::regprocedure)')
            sql(definition.replace('\r\n','\n').replace('\r','\n').replace('\n','\r\n'))
    crlf_definitions(names)
    sql(guard);ok(True)
    definition=scalar("pg_get_functiondef('machimoa_review.classification_ready(uuid)'::regprocedure)")
    changed=definition.replace('AS $function$','AS $function$\n-- unexpected definition change\n',1)
    deny('begin;'+changed+';'+guard+'rollback;','program_dates_definition_changed')
    ok(scalar("to_regclass('machimoa_review.program_dates_install') is null"))
    sql(up);ok(scalar("to_regclass('machimoa_review.program_dates_install') is not null"))
    crlf_definitions(names+['machimoa_review.program_dates_dirty()'])
    installed=scalar("pg_get_functiondef('machimoa_review.classification_ready(uuid)'::regprocedure)")
    changed=installed.replace('AS $function$','AS $function$\n-- unexpected definition change\n',1)
    deny('begin;'+changed+';'+down,'program_dates_definition_changed')
    ok(scalar("to_regclass('machimoa_review.program_dates_install') is not null"))
    sql(down);ok(scalar("to_regclass('machimoa_review.program_dates_install') is null"))
    sql(up);ok(scalar("to_regclass('machimoa_review.program_dates_install') is not null"))
    print(json.dumps({'checks':checks,'database':args.database,'network':'none','syntheticOnly':True,'result':'passed','scope':'LF/CRLF install/rollback and definition drift protection'}))
    raise SystemExit(0)
if not scalar('(select dirty from machimoa_review.program_dates_install)'):
    deny("begin;alter function machimoa_review.content_filter_missing(jsonb) set search_path='public';"+down,'program_dates_definition_changed')
    ok(scalar("(select proconfig=array['search_path=\"\"']::text[] from pg_proc where oid='machimoa_review.content_filter_missing(jsonb)'::regprocedure)"))
    sql(down);ok(scalar("to_regclass('machimoa_review.program_dates_install') is null"));sql(up)
    deny('begin;alter table machimoa_review.program_dates_install add column unexpected text;'+down,'program_dates_schema_changed')
    ok(not scalar("exists(select 1 from pg_attribute where attrelid='machimoa_review.program_dates_install'::regclass and attname='unexpected')"))
for role in ['anon','authenticated','service_role']:
    ok(not scalar("has_table_privilege('"+role+"','machimoa_review.program_dates_install','select')"))
    ok(not scalar("has_function_privilege('"+role+"','machimoa_review.program_dates_dirty()','execute')"))
actor='00000000-0000-4000-8000-000000000001'
run=scalar("(select active_run_id from machimoa_review.source_sync_state where source_id='myseoul_program' and lease_expires_at>clock_timestamp())")
if not run:run=scalar("(select run_id from public.start_ingest_run('myseoul_program',3600))")
base=next(x['item'] for x in fixtures()['fixtures'] if x['name']=='online')
def observe():
    p=copy.deepcopy(base);old=p['external_key'].split(':')[-1];p=json.loads(json.dumps(p).replace(old,uuid4().hex.upper()));p['revision_hash']=uuid4().hex*2
    p['myseoul_facts'].update(source_revision=p['revision_hash'],residence_scope='unknown',residence='',residence_evidence=[])
    return rpc('observe_myseoul_program',[run,[p],None])[0]['id']
sid=observe();d=rpc('admin_content_filter_detail',[sid]);before=copy.deepcopy(d)
app=scalar('machimoa_review.content_filter_fact_values('+lit(sid)+','+lit(d['revision'])+')->\'application\'')
assert app['start'] and app['end']
for a in [{**app,'start':None},{'deadlineKind':'none','start':None,'end':None,'sourceStatus':'unknown'},{**app,'end':None}]:
    reject('admin_content_filter_save',[sid,d['revision'],d['version'],d['filterVersion'],{'application':{'status':'known','value':a}},actor])
    ok(rpc('admin_content_filter_detail',[sid])==before)
    legacy={**d['data'],'application':{'status':'known','value':a}}
    if a['end'] is not None or a['deadlineKind']=='none':
        ok('application' in scalar('machimoa_review.content_filter_missing('+lit(legacy)+'::jsonb)'))
        ok('application' in scalar('machimoa_review.classification_filter_missing('+lit(legacy)+'::jsonb)'))
saved=rpc('admin_content_filter_save',[sid,d['revision'],d['version'],d['filterVersion'],{'application':{'status':'known','value':app}},actor])
ok(saved['data']['application']['value']==app);ok(saved['filterVersion']==d['filterVersion']+1)
reject('admin_content_filter_save',[sid,d['revision'],d['version'],d['filterVersion'],{'application':{'status':'known','value':app}},actor],'PT409')
known=lambda v:{'status':'known','value':v}
na={'status':'not_applicable','value':None}
f={'productType':'event_program','category':'program','scope':'nationwide','regions':[],'evidence':'합성 원문: 전국 신청','foreignEligibility':'unknown','delivery':'online','deadlineKind':'fixed','deadlineOn':'2099-10-15','eventStart':'','eventEnd':''}
filters={**saved['data'],'topic':known('language_learning'),'delivery':known('online'),'audience':known('other'),'location':na,'application':known({'deadlineKind':'fixed','start':{'value':'2099-10-01','precision':'day'},'end':{'value':'2099-10-15','precision':'day'},'sourceStatus':'unknown'})}
cd=rpc('admin_review_classification_detail',[sid])
for bad in [{**filters,'application':known({**filters['application']['value'],'start':None})},{**filters,'application':known({'deadlineKind':'none','start':None,'end':None,'sourceStatus':'unknown'})}]:
    reject('admin_review_reclassify',[sid,cd['revision'],cd['version'],cd['classificationVersion'],f,bad,'합성 원문을 확인하여 분류와 필수 기간을 입력합니다.',actor])
    ok(rpc('admin_review_classification_detail',[sid])==cd)
classified=rpc('admin_review_reclassify',[sid,cd['revision'],cd['version'],cd['classificationVersion'],f,filters,'합성 원문을 확인하여 분류와 필수 기간을 입력합니다.',actor])
ok(classified['filters']==filters);ok(classified['facts']['deadlineKind']=='fixed');ok('content_filter:application' not in classified['reasons'])
sql('select machimoa_review.classification_validate('+lit(f)+'::jsonb,'+lit(filters)+'::jsonb);');ok(True)
timed=copy.deepcopy(filters);timed['application']['value']['end']={'value':'2099-10-15T18:00:00+09:00','precision':'minute'}
sql('select machimoa_review.classification_validate('+lit(f)+'::jsonb,'+lit(timed)+'::jsonb);');ok(True)
# Legacy snapshots remain readable but cannot become ready or claim new AI work.
legacy={**filters,'application':known({**filters['application']['value'],'start':None})}
sql('update machimoa_review.review_classifications set filters='+lit(legacy)+'::jsonb where source_item_id='+lit(sid)+';')
current=rpc('admin_review_classification_detail',[sid]);ok(current['filters']==legacy);ok(not current['ready']);ok('content_filter:application' in current['reasons']);ok(not scalar('machimoa_review.content_filter_ready('+lit(sid)+','+lit(current['revision'])+')'))
# Restoring a record locally is not permitted to make rollback pass: the flag persists.
sql('update machimoa_review.review_classifications set filters='+lit(filters)+'::jsonb where source_item_id='+lit(sid)+';')
ok(scalar('(select dirty from machimoa_review.program_dates_install)'))
deny(down,'program_dates_records_changed');ok(scalar("to_regclass('machimoa_review.program_dates_install') is not null"))
policy={**f,'category':'policy','productType':'policy_reference','foreignEligibility':'eligible','deadlineKind':'none','deadlineOn':''}
sql('select machimoa_review.classification_validate('+lit(policy)+'::jsonb,null);');ok(True)
space={**filters,'category':'youth_space','topic':na,'delivery':na,'audience':na,'application':na,'spaceKind':known('news'),'location':na}
ok(scalar('machimoa_review.classification_filter_missing('+lit(space)+'::jsonb)')==[])
# A generic source with no native start date can explicitly complete the same
# program category through the common facts+filter reclassification transaction.
generic=str(uuid4());revision=uuid4().hex*2
sql('insert into machimoa_review.source_items(id,source_id,external_key,revision_hash,disposition,min_fields,normalized_payload,has_source_url,body_usable,attachment_present,attachment_length,is_data_url,first_seen_at,last_seen_at,source_created_parse_status,source_updated_parse_status) values('+','.join(map(lit,[generic,'youthcenter_content','synthetic-'+uuid4().hex,revision,'observe_only',{'title':'합성 프로그램','source_url':'https://synthetic.invalid/item'},{'plain_text':'합성 원문: 신청 기간 2099-10-01 ~ 2099-10-15. 전국 신청 가능.','source_url':'https://synthetic.invalid/item'},True,True,False,0,False,'2026-10-10T00:00:00Z','2026-10-10T00:00:00Z','missing','missing']))+');')
generic_detail=rpc('admin_review_classification_detail',[generic])
sql('insert into machimoa_review.source_item_user_categories(source_item_id,revision_hash,user_category,reviewer) values('+','.join(map(lit,[generic,revision,'program','synthetic-date-reviewer']))+');')
sql('insert into machimoa_review.source_item_application_deadlines(source_item_id,revision_hash,application_deadline_kind,application_deadline_on) values('+','.join(map(lit,[generic,revision,'fixed','2099-10-15']))+');')
generic_detail=rpc('admin_review_classification_detail',[generic]);ok(generic_detail['category']=='program')
ok(scalar('machimoa_review.content_filter_fact_values('+lit(generic)+','+lit(revision)+')->\'application\'->\'start\'') is None)
generic_saved=rpc('admin_review_reclassify',[generic,revision,generic_detail['version'],0,f,filters,'합성 원문에서 시작일·마감일을 확인하여 프로그램으로 분류합니다.',actor])
ok(generic_saved['filters']==filters);ok(generic_saved['ready']);ok(generic_saved['id']==generic)
ok(scalar('machimoa_review.content_filter_ready('+lit(generic)+','+lit(revision)+')'))
print(json.dumps({'checks':checks,'database':args.database,'network':'none','syntheticOnly':True,'result':'passed'}))
