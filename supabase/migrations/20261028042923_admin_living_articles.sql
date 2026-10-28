-- Additive manual living drafts. No source/AI/candidate backfill or policy changes.
begin;
do $$ begin
 if current_user <> 'postgres' or to_regclass('public.curations') is null
    or to_regprocedure('machimoa_review.safe_source_image_url(text)') is null then
  raise exception 'living predecessor contract missing';
 end if;
 if not exists(select 1 from pg_proc where oid='machimoa_review.safe_source_image_url(text)'::regprocedure
   and pg_get_userbyid(proowner)='postgres' and proconfig=array['search_path=""']
   and md5(prosrc)='4d1fcb163dfe0aa059daa854d93647d8')
   or not exists(select 1 from pg_constraint where conrelid='public.curations'::regclass
     and conname='curations_source_image_url_ck' and md5(pg_get_constraintdef(oid))='9dabe9f0b490e9abbe7acbb55058286b') then
  raise exception 'living source image predecessor differs';
 end if;
 if to_regclass('storage.buckets') is null or to_regclass('storage.objects') is null then
  raise exception 'living Storage contract missing';
 end if;
 -- Preserve Storage ownership, ACL and default-deny RLS. Never install policies
 -- through a role which does not own Supabase Storage's tables.
 if (select count(*) from pg_class where oid in ('storage.buckets'::regclass,'storage.objects'::regclass) and relrowsecurity)<>2
   or exists(select 1 from pg_policy where polrelid in ('storage.buckets'::regclass,'storage.objects'::regclass))
   or exists(select 1 from storage.buckets where id='living-card-images') then
  raise exception 'living Storage default-deny predecessor differs';
 end if;
 if exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_review' and c.relname like 'living_%') then
  raise exception 'living objects already exist; compare migration history before applying';
 end if;
end $$;

create table machimoa_review.living_articles(
 id uuid primary key,
 document jsonb not null,
 status text not null default 'draft' check(status in ('draft','published')),
 published_id uuid unique references public.curations(id) on delete restrict,
 counter bigint not null default 1 check(counter>0),
 created_at timestamptz not null default clock_timestamp(),
 updated_at timestamptz not null default clock_timestamp(),
 check((status='draft' and published_id is null) or (status='published' and published_id is not null))
);
create table machimoa_review.living_history(
 id bigint generated always as identity primary key,
 article_id uuid not null references machimoa_review.living_articles(id) on delete restrict,
 action text not null check(action in ('save','publish')),
 actor uuid not null,occurred_at timestamptz not null default clock_timestamp(),
 previous_document jsonb,document jsonb not null,
 previous_version text not null,published_id uuid references public.curations(id) on delete restrict
);
create index living_history_article on machimoa_review.living_history(article_id,id desc);
create table machimoa_review.living_receipts(
 request_id uuid primary key,article_id uuid not null references machimoa_review.living_articles(id) on delete restrict,
 fingerprint text not null,result jsonb not null,created_at timestamptz not null default clock_timestamp()
);
-- Originals are never public. Sanitized raster files are served through a publication gate.
create table machimoa_review.living_image_assets(
 id uuid primary key,article_id uuid not null,actor uuid not null,
 status text not null default 'pending' check(status in ('pending','ready')),
 hash text not null check(hash~'^[a-f0-9]{64}$'),
 width integer not null check(width>0),height integer not null check(height>0),
 size integer not null check(size between 1 and 4194304),
 created_at timestamptz not null default clock_timestamp(),ready_at timestamptz,
 check(width::bigint*height<=16000000)
);
alter table machimoa_review.living_image_assets owner to postgres;
alter table machimoa_review.living_image_assets enable row level security;
revoke all on machimoa_review.living_image_assets from public,anon,authenticated,service_role;
create index living_image_assets_article on machimoa_review.living_image_assets(article_id);
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
 values('living-card-images','living-card-images',false,4194304,array['image/webp']);
-- No Storage policy or grant changes: browser roles remain default-denied.
alter table machimoa_review.living_articles owner to postgres;
alter table machimoa_review.living_history owner to postgres;
alter table machimoa_review.living_receipts owner to postgres;
alter table machimoa_review.living_articles enable row level security;
alter table machimoa_review.living_history enable row level security;
alter table machimoa_review.living_receipts enable row level security;
revoke all on machimoa_review.living_articles,machimoa_review.living_history,machimoa_review.living_receipts from public,anon,authenticated,service_role;
revoke all on sequence machimoa_review.living_history_id_seq from public,anon,authenticated,service_role;

-- Only a manual article's own first confirmed image may use this internal URL.
-- The existing HTTPS validator and all other sources keep their exact contract.
create function machimoa_review.living_cover_matches(p_article text,p_url text) returns boolean
language sql stable security definer set search_path='' as $$
 select coalesce(p_url ~ '^/api/living/images/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
  and exists(select 1 from machimoa_review.living_articles d
   join machimoa_review.living_image_assets a on a.id::text=d.document->'images'->0->>'id'
   where d.id::text=p_article and a.article_id=d.id and a.status='ready'
    and p_url='/api/living/images/'||a.id::text),false)
$$;
alter function machimoa_review.living_cover_matches(text,text) owner to postgres;
revoke all on function machimoa_review.living_cover_matches(text,text) from public,anon,authenticated,service_role;
alter table public.curations drop constraint curations_source_image_url_ck;
alter table public.curations add constraint curations_source_image_url_ck check(
 source_image_url is null or (
  machimoa_review.safe_source_image_url(source_image_url) is not null
  and source_image_url=machimoa_review.safe_source_image_url(source_image_url)
 ) or (source='machimoa_living' and machimoa_review.living_cover_matches(source_item_id,source_image_url))
);

create function machimoa_review.living_validate(p_document jsonb,p_publish boolean default false) returns void
language plpgsql set search_path='' as $$
declare k text;maximum integer;v text;
begin
 if jsonb_typeof(p_document) is distinct from 'object' or
 (select array_agg(key order by key collate "C") from jsonb_object_keys(p_document) key) not in (array['checkedOn','content','imageUrl','referenceUrl'],array['checkedOn','content','imageUrl','images','referenceUrl'])
 or jsonb_typeof(p_document->'content') is distinct from 'object' then
  raise sqlstate 'PT422' using message='living_invalid_input';
 end if;
 if p_document?'images' then
  if jsonb_typeof(p_document->'images') is distinct from 'array' then raise sqlstate 'PT422' using message='living_invalid_input';end if;
  if jsonb_array_length(p_document->'images')>20 then raise sqlstate 'PT422' using message='living_invalid_input';end if;
  if exists(select 1 from jsonb_array_elements(p_document->'images') i where jsonb_typeof(i) is distinct from 'object'
    or (select array_agg(key order by key collate "C") from jsonb_object_keys(i) key) is distinct from array['altJa','altKo','id']
    or jsonb_typeof(i->'id') is distinct from 'string' or (i->>'id')!~'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    or jsonb_typeof(i->'altKo') is distinct from 'string' or jsonb_typeof(i->'altJa') is distinct from 'string'
    or char_length(i->>'altKo')>500 or char_length(i->>'altJa')>500)
    or (select count(*)<>count(distinct i->>'id') from jsonb_array_elements(p_document->'images') i) then
    raise sqlstate 'PT422' using message='living_invalid_input';
  end if;
 end if;
 if (select array_agg(key order by key collate "C") from jsonb_object_keys(p_document->'content') key) is distinct from array['contentJa','contentKo','summaryJa','summaryKo','titleJa','titleKo'] then
  raise sqlstate 'PT422' using message='living_invalid_input';
 end if;
 foreach k in array array['titleKo','titleJa','summaryKo','summaryJa','contentKo','contentJa'] loop
  maximum:=case when k like 'title%' then 300 when k like 'summary%' then 1000 else 200000 end;
  if jsonb_typeof(p_document->'content'->k) is distinct from 'string' or char_length(p_document->'content'->>k)>maximum
     or p_publish and replace(p_document->'content'->>k,chr(160),' ')!~'[^[:space:]]' and (k not in ('contentKo','contentJa') or coalesce(jsonb_array_length(p_document->'images'),0)=0) then
   raise sqlstate 'PT422' using message='living_invalid_input';
  end if;
 end loop;
 foreach k in array array['imageUrl','referenceUrl','checkedOn'] loop
  if jsonb_typeof(p_document->k) is distinct from 'string' then raise sqlstate 'PT422' using message='living_invalid_input';end if;
  v:=p_document->>k;
  if k in ('imageUrl','referenceUrl') and v<>'' and machimoa_review.safe_source_image_url(v) is distinct from v then
   raise sqlstate 'PT422' using message='living_invalid_input';
  end if;
 end loop;
 v:=p_document->>'checkedOn';
 if v<>'' then
  if v !~ '^\d{4}-\d{2}-\d{2}$' then raise sqlstate 'PT422' using message='living_invalid_input';end if;
  begin
   if to_char(v::date,'YYYY-MM-DD')<>v then raise exception 'bad date';end if;
  exception when others then raise sqlstate 'PT422' using message='living_invalid_input';end;
 end if;
end $$;

create function machimoa_review.living_detail(p_id uuid) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',d.id,'document',d.document,'status',d.status,
  'version',encode(sha256(convert_to(jsonb_build_object('article',to_jsonb(d),'public',to_jsonb(c))::text,'UTF8')),'hex'),
  'publishedSlug',case when d.published_id is not null then 'living-'||d.id::text end,
  'history',coalesce((select jsonb_agg(jsonb_build_object('action',h.action,'actor',h.actor,'at',h.occurred_at) order by h.id)
   from machimoa_review.living_history h where h.article_id=d.id),'[]'::jsonb))
 from machimoa_review.living_articles d left join public.curations c on c.id=d.published_id where d.id=p_id
$$;

create function public.admin_living_read(p_id uuid default null,p_offset integer default 0) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare v jsonb;
begin
 if p_offset is null or p_offset<0 or p_offset>999999 then raise sqlstate 'PT422' using message='living_invalid_input';end if;
 if p_id is not null then
  v:=machimoa_review.living_detail(p_id);if v is null then raise sqlstate 'PT404' using message='living_not_found';end if;return v;
 end if;
 return coalesce((select jsonb_agg(x.value order by x.updated_at desc,x.id) from (
  select d.id,d.updated_at,jsonb_build_object('id',d.id,'status',d.status,'title',coalesce(nullif(d.document->'content'->>'titleKo',''),nullif(d.document->'content'->>'titleJa',''),'제목 없는 초안')) value
  from machimoa_review.living_articles d order by d.updated_at desc,d.id offset p_offset limit 25)x),'[]'::jsonb);
end $$;

create function public.admin_living_write(p_id uuid,p_version text,p_request_id uuid,p_action text,p_document jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare d machimoa_review.living_articles%rowtype;r machimoa_review.living_receipts%rowtype;
 v jsonb;fingerprint text;previous_document jsonb;pub uuid;ko text;ja text;slug text;
begin
 if p_id is null or p_request_id is null or p_actor is null or p_version is null or p_action is null
    or p_id::text!~'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    or p_request_id::text!~'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    or p_action not in ('save','publish') or p_version!~'^(0|[0-9a-f]{64})$'
    or p_action='publish' and (p_document is not null or p_version='0') then
  raise sqlstate 'PT422' using message='living_invalid_input';
 end if;
 if p_action='save' then perform machimoa_review.living_validate(p_document,false);end if;
 -- Request -> article -> public row. No worker, source, claim or AI job is touched.
 perform pg_advisory_xact_lock(hashtextextended('living-request:'||p_request_id::text,0));
 perform pg_advisory_xact_lock(hashtextextended('living-article:'||p_id::text,0));
 select * into d from machimoa_review.living_articles where id=p_id for update;
 if d.published_id is not null then perform 1 from public.curations where id=d.published_id for update;end if;
 v:=machimoa_review.living_detail(p_id);
 fingerprint:=encode(sha256(convert_to(jsonb_build_object('id',p_id,'version',p_version,'action',p_action,'document',p_document,'actor',p_actor)::text,'UTF8')),'hex');
 select * into r from machimoa_review.living_receipts where request_id=p_request_id;
 if found then
  if r.article_id<>p_id or r.fingerprint<>fingerprint or v->>'version' is distinct from r.result->>'version' then
   raise sqlstate 'PT409' using message='living_conflict';
  end if;return r.result;
 end if;
 if coalesce(v->>'version','0')<>p_version then raise sqlstate 'PT409' using message='living_conflict';end if;
 if d.status='published' then raise sqlstate 'PT409' using message='living_already_published';end if;
 previous_document:=d.document;
 if exists(select 1 from jsonb_array_elements(coalesce((case when p_action='save' then p_document else d.document end)->'images','[]'::jsonb)) i
   where not exists(select 1 from machimoa_review.living_image_assets a where a.id=(i->>'id')::uuid and a.article_id=p_id and a.status='ready')) then
  raise sqlstate 'PT422' using message='living_invalid_input';
 end if;
 if p_action='save' then
  if d.id is null then insert into machimoa_review.living_articles(id,document) values(p_id,p_document);
  else update machimoa_review.living_articles set document=p_document,counter=counter+1,updated_at=clock_timestamp() where id=p_id;end if;
 else
  if d.id is null then raise sqlstate 'PT404' using message='living_not_found';end if;
  perform machimoa_review.living_validate(d.document,true);
  ko:=d.document->'content'->>'contentKo';ja:=d.document->'content'->>'contentJa';
  if coalesce(jsonb_array_length(d.document->'images'),0)>0 then
   if replace(ko,chr(160),' ')!~'[^[:space:]]' then ko:=d.document->'content'->>'summaryKo';end if;
   if replace(ja,chr(160),' ')!~'[^[:space:]]' then ja:=d.document->'content'->>'summaryJa';end if;
  end if;
  ko:=btrim(ko);ja:=btrim(ja);
  if d.document->>'checkedOn'<>'' then
   ko:=ko||E'\n\n정보 확인일: '||(d.document->>'checkedOn');ja:=ja||E'\n\n情報確認日: '||(d.document->>'checkedOn');
  end if;
  if char_length(ko)>200000 or char_length(ja)>200000 then
   raise sqlstate 'PT422' using message='living_invalid_input';
  end if;
  slug:='living-'||p_id::text;
  -- INSERT only. Existing publications can never be overwritten by this path.
  insert into public.curations(slug,category,user_category,title,summary,content,title_ko,title_ja,summary_ko,summary_ja,content_ko,content_ja,
   source,source_item_id,source_url,source_image_url,is_published,updated_at)
  values(slug,'생활','living',btrim(d.document->'content'->>'titleKo'),btrim(d.document->'content'->>'summaryKo'),ko,
    btrim(d.document->'content'->>'titleKo'),btrim(d.document->'content'->>'titleJa'),btrim(d.document->'content'->>'summaryKo'),btrim(d.document->'content'->>'summaryJa'),ko,ja,
   'machimoa_living',p_id::text,nullif(d.document->>'referenceUrl',''),coalesce(nullif(d.document->>'imageUrl',''),case when coalesce(jsonb_array_length(d.document->'images'),0)>0 then '/api/living/images/'||(d.document->'images'->0->>'id') end),true,clock_timestamp()) returning id into pub;
  update machimoa_review.living_articles set status='published',published_id=pub,counter=counter+1,updated_at=clock_timestamp() where id=p_id;
 end if;
 select * into d from machimoa_review.living_articles where id=p_id;
 insert into machimoa_review.living_history(article_id,action,actor,previous_document,document,previous_version,published_id)
 values(p_id,p_action,p_actor,previous_document,d.document,p_version,d.published_id);
 v:=machimoa_review.living_detail(p_id);
 insert into machimoa_review.living_receipts(request_id,article_id,fingerprint,result) values(p_request_id,p_id,fingerprint,v);
 return v;
end $$;

create function machimoa_review.living_image_meta(p_id uuid) returns jsonb language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',a.id,'articleId',a.article_id,'path',a.article_id::text||'/'||a.id::text||'.webp',
 'status',a.status,'hash',a.hash,'width',a.width,'height',a.height,'size',a.size)
 from machimoa_review.living_image_assets a where a.id=p_id
$$;
create function public.admin_living_image_read(p_id uuid) returns jsonb language plpgsql stable security definer set search_path='' as $$
declare v jsonb;begin v:=machimoa_review.living_image_meta(p_id);if v is null then raise sqlstate 'PT404' using message='living_not_found';end if;return v;end $$;
create function public.public_living_gallery(p_article uuid) returns jsonb language sql stable security definer set search_path='' as $$
 select coalesce((select d.document->'images' from machimoa_review.living_articles d join public.curations c on c.id=d.published_id
 where d.id=p_article and d.status='published' and c.is_published and c.source='machimoa_living' and c.source_item_id=d.id::text),'[]'::jsonb)
$$;
create function public.public_living_image(p_id uuid) returns jsonb language plpgsql stable security definer set search_path='' as $$
declare v jsonb;begin
 select machimoa_review.living_image_meta(a.id) into v from machimoa_review.living_image_assets a
 where a.id=p_id and a.status='ready' and exists(select 1 from jsonb_array_elements(public.public_living_gallery(a.article_id)) i where i->>'id'=a.id::text);
 if v is null then raise sqlstate 'PT404' using message='living_not_found';end if;return v;end $$;
create function public.admin_living_image(p_id uuid,p_article uuid,p_version text,p_action text,p_hash text,p_meta jsonb,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare a machimoa_review.living_image_assets%rowtype;d jsonb;fresh boolean:=false;target uuid;
begin
 if p_id is null or p_actor is null or p_action is null or p_action not in ('begin','finish')
 or p_id::text!~'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then raise sqlstate 'PT422' using message='living_invalid_input';end if;
 if p_action='begin' then target:=p_article;else select article_id into target from machimoa_review.living_image_assets where id=p_id;end if;
 if target is null then raise sqlstate 'PT404' using message='living_not_found';end if;
 perform pg_advisory_xact_lock(hashtextextended('living-article:'||target::text,0));
 perform pg_advisory_xact_lock(hashtextextended('living-image:'||p_id::text,0));
 d:=machimoa_review.living_detail(target);
 if d->>'status'='published' then raise sqlstate 'PT409' using message='living_conflict';end if;
 select * into a from machimoa_review.living_image_assets where id=p_id for update;
 if p_action='begin' then
  if p_version is null or coalesce(d->>'version','0')<>p_version then raise sqlstate 'PT409' using message='living_conflict';end if;
  if p_hash is null or p_hash!~'^[a-f0-9]{64}$' or jsonb_typeof(p_meta) is distinct from 'object'
    or (select array_agg(key order by key collate "C") from jsonb_object_keys(p_meta) key) is distinct from array['height','size','width'] then raise sqlstate 'PT422' using message='living_invalid_input';end if;
  if a.id is null then
   insert into machimoa_review.living_image_assets(id,article_id,actor,hash,width,height,size)
   values(p_id,target,p_actor,p_hash,(p_meta->>'width')::integer,(p_meta->>'height')::integer,(p_meta->>'size')::integer);fresh:=true;
  elsif a.article_id<>target or a.actor<>p_actor or a.hash<>p_hash or jsonb_build_object('width',a.width,'height',a.height,'size',a.size)<>p_meta then
   raise sqlstate 'PT409' using message='living_conflict';
  end if;
 else
  if a.id is null then raise sqlstate 'PT404' using message='living_not_found';end if;
  if a.actor<>p_actor then raise sqlstate 'PT409' using message='living_conflict';end if;
  if a.status='pending' then update machimoa_review.living_image_assets set status='ready',ready_at=clock_timestamp() where id=p_id;end if;
 end if;
 return machimoa_review.living_image_meta(p_id)||jsonb_build_object('fresh',fresh);
end $$;

alter function machimoa_review.living_image_meta(uuid) owner to postgres;
alter function public.admin_living_image_read(uuid) owner to postgres;
alter function public.admin_living_image(uuid,uuid,text,text,text,jsonb,uuid) owner to postgres;
alter function public.public_living_gallery(uuid) owner to postgres;
alter function public.public_living_image(uuid) owner to postgres;
revoke all on function machimoa_review.living_image_meta(uuid),public.admin_living_image_read(uuid),public.admin_living_image(uuid,uuid,text,text,text,jsonb,uuid),public.public_living_gallery(uuid),public.public_living_image(uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_living_image_read(uuid),public.admin_living_image(uuid,uuid,text,text,text,jsonb,uuid),public.public_living_gallery(uuid),public.public_living_image(uuid) to service_role;

alter function machimoa_review.living_validate(jsonb,boolean) owner to postgres;
alter function machimoa_review.living_detail(uuid) owner to postgres;
alter function public.admin_living_read(uuid,integer) owner to postgres;
alter function public.admin_living_write(uuid,text,uuid,text,jsonb,uuid) owner to postgres;
revoke all on function machimoa_review.living_validate(jsonb,boolean),machimoa_review.living_detail(uuid),public.admin_living_read(uuid,integer),public.admin_living_write(uuid,text,uuid,text,jsonb,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_living_read(uuid,integer),public.admin_living_write(uuid,text,uuid,text,jsonb,uuid) to service_role;
notify pgrst,'reload schema';
commit;
