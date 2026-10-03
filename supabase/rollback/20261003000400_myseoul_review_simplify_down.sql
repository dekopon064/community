-- Restore the previous application before removing v2. Never erase audit data.
begin;
do $$ begin
 if exists(select 1 from machimoa_review.myseoul_fact_edits) then
 raise exception 'My v2 audit data exists: retain it and plan a data-preserving rollback';end if;
end $$;
drop function public.admin_myseoul_program_save_v2(uuid,text,text,jsonb,uuid);
drop table machimoa_review.myseoul_fact_edits;
commit;
