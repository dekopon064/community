begin;
alter table machimoa_review.curation_candidates add column general_viewing jsonb;
alter table public.curations add column program_outing jsonb;

-- The optional public fragment contains only a controlled subject, calendar and access.
create function machimoa_review.valid_general_viewing(v jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare d text;
begin
 if v is null then return true; end if;
 if jsonb_typeof(v)<>'object' or not(v ?& array['subject','from','through','weekdays','exceptions','reservationNotRequired'])
    or (select count(*) from jsonb_object_keys(v))<>(case when v->>'subject'='other' then 8 else 6 end)
    or coalesce(v->>'subject','') not in ('exhibition','garden','facility','other')
    or (v->>'subject'='other' and (jsonb_typeof(v->'labelKo') is distinct from 'string' or jsonb_typeof(v->'labelJa') is distinct from 'string'
       or length(trim(v->>'labelKo')) not between 1 and 80 or length(trim(v->>'labelJa')) not between 1 and 80
       or concat(v->>'labelKo',v->>'labelJa') ~ '[<>[:cntrl:]]'))
    or v->'reservationNotRequired'<>'true'::jsonb
    or jsonb_typeof(v->'weekdays')<>'array' or jsonb_typeof(v->'exceptions')<>'array'
    or jsonb_array_length(v->'weekdays') not between 1 and 7 or jsonb_array_length(v->'exceptions')>366
    or exists(select from jsonb_array_elements(v->'weekdays') x where x::text !~ '^[0-6]$')
    or (select count(distinct x) from jsonb_array_elements(v->'weekdays') x) <> jsonb_array_length(v->'weekdays')
    then return false; end if;
 for d in select v->>'from' union all select v->>'through' union all select jsonb_array_elements_text(v->'exceptions') loop
   if d is null or d !~ '^(19|20|21)[0-9]{2}-[0-9]{2}-[0-9]{2}$' or to_char(d::date,'YYYY-MM-DD')<>d
      or d < v->>'from' or d > v->>'through' then return false; end if;
 end loop;
 return true;
exception when data_exception then return false;
end $$;
alter table machimoa_review.curation_candidates add check (machimoa_review.valid_general_viewing(general_viewing));

alter function machimoa_review.admin_review_item(text,uuid) rename to pre_outing_admin_review_item;
create function machimoa_review.admin_review_item(p_kind text,p_id uuid)
returns jsonb language sql stable security definer set search_path='' as $$
 select machimoa_review.pre_outing_admin_review_item(p_kind,p_id) ||
 coalesce((select jsonb_build_object('viewing',general_viewing) from machimoa_review.curation_candidates
 where p_kind='candidates' and id=p_id and user_category='program' and general_viewing is not null),'{}');
$$;

create function public.admin_review_save_candidate_viewing(p_id uuid,p_revision text,p_version text,
  p_content jsonb,p_actor uuid,p_image jsonb,p_viewing jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare sid uuid;
begin
 sid:=machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor);
 if not exists(select from machimoa_review.curation_candidates where id=p_id and user_category='program'
     and review_status='pending' and published_curation_id is null) or not machimoa_review.valid_general_viewing(p_viewing)
 then raise sqlstate 'PT422' using message='review_invalid_input'; end if;
 if p_image is null then perform public.admin_review_save_candidate(p_id,p_revision,p_version,p_content,p_actor);
 else perform public.admin_review_save_candidate_image(p_id,p_revision,p_version,p_content,p_image,p_actor); end if;
 update machimoa_review.curation_candidates set general_viewing=p_viewing where id=p_id and general_viewing is distinct from p_viewing;
 if found then
   insert into machimoa_review.admin_review_events(source_item_id,candidate_id,revision_hash,action,actor,note,changed_fields)
   values(sid,p_id,p_revision,'save_candidate',p_actor,'일반 관람 일정 변경',array['general_viewing']);
 end if;
 return machimoa_review.admin_review_item('candidates',p_id);
end $$;

-- Reject explicit venue-wide admission restrictions, independently of any
-- reservation required by a separate class, tour or experience in the venue.
create function machimoa_review.admission_requires_booking(f jsonb) returns boolean
language sql immutable set search_path='' as $$
 select exists (
   select 1 from regexp_split_to_table(concat_ws(E'\n',f->>'description',f->>'conditions',f->>'application_methods'),
     '[\n.;!?"\[\]]+') evidence
   where trim(evidence, ' •※○-') ~ '(?x)
     ^ (입장 | 전시장[[:blank:]]*입장 | (일반|전시장)[[:blank:]]*관람)
       ([[:blank:]]*자체)? (은|는|도|에|에도|에는|시|을[[:blank:]]*위해|하려면)?
       [[:blank:]:：]* (반드시[[:blank:]]*)? (사전[[:blank:]]*)?예약
       ( 이[[:blank:]]*필요(합니다|하다|해요|함|$) | [[:blank:]]*필수(입니다|예요|다|$)
         | 자(만|에[[:blank:]]*한) | 제로 | 제(입니다|$) | 을[[:blank:]]*해야 )
     | ^ (사전[[:blank:]]*)?예약자(에[[:blank:]]*한해|만)[[:blank:]]*(전시장[[:blank:]]*)?입장
     | ^ (사전[[:blank:]]*)?예약[[:blank:]]*없이(는)?[[:blank:]]*입장(이|할[[:blank:]]*수)?[[:blank:]]*(불가|없)
   '
 );
$$;

-- Only endpoints from the reviewed source snapshot can become public.
create function machimoa_review.program_session(s text,f jsonb) returns jsonb
language plpgsql immutable set search_path='' as $$
declare a jsonb;b jsonb;p jsonb;op jsonb;lo jsonb;hi jsonb;m text[];day text;
 booking boolean:=false;walkin boolean:=false;body text;methods text;labelled boolean;
begin
 if f is null or f->>'delivery_mode' in ('online','course_unresolved') then return null; end if;
 body:=concat_ws(E'\n',f->>'description',f->>'session_evidence',f->>'conditions',f->>'source_status');
 if f->>'source_status' in ('reservation_closed','application_closed') or
   exists(select from jsonb_array_elements_text(case when jsonb_typeof(f->'source_status')='array' then f->'source_status' else '[]' end) as state
          where trim(state) ~ '^(매진|(접수|신청|예약|모집)[[:space:]]*(종료|마감))$') or
   regexp_replace(body,'(매진|마감|접수 종료|신청 종료)[[:space:]]*(시|될 수|전에|전까지|되지 않)[^.,;"\n]*','','g') ~ '(매진|잔여[[:space:]]*0석|(접수|신청|예약|모집)(이|가)?[[:space:]]*(종료|마감)(됨|되었습니다|됐습니다|입니다)|마감되었습니다)' then return null; end if;
 methods:=coalesce(f->>'application_methods','');
 if s='myseoul_program' then
   booking:=jsonb_typeof(f->'application_links')='array' and exists(select from jsonb_array_elements_text(f->'application_links') l where l ~ '^https?://[^[:space:]]+$')
     and methods ~ '(온라인|사전[[:space:]]*(신청|예약|접수)|신청[[:space:]]*(폼|링크|서)|구글[[:space:]]*폼|폼[[:space:]]*작성)'
     and methods !~ '(현장|당일)[[:space:]]*(신청|접수|참여|예약)(도|가|이)?[[:space:]]*가능|예약[[:space:]]*없이';
   for op in select jsonb_array_elements(f#>'{periods,operation}') loop
     if op->>'status' is distinct from 'ok' or jsonb_array_length(op->'endpoints') not between 1 and 2 then return null; end if;
     lo:=op#>'{endpoints,0}'; hi:=op->'endpoints'->-1;
     if (lo=hi and lo->>'precision'<>'day') or left(lo->>'value',10)<>left(hi->>'value',10)
       or (a is not null and (left(a->>'value',10)<>left(lo->>'value',10)
         or (lo->>'precision'<>'day' and a->>'precision'<>'day' and (lo<>a or hi<>b)))) then return null; end if;
     if a is null or lo->>'precision'<>'day' then a:=lo;b:=hi; end if;
   end loop;
 elsif s='seoul_reservation' then
   booking:=f->>'official_url' ~ '^https?://[^[:space:]]+$' and (f->'application_methods' ? 'internet')
       and not(f->'application_methods' ? 'onsite');
   p:=f->'periods';a:=p->'SVCOPNBGNDT';b:=p->'SVCOPNENDDT';
   if a->>'status' is distinct from 'ok' or b->>'status' is distinct from 'ok' then return null; end if;
   labelled:=coalesce(f->>'description','') ~ '(?:답사|회차|행사|교육|해설|운영)[[:blank:]]*일시[[:blank:]]*[:：]';
   -- A day's opening window covering multiple slots is not one bookable session.
   if body ~ '(?:[2-9]|[1-9][0-9]+)[[:blank:]]*회차|매[[:blank:]]*회차|상시[[:blank:]]*입장' and not labelled then return null; end if;
   -- Seoul supplies midnight default bounds even for a daytime session.
   -- Recover a time only from a specifically labelled session on that date.
   if labelled or left(a->>'value',10)<>left(b->>'value',10) or (a->>'value'=b->>'value' and a->>'precision'<>'day') then
     select regexp_matches(f->>'description','(?n)^[[:blank:]•-]*(?:답사|회차|행사|교육|해설|운영)[[:blank:]]*일시[[:blank:]]*[:：][[:blank:]]*(?:[\x27\x60]?(20[0-9]{2}|[0-9]{2})[.년-][[:blank:]]*)?([0-9]{1,2})[.월-][[:blank:]]*([0-9]{1,2})[.일]?[[:blank:]]*(?:\(([월화수목금토일])(?:요일)?\))?[,[:blank:]]*([0-9]{1,2})(?::([0-5][0-9]))?[[:blank:]]*[~～-][[:blank:]]*([0-9]{1,2})(?::([0-5][0-9]))?시?(?:[[:blank:]]*\([0-9]+분[[:blank:]]*(?:내외|소요)?\))?[.[:blank:]]*$','g') into strict m;
     if m[1] is null and left(a->>'value',4)<>left(b->>'value',4) then return null; end if;
     if length(m[1])=2 then m[1]:='20'||m[1]; end if;
     day:=coalesce(m[1],left(a->>'value',4))||'-'||lpad(m[2],2,'0')||'-'||lpad(m[3],2,'0');
     if day not between left(a->>'value',10) and left(b->>'value',10)
       or substr('일월화수목금토',extract(dow from day::date)::int+1,1)<>m[4] then return null; end if;
     if m[5]::int>23 or m[7]::int>23 or make_time(m[5]::int,coalesce(m[6],'0')::int,0) >= make_time(m[7]::int,coalesce(m[8],'0')::int,0) then return null; end if;
     a:=jsonb_build_object('precision','minute','value',day||'T'||lpad(m[5],2,'0')||':'||coalesce(m[6],'00')||':00+09:00');
     b:=jsonb_build_object('precision','minute','value',day||'T'||lpad(m[7],2,'0')||':'||coalesce(m[8],'00')||':00+09:00');
   end if;
 else return null;
 end if;
 -- A mixed exhibition/docent notice cannot borrow the exhibition's walk-in access.
 if not coalesce(booking,false) and methods ~ '(전화|이메일|메일)[[:space:]]*(신청|접수|예약)[^",]{0,20}(0[0-9]{1,2}-[0-9]{3,4}-[0-9]{4}|[[:alnum:]._%+-]+@[[:alnum:].-]+)' then
   booking:=true;
 end if;
 -- An onsite channel, a free ticket, and a cancellation-only seat are
 -- insufficient. Use explicit participation evidence scoped to this session.
 walkin:=not coalesce(booking,false) and not machimoa_review.admission_requires_booking(f)
   and (coalesce(f->'application_methods' ?| array['예약 불필요','예약 없이 현장 참여'],false)
        or exists (
          select 1 from regexp_split_to_table(f->>'description', E'\n') line
          where trim(line) ~ '^(해당[[:blank:]]*회차|본[[:blank:]]*프로그램)(는|은)[[:blank:]]*(사전[[:blank:]]*)?예약[[:blank:]]*없이[[:blank:]]*(현장[[:blank:]]*)?참여[[:blank:]]*(가능(합니다)?|할 수 있습니다)[.!]?$'
        ))
   and concat_ws(E'\n',methods,body) !~ '(취소석|잔여석|빈[[:blank:]]*자리|결원|잔여[[:blank:]]*좌석)[^.!?;"\n]{0,45}(현장|당일|있을|발생|한해|한하여)|(현장|당일)[^.!?;"\n]{0,35}(취소석|잔여석|결원|잔여[[:blank:]]*좌석)|사전[[:blank:]]*예약[[:blank:]]*필수';
 if a->>'value' is null or b->>'value' is null or not (coalesce(booking,false) or coalesce(walkin,false)) then return null; end if;
 a:=jsonb_build_object('value',a->>'value','precision',a->>'precision');
 b:=jsonb_build_object('value',b->>'value','precision',b->>'precision');
 if a->>'precision' is distinct from b->>'precision' or
    machimoa_review.content_filter_endpoint(a)>machimoa_review.content_filter_endpoint(b) then return null; end if;
 return jsonb_build_object('start',a,'end',b,'officialBooking',coalesce(booking,false));
exception when data_exception or no_data_found or too_many_rows or sqlstate 'PT422' then return null;
end $$;

-- Individual labelled sessions may share one booking page. Never explode a
-- continuous period into one supposed performance per day.
create function machimoa_review.program_sessions(s text,f jsonb) returns jsonb
language plpgsql immutable set search_path='' as $$
declare lines text[]; line text; common_conditions jsonb; result jsonb:='[]'; one jsonb; op jsonb;
begin
 if s='seoul_reservation' then
   select array_agg(l) into lines from regexp_split_to_table(f->>'description',E'\n') l
    where l ~ '^[[:blank:]•-]*(?:답사|회차|행사|교육|해설|운영)[[:blank:]]*일시[[:blank:]]*[:：]';
   if cardinality(lines)>1 then
     select coalesce(jsonb_agg(t),'[]') into common_conditions from (
       select regexp_split_to_table(f->>'description',E'\n') t
       union all select jsonb_array_elements_text(f->'conditions')
     ) notes where not (t=any(lines));
     for line in select unnest(lines) loop
       one:=machimoa_review.program_session(s,f||jsonb_build_object('description',line,'conditions',common_conditions));
       if one is not null and not result @> jsonb_build_array(one) then result:=result||jsonb_build_array(one); end if;
     end loop;
     return nullif(result,'[]');
   end if;
 elsif s='myseoul_program' and jsonb_typeof(f#>'{periods,operation}')='array' then
   if jsonb_array_length(f#>'{periods,operation}')>1 and not exists(
     select from jsonb_array_elements(f#>'{periods,operation}') p where coalesce(p->>'label','') !~ '[0-9]+[[:blank:]]*회차'
   ) then
     for op in select jsonb_array_elements(f#>'{periods,operation}') loop
       one:=machimoa_review.program_session(s,jsonb_set(f,'{periods,operation}',jsonb_build_array(op)));
       if one is not null and not result @> jsonb_build_array(one) then result:=result||jsonb_build_array(one); end if;
     end loop;
     return nullif(result,'[]');
   end if;
 end if;
 one:=machimoa_review.program_session(s,f);
 return case when one is not null then jsonb_build_array(one) end;
exception when data_exception then return null;
end $$;

create function machimoa_review.candidate_program_outing(cand machimoa_review.curation_candidates) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare f jsonb; s text:=machimoa_review.canonical_source_id(cand.source);
begin
 if cand.user_category='program' then
   select i.input_facts into f from machimoa_review.program_candidate_inputs i
     join machimoa_review.source_item_program_facts sf on sf.source_item_id=i.source_item_id and sf.revision_hash=i.revision_hash and sf.facts_version=i.facts_version
     where i.candidate_id=cand.id and i.revision_hash=cand.source_revision_hash;
   if not found then
     select cl.native_facts->'programFacts' into f from machimoa_review.review_classification_candidates c
       join machimoa_review.review_classification_claims cl using(job_id,claimed_at)
       join machimoa_review.source_item_program_facts sf on sf.source_item_id=c.source_item_id and sf.revision_hash=c.revision_hash
        and sf.facts=cl.native_facts->'programFacts'
       where c.candidate_id=cand.id and c.revision_hash=cand.source_revision_hash and cl.revision_hash=c.revision_hash;
   end if;
   if machimoa_review.admission_requires_booking(f) then return null; end if;
   return nullif(jsonb_strip_nulls(jsonb_build_object('sessions',machimoa_review.program_sessions(s,f),'viewing',cand.general_viewing)),'{}');
 end if;
 return null;
end $$;

create function machimoa_review.project_program_outing() returns trigger
language plpgsql security definer set search_path='' as $$
declare projected jsonb:=machimoa_review.candidate_program_outing(new);
begin
 update public.curations set program_outing=projected where id=new.published_curation_id and is_published
   and source_item_id=new.source_item_id and machimoa_review.canonical_source_id(source)=machimoa_review.canonical_source_id(new.source) and program_outing is distinct from projected;
 return new;
end $$;
create trigger project_weekly_program after insert or update of review_status,published_curation_id on machimoa_review.curation_candidates
 for each row when (new.review_status='published' and new.published_curation_id is not null)
 execute function machimoa_review.project_program_outing();

-- Existing published programs use the same version-fenced evidence, without a review action.
with eligible as materialized (
 select p.id,machimoa_review.candidate_program_outing(c) as outing from public.curations p
 join machimoa_review.curation_candidates c on c.published_curation_id=p.id and c.source_item_id=p.source_item_id
 where p.is_published and p.user_category='program' and c.review_status='published' and c.user_category='program'
 and machimoa_review.canonical_source_id(c.source)=machimoa_review.canonical_source_id(p.source)
)
update public.curations p set program_outing=e.outing from eligible e where p.id=e.id and e.outing is not null;

revoke all on function machimoa_review.candidate_program_outing(machimoa_review.curation_candidates),
 machimoa_review.pre_outing_admin_review_item(text,uuid),machimoa_review.admin_review_item(text,uuid),
 machimoa_review.admission_requires_booking(jsonb),machimoa_review.project_program_outing(),machimoa_review.program_sessions(text,jsonb),machimoa_review.program_session(text,jsonb),machimoa_review.valid_general_viewing(jsonb)
 from public,anon,authenticated,service_role;
revoke all on function public.admin_review_save_candidate_viewing(uuid,text,text,jsonb,uuid,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.admin_review_save_candidate_viewing(uuid,text,text,jsonb,uuid,jsonb,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
