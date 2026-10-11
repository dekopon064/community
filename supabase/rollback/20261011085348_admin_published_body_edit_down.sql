begin;
-- Disable the new endpoints only. Preserve content and immutable before/after
-- records: rolling back deployment must not silently revert public text.
drop function public.admin_review_save_published_body(uuid,text,text,text,jsonb,text,uuid);
drop function public.admin_review_published_detail(uuid);
drop function public.admin_review_published_list(integer,integer);
notify pgrst,'reload schema';
commit;
