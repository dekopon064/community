begin;
create table machimoa_review.suitability_runs (
 id uuid primary key, created_at timestamptz not null default clock_timestamp(),
 policy text, policy_hash text check (policy_hash ~ '^[0-9a-f]{64}$'), read_at timestamptz,
 check ((policy is null)=(policy_hash is null) and (policy is null)=(read_at is null))
);
create table machimoa_review.suitability_items (
 run_id uuid references machimoa_review.suitability_runs, item_id uuid not null,
 source text not null, external_key text not null, revision text not null, version text not null,
 job_id uuid, title text not null, evidence text not null, moved_at timestamptz,
 primary key(run_id,item_id), unique(run_id,source,external_key)
);
create table machimoa_review.suitability_decisions (
 source text not null, external_key text not null, revision text not null, policy_hash text not null,
 owner_run uuid not null references machimoa_review.suitability_runs, decision jsonb,
 primary key(source,external_key,revision,policy_hash)
);
alter table machimoa_review.suitability_runs enable row level security;
alter table machimoa_review.suitability_items enable row level security;
alter table machimoa_review.suitability_decisions enable row level security;
revoke all on machimoa_review.suitability_runs,machimoa_review.suitability_items,machimoa_review.suitability_decisions from public,anon,authenticated,service_role;
-- A saved human relevance decision applies to its own revision. A facts/filter edit does not imply one.
create function machimoa_review.suitability_operator_decided(item uuid,rev text) returns boolean
language sql stable set search_path='' as $$
 select exists(select from machimoa_review.ingest_review_decisions d where d.source_item_id=item
   and d.revision_hash=rev and d.revoked_at is null and
   ((d.review_type='relevance' and d.decision in ('approve_ai','reject') and
     d.reviewer ~* '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$')
    or (d.decision='reject' and 'manual_non_target'=any(d.reason_codes))))
$$;
revoke all on function machimoa_review.suitability_operator_decided(uuid,text) from public,anon,authenticated;
-- The STABLE reader keeps both paginated queues and their detail/version on one statement snapshot.
create function machimoa_review.suitability_snapshot() returns setof machimoa_review.suitability_items
language plpgsql stable set search_path='' as $$
declare queue text; off integer; page jsonb; entry jsonb; d jsonb; native jsonb; item machimoa_review.suitability_items;
begin
 foreach queue in array array['facts','ai'] loop
  off:=0;
  loop
   page:=case when queue='facts' then public.admin_review_list('facts',off,25)
     else public.admin_review_ai_queue(off,25,'{}')->'items' end;
   if jsonb_typeof(page) is distinct from 'array' then raise exception 'invalid snapshot'; end if;
   for entry in select value from jsonb_array_elements(page) loop
    if entry->>'sourceName' not in ('seoul_reservation','myseoul_program') then continue; end if;
    item.job_id:=null;
    if queue='ai' then
     if entry->>'status'<>'queued' or entry->>'currentRevision'<>'true' then continue; end if;
     item.job_id:=(entry->>'jobId')::uuid;
     d:=public.admin_ai_queue_review_detail(item.job_id);
     if d->>'status'<>'queued' or d->>'canExclude' is distinct from 'true' then continue; end if;
     native:=d->'review';
    else
     d:=case when entry->>'sourceName'='seoul_reservation' then public.admin_program_detail((entry->>'id')::uuid)
       else public.admin_myseoul_program_detail((entry->>'id')::uuid) end;
     if d->>'status' is distinct from 'open' then continue; end if;
     native:=d;
    end if;
    if native->>'status'='excluded' then continue; end if;
    item.item_id:=(native->>'id')::uuid;
    item.source:=entry->>'sourceName'; item.title:=native#>>'{source,title}';
    item.revision:=native->>'revision'; item.version:=d->>'version';
    select s.external_key into strict item.external_key from machimoa_review.source_items s
     where s.id=item.item_id and s.source_id=item.source and s.revision_hash=item.revision;
    if exists(select from machimoa_review.processing_jobs j where j.source_item_id=item.item_id and j.status='claimed')
     or machimoa_review.suitability_operator_decided(item.item_id,item.revision)
     or exists(select from machimoa_review.admin_exclusion_episodes e where e.source_item_id=item.item_id and e.restored_at is null)
     or exists(select from machimoa_review.curation_candidates c where machimoa_review.canonical_source_id(c.source)=item.source
       and c.source_item_id=item.external_key and c.source_revision_hash=item.revision)
     then continue; end if;
    item.evidence:=coalesce(native#>>'{source,body}','');
    if coalesce(trim(native#>>'{observedFacts,description}'),'')<>'' and
       strpos(item.evidence,native#>>'{observedFacts,description}')=0 then
     item.evidence:=concat_ws(E'\n',nullif(item.evidence,''),native#>>'{observedFacts,description}');
    end if;
    return next item;
   end loop;
   exit when jsonb_array_length(page)<25;
   off:=off+25;
  end loop;
 end loop;
end $$;

create function public.suitability_freeze(p_run uuid)
returns void language plpgsql security definer set search_path='' as $$
begin
 insert into machimoa_review.suitability_runs(id) values(p_run)
 on conflict do nothing;
 if not found then raise exception 'existing run'; end if;
 insert into machimoa_review.suitability_items
 select distinct on (s.source,s.external_key) p_run,s.item_id,s.source,s.external_key,s.revision,s.version,s.job_id,s.title,s.evidence,null
 from machimoa_review.suitability_snapshot() s order by s.source,s.external_key,s.job_id nulls first;
end $$;

create function public.suitability_start(p_run uuid,p_policy text,p_hash text,p_read_at timestamptz)
returns boolean language plpgsql security definer set search_path='' as $$
begin
 update machimoa_review.suitability_runs set policy=p_policy,policy_hash=p_hash,read_at=p_read_at
 where id=p_run and policy_hash is null and p_hash is not null and length(trim(p_policy))>0;
 return found;
end $$;

create function public.suitability_claim(p_run uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare i machimoa_review.suitability_items; policy_key text;
begin
 select policy_hash into strict policy_key from machimoa_review.suitability_runs where id=p_run;
 for i in select s.* from machimoa_review.suitability_items s where s.run_id=p_run
  and not exists(select from machimoa_review.suitability_decisions d where
   (d.source,d.external_key,d.revision,d.policy_hash)=(s.source,s.external_key,s.revision,policy_key))
  order by s.source,s.external_key loop
  insert into machimoa_review.suitability_decisions values(i.source,i.external_key,i.revision,policy_key,p_run,null)
   on conflict do nothing;
  if found then return jsonb_build_object('id',i.item_id,'title',i.title,'body',i.evidence); end if;
 end loop;
 return 'null'::jsonb;
end $$;

-- Only the worker can release its own reservation when authentication failed before inference.
create function public.suitability_release_unsent(p_run uuid,p_item uuid) returns void
language sql security definer set search_path='' as $$
 delete from machimoa_review.suitability_decisions d using machimoa_review.suitability_items i
 where d.owner_run=p_run and d.decision is null and i.run_id=p_run and i.item_id=p_item
 and (d.source,d.external_key,d.revision)=(i.source,i.external_key,i.revision)
$$;
revoke all on function public.suitability_release_unsent(uuid,uuid) from public,anon,authenticated;
grant execute on function public.suitability_release_unsent(uuid,uuid) to service_role;

create function public.suitability_save(p_run uuid,p_item uuid,p_decision jsonb) returns boolean
language plpgsql security definer set search_path='' as $$
begin
 update machimoa_review.suitability_decisions d set decision=p_decision
 from machimoa_review.suitability_items i, machimoa_review.suitability_runs r
 where i.run_id=p_run and i.item_id=p_item and r.id=p_run and d.owner_run=p_run
 and (d.source,d.external_key,d.revision,d.policy_hash)=(i.source,i.external_key,i.revision,r.policy_hash)
 and d.decision is null and p_decision->>'group' in ('exclude','check','keep');
 return found;
end $$;

create function public.suitability_report(p_run uuid default null) returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('id',r.id,'policy',r.policy,'readAt',r.read_at,'items',coalesce((
 select jsonb_agg(jsonb_build_object('id',i.item_id,'title',i.title,'source',i.source,'key',i.external_key,
  'queue',case when i.job_id is null then 'facts' else 'ai' end,'moved',i.moved_at is not null,
  'reused',d.decision is not null and d.owner_run<>r.id,'state',case when d.decision is not null then 'done'
   when d.owner_run is null then 'waiting' else 'unconfirmed' end,'decision',d.decision)
  order by i.source,i.external_key) from machimoa_review.suitability_items i left join machimoa_review.suitability_decisions d
 on (d.source,d.external_key,d.revision,d.policy_hash)=(i.source,i.external_key,i.revision,r.policy_hash)
 where i.run_id=r.id),'[]')) from machimoa_review.suitability_runs r
 where r.policy_hash is not null and (p_run is null or r.id=p_run) order by r.created_at desc limit 1
$$;

create function public.suitability_exclude(p_run uuid,p_item uuid,p_actor uuid,p_request uuid) returns text
language plpgsql security definer set search_path='' as $$
declare i machimoa_review.suitability_items; result jsonb;
begin
 select * into strict i from machimoa_review.suitability_items where run_id=p_run and item_id=p_item for update;
 if i.moved_at is not null then return 'moved'; end if;
 if not exists(select from machimoa_review.suitability_decisions d join machimoa_review.suitability_runs r
 on r.policy_hash=d.policy_hash where r.id=p_run and (d.source,d.external_key,d.revision)=(i.source,i.external_key,i.revision)
 and d.decision is not null) then return 'skipped'; end if;
 perform 1 from machimoa_review.source_items where id=p_item for update;
 perform 1 from machimoa_review.processing_jobs where source_item_id=p_item order by revision_hash,processing_stage for update;
 if machimoa_review.suitability_operator_decided(p_item,i.revision)
 or exists(select from machimoa_review.processing_jobs where source_item_id=p_item and status='claimed')
 then return 'skipped'; end if;
 if i.job_id is null then
  result:=case when i.source='seoul_reservation' then public.admin_program_detail(p_item)
   else public.admin_myseoul_program_detail(p_item) end;
  if result->>'status' is distinct from 'open' or result->>'revision' is distinct from i.revision
    or result->>'version' is distinct from i.version then return 'skipped'; end if;
  result:=public.admin_review_exclude_reason(p_item,i.revision,i.version,'service_not_suitable','',p_actor,p_request);
  if result->>'episodeId' is null or result#>>'{item,id}' is distinct from p_item::text then raise exception 'unconfirmed'; end if;
 else
  result:=public.admin_ai_queue_exclude(i.job_id,i.revision,i.version,p_request,'service_not_suitable',p_actor);
  if result->>'status' is distinct from 'cancelled' or result->>'sourceItemId' is distinct from p_item::text then raise exception 'unconfirmed'; end if;
 end if;
 update machimoa_review.suitability_items set moved_at=clock_timestamp() where run_id=p_run and item_id=p_item;
 return 'moved';
exception when sqlstate 'PT409' or sqlstate 'PT404' or no_data_found then return 'skipped';
end $$;
revoke all on function machimoa_review.suitability_snapshot(),public.suitability_freeze(uuid) from public,anon,authenticated;
grant execute on function public.suitability_freeze(uuid) to service_role;
revoke all on function public.suitability_start(uuid,text,text,timestamptz), public.suitability_claim(uuid), public.suitability_save(uuid,uuid,jsonb), public.suitability_report(uuid), public.suitability_exclude(uuid,uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.suitability_start(uuid,text,text,timestamptz), public.suitability_claim(uuid), public.suitability_save(uuid,uuid,jsonb), public.suitability_report(uuid), public.suitability_exclude(uuid,uuid,uuid,uuid) to service_role;
commit;
