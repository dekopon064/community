-- Optional public URL only. No binaries, source permissions, worker changes or backfill.
begin;

create function machimoa_review.safe_source_image_url(p_url pg_catalog.text)
returns pg_catalog.text
language sql immutable strict
set search_path = ''
as $function$
  select case when
    pg_catalog.char_length(pg_catalog.btrim(p_url)) <= 2048
    and pg_catalog.btrim(p_url) ~* '^https://(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::443)?(?:[/?][^\s\\#<>"'']*)?$'
    and pg_catalog.btrim(p_url) !~* '^https://[^/?]+\.(localhost|local|internal|invalid|test)(:443)?([/?]|$)'
    and pg_catalog.split_part(pg_catalog.btrim(p_url), '?', 1) !~* '\.svg($|/)'
    and p_url !~* '%0[ad]'
  then pg_catalog.btrim(p_url) else null end;
$function$;

alter table public.curations add column source_image_url pg_catalog.text;
alter table public.curations add constraint curations_source_image_url_ck check (
  source_image_url is null or (
    machimoa_review.safe_source_image_url(source_image_url) is not null
    and source_image_url = machimoa_review.safe_source_image_url(source_image_url)
  )
);

-- Publication already locks/validates the candidate and current source revision.
-- Project only the matching source URL AFTER that existing publication succeeds,
-- in the same transaction; do not replace shared publish/AI/worker functions.
create function machimoa_review.project_published_source_image()
returns trigger language plpgsql security definer
set search_path = ''
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
    and si.source_id in ('youthcenter_content', 'seoul_reservation');

  update public.curations c set source_image_url = v_url
  where c.id = new.published_curation_id and c.is_published
    and c.source = new.source and c.source_item_id = new.source_item_id;
  return new;
end;
$function$;

create trigger project_published_source_image
after insert or update of review_status, published_curation_id
on machimoa_review.curation_candidates
for each row when (new.review_status = 'published' and new.published_curation_id is not null)
execute function machimoa_review.project_published_source_image();

alter function machimoa_review.safe_source_image_url(pg_catalog.text) owner to postgres;
alter function machimoa_review.project_published_source_image() owner to postgres;
revoke all on function machimoa_review.safe_source_image_url(pg_catalog.text) from public, anon, authenticated;
revoke all on function machimoa_review.project_published_source_image() from public, anon, authenticated, service_role;
grant execute on function machimoa_review.safe_source_image_url(pg_catalog.text) to service_role;

notify pgrst, 'reload schema';
commit;
