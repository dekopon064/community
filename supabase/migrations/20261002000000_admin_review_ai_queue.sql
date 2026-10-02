-- Read-only administrator projection. No refresh, lease recovery or worker calls.
begin;
create function public.admin_review_ai_queue(p_offset integer default 0,p_limit integer default 25,p_watch uuid[] default '{}')
returns jsonb language plpgsql stable security definer set search_path='' as $fn$
declare result jsonb;
begin
 if p_offset is null or p_offset not between 0 and 100000 or p_limit is null or p_limit not between 1 and 25
 or p_watch is null or cardinality(p_watch)>100 or array_position(p_watch,null) is not null then
 raise sqlstate 'PT422' using message='review_invalid_input';end if;
 with projected as (
 select j.id as job_id,j.queued_at,
 jsonb_build_object(
 'jobId',j.id,'sourceItemId',s.id,'revision',j.revision_hash,
 'currentRevision',s.revision_hash=j.revision_hash,'status',j.status,
 'sourceName',s.source_id,'title',left(coalesce(s.min_fields->>'title',s.normalized_payload->>'plcyNm',s.normalized_payload->>'pstTtl','제목 확인 필요'),500),
 'completedAt',j.completed_at,'retryCount',j.retry_count,'nextRetryAt',j.next_retry_at,
 'leaseState',case when j.status<>'claimed' then 'none' when j.claim_lease_until is null then 'unknown'
 when j.claim_lease_until<=statement_timestamp() then 'expired' else 'active' end,
 'errorCode',case when j.error_code in ('ai_or_enqueue_failed','ai_blocked_cost_cap','ai_cost_bound_breach',
 'ai_refusal','ai_schema_error','ai_timeout','ai_network','ai_http_400','ai_http_401','ai_http_403','ai_http_404',
 'ai_http_429','ai_http_4xx','ai_http_5xx','ai_unexpected_thinking','ai_call_budget','ai_sampling_forbidden')
 then j.error_code else null end,
 'resultState',case when j.status<>'completed' then null
 when s.revision_hash<>j.revision_hash then 'source_changed'
 when c.id is null then 'missing'
 when c.review_status<>'pending' then 'processed'
 when exists(select 1 from machimoa_review.processing_jobs r where r.source_item_id=s.id and r.revision_hash=s.revision_hash
 and r.processing_stage<>'ai_enrichment' and r.status in ('queued','claimed')) then 'input_changed'
 when s.source_id='seoul_reservation' and (m.candidate_id is null or f.source_item_id is null or m.facts_version<>f.facts_version) then 'input_changed'
 when s.source_id<>'seoul_reservation' and exists(select 1 from machimoa_review.admin_review_events e
 where e.source_item_id=s.id and e.revision_hash=j.revision_hash and e.action='save_facts' and e.occurred_at>c.created_at) then 'input_changed'
 when c.ai_status_ko is distinct from 'success' or c.ai_status_ja is distinct from 'success'
 or exists(select 1 from unnest(array[c.title_ko,c.summary_ko,c.content_ko,c.title_ja,c.summary_ja,c.content_ja]) v
 where coalesce(v,'') !~ '[^[:space:]   -   　﻿]') then 'unavailable'
 else 'ready' end) as entry
 from machimoa_review.processing_jobs j join machimoa_review.source_items s on s.id=j.source_item_id
 left join lateral (select ca.* from machimoa_review.curation_candidates ca
 where machimoa_review.canonical_source_id(ca.source)=s.source_id and ca.source_item_id=s.external_key
 and ca.source_revision_hash=j.revision_hash order by ca.created_at desc,ca.id desc limit 1) c on true
 left join machimoa_review.program_candidate_inputs m on m.candidate_id=c.id
 left join machimoa_review.source_item_program_facts f on f.source_item_id=s.id and f.revision_hash=j.revision_hash
 where j.processing_stage='ai_enrichment' and s.source_id in ('youthcenter_policy','youthcenter_content','seoul_reservation')
 and (j.id=any(p_watch) or s.revision_hash=j.revision_hash and j.status in ('queued','claimed','failed'))
 ), page as (select * from projected where entry->>'currentRevision'='true' and entry->>'status' in ('queued','claimed','failed')
 order by queued_at,job_id offset p_offset limit p_limit+1),
 visible as (select * from page order by queued_at,job_id limit p_limit)
 select jsonb_build_object('checkedAt',statement_timestamp(),
 'items',coalesce((select jsonb_agg(entry order by queued_at,job_id) from visible),'[]'::jsonb),
 'hasMore',(select count(*)>p_limit from page),
 'observed',coalesce((select jsonb_agg(coalesce(p.entry,jsonb_build_object('jobId',w.id,'status','missing')) order by w.id)
 from (select distinct unnest(p_watch) id) w left join projected p on p.job_id=w.id),'[]'::jsonb)) into result;
 return result;
end $fn$;
alter function public.admin_review_ai_queue(integer,integer,uuid[]) owner to postgres;
revoke all on function public.admin_review_ai_queue(integer,integer,uuid[]) from public,anon,authenticated,service_role;
grant execute on function public.admin_review_ai_queue(integer,integer,uuid[]) to service_role;
commit;
