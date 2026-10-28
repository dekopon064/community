"""Network-none disposable PostgreSQL; synthetic baseline only. Never a connection URL.

The original curations CREATE is absent from this repository. This explicit minimum
fixture models its required columns; it is not proof of full historical replay.
Uses an already-installed image and never pulls an image or reads credentials.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
ACTOR='00000000-0000-4000-8000-000000000001'


def run(image):
    container='machimoa-living-test-'+uuid4().hex[:12]
    docker=['docker','--context','desktop-linux']
    def command(args,sql=None,check=True):
        # Binary stdin preserves canonical SQL function bodies on Windows too.
        result=subprocess.run(docker+args,input=sql.encode('utf-8') if sql is not None else None,capture_output=True,timeout=30)
        result.stdout=result.stdout.decode('utf-8');result.stderr=result.stderr.decode('utf-8')
        if check and result.returncode:raise RuntimeError(result.stderr.strip())
        return result
    command(['image','inspect',image])
    command(['run','--pull=never','--network','none','--name',container,'--tmpfs','/var/lib/postgresql/data',
        '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_USER=local_bootstrap','-e','POSTGRES_DB=postgres','-d',image])
    checks=0
    def sql(value,role=None,check=True):
        prefix='set role '+role+';' if role else ''
        return command(['exec','-i',container,'psql','-XqAt','-d','postgres','-U','postgres','-v','ON_ERROR_STOP=1'],prefix+value,check)
    def query(value,role=None):return json.loads(sql("select coalesce(json_agg(x),'[]'::json) from ("+value+")x",role).stdout.strip())
    def literal(value):
        if value is None:return 'null'
        if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False)
        if isinstance(value,int):return str(value)
        return "'"+str(value).replace("'","''")+"'"
    def rpc(name,args):return query('select public.'+name+'('+','.join(map(literal,args))+') value','service_role')[0]['value']
    def equal(a,b):
        nonlocal checks
        assert a==b,(a,b);checks+=1
    def fails(name,args):
        nonlocal checks
        result=sql('select public.'+name+'('+','.join(map(literal,args))+')','service_role',False)
        assert result.returncode!=0;checks+=1
    try:
        for _ in range(30):
            if command(['exec',container,'pg_isready','-U','local_bootstrap'],check=False).returncode==0:break
            time.sleep(.5)
        else:raise RuntimeError('isolated PostgreSQL not ready')
        command(['exec','-i',container,'psql','-XqAt','-d','postgres','-U','local_bootstrap','-v','ON_ERROR_STOP=1'],'create role postgres superuser login;')
        sql('''create role anon;create role authenticated;create role service_role bypassrls;
        grant usage,create on schema public to postgres;
        create role supabase_storage_admin;
        create schema machimoa_review authorization postgres;
        create schema storage;
        grant usage on schema storage to supabase_storage_admin;
        create table storage.buckets(id text primary key,name text not null,public boolean not null,file_size_limit bigint,allowed_mime_types text[]);
        create table storage.objects(id uuid primary key default gen_random_uuid(),bucket_id text references storage.buckets(id));
        alter table storage.objects enable row level security;
        alter table storage.buckets enable row level security;
        alter table storage.buckets owner to supabase_storage_admin;
        alter table storage.objects owner to supabase_storage_admin;
        grant all on storage.buckets,storage.objects to postgres;
        grant usage on schema storage to anon,authenticated,service_role;
        grant select,insert,update,delete on storage.objects to anon,authenticated,service_role;
        insert into storage.buckets values('existing-uploads','existing-uploads',false,1048576,array['image/png']);
        insert into storage.objects(bucket_id)values('existing-uploads');

        revoke all on schema machimoa_review from public,anon,authenticated,service_role;
        create table public.curations(id uuid primary key default gen_random_uuid(),slug text not null unique,
          category text not null,user_category text,title text not null,summary text not null,content text not null,
          title_ko text,title_ja text,summary_ko text,summary_ja text,content_ko text,content_ja text,
          source text,source_item_id text,source_url text,source_image_url text,
          application_deadline_kind text,application_deadline_on date,event_start_on date,event_end_on date,
          is_published boolean not null default false,created_at timestamptz not null default now(),updated_at timestamptz not null default now(),
          check((source is null)=(source_item_id is null)));
        create unique index source_pair on public.curations(source,source_item_id);
        alter table public.curations enable row level security;
        revoke all on public.curations from public,anon,authenticated,service_role;
        grant select on public.curations to anon,authenticated,service_role;
        create policy published_only on public.curations for select to anon,authenticated using(is_published);
        insert into public.curations(slug,category,title,summary,content,is_published)values('existing','생활','기존 값','기존 요약','기존 본문',true);
        ''')
        predecessor=(ROOT/'supabase/migrations/20261003000000_source_images.sql').read_text(encoding='utf-8')
        sql(predecessor[predecessor.index('create function'):predecessor.index('alter table public.curations')])
        sql('revoke all on function machimoa_review.safe_source_image_url(text) from public,anon,authenticated;grant execute on function machimoa_review.safe_source_image_url(text) to service_role;')
        contract=json.loads((ROOT/'scripts/fixtures/living-publish-db-contract.json').read_text(encoding='utf-8'))
        for constraint in contract['constraints']:
            sql('alter table public.curations add constraint '+constraint['name']+' '+constraint['definition'])
        # The migration role has Storage ACLs but is neither owner nor superuser,
        # matching the production metadata. No operating credentials are used.
        sql('grant anon,authenticated,service_role to postgres with inherit false;alter role postgres nosuperuser bypassrls;')
        equal(query("select rolsuper from pg_roles where rolname=current_user"),[{'rolsuper':False}])
        equal(query("select pg_has_role(current_user,'supabase_storage_admin','USAGE') ok"),[{'ok':False}])
        before=query('select to_jsonb(c) value from public.curations c')
        predecessors=query("select p.oid,pg_get_functiondef(p.oid) definition,p.proacl::text acl from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname in ('public','machimoa_review') order by p.oid")
        migration=(ROOT/'supabase/migrations/20261028042923_admin_living_articles.sql').read_text(encoding='utf-8')
        storage_before=query("select relname,pg_get_userbyid(relowner) owner,relacl::text acl,relrowsecurity rls from pg_class where oid in ('storage.buckets'::regclass,'storage.objects'::regclass) order by relname")
        def bootstrap(value):
            return command(['exec','-i',container,'psql','-XqAt','-d','postgres','-U','local_bootstrap','-v','ON_ERROR_STOP=1'],value)
        bootstrap('create policy unsafe_fixture on storage.objects for select to authenticated using(true);')
        equal(sql(migration,check=False).returncode!=0,True)
        equal(query("select to_regclass('machimoa_review.living_articles') is null ok"),[{'ok':True}])
        equal(query("select count(*)::int n from storage.buckets where id='living-card-images'"),[{'n':0}])
        bootstrap('drop policy unsafe_fixture on storage.objects;')
        sql(migration)
        equal(query("select relname,pg_get_userbyid(relowner) owner,relacl::text acl,relrowsecurity rls from pg_class where oid in ('storage.buckets'::regclass,'storage.objects'::regclass) order by relname"),storage_before)
        equal(query('select to_jsonb(c) value from public.curations c'),before)
        for old in predecessors:
            equal(query('select pg_get_functiondef('+str(old['oid'])+') definition,proacl::text acl from pg_proc where oid='+str(old['oid'])),[{'definition':old['definition'],'acl':old['acl']}])
        example=json.loads((ROOT/'scripts/fixtures/living-instagram-example.json').read_text(encoding='utf-8'))
        aid,request=str(uuid4()),str(uuid4())
        write=lambda version,action='save',doc=example,rid=None,actor=ACTOR:rpc('admin_living_write',[aid,version,rid or str(uuid4()),action,doc,actor])
        initial=write('0',rid=request)
        equal(initial['document'],example);equal(initial['status'],'draft');equal(len(initial['history']),1)
        equal(initial['history'][0]['actor'],ACTOR)
        equal(query('select count(*)::int n from public.curations','anon'),[{'n':1}])
        equal(write('0',rid=request),initial)
        fails('admin_living_write',[aid,'0',request,'save',{**example,'checkedOn':'2026-10-23'},ACTOR])
        fails('admin_living_write',[aid,'0',str(uuid4()),'save',example,ACTOR])
        fails('admin_living_write',[aid,initial['version'],str(uuid4()),'save',example,None])
        equal(rpc('admin_living_read',[aid,0]),initial)
        listing=rpc('admin_living_read',[None,0]);equal(set(listing[0]),{'id','status','title'})
        for field,value in [('referenceUrl','javascript:alert(1)'),('imageUrl','http://127.0.0.1/a'),('imageUrl','https://images.example.org/a.svg'),('checkedOn','2026-02-30')]:
            fails('admin_living_write',[aid,initial['version'],str(uuid4()),'save',{**example,field:value},ACTOR])
        partial={**example,'content':{**example['content'],'contentJa':''}}
        incomplete=write(initial['version'],doc=partial)
        fails('admin_living_write',[aid,incomplete['version'],str(uuid4()),'publish',None,ACTOR])
        equal(query('select count(*)::int n from public.curations'),[{'n':1}])
        complete=write(incomplete['version'])
        # Same version in two concurrent real connections: one write wins.
        def concurrent(day):
            document={**example,'checkedOn':day}
            return sql('select public.admin_living_write('+','.join(map(literal,[aid,complete['version'],str(uuid4()),'save',document,ACTOR]))+')','service_role',False).returncode==0
        with ThreadPoolExecutor(max_workers=2)as pool:equal(sum(pool.map(concurrent,['2026-10-23','2026-10-24'])),1)
        current=rpc('admin_living_read',[aid,0]);pub_request=str(uuid4())
        published=write(current['version'],'publish',None,pub_request)
        equal(published['status'],'published');equal(published['publishedSlug'],'living-'+aid)
        public=query("select * from public.curations where slug='living-"+aid+"'",'anon')[0]
        equal(public['user_category'],'living');equal(public['title_ja'],example['content']['titleJa'])
        equal(public['content_ko'],example['content']['contentKo']+'\n\n정보 확인일: '+current['document']['checkedOn'])
        equal(write(current['version'],'publish',None,pub_request),published)
        equal(query('select count(*)::int n from public.curations'),[{'n':2}])
        fails('admin_living_write',[aid,published['version'],str(uuid4()),'publish',None,ACTOR])
        fails('admin_living_write',[aid,published['version'],str(uuid4()),'save',example,ACTOR])
        equal(query("select to_jsonb(c) value from public.curations c where slug='existing'"),before)
        # An unrelated public edit invalidates the old receipt/fence as well.
        sql("update public.curations set content_ko='별도 합성 변경' where slug='living-"+aid+"'")
        fails('admin_living_write',[aid,current['version'],pub_request,'publish',None,ACTOR])
        for role in ['anon','authenticated','service_role']:
            for table in ['living_articles','living_history','living_receipts']:
                for permission in ['select','insert','update','delete']:
                    equal(query("select has_table_privilege('"+role+"','machimoa_review."+table+"','"+permission+"') ok")[0]['ok'],False)
            for function in ['public.admin_living_read(uuid,integer)','public.admin_living_write(uuid,text,uuid,text,jsonb,uuid)']:
                equal(query("select has_function_privilege('"+role+"','"+function+"','execute') ok")[0]['ok'],role=='service_role')
        for role in ['anon','authenticated']:
            result=sql('select public.admin_living_read(null,0)',role,False);equal(result.returncode!=0,True)
        equal(query("select count(*)::int n from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_review' and c.relname in ('living_articles','living_history','living_receipts') and c.relrowsecurity"),[{'n':3}])
        equal(query("select count(*)::int n from machimoa_review.living_receipts"),[{'n':5}])
        equal(query("select count(*)::int n from machimoa_review.living_history"),[{'n':5}])
        # Image upload reservations never change a document, version or publication.
        gallery_article,img1,img2,foreign=[str(uuid4()) for _ in range(4)]
        meta={'width':800,'height':1000,'size':1024}
        reserve=lambda image,owner=gallery_article,version='0',actor=ACTOR:rpc('admin_living_image',[image,owner,version,'begin','a'*64,meta,actor])
        first=reserve(img1);equal(first['status'],'pending');equal(first['fresh'],True)
        equal(reserve(img1)['fresh'],False)
        equal(rpc('public_living_gallery',[gallery_article]),[])
        fails('public_living_image',[img1])
        image_doc={**example,'images':[{'id':img1,'altKo':'첫 장','altJa':'1枚目'}]}
        fails('admin_living_write',[gallery_article,'0',str(uuid4()),'save',image_doc,ACTOR])
        rpc('admin_living_image',[img1,None,None,'finish',None,None,ACTOR])
        reserve(img2);rpc('admin_living_image',[img2,None,None,'finish',None,None,ACTOR])
        reserve(foreign,owner=str(uuid4()));rpc('admin_living_image',[foreign,None,None,'finish',None,None,ACTOR])
        for invalid in [None,[{'id':img1,'altKo':'','altJa':''}]*2,[{'id':foreign,'altKo':'','altJa':''}],[{'id':str(uuid4()),'altKo':'','altJa':''}]]:
            fails('admin_living_write',[gallery_article,'0',str(uuid4()),'save',{**example,'images':invalid},ACTOR])
        images=[{'id':img2,'altKo':'둘째 장','altJa':'2枚目'},{'id':img1,'altKo':'첫 장','altJa':'1枚目'}]
        image_doc={**example,'content':{**example['content'],'contentKo':' \n\t','contentJa':'\n'},'images':images}
        image_doc_version='0'
        for key,blank in [('titleKo',' \n\t'),('titleJa','\u00a0')]:
            invalid={**image_doc,'content':{**image_doc['content'],key:blank}}
            draft=rpc('admin_living_write',[gallery_article,image_doc_version,str(uuid4()),'save',invalid,ACTOR])
            fails('admin_living_write',[gallery_article,draft['version'],str(uuid4()),'publish',None,ACTOR])
            image_doc_version=draft['version']
        saved=rpc('admin_living_write',[gallery_article,image_doc_version,str(uuid4()),'save',image_doc,ACTOR])
        equal(saved['document']['images'],images)
        equal(rpc('admin_living_read',[gallery_article,0])['version'],saved['version'])
        fails('admin_living_image',[str(uuid4()),gallery_article,'0','begin','b'*64,meta,ACTOR])
        fails('public_living_image',[img1])
        image_pub=rpc('admin_living_write',[gallery_article,saved['version'],str(uuid4()),'publish',None,ACTOR])
        equal(rpc('public_living_gallery',[gallery_article]),images)
        equal(rpc('public_living_image',[img2])['status'],'ready')
        public_image=query("select source_image_url,content_ja from public.curations where slug='living-"+gallery_article+"'",'anon')[0]
        equal(public_image['source_image_url'],'/api/living/images/'+img2)
        equal(public_image['content_ja'],example['content']['summaryJa']+'\n\n情報確認日: '+example['checkedOn'])
        fails('admin_living_image',[str(uuid4()),gallery_article,image_pub['version'],'begin','b'*64,meta,ACTOR])
        equal(query("select public,file_size_limit,allowed_mime_types from storage.buckets where id='living-card-images'"),[{'public':False,'file_size_limit':4194304,'allowed_mime_types':['image/webp']}])
        sql("update public.curations set is_published=false where slug='living-"+gallery_article+"'")
        fails('public_living_image',[img1]);equal(rpc('public_living_gallery',[gallery_article]),[])
        for role in ['anon','authenticated','service_role']:
            for permission in ['select','insert','update','delete']:
                equal(query("select has_table_privilege('"+role+"','machimoa_review.living_image_assets','"+permission+"') ok")[0]['ok'],False)
            for function in ['public.admin_living_image_read(uuid)','public.admin_living_image(uuid,uuid,text,text,text,jsonb,uuid)','public.public_living_gallery(uuid)','public.public_living_image(uuid)']:
                equal(query("select has_function_privilege('"+role+"','"+function+"','execute') ok")[0]['ok'],role=='service_role')
        sql("insert into storage.objects(bucket_id)values('living-card-images')")
        sql("insert into storage.objects(bucket_id)values(null)")
        for role in ['anon','authenticated']:
            equal(query("select count(*)::int n from storage.objects where bucket_id='living-card-images'",role),[{'n':0}])
            equal(query("select count(*)::int n from storage.objects where bucket_id='existing-uploads'",role),[{'n':0}])
            equal(query("select count(*)::int n from storage.objects where bucket_id is null",role),[{'n':0}])
            equal(sql("insert into storage.objects(bucket_id)values('living-card-images')",role,False).returncode!=0,True)
        equal(query("select count(*)::int n from storage.objects where bucket_id='living-card-images'",'service_role'),[{'n':1}])
        equal(query("select count(*)::int n from pg_policy where polrelid in ('storage.buckets'::regclass,'storage.objects'::regclass)"),[{'n':0}])
        # Internal covers are scoped to the first ready asset of that exact article.
        equal(query("select machimoa_review.safe_source_image_url('/api/living/images/"+img2+"') is null ok"),[{'ok':True}])
        for source,source_id,url in [('other_source',gallery_article,'/api/living/images/'+img2),('machimoa_living',str(uuid4()),'/api/living/images/'+img2),('machimoa_living',gallery_article,'/api/living/images/'+img1),('machimoa_living',gallery_article,'/api/living/images/'+foreign)]:
            result=sql("insert into public.curations(slug,category,title,summary,content,source,source_item_id,source_image_url)values("+','.join(map(literal,[str(uuid4()),'생활','제목','요약','본문',source,source_id,url]))+")",check=False)
            equal(result.returncode!=0,True)
        # Draft/history remain byte-exact; only the new public projection is trimmed.
        whitespace_id=str(uuid4());padded={**example,'content':{k:'  '+v+'  ' for k,v in example['content'].items()}}
        padded_draft=rpc('admin_living_write',[whitespace_id,'0',str(uuid4()),'save',padded,ACTOR])
        padded_pub=rpc('admin_living_write',[whitespace_id,padded_draft['version'],str(uuid4()),'publish',None,ACTOR])
        equal(padded_pub['document'],padded)
        projected=query("select title_ko,content_ko from public.curations where slug='living-"+whitespace_id+"'")[0]
        equal(projected['title_ko'],example['content']['titleKo'])
        equal(projected['content_ko'],example['content']['contentKo']+'\n\n정보 확인일: '+example['checkedOn'])
        overflow_id=str(uuid4());overflow={**example,'content':{**example['content'],'contentKo':'x'*200000}}
        overflow_draft=rpc('admin_living_write',[overflow_id,'0',str(uuid4()),'save',overflow,ACTOR])
        fails('admin_living_write',[overflow_id,overflow_draft['version'],str(uuid4()),'publish',None,ACTOR])
        equal(rpc('admin_living_read',[overflow_id,0]),overflow_draft)
        equal(query("select to_jsonb(c) value from public.curations c where slug='existing'"),before)
        print(json.dumps({'passed':checks,'engine':'network-none PostgreSQL','operational_db':0,'ai':0,'real_publications':0}))
    finally:
        # Only this run's exact random test container is removed; never a workspace or shared DB.
        command(['rm','-f',container],check=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',default='postgres:17.6-bookworm');args=parser.parse_args();run(args.image)
