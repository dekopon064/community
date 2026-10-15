-- Informational source status maps to pre-reception. No data/backfill/job changes.
begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $install$
declare fn oid;body text;definition text;owner_before oid;acl_before aclitem[];config_before text[];
old_check text:=$old$coalesce(p->>'source_status','') not in ('open','reservation_closed','application_closed','unknown')$old$;
new_check text:=$new$coalesce(p->>'source_status','') not in ('announced','open','reservation_closed','application_closed','unknown')$new$;
begin
 fn:=to_regprocedure('machimoa_review.program_validate(jsonb)');
 if current_user<>'postgres' or fn is null then raise exception 'seoul_status_prerequisite';end if;
 select prosrc,pg_get_functiondef(oid),proowner,proacl,proconfig into body,definition,owner_before,acl_before,config_before
 from pg_proc where oid=fn and prosecdef and provolatile='i' and prorettype='void'::regtype
 and proowner=(select oid from pg_roles where rolname='postgres') and proconfig=array['search_path=""']
 and proacl::text='{postgres=X/postgres}';
 if body is null or encode(sha256(convert_to(replace(replace(definition,E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'473c47465b2a964bcf1758af8fdb542489dc2f3b4093a34b43c154fd46b1e403'
 or (length(body)-length(replace(body,old_check,'')))/length(old_check)<>1
 or strpos(body,'not machimoa_review.seoul_program_url_valid')=0 then
  raise exception 'seoul_status_prerequisite_changed';end if;
 execute replace(definition,old_check,new_check);
 if not exists(select 1 from pg_proc where oid=fn and prosrc=replace(body,old_check,new_check)
 and proowner=owner_before and proacl is not distinct from acl_before and proconfig=config_before
 and prosecdef and provolatile='i' and prorettype='void'::regtype) then
  raise exception 'seoul_status_contract_changed';end if;
end $install$;
do $link$
declare target record;fn oid;body text;definition text;owner_before oid;acl_before aclitem[];config_before text[];
begin
 if current_user<>'postgres' then raise exception 'seoul_status_prerequisite';end if;
 for target in select * from (values
 ('machimoa_review.content_filter_fact_values(uuid,text)',
  '2f0787341552437020be5ce2fb3f161a4587b57a6d617fa26aba155b93778f1a',false,'s',
  $old$case when f->>'source_status' in ('not_started','open','closed')$old$,
  $new$case when f->>'source_status'='announced' then 'not_started' when f->>'source_status' in ('not_started','open','closed')$new$),
 ('machimoa_review.program_evaluate_with_confirmation(jsonb,timestamp with time zone,boolean)',
  '7d815a648ec060d2a32fd4f90a44a0e437d013d3d3e3ef65c969799d1c06fcbf',true,'i',
  $old$if d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date<(d->>'value')::date else p_now<(d->>'value')::timestamptz end)$old$,
  $new$if p->>'source_status'='announced' or (d->>'status'='ok' and (case when d->>'precision'='day' then (p_now at time zone 'Asia/Seoul')::date<(d->>'value')::date else p_now<(d->>'value')::timestamptz end))$new$)
 ) v(signature,hash,security,volatility,old_clause,new_clause) loop
  fn:=to_regprocedure(target.signature);
  select prosrc,pg_get_functiondef(oid),proowner,proacl,proconfig into body,definition,owner_before,acl_before,config_before
  from pg_proc where oid=fn and prosecdef=target.security and provolatile::text=target.volatility
  and prorettype='jsonb'::regtype and proowner=(select oid from pg_roles where rolname='postgres')
  and proconfig=array['search_path=""'] and proacl::text='{postgres=X/postgres}';
  if body is null or encode(sha256(convert_to(replace(replace(definition,E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>target.hash
  or (length(body)-length(replace(body,target.old_clause,'')))/length(target.old_clause)<>1 then
   raise exception 'seoul_status_link_prerequisite_changed';end if;
  execute replace(definition,target.old_clause,target.new_clause);
  if not exists(select 1 from pg_proc where oid=fn and prosrc=replace(body,target.old_clause,target.new_clause)
   and proowner=owner_before and proacl is not distinct from acl_before and proconfig=config_before
   and prosecdef=target.security and provolatile::text=target.volatility and prorettype='jsonb'::regtype) then
   raise exception 'seoul_status_link_contract_changed';end if;
 end loop;
end $link$;
commit;
