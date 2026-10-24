-- Local-only prerequisite for a separately approved one-off. No backfill, queue,
-- public write RPC or changes to original analysis/manual history.
begin;
do $guard$ begin
 if current_user<>'postgres' or to_regclass('machimoa_review.home_color_area40_once') is not null
 or not exists(select 1 from pg_proc where oid=to_regprocedure('machimoa_review.home_color_detail(uuid)') and proowner='postgres'::regrole and prosecdef and proconfig=array['search_path=""']::text[] and md5(regexp_replace(prosrc,'\s','','g'))='f2bb1748518f4a4b327567811e9b9988')
 or not exists(select 1 from pg_proc where oid=to_regprocedure('public.public_home_card_colors(uuid[])') and proowner='postgres'::regrole and prosecdef and proconfig=array['search_path=""']::text[] and md5(regexp_replace(prosrc,'\s','','g'))='43566b1f86ce40183f58fe88b7d0ec89') then raise exception 'home_color_area40_prerequisite_changed'; end if;
end $guard$;
create table machimoa_review.home_color_area40_once (
 curation_id uuid primary key references public.curations(id) on delete cascade,
 candidate_id uuid not null,
 source_revision text not null check(source_revision ~ '^[a-f0-9]{64}$'),
 image_url text not null,
 public_hash text not null check(public_hash ~ '^[a-f0-9]{64}$'),
 candidate_hash text not null check(candidate_hash ~ '^[a-f0-9]{64}$'),
 analysis_hash text not null check(analysis_hash ~ '^[a-f0-9]{64}$'),
 expected_version text not null check(expected_version ~ '^[a-f0-9]{64}$'),
 analyzer_hash text not null check(analyzer_hash ~ '^[a-f0-9]{64}$'),
 policy text not null default 'area40-192-v1' check(policy='area40-192-v1'),
 request_id uuid not null unique,
 actor uuid not null,
 state text not null default 'processing' check(state in ('processing','completed','failed','skipped_changed','skipped_manual','expired')),
 tone text not null default 'default' check(tone in ('default','orange','yellow','green','blue','purple','red')),
 reason text check(reason in ('matched','ambiguous','analysis_failed')),
 started_at timestamptz not null default clock_timestamp(),
 expires_at timestamptz not null default clock_timestamp()+interval '60 seconds',
 finished_at timestamptz,
 check(expires_at>started_at),
 check((state='processing')=(finished_at is null)),
 check((state in ('completed','failed'))=(reason is not null)),
 check(state='completed' or tone='default'),
 check((state='completed' and ((reason='matched' and tone<>'default') or (reason='ambiguous' and tone='default')))
   or (state='failed' and reason='analysis_failed' and tone='default')
   or (state in ('processing','skipped_changed','skipped_manual','expired') and reason is null))
);
alter table machimoa_review.home_color_area40_once owner to postgres;
alter table machimoa_review.home_color_area40_once enable row level security;
revoke all on machimoa_review.home_color_area40_once from public,anon,authenticated,service_role;

create or replace function machimoa_review.home_color_detail(p_id uuid) returns jsonb
language plpgsql security definer set search_path='' as $fn$
declare x machimoa_review.curation_candidates%rowtype; c public.curations%rowtype;
 h machimoa_review.home_card_colors%rowtype; o machimoa_review.home_card_color_choices%rowtype;
 r machimoa_review.home_color_area40_once%rowtype; active boolean; fingerprint text;
begin
 select * into x from machimoa_review.curation_candidates where id=p_id and review_status='published';
 if not found or x.published_curation_id is null then raise exception 'home_color_not_found'; end if;
 select * into c from public.curations where id=x.published_curation_id and is_published
   and source=x.source and source_item_id=x.source_item_id;
 if not found then raise exception 'home_color_not_found'; end if;
 select * into h from machimoa_review.home_card_colors where curation_id=c.id;
 select * into o from machimoa_review.home_card_color_choices where curation_id=c.id order by version desc limit 1;
 select * into r from machimoa_review.home_color_area40_once where curation_id=c.id;
 active:=coalesce(h.state in ('pending','processing') and h.expires_at>statement_timestamp(),false);
 fingerprint:=encode(sha256(convert_to(jsonb_build_object('candidate',to_jsonb(x),'public',to_jsonb(c),
   'analysis',to_jsonb(h),'choice',to_jsonb(o),'area40',to_jsonb(r))::text,'UTF8')),'hex');
 return jsonb_build_object('id',x.id,'publishedId',c.id,'revision',x.source_revision_hash,'version',fingerprint,
   'analysisState',case when r.state='completed' then 'completed' else coalesce(h.state,'missing') end,
   'analysisTone',case when r.state='completed' then r.tone else coalesce(h.tone,'default') end,
   'analysisReason',case when r.state='completed' then r.reason else h.reason end,
   'analysisActive',active,'tone',coalesce(o.tone,case when r.state='completed' then r.tone when h.state='completed' then h.tone else 'default' end),
   'manual',o.curation_id is not null,'choiceVersion',coalesce(o.version,0),'canEdit',not active,
   'changedAt',o.created_at);
end $fn$;

create or replace function public.public_home_card_colors(p_ids uuid[]) returns jsonb
language plpgsql stable security definer set search_path='' as $fn$
declare result jsonb;
begin
 if p_ids is null or cardinality(p_ids)>6 or array_position(p_ids,null) is not null then raise exception 'home_color_invalid'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',c.id,
   'tone',coalesce(o.tone,case when r.state='completed' then r.tone when h.state='completed' then h.tone else 'default' end),
   'manual',o.tone is not null,
   'ready',o.tone is not null or not(coalesce(h.state in ('pending','processing'),false) and h.expires_at>statement_timestamp())) order by c.id),'[]'::jsonb)
 into result from public.curations c left join machimoa_review.home_card_colors h on h.curation_id=c.id
 left join machimoa_review.home_color_area40_once r on r.curation_id=c.id
 left join lateral(select a.tone from machimoa_review.home_card_color_choices a where a.curation_id=c.id order by version desc limit 1) o on true
 where c.id=any(p_ids) and c.is_published;
 return result;
end $fn$;
-- CREATE OR REPLACE preserves existing function ownership, ACL and signatures.
notify pgrst,'reload schema';
commit;
