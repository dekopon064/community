-- Local draft: preserve immutable first-analysis rows; append operator choices.
begin;
do $guard$
begin
 if current_user<>'postgres' or to_regclass('machimoa_review.home_card_colors') is null
   or to_regclass('machimoa_review.home_card_color_choices') is not null
   or not exists(select 1 from pg_proc p where p.oid=to_regprocedure('public.public_home_card_colors(uuid[])')
      and p.proowner='postgres'::regrole and p.prosecdef
      and md5(regexp_replace(p.prosrc,'\s','','g'))='243103cd7a0c84332fbf01ff64b0a860') then
  raise exception 'home_color_prerequisite_changed';
 end if;
end $guard$;

create table machimoa_review.home_card_color_choices (
 curation_id uuid not null references public.curations(id) on delete cascade,
 version bigint not null check(version>0),
 candidate_id uuid not null,
 source_revision text not null check(source_revision ~ '^[a-f0-9]{64}$'),
 tone text not null check(tone in ('default','orange','yellow','green','blue','purple','red')),
 previous_tone text not null check(previous_tone in ('default','orange','yellow','green','blue','purple','red')),
 expected_version text not null check(expected_version ~ '^[a-f0-9]{64}$'),
 request_id uuid not null unique,
 actor uuid not null,
 created_at timestamptz not null default clock_timestamp(),
 primary key(curation_id,version)
);
alter table machimoa_review.home_card_color_choices enable row level security;
revoke all on machimoa_review.home_card_color_choices from public,anon,authenticated,service_role;

-- Safe admin projection: no source/image URL, claim token, worker or AI response.
create function machimoa_review.home_color_detail(p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare x machimoa_review.curation_candidates%rowtype; c public.curations%rowtype;
 h machimoa_review.home_card_colors%rowtype; o machimoa_review.home_card_color_choices%rowtype;
 active boolean; fingerprint text;
begin
 select * into x from machimoa_review.curation_candidates where id=p_id and review_status='published';
 if not found or x.published_curation_id is null then raise exception 'home_color_not_found'; end if;
 select * into c from public.curations where id=x.published_curation_id and is_published
   and source=x.source and source_item_id=x.source_item_id;
 if not found then raise exception 'home_color_not_found'; end if;
 select * into h from machimoa_review.home_card_colors where curation_id=c.id;
 select * into o from machimoa_review.home_card_color_choices where curation_id=c.id order by version desc limit 1;
 active:=coalesce(h.state in ('pending','processing') and h.expires_at>statement_timestamp(),false);
 fingerprint:=encode(sha256(convert_to(jsonb_build_object('candidate',to_jsonb(x),'public',to_jsonb(c),
   'analysis',to_jsonb(h),'choice',to_jsonb(o))::text,'UTF8')),'hex');
 return jsonb_build_object('id',x.id,'publishedId',c.id,'revision',x.source_revision_hash,'version',fingerprint,
   'analysisState',coalesce(h.state,'missing'),'analysisTone',coalesce(h.tone,'default'),'analysisReason',h.reason,
   'analysisActive',active,'tone',coalesce(o.tone,case when h.state='completed' then h.tone else 'default' end),
   'manual',o.curation_id is not null,'choiceVersion',coalesce(o.version,0),'canEdit',not active,
   'changedAt',o.created_at);
end $fn$;

create function public.admin_review_home_color(p_id uuid) returns jsonb
language sql security definer set search_path='' as $fn$
 select machimoa_review.home_color_detail(p_id);
$fn$;

create function public.admin_review_set_home_color(p_id uuid,p_revision text,p_version text,p_tone text,p_request uuid,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare x machimoa_review.curation_candidates%rowtype; c public.curations%rowtype;
 h machimoa_review.home_card_colors%rowtype; prior machimoa_review.home_card_color_choices%rowtype;
 detail jsonb;
begin
 if p_id is null or p_actor is null or p_request is null or p_revision is null or p_revision !~ '^[a-f0-9]{64}$'
  or p_version is null or p_version !~ '^[a-f0-9]{64}$' or p_tone is null
  or p_tone not in ('default','orange','yellow','green','blue','purple','red') then raise exception 'home_color_invalid'; end if;
 -- Match publication/edit lock order. Automatic finish locks public -> analysis
 -- and never candidate, so there is no reverse dependency.
 select * into x from machimoa_review.curation_candidates where id=p_id for update;
 if not found or x.review_status<>'published' or x.published_curation_id is null then raise exception 'home_color_conflict'; end if;
 select * into c from public.curations where id=x.published_curation_id for update;
 if not found or not c.is_published or c.source is distinct from x.source or c.source_item_id is distinct from x.source_item_id
   or x.source_revision_hash<>p_revision then raise exception 'home_color_conflict'; end if;
 select * into h from machimoa_review.home_card_colors where curation_id=c.id for share;
 detail:=machimoa_review.home_color_detail(p_id);
 select * into prior from machimoa_review.home_card_color_choices where request_id=p_request;
 if found then
  if prior.curation_id<>c.id or prior.candidate_id<>p_id or prior.source_revision<>p_revision
   or prior.expected_version<>p_version or prior.tone<>p_tone or prior.actor<>p_actor
   or prior.version<>(detail->>'choiceVersion')::bigint then raise exception 'home_color_conflict'; end if;
  return detail; -- Confirmed duplicate, never a new history row or overwrite.
 end if;
 if detail->>'version'<>p_version or not (detail->>'canEdit')::boolean then raise exception 'home_color_conflict'; end if;
 if detail->>'tone'=p_tone then return detail; end if;
 insert into machimoa_review.home_card_color_choices(curation_id,version,candidate_id,source_revision,tone,
   previous_tone,expected_version,request_id,actor)
 values(c.id,(detail->>'choiceVersion')::bigint+1,p_id,p_revision,p_tone,detail->>'tone',p_version,p_request,p_actor);
 return machimoa_review.home_color_detail(p_id);
end $fn$;

-- Preserve the bounded public read and preparation gate. Expose only tone and
-- manual flag, never admin metadata. A deliberate choice also works sans image.
create or replace function public.public_home_card_colors(p_ids uuid[]) returns jsonb
language plpgsql stable security definer set search_path='' as $fn$
declare result jsonb;
begin
 if p_ids is null or cardinality(p_ids)>6 or array_position(p_ids,null) is not null then raise exception 'home_color_invalid'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',c.id,
   'tone',coalesce(o.tone,case when h.state='completed' then h.tone else 'default' end),
   'manual',o.tone is not null,
   'ready',o.tone is not null or not(coalesce(h.state in ('pending','processing'),false) and h.expires_at>statement_timestamp())) order by c.id),'[]'::jsonb)
 into result from public.curations c left join machimoa_review.home_card_colors h on h.curation_id=c.id
 left join lateral(select a.tone from machimoa_review.home_card_color_choices a where a.curation_id=c.id order by version desc limit 1) o on true
 where c.id=any(p_ids) and c.is_published;
 return result;
end $fn$;

alter table machimoa_review.home_card_color_choices owner to postgres;
alter function machimoa_review.home_color_detail(uuid) owner to postgres;
alter function public.admin_review_home_color(uuid) owner to postgres;
alter function public.admin_review_set_home_color(uuid,text,text,text,uuid,uuid) owner to postgres;
revoke all on function machimoa_review.home_color_detail(uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_review_home_color(uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_review_set_home_color(uuid,text,text,text,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function public.admin_review_home_color(uuid) to service_role;
grant execute on function public.admin_review_set_home_color(uuid,text,text,text,uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
