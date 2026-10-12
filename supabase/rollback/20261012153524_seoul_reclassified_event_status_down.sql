begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $$ declare r record;p record;begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 for r in select * from (values
 ('machimoa_review.classification_reasons(uuid,jsonb)','89b0853371874b89c3483e4c70110e52438d72e521ce50399486e242ce6faeb0'),
 ('machimoa_review.classification_reasons_before_seoul_event_status(uuid,jsonb)','0cf3b7bd5746cb7bd745ff9abc0a185616777fc6e1675d51bfecca857f9e783f')
 ) expected(signature,hash) loop
 select * into p from pg_proc where oid=to_regprocedure(r.signature);
 if p.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>r.hash
 or pg_get_userbyid(p.proowner)<>'postgres' or p.proacl::text is distinct from '{postgres=X/postgres}'
 or p.proconfig is distinct from array['search_path=""']::text[] or p.prosecdef
 then raise exception 'seoul_event_status_successor_changed';end if;
 end loop;
 execute replace(pg_get_functiondef(to_regprocedure('machimoa_review.classification_reasons_before_seoul_event_status(uuid,jsonb)')),
 'FUNCTION machimoa_review.classification_reasons_before_seoul_event_status(', 'FUNCTION machimoa_review.classification_reasons(');
end $$;
drop function machimoa_review.classification_reasons_before_seoul_event_status(uuid,jsonb);
-- Existing facts, history and jobs are never rewritten on restoration either.
commit;
