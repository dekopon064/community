begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $$ declare r record;current_definition text;begin
if current_user<>'postgres' then raise exception 'postgres_required';end if;
lock table machimoa_review.review_classifications,machimoa_review.review_classification_history,machimoa_review.review_classification_claims,machimoa_review.review_classification_candidates,machimoa_review.review_classification_publications in access exclusive mode;
if exists(select 1 from machimoa_review.review_classifications) or exists(select 1 from machimoa_review.review_classification_history) or exists(select 1 from machimoa_review.review_classification_claims) or exists(select 1 from machimoa_review.review_classification_candidates) or exists(select 1 from machimoa_review.review_classification_publications) then raise exception 'classification_records_present';end if;
for r in select * from machimoa_review.classification_installed_objects loop
if r.kind='function' then
if to_regprocedure(r.name) is null or pg_get_functiondef(to_regprocedure(r.name)) is distinct from r.definition or (select jsonb_build_object('acl',proacl::text,'owner',pg_get_userbyid(proowner))::text from pg_proc where oid=to_regprocedure(r.name)) is distinct from r.acl then raise exception 'classification_successor_changed: %',r.name;end if;
elsif r.kind='table' then if machimoa_review.classification_table_metadata(r.name)::text is distinct from r.definition then raise exception 'classification_successor_table_changed';end if;
else select pg_get_triggerdef(oid) into current_definition from pg_trigger where tgname=r.name;
if current_definition is distinct from r.definition then raise exception 'classification_successor_trigger_changed';end if;end if;
end loop;end $$;
drop trigger classification_claim_guard on machimoa_review.processing_jobs;
drop trigger classification_candidate_update on machimoa_review.curation_candidates;
do $$ declare r record;begin
for r in select * from machimoa_review.classification_function_backup loop execute r.definition;end loop;
for r in select name from machimoa_review.classification_installed_objects where kind='function' and name<>'machimoa_review.classification_table_metadata(text)' and name not in (select name from machimoa_review.classification_function_backup) loop execute 'drop function '||r.name;end loop;
end $$;
drop function machimoa_review.classification_table_metadata(text);
drop table machimoa_review.review_classification_publications,machimoa_review.review_classification_candidates,machimoa_review.review_classification_claims,machimoa_review.review_classification_history,machimoa_review.review_classifications,machimoa_review.classification_installed_objects,machimoa_review.classification_function_backup;
notify pgrst,'reload schema';commit;
