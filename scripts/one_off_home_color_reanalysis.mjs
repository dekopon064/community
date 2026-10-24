// Explicit, operator-reviewed one-off. No credentials, CLI execution, scheduler,
// network transport or auth bypass: callers supply approved SQL/image dependencies.
import {createHash, randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
export const policy='area40-192-v1';
const table='machimoa_review.home_color_area40_once';
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const hash=/^[0-9a-f]{64}$/;
const quote=x=>x==null?'null':"'"+String(x).replaceAll("'","''")+"'";
const digest=x=>createHash('sha256').update(x).digest('hex');
export async function analyzerHash(){return digest(await readFile(new URL('../app/lib/home-colors/analysis.ts',import.meta.url)));}
const sha=expr=>`encode(sha256(convert_to((${expr})::text,'UTF8')),'hex')`;
const checks=`c.is_published and x.review_status='published' and x.published_curation_id=c.id
 and (select count(*) from machimoa_review.curation_candidates a where a.published_curation_id=c.id and a.review_status='published')=1
 and x.source=c.source and x.source_item_id=c.source_item_id and h.candidate_id=x.id
 and h.source_revision=x.source_revision_hash and h.image_url is not distinct from c.source_image_url
 and h.state in ('completed','failed') and c.source_image_url is not null`;
const manual=`exists(select 1 from machimoa_review.home_card_color_choices o where o.curation_id=c.id)`;
const fields=`c.id,x.id candidate_id,x.source_revision_hash revision,c.source_image_url image_url,
 ${sha('to_jsonb(c)')} public_hash,${sha('to_jsonb(x)')} candidate_hash,${sha('to_jsonb(h)')} analysis_hash,
 case when c.source=x.source and c.source_item_id=x.source_item_id then machimoa_review.home_color_detail(x.id)->>'version' end version`;
export function planSql(limit=100){
 if(!Number.isInteger(limit)||limit<1||limit>500)throw Error('invalid_limit');
 return `select ${fields},case when ${manual} then 'manual'
 when r.curation_id is not null then 'already_attempted'
 when (select count(*) from machimoa_review.curation_candidates a where a.published_curation_id=c.id and a.review_status='published')<>1
 or not coalesce((${checks}),false) then 'ineligible' else 'eligible' end eligibility
 from public.curations c
 left join lateral(select a.* from machimoa_review.curation_candidates a where a.published_curation_id=c.id and a.review_status='published' order by a.id limit 1) x on true
 left join machimoa_review.home_card_colors h on h.curation_id=c.id
 left join ${table} r on r.curation_id=c.id
 where c.is_published
 order by c.id limit ${limit+1};`;
}
function validate(p){
 if(!p||!uuid.test(p.id)||!uuid.test(p.candidate_id)||!hash.test(p.revision)
 ||!['public_hash','candidate_hash','analysis_hash','version'].every(k=>hash.test(p[k]))
 ||typeof p.image_url!=='string'||p.image_url.length>4096)throw Error('invalid_plan');
}
// Separate lock statement followed by a fresh READ COMMITTED snapshot: manual
// choices committed while waiting for the candidate lock must be visible.
function locked(p,body){return `begin isolation level read committed;set local lock_timeout='5s';set local statement_timeout='15s';
 do $lock$ begin
 if current_user<>'postgres' then raise exception 'operator_role_required'; end if;
 perform 1 from machimoa_review.curation_candidates where id=${quote(p.candidate_id)}::uuid for update;
 perform 1 from public.curations where id=${quote(p.id)}::uuid for update;
 perform 1 from machimoa_review.home_card_colors where curation_id=${quote(p.id)}::uuid for share;
 end $lock$;
 ${body}
 commit;`;}
export function reserveSql(p,actor,request,codeHash){
 validate(p);if(!uuid.test(actor)||!uuid.test(request)||!hash.test(codeHash))throw Error('invalid_actor_request');
 return locked(p,`with inserted as (
 insert into ${table}(curation_id,candidate_id,source_revision,image_url,public_hash,candidate_hash,analysis_hash,
 expected_version,request_id,actor,analyzer_hash)
 select c.id,x.id,x.source_revision_hash,c.source_image_url,${quote(p.public_hash)},${quote(p.candidate_hash)},${quote(p.analysis_hash)},
 ${quote(p.version)},${quote(request)}::uuid,${quote(actor)}::uuid,${quote(codeHash)}
 from public.curations c join machimoa_review.curation_candidates x on x.id=${quote(p.candidate_id)}::uuid
 join machimoa_review.home_card_colors h on h.curation_id=c.id
 where c.id=${quote(p.id)}::uuid and c.source_image_url=${quote(p.image_url)} and ${checks} and not ${manual}
 and ${sha('to_jsonb(c)')}=${quote(p.public_hash)} and ${sha('to_jsonb(x)')}=${quote(p.candidate_hash)}
 and ${sha('to_jsonb(h)')}=${quote(p.analysis_hash)}
 and machimoa_review.home_color_detail(x.id)->>'version'=${quote(p.version)}
 on conflict do nothing returning *)
 select jsonb_build_object('status',case when exists(select 1 from inserted) then 'reserved'
 when exists(select 1 from ${table} where curation_id=${quote(p.id)}::uuid) then 'already_attempted' else 'changed' end) result;`);
}
export function finishSql(p,actor,request,result){
 validate(p);if(!uuid.test(actor)||!uuid.test(request)||!result||!['completed','failed'].includes(result.state)
 ||!['default','orange','yellow','green','blue','purple','red'].includes(result.tone)
 ||!(result.state==='completed'?result.reason==='matched'&&result.tone!=='default'||result.reason==='ambiguous'&&result.tone==='default':result.reason==='analysis_failed'&&result.tone==='default'))throw Error('invalid_result');
 return locked(p,`with current as (
 select r.*,case when exists(select 1 from machimoa_review.home_card_color_choices o where o.curation_id=r.curation_id) then 'skipped_manual'
 when r.expires_at<=clock_timestamp() then 'expired'
 when not coalesce((${checks}),false) or ${sha('to_jsonb(c)')}<>r.public_hash
 or ${sha('to_jsonb(x)')}<>r.candidate_hash or ${sha('to_jsonb(h)')}<>r.analysis_hash then 'skipped_changed'
 else ${quote(result.state)} end final_state
 from ${table} r left join public.curations c on c.id=r.curation_id
 left join machimoa_review.curation_candidates x on x.id=r.candidate_id
 left join machimoa_review.home_card_colors h on h.curation_id=r.curation_id
 where r.curation_id=${quote(p.id)}::uuid and r.candidate_id=${quote(p.candidate_id)}::uuid
 and r.source_revision=${quote(p.revision)} and r.image_url=${quote(p.image_url)} and r.request_id=${quote(request)}::uuid and r.actor=${quote(actor)}::uuid
 and r.public_hash=${quote(p.public_hash)} and r.candidate_hash=${quote(p.candidate_hash)} and r.analysis_hash=${quote(p.analysis_hash)}
 and r.expected_version=${quote(p.version)} and r.state='processing' for update of r
 ), updated as (
 update ${table} r set state=a.final_state,tone=case when a.final_state='completed' then ${quote(result.tone)} else 'default' end,
 reason=case when a.final_state='completed' then ${quote(result.reason)} when a.final_state='failed' then 'analysis_failed' else null end,
 finished_at=clock_timestamp() from current a where r.curation_id=a.curation_id returning r.state,r.tone)
 select jsonb_build_object('status',coalesce((select state from updated),'unconfirmed'),'tone',(select tone from updated)) result;`);
}
export async function runReanalysis({rows,limit=100,actor,execute=false,sql,loadImage,analyze,codeHash,confirmedCodeHash}){
 if(!Number.isInteger(limit)||limit<1||limit>500||!Array.isArray(rows)||rows.length>limit
 ||new Set(rows.map(p=>p.id)).size!==rows.length)throw Error('scope_changed');
 if(!execute)return rows.map(({id,eligibility})=>({id,status:eligibility}));
 if(!uuid.test(actor)||typeof sql!=='function'||typeof loadImage!=='function'||typeof analyze!=='function'
 ||!hash.test(codeHash)||codeHash!==confirmedCodeHash||codeHash!==await analyzerHash())throw Error('execution_not_confirmed');
 const out=[];
 for(const p of rows){
  if(p.eligibility!=='eligible'){out.push({id:p.id,status:p.eligibility});continue;}
  const request=randomUUID();let reserved;
  try{reserved=await sql(reserveSql(p,actor,request,codeHash));}catch{throw Object.assign(Error('reserve_unknown_stop'),{results:out});}
  if(!['reserved','already_attempted','changed'].includes(reserved?.status))throw Object.assign(Error('reserve_unknown_stop'),{results:out});
  if(reserved.status!=='reserved'){out.push({id:p.id,status:reserved.status});continue;}
  let result;
  try{const value=await analyze(await loadImage(p.image_url));result={...value,state:'completed'};}
  catch{result={tone:'default',reason:'analysis_failed',state:'failed'};}
  let finished;
  try{finished=await sql(finishSql(p,actor,request,result));}catch{throw Object.assign(Error('finish_unknown_stop'),{results:out});}
  if(!['completed','failed','skipped_manual','skipped_changed','expired'].includes(finished?.status))throw Object.assign(Error('finish_unknown_stop'),{results:out});
  out.push({id:p.id,...finished});
 }
 return out;
}
