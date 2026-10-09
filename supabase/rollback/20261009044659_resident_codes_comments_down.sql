-- This rollback preserves all resident/comment/request records by refusing
-- to run once any exist, or when the installed contract has subsequently changed.
begin;
lock table machimoa_comments.residents,machimoa_comments.comments,machimoa_comments.requests,machimoa_comments.install_guard in access exclusive mode;
do $guard$
declare actual jsonb;
begin
 if current_user<>'postgres' then raise exception 'requires postgres'; end if;
 if (select count(*) from machimoa_comments.install_guard)<>1 then raise exception 'missing installed comment contract'; end if;
 select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
) into actual;
 if actual is distinct from (select fingerprint from machimoa_comments.install_guard where singleton) then raise exception 'subsequent comment contract changes: rollback blocked'; end if;
 if exists(select 1 from machimoa_comments.residents) or exists(select 1 from machimoa_comments.comments) or exists(select 1 from machimoa_comments.requests) then raise exception 'resident/comment records exist: rollback blocked'; end if;
end $guard$;
drop function public.list_information_comments(uuid,timestamptz,uuid),public.prepare_comment_resident(uuid),public.create_information_comment(uuid,uuid,text,text),public.information_comment_request_state(uuid,uuid),public.remove_information_comment(uuid,uuid),public.admin_hide_information_comment(uuid,uuid,uuid),public.purge_expired_hidden_information_comments(integer);
drop function machimoa_comments.list(uuid,timestamptz,uuid),machimoa_comments.prepare(uuid),machimoa_comments.create_comment(uuid,uuid,text,text),machimoa_comments.request_state(uuid,uuid),machimoa_comments.remove_comment(uuid,uuid),machimoa_comments.hide_comment(uuid,uuid,uuid),machimoa_comments.purge_hidden(integer);
drop function machimoa_comments.require_content(uuid,boolean),machimoa_comments.normalize_body(text);
drop table machimoa_comments.requests;
drop table machimoa_comments.comments;
drop table machimoa_comments.residents;
drop table machimoa_comments.install_guard;
drop schema machimoa_comments;
notify pgrst,'reload schema';
commit;
