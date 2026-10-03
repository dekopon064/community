-- Local-only follow-up. No source/permission activation and no existing RPC redefinition.
begin;
create table machimoa_review.myseoul_list_discoveries (
 external_key text primary key check(external_key ~ '^[A-F0-9]{32}:[A-F0-9]{32}$'),
 official_url text not null check(official_url='https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?cntr_no='||split_part(external_key,':',1)||'&prgrm_no='||split_part(external_key,':',2)||'&lang=ko'),
 first_seen_at timestamptz not null default clock_timestamp(),
 last_seen_at timestamptz not null default clock_timestamp(),
 first_run_id uuid not null references machimoa_review.ingest_runs(id),
 state text not null check(state in ('pending','processed','skipped_closed')),
 attempts integer not null default 0 check(attempts>=0),
 last_attempt_at timestamptz,
 last_error text check(last_error is null or last_error='detail_failed')
);
create table machimoa_review.myseoul_list_run_state (
 run_id uuid primary key references machimoa_review.ingest_runs(id),
 total integer not null check(total between 0 and 100000),
 pages integer not null default 0 check(pages between 0 and 2),
 first_all_new boolean not null default false,
 seen_keys text[] not null default '{}',
 new_count integer not null default 0,
 known_count integer not null default 0,
 closed_skipped integer not null default 0,
 selected_keys text[],
 carried_count integer not null default 0,
 attempted_keys text[] not null default '{}',
 processed integer not null default 0,
 failed integer not null default 0
);
alter table machimoa_review.myseoul_list_discoveries enable row level security;
alter table machimoa_review.myseoul_list_run_state enable row level security;
revoke all on machimoa_review.myseoul_list_discoveries,machimoa_review.myseoul_list_run_state from public,anon,authenticated,service_role;

create function public.discover_myseoul_list_page(p_run_id uuid,p_page integer,p_total integer,p_entries jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare r machimoa_review.myseoul_list_run_state%rowtype;e jsonb;k text;is_known boolean;has_source boolean;n integer:=0;c integer:=0;
begin
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 if p_page is null or p_page not in (1,2) or p_total is null or p_total not between 0 and 100000 or p_entries is null or jsonb_typeof(p_entries)<>'array' then
 raise exception using errcode='PT422',message='invalid_myseoul_list';end if;
 if jsonb_array_length(p_entries)<>least(10,greatest(0,p_total-(p_page-1)*10)) then raise exception using errcode='PT422',message='incomplete_myseoul_list';end if;
 if p_page=1 then insert into machimoa_review.myseoul_list_run_state(run_id,total) values(p_run_id,p_total) on conflict do nothing;end if;
 select * into r from machimoa_review.myseoul_list_run_state where run_id=p_run_id for update;
 if not found or r.pages<>p_page-1 or r.total<>p_total or r.selected_keys is not null or (p_page=2 and not r.first_all_new) then
 raise exception using errcode='PT409',message='myseoul_list_sequence_conflict';end if;
 for e in select value from jsonb_array_elements(p_entries) loop
 if jsonb_typeof(e)<>'object' or (select count(*) from jsonb_object_keys(e))<>3 or not e ?& array['key','url','state'] or
 jsonb_typeof(e->'key')<>'string' or jsonb_typeof(e->'url')<>'string' or jsonb_typeof(e->'state')<>'string' then raise exception using errcode='PT422',message='invalid_myseoul_list_entry';end if;
 k:=e->>'key';
 if k !~ '^[A-F0-9]{32}:[A-F0-9]{32}$' or k=any(r.seen_keys) or e->>'state' not in ('closed','unknown') or
 e->>'url' is distinct from 'https://global.seoul.go.kr/hmpg/ecpr/prgm/prgmDetail.do?cntr_no='||split_part(k,':',1)||'&prgrm_no='||split_part(k,':',2)||'&lang=ko' then
 raise exception using errcode='PT422',message='invalid_myseoul_list_entry';end if;
 select exists(select 1 from machimoa_review.source_items where source_id='myseoul_program' and external_key=k) into has_source;
 is_known:=has_source or exists(select 1 from machimoa_review.myseoul_list_discoveries where external_key=k);
 if is_known then r.known_count:=r.known_count+1;else n:=n+1;end if;
 insert into machimoa_review.myseoul_list_discoveries(external_key,official_url,first_run_id,state)
 values(k,e->>'url',p_run_id,case when has_source then 'processed' when e->>'state'='closed' then 'skipped_closed' else 'pending' end)
 on conflict(external_key) do update set last_seen_at=clock_timestamp(),state=
 case when has_source or myseoul_list_discoveries.state='processed' then 'processed'
 when e->>'state'='closed' then 'skipped_closed' else 'pending' end;
 if not has_source and e->>'state'='closed' then c:=c+1;end if;
 r.seen_keys:=array_append(r.seen_keys,k);
 end loop;
 update machimoa_review.myseoul_list_run_state set pages=p_page,seen_keys=r.seen_keys,new_count=new_count+n,known_count=r.known_count,closed_skipped=closed_skipped+c,
 first_all_new=case when p_page=1 then n=10 else first_all_new end where run_id=p_run_id;
 return jsonb_build_object('allNew',n=10,'new',n,'known',jsonb_array_length(p_entries)-n,'page',p_page);
end $$;

create function public.myseoul_pending_details(p_run_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare r machimoa_review.myseoul_list_run_state%rowtype;keys text[];result jsonb;carried integer;
begin
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 select * into r from machimoa_review.myseoul_list_run_state where run_id=p_run_id for update;
 if not found or r.pages=0 or (r.pages=1 and r.first_all_new) or r.selected_keys is not null then raise exception using errcode='PT409',message='myseoul_list_sequence_conflict';end if;
 -- Unknown observation response from a previous run: reconcile, never re-fetch it.
 update machimoa_review.myseoul_list_discoveries d set state='processed',last_error=null
 where d.state='pending' and exists(select 1 from machimoa_review.source_items s where s.source_id='myseoul_program' and s.external_key=d.external_key);
 select coalesce(array_agg(external_key order by prior desc,last_attempt_at nulls first,first_seen_at,external_key),'{}'),
 coalesce(jsonb_agg(jsonb_build_object('key',external_key,'url',official_url) order by prior desc,last_attempt_at nulls first,first_seen_at,external_key),'[]'),
 count(*) filter(where prior) into keys,result,carried from (
 select d.*,d.first_run_id<>p_run_id prior from machimoa_review.myseoul_list_discoveries d where state='pending'
 order by (first_run_id<>p_run_id) desc,last_attempt_at nulls first,first_seen_at,external_key limit 10) q;
 update machimoa_review.myseoul_list_run_state set selected_keys=keys,carried_count=carried where run_id=p_run_id;
 return result;
end $$;

create function public.record_myseoul_detail_attempt(p_run_id uuid,p_key text,p_outcome text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare r machimoa_review.myseoul_list_run_state%rowtype;
begin
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 select * into r from machimoa_review.myseoul_list_run_state where run_id=p_run_id for update;
 if p_outcome is null or p_outcome not in ('processed','detail_failed') or p_key is null then raise exception using errcode='PT422',message='invalid_myseoul_detail_result';end if;
 if not found or r.selected_keys is null or not p_key=any(r.selected_keys) or p_key=any(r.attempted_keys) then raise exception using errcode='PT409',message='myseoul_detail_attempt_conflict';end if;
 if p_outcome='processed' and not exists(select 1 from machimoa_review.source_items where source_id='myseoul_program' and external_key=p_key) then
 raise exception using errcode='PT409',message='myseoul_observation_missing';end if;
 update machimoa_review.myseoul_list_discoveries set state=case when p_outcome='processed' then 'processed' else 'pending' end,
 attempts=attempts+1,last_attempt_at=clock_timestamp(),last_error=case when p_outcome='processed' then null else 'detail_failed' end where external_key=p_key;
 update machimoa_review.myseoul_list_run_state set attempted_keys=array_append(attempted_keys,p_key),
 processed=processed+case when p_outcome='processed' then 1 else 0 end,failed=failed+case when p_outcome='detail_failed' then 1 else 0 end where run_id=p_run_id;
 return jsonb_build_object('outcome',p_outcome);
end $$;

create function public.finish_myseoul_list_collection(p_run_id uuid,p_requests integer,p_failed boolean) returns jsonb
language plpgsql security definer set search_path='' as $$
declare r machimoa_review.myseoul_list_run_state%rowtype;summary jsonb;state text;reason text;remaining integer;
begin
 perform 1 from machimoa_review.source_sync_state where source_id='myseoul_program' and active_run_id=p_run_id and lease_owner=p_run_id and lease_expires_at>clock_timestamp() for update;
 if not found then raise exception using errcode='PT409',message='myseoul_lease_lost';end if;
 if p_requests is null or p_requests not between 0 and 12 or p_failed is null then raise exception using errcode='PT422',message='invalid_myseoul_finish';end if;
 select * into r from machimoa_review.myseoul_list_run_state where run_id=p_run_id for update;
 if not p_failed and (not found or r.selected_keys is null or cardinality(r.attempted_keys)<>cardinality(r.selected_keys) or p_requests<>r.pages+cardinality(r.attempted_keys)) then
 raise exception using errcode='PT409',message='myseoul_run_incomplete';end if;
 select count(*) into remaining from machimoa_review.myseoul_list_discoveries d where d.state='pending';
 reason:=case when p_failed then 'read_or_outcome_unknown' when r.failed>0 then 'detail_failed' when remaining>0 then 'detail_budget_limit'
 when r.pages=2 then 'two_page_limit' when r.total<10 then 'short_first_page' else 'first_page_existing' end;
 state:=case when p_failed then 'failed' when coalesce(r.failed,0)>0 or remaining>0 then 'incomplete' else 'complete' end;
 summary:=jsonb_build_object('coverage','program_list_first_two_pages','source_complete',false,'list_pages',coalesce(r.pages,0),
 'discovered',coalesce(cardinality(r.seen_keys),0),'new',coalesce(r.new_count,0),'known',coalesce(r.known_count,0),
 'closed_skipped',coalesce(r.closed_skipped,0),'selected',coalesce(cardinality(r.selected_keys),0),'carried_selected',coalesce(r.carried_count,0),
 'processed',coalesce(r.processed,0),'failed',coalesce(r.failed,0),'pending_remaining',remaining,'stop_reason',reason);
 perform machimoa_review.finish_ingest_run(p_run_id,state,reason,p_requests,false,coalesce(r.processed,0));
 update machimoa_review.ingest_runs set run_summary=summary where id=p_run_id;
 return jsonb_build_object('status',state,'summary',summary);
end $$;

revoke all on function public.discover_myseoul_list_page(uuid,integer,integer,jsonb),public.myseoul_pending_details(uuid),public.record_myseoul_detail_attempt(uuid,text,text),public.finish_myseoul_list_collection(uuid,integer,boolean) from public,anon,authenticated,service_role;
grant execute on function public.discover_myseoul_list_page(uuid,integer,integer,jsonb),public.myseoul_pending_details(uuid),public.record_myseoul_detail_attempt(uuid,text,text),public.finish_myseoul_list_collection(uuid,integer,boolean) to service_role;
notify pgrst,'reload schema';
commit;
