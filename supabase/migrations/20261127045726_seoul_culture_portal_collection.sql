-- Local collector contract. Deliberately disabled/testing_only; no publication or AI grant.
begin;
insert into machimoa_review.ingest_sources
 (source_id,provider,source_kind,connector_type,enabled,permission_status,legacy_curation_source)
 values('seoul_culture_portal','seoul_culture_portal','content','public_homepage_partial',false,'testing_only','seoul_culture_portal');
insert into machimoa_review.source_sync_state(source_id) values('seoul_culture_portal');

create table machimoa_review.culture_portal_observations(
 id bigint generated always as identity primary key,
 run_id uuid not null references machimoa_review.ingest_runs(id),
 external_key text not null check(external_key ~ '^[1-9][0-9]{0,11}$'),
 revision text not null check(revision ~ '^[0-9a-f]{64}$'),
 event jsonb not null check(jsonb_typeof(event)='object' and octet_length(event::text)<=200000),
 review jsonb not null check(jsonb_typeof(review)='object' and octet_length(review::text)<=200000),
 outcome text not null check(outcome in ('new_review','duplicate_skipped','change_review','scope_excluded')),
 matches jsonb not null default '[]',
 observed_at timestamptz not null default clock_timestamp(),
 unique(external_key,revision)
);
create table machimoa_review.culture_portal_fetch_failures(
 run_id uuid not null references machimoa_review.ingest_runs(id),
 url text not null,
 code text not null check(code in ('detail_unavailable','detail_structure_changed')),
 created_at timestamptz not null default clock_timestamp(),
 primary key(run_id,url)
);
alter table machimoa_review.culture_portal_observations enable row level security;
alter table machimoa_review.culture_portal_fetch_failures enable row level security;
revoke all on machimoa_review.culture_portal_observations,machimoa_review.culture_portal_fetch_failures from public,anon,authenticated,service_role;
revoke all on sequence machimoa_review.culture_portal_observations_id_seq from public,anon,authenticated,service_role;

create function machimoa_review.culture_portal_run_lock(p_run uuid) returns void
language plpgsql security definer set search_path='' as $$
begin
 perform 1 from machimoa_review.source_sync_state s join machimoa_review.ingest_runs r on r.id=s.active_run_id
 join machimoa_review.ingest_sources src on src.source_id=s.source_id
 where s.source_id='seoul_culture_portal' and s.active_run_id=p_run and s.lease_owner=p_run
 and s.lease_expires_at>clock_timestamp() and r.status='running' and r.source_id=s.source_id
 and src.enabled and src.permission_status in ('testing_only','approved_noncommercial','approved_commercial')
 for update of s for share of src;
 if not found then raise sqlstate 'PT409' using message='portal_run_unavailable';end if;
end $$;

-- Compare identities only on known official event-detail routes, never arbitrary URLs.
create function machimoa_review.culture_portal_identity(v text) returns text
language sql immutable set search_path='' as $$
 select case
 when v ~ '^https://culture[.]seoul[.]go[.]kr/culture/culture/cultureEvent/view[.]do[?](cultcode=[1-9][0-9]{0,11}(&menuNo=200010)?|menuNo=200010&cultcode=[1-9][0-9]{0,11})$' then
 'portal:'||substring(v from '[?&]cultcode=([1-9][0-9]{0,11})(?:&|$)')
 when v ~ '^https://yeyak[.]seoul[.]go[.]kr/web/reservation/selectReservView[.]do[?]' then
 'reservation:'||substring(v from '[?&]rsv_svc_id=(S[0-9]{10,30})(?:&|$)') end
$$;

create function public.culture_portal_collection_contract() returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('contract','seoul-culture-portal-v1','mode','review_only')
$$;

create function public.record_culture_portal_fetch_failure(p_run_id uuid,p_url text,p_code text) returns text
language plpgsql security definer set search_path='' as $$
begin
 perform machimoa_review.culture_portal_run_lock(p_run_id);
 if p_url is null or p_url !~ '^https://culture[.]seoul[.]go[.]kr/culture/culture/cultureEvent/view[.]do[?]cultcode=[1-9][0-9]{0,11}&menuNo=200010$'
 or p_code is null or p_code not in ('detail_unavailable','detail_structure_changed') then
 raise sqlstate 'PT422' using message='portal_failure_invalid';end if;
 insert into machimoa_review.culture_portal_fetch_failures(run_id,url,code) values(p_run_id,p_url,p_code);
 return 'recorded';
end $$;

create function public.observe_culture_portal_event(p_run_id uuid,p_event jsonb,p_review jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare k text;rev text;sid uuid;old machimoa_review.culture_portal_observations%rowtype;
 s machimoa_review.source_items%rowtype; matches jsonb:='[]'; reasons text[];outcome text;
 payload jsonb;item jsonb;vtitle text;venue text;start_day text;end_day text;exact_ids uuid[];suspect_ids uuid[];review_queued boolean:=false;
begin
 perform machimoa_review.culture_portal_run_lock(p_run_id);
 if p_event is null or p_review is null or jsonb_typeof(p_event)<>'object' or jsonb_typeof(p_review)<>'object'
 or p_event->>'contract' is distinct from 'seoul-culture-portal-v1'
 or not p_event ?& array['external_key','revision_hash','title','source_url','description','source_category','evidence','reservation_links','tables']
 or p_event->>'external_key' !~ '^[1-9][0-9]{0,11}$' or p_event->>'revision_hash' !~ '^[0-9a-f]{64}$'
 or char_length(p_event->>'title') not between 1 and 500
 or p_event->>'source_url' is distinct from 'https://culture.seoul.go.kr/culture/culture/cultureEvent/view.do?cultcode='||(p_event->>'external_key')||'&menuNo=200010'
 or jsonb_typeof(p_event->'evidence') is distinct from 'array' or jsonb_typeof(p_event->'reservation_links') is distinct from 'array'
 or jsonb_typeof(p_review->'reasons') is distinct from 'array' or jsonb_typeof(p_review->'issues') is distinct from 'array'
 or p_review->>'ai_status' is distinct from 'blocked'
 or p_review->>'scope' is null or p_review->>'scope' not in ('culture_experience','unconfirmed','out_of_scope')
 or octet_length(p_event::text)>200000 or octet_length(p_review::text)>200000
 then raise sqlstate 'PT422' using message='portal_observation_invalid';end if;
 if exists(select 1 from unnest(array['external_key','revision_hash','title','source_url','description','source_category']) f
   where jsonb_typeof(p_event->f) is distinct from 'string')
 or jsonb_typeof(p_event->'tables') is distinct from 'array'
 or jsonb_array_length(p_review->'issues')>100 or jsonb_array_length(p_review->'reasons')>100
 or exists(select 1 from jsonb_array_elements(p_review->'issues') i where
   jsonb_typeof(i) is distinct from 'object' or jsonb_typeof(i->'code') is distinct from 'string'
   or i->>'code' !~ '^portal_[a-z_]{1,60}$' or jsonb_typeof(i->'field') is distinct from 'string'
   or jsonb_typeof(i->'evidence') is distinct from 'array')
 then raise sqlstate 'PT422' using message='portal_observation_invalid';end if;
 if exists(select 1 from jsonb_array_elements(p_review->'issues') i,
   lateral jsonb_array_elements(i->'evidence') e where jsonb_typeof(e) is distinct from 'string')
 then raise sqlstate 'PT422' using message='portal_evidence_invalid';end if;
 if exists(select 1 from jsonb_array_elements(p_event->'evidence') e where jsonb_typeof(e)<>'object'
 or e->>'origin' is null or e->>'origin' not in ('structured','body','image_alt_unverified')
 or jsonb_typeof(e->'value') is distinct from 'string' or jsonb_typeof(e->'field') is distinct from 'string')
 or exists(select 1 from jsonb_array_elements(p_review->'reasons') r where jsonb_typeof(r) is distinct from 'string' or r#>>'{}' !~ '^portal_[a-z_]{1,60}$')
 then raise sqlstate 'PT422' using message='portal_evidence_invalid';end if;
 k:=p_event->>'external_key';rev:=p_event->>'revision_hash';
 -- Serializes this collector; observations and review insertion commit together.
 perform pg_advisory_xact_lock(hashtextextended('culture-portal:'||k,0));
 select * into old from machimoa_review.culture_portal_observations where external_key=k and revision=rev;
 if found then
  if old.event is distinct from p_event then raise sqlstate 'PT409' using message='portal_revision_collision';end if;
  return jsonb_build_object('outcome','unchanged','revision',rev,'matches',old.matches);
 end if;
 select * into s from machimoa_review.source_items where source_id='seoul_culture_portal' and external_key=k for update;
 if found then
  outcome:='change_review';sid:=s.id;
  -- Keep operator values/revision/candidates and old observations intact.
  -- Do not reopen completed/cancelled decisions or excluded/held items.
  insert into machimoa_review.processing_jobs(source_item_id,revision_hash,processing_stage,status,reason_codes,queued_at,available_at)
   select sid,s.revision_hash,'content_review','queued',array['portal_source_changed'],clock_timestamp(),clock_timestamp() where s.disposition<>'non_target'
   on conflict(source_item_id,revision_hash,processing_stage) do nothing;
 else
  vtitle:=regexp_replace(lower(p_event->>'title'),'[^[:alnum:]]','','g');
  select value->>'value' into venue from jsonb_array_elements(p_event->'evidence') where value->>'field'='venue' limit 1;
  select substring(value->>'value' from '[0-9]{4}-[0-9]{2}-[0-9]{2}'),
   substring(value->>'value' from '~[[:space:]]*([0-9]{4}-[0-9]{2}-[0-9]{2})') into start_day,end_day
   from jsonb_array_elements(p_event->'evidence') where value->>'field'='period' limit 1;
  select array_agg(si.id) into exact_ids from machimoa_review.source_items si
   where si.source_id<>'seoul_culture_portal' and machimoa_review.culture_portal_identity(p_event->>'source_url') in
    (machimoa_review.culture_portal_identity(si.min_fields->>'source_url'),
     machimoa_review.culture_portal_identity(si.normalized_payload->>'source_url'),
     machimoa_review.culture_portal_identity(si.normalized_payload->>'official_url'));
  select array_agg(si.id) into suspect_ids from machimoa_review.source_items si where si.source_id<>'seoul_culture_portal'
   and (not(si.id=any(coalesce(exact_ids,'{}')))) and (
    (regexp_replace(lower(si.min_fields->>'title'),'[^[:alnum:]]','','g')=vtitle and
      ((venue is not null and char_length(venue)>=3 and strpos(si.normalized_payload::text,venue)>0) or
       (start_day is not null and end_day is not null and strpos(si.normalized_payload::text,start_day)>0 and strpos(si.normalized_payload::text,end_day)>0)))
    or exists(select 1 from jsonb_array_elements(p_event->'reservation_links') l where
       si.source_id='seoul_reservation' and si.external_key=l->>'key'));
  select coalesce(jsonb_agg(jsonb_build_object('id',si.id,'title',coalesce(si.min_fields->>'title','제목 확인 필요'),
   'source',si.source_id,'kind',case when si.id=any(coalesce(exact_ids,'{}')) then 'same_official_identity' else 'possible_overlap' end)),'[]')
   into matches from machimoa_review.source_items si where si.id=any(coalesce(exact_ids,'{}')||coalesce(suspect_ids,'{}'));
  if cardinality(exact_ids)>0 and not (p_review->'reasons' ? 'portal_information_conflict') then outcome:='duplicate_skipped';
  elsif p_review->>'scope'='out_of_scope' then outcome:='scope_excluded';
  else
   outcome:='new_review';
   select array_agg(value) into reasons from jsonb_array_elements_text(p_review->'reasons');
   reasons:=coalesce(reasons,'{}')||array['portal_facts_review'];
   if cardinality(suspect_ids)>0 or cardinality(exact_ids)>0 then reasons:=reasons||array['portal_duplicate_suspected'];end if;
   payload:=p_event||jsonb_build_object('plain_text',(
    select string_agg((case e->>'origin' when 'structured' then '[기본 정보] ' when 'image_alt_unverified' then '[이미지 대체텍스트 · 이미지 대조 필요] ' else '[상세 본문] ' end)||(e->>'field')||E'\n'||(e->>'value'),E'\n\n')
    from jsonb_array_elements(p_event->'evidence') e));
   item:=jsonb_build_object('external_key',k,'revision_hash',rev,'disposition','observe_only',
    'min_fields',jsonb_build_object('title',p_event->>'title','source_url',p_event->>'source_url'),
    'normalized_payload',payload,'has_source_url',true,'body_usable',length(p_event->>'description')>=20,
    'attachment_present',false,'attachment_length',0,'is_data_url',false,
    'source_created_parse_status','missing','source_updated_parse_status','missing',
    'jobs',jsonb_build_array(jsonb_build_object('stage','content_review','reason_codes',to_jsonb(reasons))), 'relationships','[]'::jsonb);
   perform * from machimoa_review.upsert_source_observations('seoul_culture_portal',p_run_id,jsonb_build_array(item),null);
   select id into sid from machimoa_review.source_items where source_id='seoul_culture_portal' and external_key=k;
  end if;
 end if;
 insert into machimoa_review.culture_portal_observations(run_id,external_key,revision,event,review,outcome,matches)
 values(p_run_id,k,rev,p_event,p_review,outcome,matches);
 if sid is not null then
  select exists(select 1 from machimoa_review.processing_jobs j where j.source_item_id=sid
   and j.processing_stage='content_review' and j.status='queued') into review_queued;
 end if;
 return jsonb_build_object('outcome',outcome,'revision',rev,'sourceItemId',sid,'matches',matches,'reviewQueued',review_queued);
end $$;

-- Reuse the authenticated admin review read path; do not add a public data endpoint.
alter function machimoa_review.admin_review_item(text,uuid) rename to admin_review_item_before_culture_portal;
create function machimoa_review.admin_review_item(p_kind text,p_id uuid) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare result jsonb;obs machimoa_review.culture_portal_observations%rowtype;
begin
 result:=machimoa_review.admin_review_item_before_culture_portal(p_kind,p_id);
 if p_kind='facts' and result->'source'->>'name'='seoul_culture_portal' then
  select o.* into obs from machimoa_review.culture_portal_observations o
   join machimoa_review.source_items s on s.external_key=o.external_key and s.source_id='seoul_culture_portal'
   where s.id=p_id order by o.id desc limit 1;
  result:=result||jsonb_build_object('collectionReview',jsonb_build_object('outcome',obs.outcome,
   'issues',obs.review->'issues','matches',obs.matches,'observedRevision',obs.revision),
   'version',encode(sha256(convert_to((result->>'version')||':'||obs.id::text,'UTF8')),'hex'));
 end if;
 return result;
end $$;

revoke all on function machimoa_review.culture_portal_run_lock(uuid),machimoa_review.culture_portal_identity(text),
 machimoa_review.admin_review_item(text,uuid),machimoa_review.admin_review_item_before_culture_portal(text,uuid) from public,anon,authenticated,service_role;
revoke all on function public.culture_portal_collection_contract(),public.record_culture_portal_fetch_failure(uuid,text,text),
 public.observe_culture_portal_event(uuid,jsonb,jsonb) from public,anon,authenticated,service_role;
grant execute on function public.culture_portal_collection_contract(),public.record_culture_portal_fetch_failure(uuid,text,text),
 public.observe_culture_portal_event(uuid,jsonb,jsonb) to service_role;
commit;
