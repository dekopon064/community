-- Keep the rollback fence, and restrict its UPDATE to the singleton row.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
lock table machimoa_review.myseoul_fact_edits,machimoa_review.myseoul_residence_reviews,machimoa_review.review_classification_history,machimoa_review.review_classifications,machimoa_review.source_item_content_filters,machimoa_review.source_item_program_facts in share row exclusive mode;
do $$ begin
if (select dirty from machimoa_review.review_continuity_install where singleton) is distinct from false then raise exception 'continuity_where_records_present';end if;
if to_regprocedure('machimoa_review.review_continuity_dirty()') is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(to_regprocedure('machimoa_review.review_continuity_dirty()')),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'bd9b32fbd5b10e080f8a6a965745df842d0870baec70b2dce0f1ea01a38fa641' then raise exception 'continuity_where_successor_changed';end if;
if (select pg_get_userbyid(proowner) from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()'))<>'postgres' or (select proacl::text from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()')) is distinct from '{postgres=X/postgres}' or (select proconfig from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()')) is distinct from array['search_path=""']::text[] or (select prosecdef from pg_proc where oid=to_regprocedure('machimoa_review.review_continuity_dirty()')) then raise exception 'continuity_where_privileges_changed';end if;
if not exists(select 1 from pg_class where oid=to_regclass('machimoa_review.review_continuity_install') and relrowsecurity and pg_get_userbyid(relowner)='postgres' and relacl::text='{postgres=arwdDxtm/postgres}') then raise exception 'continuity_where_table_changed';end if;
if (select count(*) from pg_trigger where tgrelid in ('machimoa_review.review_classifications'::regclass,'machimoa_review.review_classification_history'::regclass,'machimoa_review.source_item_content_filters'::regclass,'machimoa_review.myseoul_residence_reviews'::regclass,'machimoa_review.myseoul_fact_edits'::regclass,'machimoa_review.source_item_program_facts'::regclass) and tgname='review_continuity_dirty' and tgfoid='machimoa_review.review_continuity_dirty()'::regprocedure and tgenabled='O' and not tgisinternal and tgtype=28)<>6 then raise exception 'continuity_where_triggers_changed';end if;
end $$;
create or replace function machimoa_review.review_continuity_dirty() returns trigger language plpgsql set search_path='' as $function$begin update machimoa_review.review_continuity_install set dirty=true;return null;end $function$;
commit;
