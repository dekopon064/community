begin;
set local lock_timeout = '5s';

CREATE OR REPLACE FUNCTION machimoa_review.content_filter_after_facts(p_id uuid, p_revision text)
 RETURNS void
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare f machimoa_review.source_item_content_filters%rowtype;b jsonb;d jsonb;k text;fields text[]:='{}';cat text;confirmed jsonb;derived_origins jsonb:='{}';
begin
 select * into f from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found then
 perform machimoa_review.content_filter_register_pending(p_id,p_revision);
 select * into f from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision for update;
 if not found then return;end if;end if;b:=machimoa_review.content_filter_binding(p_id,p_revision);d:=f.data;cat:=b->>'category';
 if cat is distinct from d->>'category' then
 if cat not in ('program','event','youth_space') or cat is null then return;end if;
 d:=jsonb_build_object('schema','content-filters-v1','category',cat);
 for k in select unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) loop
 d:=d||jsonb_build_object(k,jsonb_build_object('status',case when (cat='program' and k in ('spaceKind','schedule')) or (cat='event' and k in ('delivery','audience','spaceKind','application')) or (cat='youth_space' and k in ('topic','delivery','audience','application','schedule')) then 'not_applicable' else 'unknown' end,'value',null));end loop;fields:=array['category'];
 else
 for k in select key from jsonb_each(b-'category') loop
   if b->k is distinct from f.source_binding->k and d->k->>'status'<>'not_applicable' then
     -- The topic binding is [purpose, content_kind, description]. Confirming that the
     -- same Seoul reservation is a program does not change the evidence for its topic.
     if k='topic' and cat='program' and f.source_binding->>'category'='program'
        and d#>>'{topic,status}'='known'
        and f.source_binding#>>'{topic,1}'='unknown' and b#>>'{topic,1}'='program'
        and b#>'{topic,0}' is not distinct from f.source_binding#>'{topic,0}'
        and b#>'{topic,2}' is not distinct from f.source_binding#>'{topic,2}'
        and exists (select 1 from machimoa_review.source_items
                    where id=p_id and source_id='seoul_reservation')
     then
       continue;
     end if;
     d:=jsonb_set(d,array[k],jsonb_build_object('status','unknown','value',null));
     fields:=array_append(fields,k);
   end if;
 end loop;
 -- A changed delivery mode requires a fresh location decision without inventing it.
 if 'delivery'=any(fields) and d->'location'->>'status'='not_applicable' then d:=jsonb_set(d,array['location'],jsonb_build_object('status','unknown','value',null));fields:=array_append(fields,'location');end if;
 end if;
 if d->>'category'='program' then
 confirmed:=machimoa_review.content_filter_fact_values(p_id,p_revision);
 for k in select jsonb_object_keys(confirmed) loop
 if d->k->>'status'='unknown' then -- Preserve a separately confirmed start while the authoritative deadline is unchanged.
 if k='application' and (select source_id from machimoa_review.source_items where id=p_id) in ('youthcenter_content','youthcenter_policy') and f.data->'application'->>'status'='known' and confirmed->k->'start'='null'::jsonb and confirmed->k->'end'=f.data->k->'value'->'end' then confirmed:=jsonb_set(confirmed,array[k,'start'],f.data->k->'value'->'start');end if;
 d:=jsonb_set(d,array[k],jsonb_build_object('status','known','value',confirmed->k));derived_origins:=derived_origins||jsonb_build_object(k,'confirmed_facts');end if;end loop;
 if d->'delivery'->>'value'='online' then d:=jsonb_set(d,array['location'],jsonb_build_object('status','not_applicable','value',null));end if;end if;
 if b is distinct from f.source_binding then
 update machimoa_review.source_item_content_filters set data=d,source_binding=b,origins=origins||coalesce((select jsonb_object_agg(field_key,'source_change') from unnest(array['topic','location','delivery','audience','spaceKind','application','schedule']) field_key where field_key=any(fields) or 'category'=any(fields)),'{}'::jsonb)||derived_origins,filter_version=filter_version+1,updated_at=clock_timestamp() where source_item_id=p_id and revision_hash=p_revision;
 insert into machimoa_review.content_filter_edits(source_item_id,revision_hash,filter_version,origin,fields,before_data,after_data)
 select p_id,p_revision,filter_version,'source_change',fields,f.data,d from machimoa_review.source_item_content_filters where source_item_id=p_id and revision_hash=p_revision;end if;
 perform machimoa_review.content_filter_review_sync(p_id,p_revision);
end $function$
;

commit;
