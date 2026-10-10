import { emptyContentFilters, parseContentFilters, programApplicationComplete } from '../contentFilters';
import type { ContentFilters, FilterKey } from '../contentFilters';
import { ReviewFailure } from './contracts';
import type { Facts, Category } from './contracts';
import { validateFacts, validateContent } from './validation';
import type { CandidateContent } from './contracts';

export const classificationCategories = ['policy', 'program', 'event', 'youth_space', 'living'] as const;
export const classificationFields = (category: Category): FilterKey[] => category === 'program'
  ? ['topic', 'delivery', 'audience', 'location', 'application'] : category === 'event'
    ? ['topic', 'location', 'schedule'] : category === 'youth_space' ? ['spaceKind', 'location'] : [];
export type ClassificationDetail = {
  id: string; revision: string; version: string; classificationVersion: number; active: boolean;
  category: Category; facts: Facts; filters: ContentFilters | null; note: string;
  editable: boolean; ready: boolean; reasons: string[]; sourceReasons: string[];
  publication?: {version:string; category:Category; content:CandidateContent; applied:boolean} | null;
};
const comparable=(v:unknown):unknown=>Array.isArray(v)?v.map(comparable):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b)).map(([k,x])=>[k,comparable(x)])):v;
export function classificationMatches(item:ClassificationDetail,sent:ReturnType<typeof classificationCommand>){
  return item.revision===sent.revision&&item.classificationVersion===sent.classificationVersion+1&&item.note===sent.note
    && JSON.stringify(comparable(item.facts))===JSON.stringify(comparable(sent.facts))
    && JSON.stringify(comparable(item.filters))===JSON.stringify(comparable(sent.filters));
}
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new ReviewFailure('invalid_input');
  return v as Record<string, unknown>;
};
export function classificationDraft(current: Facts, category: Category): Facts {
  // Preserve the saved snapshot; date meanings must be confirmed independently.
  return { ...structuredClone(current), category,
    deadlineKind: ['policy','program'].includes(category) && ['policy','program'].includes(current.category) ? current.deadlineKind : '',
    deadlineOn: ['policy','program'].includes(category) && ['policy','program'].includes(current.category) ? current.deadlineOn : '',
    eventStart: category === 'event' && current.category === 'event' ? current.eventStart : '',
    eventEnd: category === 'event' && current.category === 'event' ? current.eventEnd : '' };
}
export function classificationFilters(category: Category, previous: ContentFilters | null): ContentFilters | null {
  if (!['program','event','youth_space'].includes(category)) return null;
  if (previous?.category === category) return structuredClone(previous);
  const next=emptyContentFilters(category as ContentFilters['category']);
  // Confirmed actual venues retain their meaning; schedules and category-specific
  // topics do not. Online/not-applicable is not an offline event venue.
  if(previous?.location.status==='known')next.location=structuredClone(previous.location);
  return next;
}
export function classificationPublicContent(raw:unknown):CandidateContent {
  const o=object(raw),limits={titleKo:300,titleJa:300,summaryKo:1000,summaryJa:1000,contentKo:200000,contentJa:200000};
  if(Object.keys(o).sort().join(',')!==Object.keys(limits).sort().join(','))throw new ReviewFailure('unavailable');
  return Object.fromEntries(Object.entries(limits).map(([k,max])=>{const v=o[k]??'';if(typeof v!=='string'||v.length>max)throw new ReviewFailure('unavailable');return[k,v];})) as CandidateContent;
}
export function classificationApplyCommand(raw:unknown) {
  const o=object(raw);
  if(Object.keys(o).sort().join(',')!=='action,bodyReviewed,classificationVersion,content,note,publicationVersion,revision,version'||o.action!=='apply_public'||o.bodyReviewed!==true||!hash(o.revision)||!hash(o.version)||!hash(o.publicationVersion)||!Number.isSafeInteger(o.classificationVersion)||Number(o.classificationVersion)<1||typeof o.note!=='string'||o.note.trim().length<10||o.note.length>4000)throw new ReviewFailure('invalid_input');
  return {action:'apply_public' as const,bodyReviewed:true as const,revision:o.revision,version:o.version,publicationVersion:o.publicationVersion,classificationVersion:Number(o.classificationVersion),content:validateContent(o.content),note:o.note.trim()};
}
export function classificationFilterFacts(current: Facts, filters: ContentFilters): Facts {
  // One explicit filter edit supplies both representations of the same fact.
  // Participant eligibility is independent of venue and never inferred here.
  const next = { ...current };
  if (current.category === 'program') {
    next.delivery = filters.delivery.status === 'known' ? ({online:'online',onsite:'offline',mixed:'hybrid'} as const)[filters.delivery.value] : 'unknown';
    if (filters.application.status === 'known') {
      next.deadlineKind = filters.application.value.sourceStatus === 'closed' && filters.application.value.deadlineKind === 'none' ? 'closed' : filters.application.value.deadlineKind;
      next.deadlineOn = next.deadlineKind === 'fixed' ? filters.application.value.end?.value.slice(0,10) ?? '' : '';
    } else { next.deadlineKind = ''; next.deadlineOn = ''; }
  }
  if (current.category === 'event') {
    const dates = filters.schedule.status === 'known' ? filters.schedule.value.occurrences : [];
    next.eventStart = dates.map(x=>x.start.value.slice(0,10)).sort()[0] ?? '';
    next.eventEnd = dates.map(x=>x.end.value.slice(0,10)).sort().at(-1) ?? '';
  }
  return next;
}
export function classificationMissing(f: Facts, filters: ContentFilters | null): string[] {
  const missing: string[] = [];
  if (!classificationCategories.includes(f.category as typeof classificationCategories[number])) missing.push('category');
  if (!f.productType) missing.push('productType');
  if (f.delivery === 'unknown') missing.push('delivery');
  if (f.productType !== 'living_guide') {
    if (f.scope === 'unknown' || f.scope === 'specific' && !f.regions.length) missing.push('scope');
    if (!f.evidence.trim()) missing.push('evidence');
  }
  if (f.productType === 'policy_reference' && f.foreignEligibility === 'unknown') missing.push('foreignEligibility');
  if (['policy','program'].includes(f.category) && !f.deadlineKind) missing.push('deadlineKind');
  if (f.category === 'program' && f.deadlineKind !== 'fixed') missing.push('deadlineKind');
  if (f.category === 'event' && (!f.eventStart || !f.eventEnd)) missing.push('eventStart','eventEnd');
  if (classificationFields(f.category).length) {
    if (!filters || filters.category !== f.category) missing.push('filters');
    // Province-only locations and optional times need no fabricated detail.
    else missing.push(...classificationFields(f.category).filter(k=>{
      if(filters[k].status==='unknown')return true;
      if(k==='application'&&!programApplicationComplete(filters))return true;
      const candidate={...emptyContentFilters(filters.category),[k]:filters[k]};
      if(k==='location'){candidate.delivery=filters.delivery;candidate.spaceKind=filters.spaceKind;}
      if(k==='delivery'&&filters.delivery.status==='known'&&filters.delivery.value==='online'||k==='spaceKind'&&filters.spaceKind.status==='known'&&filters.spaceKind.value==='news')candidate.location={status:'not_applicable',value:null};
      try{parseContentFilters(candidate);return false;}catch{return true;}
    }).map(k => 'filter:' + k));
  } else if (filters !== null) missing.push('filters');
  return [...new Set(missing)];
}
export function classificationCommand(raw: unknown) {
  const o = object(raw);
  if (Object.keys(o).sort().join(',') !== 'classificationVersion,facts,filters,note,revision,version'
    || !hash(o.revision) || !hash(o.version) || !Number.isSafeInteger(o.classificationVersion) || Number(o.classificationVersion) < 0
    || typeof o.note !== 'string' || o.note.trim().length < 10 || o.note.length > 4000) throw new ReviewFailure('invalid_input');
  const facts = validateFacts(o.facts);
  let filters: ContentFilters | null;
  try { filters = o.filters === null ? null : parseContentFilters(o.filters); } catch { throw new ReviewFailure('invalid_input'); }
  const missing = classificationMissing(facts, filters);
  if (missing.length) throw new ReviewFailure('invalid_input', Object.fromEntries(missing.map(k => [k,'새 분류에 필요한 값과 원문 근거를 확인해 주세요.'])));
  return { revision:o.revision, version:o.version, classificationVersion:Number(o.classificationVersion), facts, filters, note:o.note.trim() };
}
export function classificationDetail(raw: unknown, id: string): ClassificationDetail {
  try {
    const o = object(raw);
    if (o.id !== id || !hash(o.revision) || !hash(o.version) || !Number.isSafeInteger(o.classificationVersion)
      || Number(o.classificationVersion) < 0 || typeof o.active !== 'boolean' || typeof o.editable !== 'boolean' || typeof o.ready !== 'boolean'
      || typeof o.note !== 'string' || !Array.isArray(o.reasons) || !Array.isArray(o.sourceReasons)
      || [...o.reasons,...o.sourceReasons].some(v => typeof v !== 'string')) throw Error();
    const facts = validateFacts(o.facts), filters = o.filters === null ? null : parseContentFilters(o.filters);
    if (o.category !== facts.category || filters && filters.category !== facts.category || o.active && Number(o.classificationVersion) < 1) throw Error();
    let publication:ClassificationDetail['publication'];
    if(o.publication!=null){const p=object(o.publication);if(!hash(p.version)||!classificationCategories.includes(p.category as typeof classificationCategories[number])||typeof p.applied!=='boolean')throw Error();publication={version:p.version,category:p.category as Category,content:classificationPublicContent(p.content),applied:p.applied};}
    return { id, revision:o.revision, version:o.version, classificationVersion:Number(o.classificationVersion), active:o.active,
      category:facts.category, facts, filters, note:o.note, editable:o.editable, ready:o.ready, reasons:o.reasons as string[], sourceReasons:o.sourceReasons as string[],...(publication?{publication}:{}) };
  } catch { throw new ReviewFailure('unavailable'); }
}
