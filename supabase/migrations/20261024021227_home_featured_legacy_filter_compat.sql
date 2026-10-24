-- Match parseContentFilters' existing optional foreignerProgram compatibility.
-- Current stored facts, publication state, pins and all history remain untouched.
begin;
set local lock_timeout='5s';set local statement_timeout='30s';
do $guard$
declare p record;begin
 select * into p from pg_proc where oid=to_regprocedure('machimoa_review.home_featured_eligible(public.curations,timestamptz)');
 if p.oid is null then raise exception 'home_featured_legacy_prerequisite_changed';end if;
 if current_user<>'postgres' or pg_get_userbyid(p.proowner)<>'postgres' or p.prosecdef
  or p.proconfig is distinct from array['search_path=""']::text[] or p.proacl::text is distinct from '{postgres=X/postgres}'
  or encode(sha256(convert_to(btrim(replace(replace(p.prosrc,E'\r\n',E'\n'),E'\r',E'\n'),E' \t\n'),'UTF8')),'hex')<>'5af2e6b36a839b519541a8ffa9cc419251394261cc3fa1ee894eaca0396b7497' then
  raise exception 'home_featured_legacy_prerequisite_changed';end if;
end $guard$;
create or replace function machimoa_review.home_featured_eligible(c public.curations,p_now timestamptz) returns boolean
language plpgsql stable set search_path='' as $fn$
declare d jsonb; a jsonb; o jsonb; valid boolean:=false; starts timestamptz; ends timestamptz;
begin
 if not coalesce(c.is_published,false) or p_now is null or
  btrim(coalesce(c.title_ko,''))='' or btrim(coalesce(c.summary_ko,''))='' or btrim(coalesce(c.content_ko,''))='' or
  btrim(coalesce(c.title_ja,''))='' or btrim(coalesce(c.summary_ja,''))='' or btrim(coalesce(c.content_ja,''))='' then return false;end if;
 d:=c.content_filters;
 begin
  if jsonb_typeof(d)='object' then
   perform machimoa_review.content_filter_validate(d);
   valid:=d->>'category'=c.user_category;
  end if;
 exception when sqlstate 'PT422' then valid:=false;
 end;
 if c.user_category='program' then
  if not coalesce(valid,false) or d#>>'{application,status}'<>'known' then return false;end if;
  a:=d#>'{application,value}';
  if a->>'sourceStatus'='closed' then return false;end if;
  starts:=case when a->'start'<>'null'::jsonb then machimoa_review.content_filter_endpoint(a->'start') end;
  ends:=case when a->'end'<>'null'::jsonb then machimoa_review.content_filter_endpoint(a->'end')+
    case when a#>>'{end,precision}'='day' then interval '1 day' else interval '0.001 second' end end;
  if ends is not null and p_now>=ends then return false;end if;
  return coalesce((a->>'sourceStatus'='open' and (starts is null or p_now>=starts))
    or (a->>'sourceStatus'='not_started' and starts is not null and p_now>=starts),false);
 elsif c.user_category='event' then
  if coalesce(valid,false) then
   if d#>>'{schedule,status}'<>'known' then return false;end if;
   for o in select value from jsonb_array_elements(d#>'{schedule,value,occurrences}') loop
    ends:=machimoa_review.content_filter_endpoint(o->'end')+
      case when o#>>'{end,precision}'='day' then interval '1 day' else interval '0.001 second' end;
    if p_now<ends then return true;end if;
   end loop;
   return false;
  end if;
  begin
   starts:=machimoa_review.content_filter_day(c.event_start_on::text)::timestamp at time zone 'Asia/Seoul';
   ends:=machimoa_review.content_filter_day(c.event_end_on::text)::timestamp at time zone 'Asia/Seoul';
   return starts<=ends and p_now<ends+interval '1 day';
  exception when sqlstate 'PT422' then return false;end;
 end if;
 return false;
end $fn$;
notify pgrst,'reload schema';
commit;
