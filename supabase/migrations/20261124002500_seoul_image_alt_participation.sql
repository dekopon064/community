begin;
set local lock_timeout = '5s';

-- Apply only to a future observation with extracted detail-image evidence.
-- Editing the description invalidates the link to the observation's proof.
create function machimoa_review.seoul_program_source_participation(
  filters jsonb, facts jsonb, source jsonb, actor_confirmed boolean
) returns boolean language plpgsql immutable set search_path = '' as $$
declare evidence jsonb := source->'image_alt_evidence';
begin
  if evidence->>'source' = 'DTLCONT.img.alt'
     and facts->>'description' = source->>'program_text' then
    if evidence->'recruitment' = 'true'::jsonb or evidence->'group_only' = 'true'::jsonb then
      return false;
    end if;
    if not actor_confirmed and evidence->'used_for_description' = 'true'::jsonb then
      if evidence->'audience_booking' is distinct from 'true'::jsonb then return false; end if;
      -- Explicit spectator booking can support a cultural program; broad age tags alone cannot.
      if filters #>> '{topic,value}' is distinct from 'culture_experience' then return false; end if;
      actor_confirmed := true;
    end if;
  end if;
  return machimoa_review.seoul_personal_program(filters,facts,source->>'title',actor_confirmed);
end $$;
revoke all on function machimoa_review.seoul_program_source_participation(jsonb,jsonb,jsonb,boolean)
  from public,anon,authenticated,service_role;

create or replace function machimoa_review.content_filter_review_sync(p_id uuid,p_revision text)
returns void language plpgsql set search_path = '' as $$
declare
  s machimoa_review.source_items%rowtype;
  pf machimoa_review.source_item_program_facts%rowtype;
  cf machimoa_review.source_item_content_filters%rowtype;
  supported boolean;
begin
  perform machimoa_review.before_seoul_purpose_filter_review_sync(p_id,p_revision);
  select * into s from machimoa_review.source_items
    where id=p_id and revision_hash=p_revision and source_id='seoul_reservation';
  if not found then return; end if;
  select * into pf from machimoa_review.source_item_program_facts
    where source_item_id=p_id and revision_hash=p_revision;
  if not found or pf.manual_excluded or (not pf.purpose_from_filters and pf.facts->>'content_kind'<>'unknown')
     or exists(select 1 from machimoa_review.admin_review_events where source_item_id=p_id
       and revision_hash=p_revision and changed_fields && array['content_kind','resolved:program_purpose_unconfirmed'])
     or exists(select 1 from machimoa_review.review_classifications where source_item_id=p_id and revision_hash=p_revision)
     or machimoa_review.admin_trash_pending(p_id,p_revision) or machimoa_review.ai_recheck_pending(p_id,p_revision)
     or exists(select 1 from machimoa_review.processing_jobs where source_item_id=p_id
       and (status='claimed' or (revision_hash=p_revision and processing_stage='ai_enrichment' and status in ('failed','completed'))))
     or exists(select 1 from machimoa_review.curation_candidates where
       machimoa_review.canonical_source_id(source)=s.source_id and source_item_id=s.external_key) then return; end if;
  select * into cf from machimoa_review.source_item_content_filters
    where source_item_id=p_id and revision_hash=p_revision;
  if not found or cf.source_binding->>'category' is distinct from 'program'
     or cf.source_binding is distinct from machimoa_review.content_filter_binding(p_id,p_revision) then return; end if;
  supported := machimoa_review.seoul_program_source_participation(cf.data,pf.facts,s.normalized_payload,
    exists(select 1 from machimoa_review.admin_review_events where source_item_id=p_id
      and revision_hash=p_revision and 'application_actor'=any(changed_fields)));
  if supported = pf.purpose_from_filters then return; end if;

  update machimoa_review.source_item_program_facts set
    facts=jsonb_set(facts,'{content_kind}',to_jsonb(case when supported then 'program'::text else 'unknown' end)),
    purpose_from_filters=supported, facts_version=facts_version+1, updated_at=clock_timestamp()
    where source_item_id=p_id and revision_hash=p_revision;
  -- The changed purpose is part of the topic binding. Its input topic is still valid.
  update machimoa_review.source_item_content_filters set source_binding=machimoa_review.content_filter_binding(p_id,p_revision)
    where source_item_id=p_id and revision_hash=p_revision;
  perform machimoa_review.program_refresh(p_id);
end $$;
commit;
