begin;
set local lock_timeout = '5s';

-- Track ownership per revision so withdrawing a topic only withdraws our own inference.
alter table machimoa_review.source_item_program_facts
  add column purpose_from_filters boolean not null default false;

create function machimoa_review.seoul_personal_program(
  filters jsonb, facts jsonb, title text, actor_confirmed boolean
) returns boolean language plpgsql immutable set search_path = '' as $$
declare
  body text := coalesce(facts->>'description', '');
  target text := coalesce(facts->>'target_raw', '');
  material text := concat_ws(E'\n', title, body, target);
  topic text := filters #>> '{topic,value}';
begin
  if filters->>'category' is distinct from 'program'
     or filters #>> '{topic,status}' is distinct from 'known'
     or topic is null or facts->>'application_actor' not in ('individual','individual_or_group')
     or facts->>'application_actor' is null
     or facts->'conflicts' ?| array['application_actor_conflict','target_conflict']
     or facts->'missing' ?| array['attachment_dependent','program_description_missing']
     or btrim(body) = '' then return false; end if;

  -- Broad provider audience tags may accompany a grant, hiring notice or group-only booking.
  if material ~ '(보조금|지원금|융자|대출|사업주|채용|취업[[:space:]]*(지원|훈련|목적)|직업훈련|기관[[:space:]]*운영지원)'
     or material ~ '(기관|단체|학교|법인|사업자|여행사)[[:space:]]*(신청|예약|접수|참여|담당자)?[[:space:]]*(만|전용|한정)'
     or material ~ '개인[[:space:]]*(신청|예약|참여|접수)[[:space:]]*(은|는|이|가)?[[:space:]]*(불가|불가능|제외|금지|할 수 없)'
     or material ~ '(개인|누구나)[^[:cntrl:].]{0,20}(신청|예약|참가|참여)[^[:cntrl:].]{0,8}가능[[:space:]]*(여부|하지|한지|한 지|할지)'
     or material ~ '(기관|단체|법인|학교)[[:space:]]*(으로|로|에)[[:space:]]*한정'
     or material ~ '(신청|참여|예약)[[:space:]]*(대상|자격)[[:space:]]*[:：][[:space:]]*(문화)?(기관|단체|학교|법인|사업자)([[:space:]]*($|[[:cntrl:]])|에 한)'
     or body ~ '(프로그램|활동|체험|교육|행사)[[:space:]]*(내용|여부)?[[:space:]]*[:：]?[[:space:]]*(미정|불명확|확인 필요)' then
    return false;
  end if;
  -- A career topic can itself indicate the separate employment purpose.
  if topic = 'employment_career' then return false; end if;
  if topic = 'other' and
     body !~ '(참가자|참여자|수강생)[[:space:]]*모집|교육[[:space:]]*참가|수업[[:space:]]*참여' then return false; end if;

  return actor_confirmed
     or body ~ '(개인(과|[[:space:]]*[/·,]|[[:space:]]+및)[[:space:]]*단체[[:space:]]*(모두)?|개인|누구나)[[:space:]]*(신청|참여|예약|참가)[[:space:]]*((이|가)?[[:space:]]*가능|할[[:space:]]*수[[:space:]]*있)'
     or body ~ '(대상|대상[[:space:]]*[&·및]+[[:space:]]*인원)[[:space:]]*[:：][[:space:]]*(성인|시민|어린이|청소년|가족|초등학생)[[:space:]]*누구나'
     or (target ~ '^(성인|어린이|청소년|초등학생|청년|가족)([[:space:]]*[,·/][[:space:]]*(성인|어린이|청소년|초등학생|청년|가족))*$'
         and body ~ '참가자[[:space:]]*모집|선착순[[:space:]]*(예약|접수|신청)|1인당|회차당[[:space:]]*(최대[[:space:]]*)?[0-9]+명')
     or (body ~ '예약자[[:space:]]*안내' and body ~ '(신청 시|예약취소|예약 취소)'
         and body ~ '(출발|운영 당일)[^\n]{0,40}집결'
         and body ~ '(초등학생|어린이|청소년|성인|만[[:space:]]*[0-9]+세)[^\n]{0,30}(참여|참가)');
end $$;

-- Observation, authenticated filter edits and fact re-evaluation already converge here
-- with the source row locked. Keep the existing queue and permission contracts.
alter function machimoa_review.content_filter_review_sync(uuid,text)
  rename to before_seoul_purpose_filter_review_sync;
create function machimoa_review.content_filter_review_sync(p_id uuid,p_revision text)
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
  supported := machimoa_review.seoul_personal_program(cf.data,pf.facts,s.normalized_payload->>'title',
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
revoke all on function machimoa_review.seoul_personal_program(jsonb,jsonb,text,boolean),
  machimoa_review.content_filter_review_sync(uuid,text),
  machimoa_review.before_seoul_purpose_filter_review_sync(uuid,text) from public,anon,authenticated,service_role;
commit;
