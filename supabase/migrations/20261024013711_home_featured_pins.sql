-- Home-only selection metadata. No content updates, backfill, cron or expiry job.
begin;
do $guard$
begin
 if current_user<>'postgres' or to_regclass('machimoa_review.curation_candidates') is null
  or to_regclass('machimoa_review.home_featured_state') is not null
  or to_regclass('machimoa_review.home_featured_history') is not null
  or to_regprocedure('machimoa_review.content_filter_validate(jsonb)') is null
  or to_regprocedure('machimoa_review.content_filter_endpoint(jsonb)') is null then
  raise exception 'home_featured_prerequisite_changed';
 end if;
end $guard$;

create table machimoa_review.home_featured_state (
 singleton boolean primary key default true check(singleton),
 version bigint not null default 0 check(version>=0),
 pins uuid[] not null default '{}' check(cardinality(pins)<=2 and array_position(pins,null) is null
   and (array_ndims(pins) is null or array_ndims(pins)=1) and (array_lower(pins,1) is null or array_lower(pins,1)=1)
   and (cardinality(pins)<2 or pins[1]<>pins[2]))
);
insert into machimoa_review.home_featured_state default values;
create table machimoa_review.home_featured_history (
 version bigint primary key check(version>0), request_id uuid not null unique,
 view_candidate uuid not null, source_revision text not null check(source_revision ~ '^[a-f0-9]{64}$'),
 expected_version text not null check(expected_version ~ '^[a-f0-9]{64}$'),
 target_id uuid not null, position integer check(position in (1,2)),
 action text not null check(action in ('pin','unpin','reorder')),
 before_pins uuid[] not null, after_pins uuid[] not null,
 actor uuid not null, created_at timestamptz not null default clock_timestamp()
);
alter table machimoa_review.home_featured_state enable row level security;
alter table machimoa_review.home_featured_history enable row level security;
revoke all on machimoa_review.home_featured_state,machimoa_review.home_featured_history from public,anon,authenticated,service_role;

-- Server-time counterpart of public programTiming/eventTiming. Reuse the
-- installed filter validators; do not parse prose or infer an unknown state.
create function machimoa_review.home_featured_eligible(c public.curations,p_now timestamptz) returns boolean
language plpgsql stable set search_path='' as $fn$
declare d jsonb; a jsonb; o jsonb; valid boolean:=false; starts timestamptz; ends timestamptz;
begin
 if not coalesce(c.is_published,false) or p_now is null or
  btrim(coalesce(c.title_ko,''))='' or btrim(coalesce(c.summary_ko,''))='' or btrim(coalesce(c.content_ko,''))='' or
  btrim(coalesce(c.title_ja,''))='' or btrim(coalesce(c.summary_ja,''))='' or btrim(coalesce(c.content_ja,''))='' then return false;end if;
 d:=c.content_filters;
 begin
  if jsonb_typeof(d)='object' then
   perform machimoa_review.content_filter_validate(d);
   valid:=d->>'category'=c.user_category and d ? 'foreignerProgram';
  end if;
 exception when sqlstate 'PT422' then valid:=false;
 end;
 if c.user_category='program' then
  if not coalesce(valid,false) or d#>>'{application,status}'<>'known' then return false;end if;
  a:=d#>'{application,value}';
  if a->>'sourceStatus'='closed' then return false;end if;
  starts:=case when a->'start'<>'null'::jsonb then machimoa_review.content_filter_endpoint(a->'start') end;
  ends:=case when a->'end'<>'null'::jsonb then machimoa_review.content_filter_endpoint(a->'end')+
    case when a#>>'{end,precision}'='day' then interval '1 day' else interval '0.001 second' end end;
  if ends is not null and p_now>=ends then return false;end if;
  return coalesce((a->>'sourceStatus'='open' and (starts is null or p_now>=starts))
    or (a->>'sourceStatus'='not_started' and starts is not null and p_now>=starts),false);
 elsif c.user_category='event' then
  if coalesce(valid,false) then
   if d#>>'{schedule,status}'<>'known' then return false;end if;
   for o in select value from jsonb_array_elements(d#>'{schedule,value,occurrences}') loop
    ends:=machimoa_review.content_filter_endpoint(o->'end')+
      case when o#>>'{end,precision}'='day' then interval '1 day' else interval '0.001 second' end;
    if p_now<ends then return true;end if;
   end loop;
   return false;
  end if;
  begin
   starts:=machimoa_review.content_filter_day(c.event_start_on::text)::timestamp at time zone 'Asia/Seoul';
   ends:=machimoa_review.content_filter_day(c.event_end_on::text)::timestamp at time zone 'Asia/Seoul';
   return starts<=ends and p_now<ends+interval '1 day';
  exception when sqlstate 'PT422' then return false;end;
 end if;
 return false;
end $fn$;

create function machimoa_review.home_featured_detail(p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare x machimoa_review.curation_candidates%rowtype; c public.curations%rowtype;
 s machimoa_review.home_featured_state%rowtype; snapshots jsonb; pins jsonb; fingerprint text;
begin
 select * into s from machimoa_review.home_featured_state where singleton;
 if not found then raise exception 'home_featured_unavailable';end if;
 select * into x from machimoa_review.curation_candidates where id=p_id;
 if not found or x.published_curation_id is null then raise exception 'home_featured_not_found';end if;
 select * into c from public.curations where id=x.published_curation_id
  and source=x.source and source_item_id=x.source_item_id;
 if not found then raise exception 'home_featured_not_found';end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',v.id,'public',to_jsonb(p)) order by v.n),'[]')
  into snapshots from unnest(s.pins) with ordinality v(id,n) left join public.curations p on p.id=v.id;
 select coalesce(jsonb_agg(jsonb_build_object('id',v.id,'position',v.n,
   'title',coalesce(nullif(p.title_ko,''),nullif(p.title,''),'공개 글을 확인할 수 없습니다.'),
   'eligible',coalesce(machimoa_review.home_featured_eligible(p,statement_timestamp()),false)) order by v.n),'[]')
  into pins from unnest(s.pins) with ordinality v(id,n) left join public.curations p on p.id=v.id;
 fingerprint:=encode(sha256(convert_to(jsonb_build_object('state',to_jsonb(s),'candidate',to_jsonb(x),
  'public',to_jsonb(c),'pins',snapshots)::text,'UTF8')),'hex');
 return jsonb_build_object('id',x.id,'publishedId',c.id,'revision',x.source_revision_hash,'version',fingerprint,
  'stateVersion',s.version,'position',array_position(s.pins,c.id),'pins',pins,
  'eligible',x.review_status='published' and machimoa_review.home_featured_eligible(c,statement_timestamp()));
end $fn$;

create function public.admin_review_home_featured(p_id uuid) returns jsonb
language sql security definer set search_path='' as $fn$
 select machimoa_review.home_featured_detail(p_id);
$fn$;

create function public.admin_review_set_home_featured(p_id uuid,p_revision text,p_version text,p_target uuid,p_position integer,p_request uuid,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare s machimoa_review.home_featured_state%rowtype; x machimoa_review.curation_candidates%rowtype;
 h machimoa_review.home_featured_history%rowtype; detail jsonb; next_pins uuid[]; rest uuid[]; verb text;
begin
 if p_id is null or p_actor is null or p_target is null or p_request is null or
  p_revision is null or p_revision !~ '^[a-f0-9]{64}$' or p_version is null or p_version !~ '^[a-f0-9]{64}$'
  or (p_position is not null and p_position not in (1,2)) then raise exception 'home_featured_invalid';end if;
 -- Global selection first, then candidate -> public, in the existing publication
 -- lock direction. Concurrent pin edits serialize on the single state row.
 select * into s from machimoa_review.home_featured_state where singleton for update;
 if not found then raise exception 'home_featured_unavailable';end if;
 select * into x from machimoa_review.curation_candidates where id=p_id for update;
 if not found or x.published_curation_id is null or x.source_revision_hash<>p_revision then raise exception 'home_featured_conflict';end if;
 perform id from public.curations where id=any(s.pins||array[x.published_curation_id]) order by id for share;
 detail:=machimoa_review.home_featured_detail(p_id);
 select * into h from machimoa_review.home_featured_history where request_id=p_request;
 if found then
  if h.view_candidate<>p_id or h.source_revision<>p_revision or h.expected_version<>p_version
   or h.target_id<>p_target or h.position is distinct from p_position or h.actor<>p_actor or h.version<>s.version then
   raise exception 'home_featured_conflict';end if;
  return detail;
 end if;
 if detail->>'version'<>p_version then raise exception 'home_featured_conflict';end if;
 if p_position is not null then
  if p_target<>x.published_curation_id or not (detail->>'eligible')::boolean then raise exception 'home_featured_ineligible';end if;
  if not p_target=any(s.pins) and cardinality(s.pins)=2 then raise exception 'home_featured_full';end if;
  rest:=array_remove(s.pins,p_target);
  if p_position>cardinality(rest)+1 then raise exception 'home_featured_invalid';end if;
  next_pins:=coalesce(rest[1:p_position-1],'{}'::uuid[])||array[p_target]||coalesce(rest[p_position:cardinality(rest)],'{}'::uuid[]);
  verb:=case when p_target=any(s.pins) then 'reorder' else 'pin' end;
 else
  -- Allow explicit removal of an existing hidden/ended pin from this small
  -- published-item panel, so it cannot permanently occupy one of the two slots.
  if p_target<>x.published_curation_id and not p_target=any(s.pins) then raise exception 'home_featured_invalid';end if;
  next_pins:=array_remove(s.pins,p_target);verb:='unpin';
 end if;
 if next_pins=s.pins then return detail;end if;
 update machimoa_review.home_featured_state set version=version+1,pins=next_pins where singleton;
 insert into machimoa_review.home_featured_history(version,request_id,view_candidate,source_revision,expected_version,
  target_id,position,action,before_pins,after_pins,actor)
 values(s.version+1,p_request,p_id,p_revision,p_version,p_target,p_position,verb,s.pins,next_pins,p_actor);
 return machimoa_review.home_featured_detail(p_id);
end $fn$;

create function public.public_home_featured_pins() returns jsonb
language sql stable security definer set search_path='' as $fn$
 select coalesce(jsonb_agg(jsonb_build_object('id',c.id,'position',p.n) order by p.n),'[]'::jsonb)
 from machimoa_review.home_featured_state s cross join lateral unnest(s.pins) with ordinality p(id,n)
 join public.curations c on c.id=p.id
 where s.singleton and machimoa_review.home_featured_eligible(c,statement_timestamp());
$fn$;

alter table machimoa_review.home_featured_state owner to postgres;
alter table machimoa_review.home_featured_history owner to postgres;
alter function machimoa_review.home_featured_eligible(public.curations,timestamptz) owner to postgres;
alter function machimoa_review.home_featured_detail(uuid) owner to postgres;
alter function public.admin_review_home_featured(uuid) owner to postgres;
alter function public.admin_review_set_home_featured(uuid,text,text,uuid,integer,uuid,uuid) owner to postgres;
alter function public.public_home_featured_pins() owner to postgres;
revoke all on function machimoa_review.home_featured_eligible(public.curations,timestamptz),machimoa_review.home_featured_detail(uuid),public.admin_review_home_featured(uuid),public.admin_review_set_home_featured(uuid,text,text,uuid,integer,uuid,uuid),public.public_home_featured_pins() from public,anon,authenticated,service_role;
grant execute on function public.admin_review_home_featured(uuid),public.admin_review_set_home_featured(uuid,text,text,uuid,integer,uuid,uuid) to service_role;
grant execute on function public.public_home_featured_pins() to anon,authenticated,service_role;
notify pgrst,'reload schema';
commit;
