-- Forward-only repair of a transport encoding issue. No row/history changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $guard$
declare p record; h text;
begin
 select * into p from pg_proc where oid=to_regprocedure('machimoa_review.home_featured_detail(uuid)');
 if p.oid is null then raise exception 'home_featured_text_prerequisite_changed';end if;
 h:=encode(sha256(convert_to(btrim(replace(replace(p.prosrc,E'\r\n',E'\n'),E'\r',E'\n'),E' \t\n'),'UTF8')),'hex');
 if current_user<>'postgres' or pg_get_userbyid(p.proowner)<>'postgres' or not p.prosecdef
  or p.proconfig is distinct from array['search_path=""']::text[]
  or p.proacl::text is distinct from '{postgres=X/postgres}'
  or h not in ('21107f870c9f79f83686f6c83831326436b28f1462cf0333d5d93a9419a639c1','4e65046395486cf09f1d64a1e9ac7f7f8fcd060485a41fd7d14a6a0db3354aad') then
  raise exception 'home_featured_text_prerequisite_changed';
 end if;
end $guard$;
create or replace function machimoa_review.home_featured_detail(p_id uuid) returns jsonb
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
notify pgrst,'reload schema';
commit;
