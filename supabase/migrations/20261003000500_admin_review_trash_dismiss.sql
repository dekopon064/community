-- Local implementation only. No source/facts/worker writes and no record deletion.
begin;
do $$begin if current_user <> 'postgres' then raise exception 'postgres owner required'; end if; end$$;
create table machimoa_review.admin_trash_dismiss_requests (
 request_id uuid primary key, actor uuid not null, input jsonb not null,
 response jsonb not null, created_at timestamptz not null default clock_timestamp()
);
create table machimoa_review.admin_trash_dismissals (
 episode_id uuid primary key references machimoa_review.admin_exclusion_episodes(id),
 request_id uuid not null references machimoa_review.admin_trash_dismiss_requests(request_id),
 actor uuid not null, dismissed_at timestamptz not null
);
alter table machimoa_review.admin_trash_dismiss_requests enable row level security;
alter table machimoa_review.admin_trash_dismissals enable row level security;
revoke all on machimoa_review.admin_trash_dismiss_requests,machimoa_review.admin_trash_dismissals from public,anon,authenticated,service_role;

-- Deletion versions deliberately concern the exclusion episode, not worker/source
-- availability: blocked entries may be hidden without acquiring worker/source locks.
create function machimoa_review.admin_trash_dismiss_version(p_episode uuid) returns text
language sql stable security definer set search_path='' as $$
 select encode(sha256(convert_to(to_jsonb(e)::text,'UTF8')),'hex')
 from machimoa_review.admin_exclusion_episodes e where id=p_episode
$$;
create function public.admin_review_trash_dismiss_preview() returns jsonb
language sql volatile security definer set search_path='' as $$
 with stamp as (select clock_timestamp() t), targets as (
 select e.id, machimoa_review.admin_trash_dismiss_version(e.id) version
 from machimoa_review.admin_exclusion_episodes e,stamp
 where e.restored_at is null and e.expires_at>stamp.t
 and e.source_name in ('youthcenter_policy','youthcenter_content','seoul_reservation')
 and not exists(select 1 from machimoa_review.admin_trash_dismissals d where d.episode_id=e.id)
 ), summary as (
 select count(*) n,coalesce(jsonb_agg(jsonb_build_array(id,version) order by id),'[]') v from targets
 ) select jsonb_build_object('count',n,'version',encode(sha256(convert_to(v::text,'UTF8')),'hex')) from summary
$$;

-- Keep the latest publication guards and future unrelated list logic intact.
-- Refuse an unexpected predecessor instead of replacing its whole definition.
do $$declare definition text;needle text := 'where e.restored_at is null and e.expires_at>stamp';begin
 definition:=pg_get_functiondef('public.admin_review_trash(integer,integer)'::regprocedure);
 if position(needle in definition)=0 or position('''version'',machimoa_review.admin_trash_version(q.id)' in definition)=0 then
 raise exception 'Unexpected trash list predecessor'; end if;
 definition:=replace(definition,needle,needle||' and not exists(select 1 from machimoa_review.admin_trash_dismissals d where d.episode_id=e.id)');
 definition:=replace(definition,'''version'',machimoa_review.admin_trash_version(q.id)',
 '''version'',machimoa_review.admin_trash_version(q.id),''dismissVersion'',machimoa_review.admin_trash_dismiss_version(q.id)');
 execute definition;
end$$;

-- A restore that races a dismissal must fail at the episode update. This trigger
-- also remains installed on rollback so historical dismissals never revive.
create function machimoa_review.admin_trash_block_dismissed_restore() returns trigger
language plpgsql security definer set search_path='' as $$begin
 if new.restored_at is not null and old.restored_at is null and exists(
 select 1 from machimoa_review.admin_trash_dismissals where episode_id=old.id) then
 raise sqlstate 'PT409' using message='review_already_processed';end if;
 return new;
end$$;
create trigger admin_trash_block_dismissed_restore before update of restored_at
on machimoa_review.admin_exclusion_episodes for each row
execute function machimoa_review.admin_trash_block_dismissed_restore();

create function public.admin_review_trash_dismiss(p_action text,p_episode uuid,p_version text,p_actor uuid,p_request uuid) returns jsonb
language plpgsql security definer set search_path='' as $$
declare e machimoa_review.admin_exclusion_episodes%rowtype; r machimoa_review.admin_trash_dismiss_requests%rowtype;
 stamp timestamptz;preview jsonb;ids uuid[];input jsonb;result jsonb;n integer;
begin
 if p_actor is null or p_request is null or p_action is null or p_action not in ('dismiss','empty')
 or p_version is null or p_version!~'^[a-f0-9]{64}$' or (p_action='dismiss' and p_episode is null)
 or (p_action='empty' and p_episode is not null) then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 -- Same request serialization without taking any source/worker locks.
 perform pg_advisory_xact_lock(hashtextextended('trash-dismiss:'||p_request::text,0));
 input:=jsonb_build_array(p_action,p_episode,p_version);
 select * into r from machimoa_review.admin_trash_dismiss_requests where request_id=p_request;
 if found then
 if r.actor<>p_actor or r.input<>input then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 return r.response;end if;
 if p_action='dismiss' then
 select * into e from machimoa_review.admin_exclusion_episodes where id=p_episode for update;
 if not found then raise sqlstate 'PT404' using message='review_not_found';end if;
 stamp:=clock_timestamp();
 if e.source_name not in ('youthcenter_policy','youthcenter_content','seoul_reservation') then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 if e.restored_at is not null or exists(select 1 from machimoa_review.admin_trash_dismissals where episode_id=e.id) then raise sqlstate 'PT409' using message='review_already_processed';end if;
 if e.expires_at<=stamp then raise sqlstate 'PT409' using message='trash_expired';end if;
 if machimoa_review.admin_trash_dismiss_version(e.id) is distinct from p_version then raise sqlstate 'PT409' using message='review_conflict';end if;
 ids:=array[e.id];
 else
 -- Bound atomic batches. IDs stay server-side; never accept a browser-supplied list.
 -- Lock only episodes, in deterministic order. New exclusions arriving after the
 -- checked snapshot remain visible and are never silently added to this batch.
 stamp:=clock_timestamp();
 select array_agg(id order by id) into ids from (
 select target.id from machimoa_review.admin_exclusion_episodes target
 where target.restored_at is null and target.expires_at>stamp
 and target.source_name in ('youthcenter_policy','youthcenter_content','seoul_reservation')
 and not exists(select 1 from machimoa_review.admin_trash_dismissals d where d.episode_id=target.id)
 order by target.id limit 5001 for update of target) locked;
 if coalesce(cardinality(ids),0)>5000 then raise sqlstate 'PT422' using message='review_invalid_input';end if;
 stamp:=clock_timestamp(); -- Check expiry again after lock waits.
 select coalesce(array_agg(target.id order by target.id),'{}'),jsonb_build_object('count',count(*),'version',
 encode(sha256(convert_to(coalesce(jsonb_agg(jsonb_build_array(target.id,machimoa_review.admin_trash_dismiss_version(target.id)) order by target.id),'[]')::text,'UTF8')),'hex'))
 into ids,preview from machimoa_review.admin_exclusion_episodes target
 where target.id=any(coalesce(ids,'{}')) and target.restored_at is null and target.expires_at>stamp
 and not exists(select 1 from machimoa_review.admin_trash_dismissals d where d.episode_id=target.id);
 if preview->>'version' is distinct from p_version or cardinality(ids)=0
 or public.admin_review_trash_dismiss_preview()->>'version' is distinct from p_version then
 raise sqlstate 'PT409' using message='review_conflict';end if;
 end if;
 result:=jsonb_build_object('action',p_action,'count',cardinality(ids),'episodeId',p_episode);
 insert into machimoa_review.admin_trash_dismiss_requests(request_id,actor,input,response,created_at) values(p_request,p_actor,input,result,stamp);
 insert into machimoa_review.admin_trash_dismissals(episode_id,request_id,actor,dismissed_at) select id,p_request,p_actor,stamp from unnest(ids) id;
 get diagnostics n=row_count;
 if n<>cardinality(ids) then raise exception 'Incomplete dismissal';end if;
 return result;
end$$;
revoke all on function machimoa_review.admin_trash_dismiss_version(uuid),machimoa_review.admin_trash_block_dismissed_restore() from public,anon,authenticated,service_role;
revoke all on function public.admin_review_trash_dismiss_preview(),public.admin_review_trash_dismiss(text,uuid,text,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_review_trash_dismiss_preview(),public.admin_review_trash_dismiss(text,uuid,text,uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;

