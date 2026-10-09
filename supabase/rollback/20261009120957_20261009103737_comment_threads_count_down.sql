-- Refuse rollback after later records or contract changes; never delete user data.
begin;
lock table machimoa_comments.residents,machimoa_comments.comments,machimoa_comments.requests,
 machimoa_comments.thread_guard in access exclusive mode;
do $guard$
declare actual jsonb;g machimoa_comments.thread_guard;entry record;expected text;
begin
 if current_user<>'postgres' then raise exception 'requires postgres'; end if;
 select * into strict g from machimoa_comments.thread_guard where singleton;
select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comment_threads','list_information_comment_replies','count_information_comments','create_information_comment_reply','list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
) into actual;
 if actual is distinct from g.installed_fingerprint then raise exception 'subsequent thread contract changes: rollback blocked'; end if;
 if g.records_fingerprint is distinct from machimoa_comments.numeric_records_fingerprint() then raise exception 'subsequent comment records: rollback blocked'; end if;
 if md5(g.original_fingerprint::text)<>'6f9734075c5cae07f0caee62cc400ff5' then raise exception 'unexpected original contract'; end if;
 for entry in select * from jsonb_each_text(g.original_definitions) loop
  select value->>1 into expected from jsonb_array_elements(g.original_fingerprint->'functions') where value->>0=entry.key;
  if expected is null or md5(replace(entry.value,E'\r\n',E'\n'))<>expected then raise exception 'unexpected original definition'; end if;
 end loop;
end $guard$;
drop function public.create_information_comment_reply(uuid,uuid,text,text,uuid);
drop function public.count_information_comments(uuid);
drop function public.list_information_comment_replies(uuid,uuid,timestamptz,uuid);
drop function public.list_information_comment_threads(uuid,timestamptz,uuid);
do $restore$
declare entry record;
begin for entry in select * from jsonb_each_text((select original_definitions from machimoa_comments.thread_guard where singleton)) loop execute entry.value; end loop; end $restore$;
drop function machimoa_comments.create_thread_comment(uuid,uuid,text,text,uuid);
drop function machimoa_comments.public_count(uuid);
drop function machimoa_comments.thread_list(uuid,uuid,timestamptz,uuid);
drop trigger comments_parent_guard on machimoa_comments.comments;
drop function machimoa_comments.validate_parent();
drop index machimoa_comments.comments_root_page_idx;
drop index machimoa_comments.comments_reply_page_idx;
alter table machimoa_comments.comments drop constraint comments_parent_content_fk;
alter table machimoa_comments.comments drop constraint comments_id_content_unique;
alter table machimoa_comments.comments drop constraint comments_not_self;
alter table machimoa_comments.comments drop column parent_id;
drop table machimoa_comments.thread_guard;
do $verify$
declare actual jsonb;
begin
select jsonb_build_object(
 'schema',(select jsonb_build_array(nspowner::regrole::text,nspacl::text) from pg_namespace where nspname='machimoa_comments'),
 'functions',(select jsonb_agg(jsonb_build_array(p.oid::regprocedure::text,md5(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n')),p.proacl::text,p.proowner::regrole::text) order by p.oid::regprocedure::text) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='machimoa_comments' or (n.nspname='public' and p.proname in ('list_information_comment_threads','list_information_comment_replies','count_information_comments','create_information_comment_reply','list_information_comments','prepare_comment_resident','create_information_comment','information_comment_request_state','remove_information_comment','admin_hide_information_comment','purge_expired_hidden_information_comments'))),
 'relations',(select jsonb_agg(jsonb_build_array(c.relname,c.relkind,c.relowner::regrole::text,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity) order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'columns',(select jsonb_agg(jsonb_build_array(c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attacl::text,pg_get_expr(d.adbin,d.adrelid)) order by c.relname,a.attnum) from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where n.nspname='machimoa_comments' and a.attnum>0 and not a.attisdropped),
 'constraints',(select jsonb_agg(jsonb_build_array(c.relname,q.conname,pg_get_constraintdef(q.oid)) order by c.relname,q.conname) from pg_constraint q join pg_class c on c.oid=q.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'indexes',(select jsonb_agg(pg_get_indexdef(i.indexrelid) order by i.indexrelid::regclass::text) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'policies',(select jsonb_agg(jsonb_build_array(c.relname,p.polname,p.polcmd,p.polroles::text,p.polqual::text,p.polwithcheck::text,p.polpermissive) order by c.relname,p.polname) from pg_policy p join pg_class c on c.oid=p.polrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments'),
 'triggers',(select jsonb_agg(jsonb_build_array(c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled) order by c.relname,t.tgname) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='machimoa_comments' and not t.tgisinternal)
) into actual;
 if actual is distinct from (select installed_fingerprint from machimoa_comments.numeric_code_guard where singleton) then raise exception 'restored contract mismatch'; end if;
end $verify$;
notify pgrst,'reload schema';
commit;
