-- Culture REST external source links: private structural validation only.
-- No table changes, data writes, backfill or new public RPC.
-- The original program validator retains all checks except its URL predicate.
begin;

create function machimoa_review.seoul_external_query_value(raw text) returns text
language plpgsql immutable set search_path='' as $$
declare value text:=''; c text; n integer; i integer:=1;
begin
 while i<=char_length(raw) loop
  c:=substr(raw,i,1);
  if c='%' then
   if substr(raw,i+1,2)!~'^[0-9A-Fa-f]{2}$' then return null;end if;
   n:=get_byte(decode(substr(raw,i+1,2),'hex'),0);
   if n<32 or n>126 then return null;end if;
   c:=chr(n);i:=i+2;
  elsif c='+' then c:=' ';end if;
  value:=value||c;i:=i+1;
 end loop;
 return value;
end $$;
revoke all on function machimoa_review.seoul_external_query_value(text) from public,anon,authenticated,service_role;

create function machimoa_review.seoul_program_url_valid(url text) returns boolean
language plpgsql immutable set search_path='' as $$
declare parts text[]; route text; required text[]; optional text[];
 seen text[]:='{}'; pair text; name text; value text; position integer;
begin
 if url is null or char_length(url)>2048 or url~'[[:space:][:cntrl:]]' or strpos(url,chr(92))>0 then return false;end if;
 if url~'^https?://yeyak[.]seoul[.]go[.]kr/web/reservation/selectReservView[.]do[?]rsv_svc_id=[A-Za-z0-9_-]+$' then return true;end if;
 parts:=regexp_match(url,'^https://([^/?#]+)(/[^?#]*)([?]([^#]*))?$');
 if parts is null then return false;end if;
 route:=parts[1]||parts[2];
 case route
 when 'umppa.seoul.go.kr/icare/user/chilProgrm/orgideaExprnCtzn/BD_selectOrgideaExprnCtzn.do' then
  required:=array['q_progrmCl','q_placeCode','q_progrmSn'];optional:='{}';
 when 'kctg.or.kr/tour/touristSiteView.do','www.kctg.or.kr/tour/touristSiteView.do' then
  required:=array['tourist_cd'];optional:=array['page_no'];
 when 'firesafety.eseoul.go.kr/multi/main.do' then required:='{}';optional:='{}';
 when 'culture.gangseo.seoul.kr/gsfc/education/view.do' then required:=array['eduSn'];optional:=array['menuNo'];
 else return false;end case;
 if coalesce(parts[4],'')<>'' then
  foreach pair in array string_to_array(parts[4],'&') loop
   position:=strpos(pair,'=');
   if position<=1 then return false;end if;
   name:=substr(pair,1,position-1);
   if not name=any(required||optional) or name=any(seen) then return false;end if;
   value:=machimoa_review.seoul_external_query_value(substr(pair,position+1));
   if value is null then return false;end if;
   if name='tourist_cd' then
    if value!~'^[A-Za-z0-9_-]{1,128}$' then return false;end if;
   elsif not(name='page_no' and value='') and value!~'^[0-9]{1,32}$' then return false;end if;
   seen:=array_append(seen,name);
  end loop;
 end if;
 return required<@seen;
end $$;
revoke all on function machimoa_review.seoul_program_url_valid(text) from public,anon,authenticated,service_role;

-- Only replace the existing URL predicate. Every other field/period/schema
-- check and the function's signature, owner, ACL and search_path must survive.
do $install$
declare fn oid; body text; definition text; old_owner oid; old_acl aclitem[]; old_config text[];
 old_check text:=$old$if p->>'official_url'<>'' and p->>'official_url' !~ '^https?://yeyak[.]seoul[.]go[.]kr/web/reservation/selectReservView[.]do[?]rsv_svc_id=[A-Za-z0-9_-]+$' then$old$;
 new_check text:=$new$if p->>'official_url'<>'' and not machimoa_review.seoul_program_url_valid(p->>'official_url') then$new$;
begin
 fn:=to_regprocedure('machimoa_review.program_validate(jsonb)');
 if current_user<>'postgres' or fn is null then raise exception 'seoul_program_url_prerequisite';end if;
 select prosrc,pg_get_functiondef(oid),proowner,proacl,proconfig into body,definition,old_owner,old_acl,old_config
 from pg_proc where oid=fn and prosecdef and provolatile='i' and prorettype='void'::regtype
 and proowner=(select oid from pg_roles where rolname='postgres') and proconfig=array['search_path=""'];
 if body is null or (length(body)-length(replace(body,old_check,'')))/length(old_check)<>1 then
  raise exception 'seoul_program_url_prerequisite_changed';end if;
 execute replace(definition,old_check,new_check);
 if not exists(select 1 from pg_proc where oid=fn and prosrc=replace(body,old_check,new_check)
 and proowner=old_owner and proacl is not distinct from old_acl and proconfig=old_config
 and prosecdef and provolatile='i' and prorettype='void'::regtype) then
  raise exception 'seoul_program_url_contract_changed';end if;
end $install$;
commit;
