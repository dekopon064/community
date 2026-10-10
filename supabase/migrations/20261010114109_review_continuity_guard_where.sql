-- Keep the rollback fence, and restrict its UPDATE to the singleton row.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $$ begin
if to_regprocedure('machimoa_review.review_continuity_dirty()') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.review_continuity_dirty()')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'0b8ef65428b103b76e72f26a2ca72e5c41afd6c64fd40582fdb472a7f11987a5' then raise exception 'continuity_where_predecessor_changed';end if;
if (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()'))<>'postgres' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()')) is distinct from '{postgres=X/postgres}' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()')) is distinct from array['search_path=""']::text[] or (select prosecdef from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()')) then raise exception 'continuity_where_privileges_changed';end if;
if not exists(select 1 from pg_class where oid=to_regclass('machimoa_review.review_continuity_install') and relrowsecurity and pg_get_userbyid(relowner)='postgres' and relacl::text='{postgres=arwdDxtm/postgres}') then raise exception 'continuity_where_table_changed';end if;
if (select count(*) from pg_trigger where tgrelid in ('machimoa_review.review_classifications'::regclass,'machimoa_review.review_classification_history'::regclass,'machimoa_review.source_item_content_filters'::regclass,'machimoa_review.myseoul_residence_reviews'::regclass,'machimoa_review.myseoul_fact_edits'::regclass,'machimoa_review.source_item_program_facts'::regclass) and tgname='review_continuity_dirty' and tgfoid='machimoa_review.review_continuity_dirty()'::regprocedure and tgenabled='O' and not tgisinternal and tgtype=28)<>6 then raise exception 'continuity_where_triggers_changed';end if;
end $$;
create or replace function machimoa_review.review_continuity_dirty() returns trigger language plpgsql set search_path='' as $function$begin update machimoa_review.review_continuity_install set dirty=true where singleton=true;return null;end $function$;
commit;
