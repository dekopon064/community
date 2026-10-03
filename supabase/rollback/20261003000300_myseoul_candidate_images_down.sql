-- Preserve choices/history/columns and public URLs. Refuse rollback when choices
-- would lose their publishing semantics; resolve that explicitly before rollback.
begin;
do $restore$
declare b record;
begin
 if current_user<>'postgres' then raise exception 'postgres_required'; end if;
 if exists(select 1 from machimoa_review.curation_candidates where image_selection_mode<>'source') then
   raise exception 'candidate_image_choices_require_preservation';
 end if;
 for b in select * from machimoa_review.myseoul_image_function_backup loop
   if pg_get_functiondef(to_regprocedure(b.name)) is distinct from b.installed then raise exception 'candidate_image_function_changed'; end if;
 end loop;
 for b in select * from machimoa_review.myseoul_image_function_backup loop execute b.definition; end loop;
end $restore$;
drop function public.admin_myseoul_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid);
notify pgrst,'reload schema';
commit;
