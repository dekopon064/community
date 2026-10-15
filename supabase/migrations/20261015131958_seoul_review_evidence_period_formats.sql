begin;
set local lock_timeout='5s';set local statement_timeout='30s';
-- DDL only: no observations, review updates, jobs, AI, history or candidates.
do $$ declare p record;begin
 select * into p from pg_proc where oid=to_regprocedure('machimoa_review.seoul_same_period_supported(jsonb)');
 if p.oid is null or pg_get_userbyid(p.proowner)<>'postgres' or p.prosecdef or p.provolatile<>'i'
 or p.proconfig is distinct from array['search_path=""']::text[] or p.proacl::text is distinct from '{postgres=X/postgres}'
 or encode(sha256(convert_to(replace(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'b2e56233844f06a65f8ab48701bc63a8223dd848a630042dbee1020a61ae8a08'
 then raise exception 'review_period_format_predecessor_changed';end if;
end $$;
create or replace function machimoa_review.seoul_same_period_supported(p jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare line text; statement text; role_name text; m text[]; a date; b date; k text;
 seen text[]:='{}'; proof_count int:=0; ep jsonb; clock_value text; clocks text[];
 pattern text:='(20[0-9]{2})\s*[.년/-]\s*([0-9]{1,2})\s*[.월/-]\s*([0-9]{1,2})\s*(?:일|\.)?\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*\))?\s*(?:[~～〜–—-]|부터)\s*(?:(20[0-9]{2})\s*[.년/-]\s*)?(?:([0-9]{1,2})\s*[.월/-]\s*)?([0-9]{1,2})\s*(?:일|\.)?\s*(?:\(\s*([월화수목금토일])(?:요일)?\s*\))?';
begin
 perform machimoa_review.program_validate(p);
 if not (p->'missing' ? 'body_period_needs_confirmation')
 or p->'conflicts' ?| array['body_period_needs_confirmation','body_api_period_conflict','date_weekday_conflict','invalid_body_date','period_order_conflict']
 or exists(select 1 from jsonb_each(p->'periods') x where x.value->>'status'<>'ok') then return false;end if;
 for line in select regexp_split_to_table(p->>'description',E'\n') loop
  line:=regexp_replace(btrim(line),'^[[:space:]□■○ㅇ❍〇◎❐•⦁●▪▶▷►▹※*·✅☑✔✓◆◇🔸🔹📍♠♣️-]+','');
  line:=regexp_replace(line,'^(?:[0-9]{1,2}[.)]\s*|[①-⑳]\s*)','');
  role_name:=case when line ~ '^(접수기간|신청기간|모집기간)\s*[:：]' then 'RCPT'
                  when line ~ '^(운영기간|진행기간)\s*[:：]' then 'SVCOPN' end;
  if role_name is null then continue;end if;
  statement:=btrim(regexp_replace(line,'^[^:：]+[:：]\s*',''));
  clocks:=array[null,null]::text[];
  if role_name='SVCOPN' and statement ~ '^(20[0-9]{2})\.[0-9]{1,2}\.[0-9]{1,2}\.?$' then
   m:=regexp_match(statement,'^(20[0-9]{2})\.([0-9]{1,2})\.([0-9]{1,2})\.?$');
   a:=make_date(m[1]::int,m[2]::int,m[3]::int);b:=a;
  elsif statement ~ '^(20[0-9]{2})년\s*[0-9]{1,2}월\s*[0-9]{1,2}일\s*[0-9]{1,2}시\s*~\s*[0-9]{1,2}월\s*[0-9]{1,2}일\s*[0-9]{1,2}시$' then
   m:=regexp_match(statement,'^(20[0-9]{2})년\s*([0-9]{1,2})월\s*([0-9]{1,2})일\s*([0-9]{1,2})시\s*~\s*([0-9]{1,2})월\s*([0-9]{1,2})일\s*([0-9]{1,2})시$');
   if m[4]::int>23 or m[7]::int>23 then return false;end if;
   a:=make_date(m[1]::int,m[2]::int,m[3]::int);b:=make_date(m[1]::int,m[5]::int,m[6]::int);
   clocks:=array[lpad(m[4],2,'0')||':00:00',lpad(m[7],2,'0')||':00:00'];
  else
   m:=regexp_match(statement,'^'||pattern||'\s*$');
   if m is null then m:=regexp_match(statement,'^'||pattern||'\s+([0-9]{1,2}):([0-5][0-9])\s*$');end if;
   if m is null then return false;end if;
   a:=make_date(m[1]::int,m[2]::int,m[3]::int);
   b:=make_date(coalesce(m[5],m[1])::int,coalesce(m[6],m[2])::int,m[7]::int);
   if m[4] is not null and m[4]<>substr('월화수목금토일',extract(isodow from a)::int,1)
    or m[8] is not null and m[8]<>substr('월화수목금토일',extract(isodow from b)::int,1) then return false;end if;
   if array_length(m,1)=10 then
    if m[9]::int>23 then return false;end if;
    clocks[2]:=lpad(m[9],2,'0')||':'||m[10]||':00';
   end if;
  end if;
  if a>b then return false;end if;
  foreach k in array array['BGNDT','ENDDT'] loop
   ep:=p->'periods'->(role_name||k);
   if (case when ep->>'precision'='day' then (ep->>'value')::date
       else ((ep->>'value')::timestamptz at time zone 'Asia/Seoul')::date end)
       is distinct from (case when k='BGNDT' then a else b end) then return false;end if;
   clock_value:=clocks[case when k='BGNDT' then 1 else 2 end];
   if clock_value is not null and (ep->>'precision'<>'second' or
    to_char((ep->>'value')::timestamptz at time zone 'Asia/Seoul','HH24:MI:SS')<>clock_value) then return false;end if;
  end loop;
  seen:=array_append(seen,statement);proof_count:=proof_count+1;
 end loop;
 if proof_count=0 or jsonb_array_length(p->'period_evidence')=0 then return false;end if;
 if exists(select 1 from jsonb_array_elements_text(p->'period_evidence') e where not e=any(seen)) then return false;end if;
 return true;
exception when datetime_field_overflow or invalid_datetime_format or invalid_text_representation then return false;
end $$;

commit;
