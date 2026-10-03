-- Feature stop only, NOT an undo of users' dismissals. Historical records,
-- filtered listing, and restore-block trigger intentionally remain installed.
-- Old application code can still list/restore non-dismissed episodes.
-- Do not drop dismissal tables/trigger or strip list filters: that revives items.
begin;
revoke all on function public.admin_review_trash_dismiss_preview(),public.admin_review_trash_dismiss(text,uuid,text,uuid,uuid) from service_role;
notify pgrst,'reload schema';
commit;
