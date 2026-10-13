// SQL source/guard inspection only. Does not instantiate a DB or execute SQL.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const file=n=>readFileSync(new URL('../supabase/migrations/'+n,import.meta.url),'utf8').replaceAll('\r','');
const previous=file('20261003000300_myseoul_candidate_images.sql');
const next=file('20261013003454_seoul_candidate_images.sql');
const source=previous.match(/create or replace function machimoa_review\.project_published_source_image\(\)[\s\S]*?as \$fn\$([\s\S]*?)\$fn\$/)[1];
const expected=next.match(/\$expected\$([\s\S]*?)\$expected\$/)[1];
assert.equal(expected,source); // exact existing projection guard, not a made-up hash
const installation=next.slice(0,next.indexOf('create function public.admin_review_save_candidate_image')).replace(/\$expected\$[\s\S]*?\$expected\$/g,'');
assert(!/\b(update|delete\s+from|insert\s+into)\s+(public\.curations|machimoa_review\.source_items)\b/i.test(installation));
assert(next.includes("machimoa_review.admin_review_lock('candidates',p_id,p_revision,p_version,p_actor)"));
assert(next.includes("machimoa_review.admin_review_candidate_action('save_candidate',p_id,p_revision,p_version,p_content,null,p_actor)"));
assert(next.includes("c.review_status<>'pending'")&&next.includes('c.published_curation_id is not null'));
assert(next.includes('si.revision_hash=c.source_revision_hash')&&next.includes('s.legacy_curation_source=c.source'));
assert(next.includes("c.source not in ('myseoul_program','seoul_reservation')"));
assert(next.includes("'save_candidate',p_actor")&&next.includes("array['image_selection_mode','image_override_url']"));
assert(next.includes('revoke all on function public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) from public,anon,authenticated'));
assert(next.includes('grant execute on function public.admin_review_save_candidate_image(uuid,text,text,jsonb,jsonb,uuid) to service_role'));
assert(!/create or replace function public\.admin_myseoul_save_candidate_image/i.test(next));
assert(!/alter table .*add column/m.test(next));
assert(next.trim().endsWith('commit;'));
console.log('Seoul image migration: 13 source/guard inspections passed; SQL runtime not executed.');
