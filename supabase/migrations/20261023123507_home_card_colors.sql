-- Local-only: one analysis attempt per public curation; no content backfill,
-- stored image bytes, job queue, reanalysis, or changes to existing publish RPCs.
begin;
do $guard$
begin
 if current_user <> 'postgres' then raise exception 'postgres_required'; end if;
 if to_regprocedure('public.admin_review_publish(uuid,text,text,uuid)') is null
   or to_regprocedure('machimoa_review.safe_source_image_url(text)') is null
   or not exists(select 1 from pg_trigger where tgrelid='machimoa_review.curation_candidates'::regclass
     and tgname='project_published_source_image' and not tgisinternal and tgenabled='O')
   or to_regclass('machimoa_review.home_card_colors') is not null then
   raise exception 'home_color_prerequisite_changed';
 end if;
end $guard$;

create table machimoa_review.home_card_colors (
 curation_id uuid primary key references public.curations(id) on delete cascade,
 candidate_id uuid not null,
 source_revision text not null check(source_revision ~ '^[a-f0-9]{64}$'),
 image_url text,
 tone text not null default 'default' check(tone in ('default','orange','yellow','green','blue','purple','red')),
 state text not null check(state in ('pending','processing','completed','failed','no_image')),
 reason text check(reason in ('matched','ambiguous','analysis_failed','image_changed','expired')),
 published_by text not null,
 claimed_by uuid,
 token uuid,
 created_at timestamptz not null default clock_timestamp(),
 expires_at timestamptz not null default clock_timestamp()+interval '60 seconds',
 started_at timestamptz,
 finished_at timestamptz,
 check(state='completed' or tone='default'),
 check((state in ('completed','failed','no_image')) = (finished_at is not null)),
 check(state<>'processing' or (token is not null and claimed_by is not null and started_at is not null)),
 check(state not in ('pending','processing') or image_url is not null)
);
alter table machimoa_review.home_card_colors enable row level security;
revoke all on machimoa_review.home_card_colors from public,anon,authenticated,service_role;

create function machimoa_review.prepare_home_card_color() returns trigger
language plpgsql security definer set search_path='' as $fn$
declare image text;
begin
 select machimoa_review.safe_source_image_url(c.source_image_url) into image
 from public.curations c where c.id=new.published_curation_id and c.is_published
   and c.source=new.source and c.source_item_id=new.source_item_id;
 if not found then return new; end if;
 insert into machimoa_review.home_card_colors(curation_id,candidate_id,source_revision,image_url,state,published_by,finished_at)
 values(new.published_curation_id,new.id,new.source_revision_hash,image,
   case when image is null then 'no_image' else 'pending' end,coalesce(new.reviewed_by,''),
   case when image is null then clock_timestamp() else null end)
 on conflict(curation_id) do nothing; -- No retry/reanalysis even after image changes.
 return new;
end $fn$;

-- Alphabetical AFTER-trigger ordering: the existing URL projection completes
-- first, then this trigger snapshots that URL in the same publication transaction.
create trigger zz_prepare_home_card_color
after insert or update of review_status,published_curation_id on machimoa_review.curation_candidates
for each row when (new.review_status='published' and new.published_curation_id is not null)
execute function machimoa_review.prepare_home_card_color();

create function public.admin_home_color_claim(p_id uuid,p_candidate uuid,p_actor uuid) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare c public.curations%rowtype; h machimoa_review.home_card_colors%rowtype;
begin
 if p_actor is null or p_id is null or p_candidate is null then raise exception 'home_color_invalid'; end if;
 select * into c from public.curations where id=p_id and is_published for share;
 if not found then raise exception 'home_color_conflict'; end if;
 select * into h from machimoa_review.home_card_colors where curation_id=p_id for update;
 if not found or h.candidate_id<>p_candidate or h.published_by<>p_actor::text
   or not exists(select 1 from machimoa_review.curation_candidates x where x.id=p_candidate
     and x.published_curation_id=p_id and x.review_status='published' and x.source=c.source
     and x.source_item_id=c.source_item_id and x.source_revision_hash=h.source_revision) then
   raise exception 'home_color_conflict';
 end if;
 if h.state='no_image' then return jsonb_build_object('state','no_image'); end if;
 if h.state='processing' then return jsonb_build_object('state','processing'); end if;
 if h.state<>'pending' then return jsonb_build_object('state','settled'); end if;
 if h.expires_at<=clock_timestamp() or c.source_image_url is distinct from h.image_url then
   update machimoa_review.home_card_colors set state='failed',finished_at=clock_timestamp(),
     reason=case when h.expires_at<=clock_timestamp() then 'expired' else 'image_changed' end where curation_id=p_id;
   return jsonb_build_object('state','settled');
 end if;
 update machimoa_review.home_card_colors set state='processing',token=gen_random_uuid(),claimed_by=p_actor,
   started_at=clock_timestamp() where curation_id=p_id returning * into h;
 return jsonb_build_object('state','claimed','token',h.token,'url',h.image_url);
end $fn$;

create function public.admin_home_color_finish(p_id uuid,p_token uuid,p_actor uuid,p_tone text,p_state text,p_reason text) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare c public.curations%rowtype; h machimoa_review.home_card_colors%rowtype;
begin
 if p_id is null or p_token is null or p_actor is null or p_state is null or p_state not in ('completed','failed')
   or p_tone is null or p_tone not in ('default','orange','yellow','green','blue','purple','red')
   or p_reason is null or (p_state='failed' and (p_tone<>'default' or p_reason<>'analysis_failed'))
   or (p_state='completed' and (p_reason not in ('matched','ambiguous') or (p_reason='ambiguous' and p_tone<>'default'))) then
   raise exception 'home_color_invalid';
 end if;
 select * into c from public.curations where id=p_id for share;
 if not found then raise exception 'home_color_conflict'; end if;
 select * into h from machimoa_review.home_card_colors where curation_id=p_id for update;
 if not found or h.token is distinct from p_token or h.claimed_by is distinct from p_actor then raise exception 'home_color_conflict'; end if;
 -- A repeated confirmed completion may be read, but can never overwrite it.
 if h.state in ('completed','failed') then
   if h.state<>p_state or h.tone<>p_tone or h.reason<>p_reason then raise exception 'home_color_conflict'; end if;
   return jsonb_build_object('state',h.state,'tone',h.tone);
 end if;
 if h.state<>'processing' then raise exception 'home_color_conflict'; end if;
 if h.expires_at<=clock_timestamp() or not c.is_published or c.source_image_url is distinct from h.image_url then
   p_state:='failed';p_tone:='default';p_reason:=case when h.expires_at<=clock_timestamp() then 'expired' else 'image_changed' end;
 end if;
 update machimoa_review.home_card_colors set state=p_state,tone=p_tone,reason=p_reason,finished_at=clock_timestamp()
 where curation_id=p_id;
 return jsonb_build_object('state',p_state,'tone',p_tone);
end $fn$;

-- Read-only, bounded projection. Never returns image URLs, actor or attempt data.
create function public.public_home_card_colors(p_ids uuid[]) returns jsonb
language plpgsql stable security definer set search_path='' as $fn$
declare result jsonb;
begin
 if p_ids is null or cardinality(p_ids)>6 or array_position(p_ids,null) is not null then raise exception 'home_color_invalid'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',c.id,
   'tone',case when h.state='completed' then h.tone else 'default' end,
   'ready',not(coalesce(h.state in ('pending','processing'),false) and h.expires_at>statement_timestamp())) order by c.id),'[]'::jsonb)
 into result from public.curations c left join machimoa_review.home_card_colors h on h.curation_id=c.id
 where c.id=any(p_ids) and c.is_published;
 return result;
end $fn$;

alter table machimoa_review.home_card_colors owner to postgres;
alter function machimoa_review.prepare_home_card_color() owner to postgres;
alter function public.admin_home_color_claim(uuid,uuid,uuid) owner to postgres;
alter function public.admin_home_color_finish(uuid,uuid,uuid,text,text,text) owner to postgres;
alter function public.public_home_card_colors(uuid[]) owner to postgres;
revoke all on function machimoa_review.prepare_home_card_color() from public,anon,authenticated,service_role;
revoke all on function public.admin_home_color_claim(uuid,uuid,uuid) from public,anon,authenticated,service_role;
revoke all on function public.admin_home_color_finish(uuid,uuid,uuid,text,text,text) from public,anon,authenticated,service_role;
revoke all on function public.public_home_card_colors(uuid[]) from public,anon,authenticated,service_role;
grant execute on function public.admin_home_color_claim(uuid,uuid,uuid) to service_role;
grant execute on function public.admin_home_color_finish(uuid,uuid,uuid,text,text,text) to service_role;
grant execute on function public.public_home_card_colors(uuid[]) to anon,authenticated,service_role;
notify pgrst,'reload schema';
commit;
