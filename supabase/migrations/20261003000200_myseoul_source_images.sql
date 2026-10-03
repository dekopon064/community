-- URL-only My Seoul+ projection. Existing publication trigger/ACL/worker unchanged.
begin;
do $guard$
begin
 if (select pg_catalog.replace(p.prosrc, pg_catalog.chr(13), '') from pg_catalog.pg_proc p where p.oid = 'machimoa_review.project_published_source_image()'::pg_catalog.regprocedure)
    is distinct from pg_catalog.replace($expected$
declare v_url pg_catalog.text;
begin
  select machimoa_review.safe_source_image_url(
    coalesce(si.normalized_payload ->> 'source_image_url',
      case when si.source_id = 'seoul_reservation'
        then si.normalized_payload #>> '{provider_fields,IMGURL}' end)
  ) into v_url
  from machimoa_review.source_items si
  join machimoa_review.ingest_sources s on s.source_id = si.source_id
  where s.legacy_curation_source = new.source
    and si.external_key = new.source_item_id
    and si.revision_hash = new.source_revision_hash
    and si.source_id in ('youthcenter_content', 'seoul_reservation');

  update public.curations c set source_image_url = v_url
  where c.id = new.published_curation_id and c.is_published
    and c.source = new.source and c.source_item_id = new.source_item_id;
  return new;
end;
$expected$, pg_catalog.chr(13), '') then
  raise exception 'source_image_projection_definition_changed';
 end if;
end;
$guard$;
create or replace function machimoa_review.project_published_source_image()
returns trigger language plpgsql security definer set search_path = ''
as $function$
declare v_url pg_catalog.text;
begin
  select machimoa_review.safe_source_image_url(
    coalesce(si.normalized_payload ->> 'source_image_url',
      case when si.source_id = 'seoul_reservation'
        then si.normalized_payload #>> '{provider_fields,IMGURL}' end)
  ) into v_url
  from machimoa_review.source_items si
  join machimoa_review.ingest_sources s on s.source_id = si.source_id
  where s.legacy_curation_source = new.source
    and si.external_key = new.source_item_id
    and si.revision_hash = new.source_revision_hash
    and si.source_id in ('youthcenter_content', 'seoul_reservation', 'myseoul_program');

  update public.curations c set source_image_url = v_url
  where c.id = new.published_curation_id and c.is_published
    and c.source = new.source and c.source_item_id = new.source_item_id;
  return new;
end;
$function$;
-- My explicit published edits/change confirmations also update these candidate
-- projection fields. Clear stale/removed URLs atomically in that same transaction.
-- Existing youth/Seoul trigger and shared publish/worker functions are untouched.
create trigger project_myseoul_updated_source_image
after update of title_ko, title_ja, summary_ko, summary_ja, content_ko, content_ja,
 user_category, application_deadline_kind, application_deadline_on, event_start_on, event_end_on
on machimoa_review.curation_candidates
for each row when (new.source = 'myseoul_program' and new.review_status = 'published'
 and new.published_curation_id is not null)
execute function machimoa_review.project_published_source_image();
notify pgrst, 'reload schema';
commit;
