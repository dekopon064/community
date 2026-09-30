-- LOCAL DRAFT. Does NOT undo saved facts, reviews, public content or publication lineage.
-- Refuse destructive audit loss after any use; preserve/export history before separate rollback approval.
begin;
do $guard$ begin
  if current_user <> 'postgres' then raise exception 'postgres migration owner required'; end if;
  if exists(select 1 from machimoa_review.admin_review_events) then
    raise exception 'admin review history exists: retain audit and prepare a separate rollback plan';
  end if;
end $guard$;
drop function public.admin_review_detail(text,uuid);
drop function public.admin_review_list(text,integer,integer);
drop function public.admin_review_save_facts(uuid,text,text,jsonb,uuid);
drop function public.admin_review_exclude(uuid,text,text,text,uuid);
drop function public.admin_review_save_candidate(uuid,text,text,jsonb,uuid);
drop function public.admin_review_publish(uuid,text,text,uuid);
drop function public.admin_review_reject(uuid,text,text,text,uuid);
drop function machimoa_review.admin_review_candidate_action(text,uuid,text,text,jsonb,text,uuid);
drop function machimoa_review.admin_review_lock(text,uuid,text,text,uuid);
drop function machimoa_review.admin_review_item(text,uuid);
drop function machimoa_review.admin_review_snapshot(text,uuid);
drop function machimoa_review.admin_review_source(text,uuid);
drop table machimoa_review.admin_review_events;
notify pgrst, 'reload schema';
commit;
