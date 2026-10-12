begin;
set local lock_timeout='5s'; set local statement_timeout='30s';
-- No observation, classification, history or job backfill. An explicit review
-- save uses the existing transaction to re-evaluate and queue a candidate job.
do $$ declare p record; begin
 if current_user<>'postgres' then raise exception 'postgres_required';end if;
 select * into p from pg_proc where oid=to_regprocedure('machimoa_review.classification_reasons(uuid,jsonb)');
 if p.oid is null or encode(sha256(convert_to(replace(replace(pg_get_functiondef(p.oid),E'\r\n',E'\n'),E'\r',E'\n'),'UTF8')),'hex')<>'229ae5efba2f0319c295f50542c581af5840b3b1b1cb99993e6c61c7b51b23e7'
 or pg_get_userbyid(p.proowner)<>'postgres' or p.proacl::text is distinct from '{postgres=X/postgres}'
 or p.proconfig is distinct from array['search_path=""']::text[] or p.prosecdef
 or to_regprocedure('machimoa_review.classification_reasons_before_seoul_event_status(uuid,jsonb)') is not null
 then raise exception 'seoul_event_status_predecessor_changed';end if;
 execute replace(pg_get_functiondef(p.oid),'FUNCTION machimoa_review.classification_reasons(',
 'FUNCTION machimoa_review.classification_reasons_before_seoul_event_status(');
end $$;
revoke all on function machimoa_review.classification_reasons_before_seoul_event_status(uuid,jsonb) from public,anon,authenticated,service_role;

create or replace function machimoa_review.classification_reasons(p_id uuid,f jsonb) returns text[]
language plpgsql stable set search_path='' as $$
declare codes text[]; s machimoa_review.source_items%rowtype; pf machimoa_review.source_item_program_facts%rowtype;
 raw_status text; notice boolean; schedule jsonb; endpoint jsonb; latest_end timestamptz; day_only boolean; bound timestamptz;
begin
 codes:=machimoa_review.classification_reasons_before_seoul_event_status(p_id,f);
 select * into s from machimoa_review.source_items where id=p_id;
 -- Current reviewed category, never the source's original program category.
 if s.source_id is distinct from 'seoul_reservation' or f->>'category' is distinct from 'event'
 or f->>'productType' is distinct from 'event_program' then return codes;end if;
 select * into pf from machimoa_review.source_item_program_facts where source_item_id=p_id and revision_hash=s.revision_hash;
 raw_status:=btrim(s.normalized_payload->'provider_fields'->>'SVCSTATNM');
 -- 안내중 is a known informational status, not an assertion of open booking.
 -- Other unknown values remain reviewable; no status or fact is rewritten.
 notice:=raw_status='안내중' and pf.facts->>'source_status'='unknown'
 and not (pf.facts->'conflicts' ? 'source_status_conflict');
 if coalesce(notice,false) then codes:=array_remove(codes,'source_status_unknown');end if;
 if raw_status in ('취소','서비스취소','운영취소','행사취소','접수취소') then codes:=array_append(codes,'event_cancelled');end if;
 if raw_status in ('종료','서비스종료','운영종료','행사종료') then codes:=array_append(codes,'event_ended');end if;
 if pf.facts->>'source_status' in ('reservation_closed','application_closed')
 or raw_status in ('예약마감','접수종료') then codes:=array_append(codes,'not_currently_accepting');end if;
 -- Dates come from the saved current event classification. A date-only end
 -- includes the whole Korean calendar day, without inventing a midnight time.
 if f->>'eventEnd' ~ '^\d{4}-\d{2}-\d{2}$' and
 (statement_timestamp() at time zone 'Asia/Seoul')::date>(f->>'eventEnd')::date
 then codes:=array_append(codes,'event_ended');end if;
 select filters->'schedule' into schedule from machimoa_review.review_classifications
 where source_item_id=p_id and revision_hash=s.revision_hash and facts->>'category'='event';
 if schedule->>'status'='known' then
 for endpoint in select x->'end' from jsonb_array_elements(schedule->'value'->'occurrences') x loop
 day_only:=endpoint->>'precision'='day';
 bound:=case when day_only then ((endpoint->>'value')::date+1)::timestamp at time zone 'Asia/Seoul'
 else (endpoint->>'value')::timestamptz end;
 if latest_end is null or bound>latest_end then latest_end:=bound;end if;
 end loop;
 if latest_end is not null and statement_timestamp()>=latest_end then codes:=array_append(codes,'event_ended');end if;
 end if;
 return array(select distinct c from unnest(codes) c);
end $$;
revoke all on function machimoa_review.classification_reasons(uuid,jsonb) from public,anon,authenticated,service_role;
commit;
