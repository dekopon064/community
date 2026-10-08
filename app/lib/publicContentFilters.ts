import { districtChoices, eventTopics, filterDay, parseContentFilters, programTopics, provinceLabels } from './contentFilters';
import type { ContentFilters, FilterCategory, FilterEndpoint, FilterOccurrence } from './contentFilters';
import type { LocalizedCuration } from './types';

// Only published display data crosses the client boundary. No body, actor or source history.
export type PublicCurationItem = Pick<LocalizedCuration, 'id'|'slug'|'userCategory'|'title'|'summary'|'source_image_url'|'application_deadline_kind'|'application_deadline_on'|'event_start_on'|'event_end_on'|'created_at'|'contentFilters'>;
export function publicCurationItem(item: LocalizedCuration): PublicCurationItem {
  const { id, slug, userCategory, title, summary, source_image_url, application_deadline_kind, application_deadline_on, event_start_on, event_end_on, created_at, contentFilters } = item;
  return { id, slug, userCategory, title, summary, source_image_url, application_deadline_kind, application_deadline_on, event_start_on, event_end_on, created_at, contentFilters };
}
export type Province = keyof typeof provinceLabels;
export const deliveries = ['online', 'onsite', 'mixed'] as const;
export const audiences = ['children', 'other'] as const;
export const applicationStates = ['not_started', 'open', 'closed'] as const;
export const spaceKinds = ['introduction', 'news'] as const;
export type ApplicationState = typeof applicationStates[number] | 'unknown';
export type ExplorationQuery = {
  topics: string[]; provinces: Province[]; districts: string[];
  deliveries: string[]; audiences: string[]; states: string[]; spaceKinds: string[];
  date: string; sort: 'default'|'latest';
};
export const explorationKeys = ['topic','region','district','delivery','audience','status','space','date','sort'] as const;
export function supportsExploration(category?: string): category is FilterCategory {
  return category === 'program' || category === 'event' || category === 'youth_space';
}
function day(value: string | null | undefined): string | null {
  try { return filterDay(value); } catch { return null; }
}
function choices(params: URLSearchParams, key: string, allowed: readonly string[]) {
  return [...new Set(params.getAll(key).slice(0,100).filter(v => allowed.includes(v)))];
}
export function readExplorationQuery(params: URLSearchParams, category?: string): ExplorationQuery {
  // Space news keeps validated introduction-region selections in the URL.
  // matchesRegion ignores them for news; switching tabs can restore them after reload.
  const provinces = supportsExploration(category) ? choices(params,'region',Object.keys(provinceLabels)) as Province[] : [];
  const validDistricts = provinces.flatMap(p => districtChoices[p].map(d => `${p}:${d}`));
  return {
    topics: category === 'program' ? choices(params,'topic',Object.keys(programTopics)) : category === 'event' ? choices(params,'topic',Object.keys(eventTopics)) : [],
    provinces, districts: choices(params,'district',validDistricts),
    deliveries: category === 'program' ? choices(params,'delivery',deliveries) : [],
    audiences: category === 'program' ? choices(params,'audience',audiences) : [],
    states: category === 'program' ? choices(params,'status',applicationStates) : [],
    spaceKinds: category === 'youth_space' ? choices(params,'space',spaceKinds) : [],
    date: category === 'event' ? day(params.get('date')) ?? '' : '',
    sort: (category === 'program' || category === 'event') && params.get('sort') === 'latest' ? 'latest' : 'default',
  };
}
export function writeExplorationQuery(current: URLSearchParams, query: ExplorationQuery, category?: string): URLSearchParams {
  const next = new URLSearchParams(current);
  explorationKeys.forEach(k => next.delete(k));
  next.delete('page');
  const values: Record<string,string[]> = { topic:query.topics,region:query.provinces,district:query.districts,delivery:query.deliveries,audience:query.audiences,status:query.states,space:query.spaceKinds,date:query.date?[query.date]:[],sort:query.sort==='latest'?['latest']:[] };
  for (const [key,items] of Object.entries(values)) items.forEach(v => next.append(key,v));
  const valid = readExplorationQuery(next,category);
  for (const [key,items] of Object.entries({ topic:valid.topics,region:valid.provinces,district:valid.districts,delivery:valid.deliveries,audience:valid.audiences,status:valid.states,space:valid.spaceKinds,date:valid.date?[valid.date]:[],sort:valid.sort==='latest'?['latest']:[] })) {
    next.delete(key); items.forEach(v => next.append(key,v));
  }
  return next;
}
export function selectedConditionCount(q: ExplorationQuery) {
  return q.topics.length + q.provinces.length + q.districts.length + q.deliveries.length + q.audiences.length + q.states.length + q.spaceKinds.length + Number(Boolean(q.date));
}
function metadata(item: PublicCurationItem): ContentFilters | null {
  try {
    const data = parseContentFilters(item.contentFilters);
    return data.category === item.userCategory ? data : null;
  } catch { return null; }
}
const DAY = 86400000;
// Comparison boundaries only; the stored endpoint and precision are never changed.
export function endpointBoundary(endpoint: FilterEndpoint, end = false): number {
  return endpoint.precision === 'day'
    ? Date.parse(endpoint.value+'T00:00:00+09:00') + (end ? DAY : 0)
    : Date.parse(endpoint.value) + (end ? 1 : 0);
}
export type ProgramTiming = { state: ApplicationState; deadline: FilterEndpoint|null; deadlineKind: 'fixed'|'none'|'unknown'; group: number; order: number };
export function programTiming(item: PublicCurationItem, now: number): ProgramTiming {
  const data = metadata(item);
  let state: ApplicationState = 'unknown', deadline: FilterEndpoint|null = null, kind: ProgramTiming['deadlineKind'] = 'unknown';
  if (data) {
    if (data.application.status === 'known') {
      const app = data.application.value;
      kind = app.deadlineKind; deadline = app.end;
      const start = app.start ? endpointBoundary(app.start) : null;
      const end = deadline ? endpointBoundary(deadline,true) : null;
      if (app.sourceStatus === 'closed' || (end !== null && now >= end)) state = 'closed';
      else if (app.sourceStatus === 'open') state = start !== null && now < start ? 'unknown' : 'open';
      else if (app.sourceStatus === 'not_started') state = start !== null && now >= start ? 'open' : 'not_started';
    }
  } else {
    // Legacy public deadline fields are already published structured facts, not extracted text.
    const saved = day(item.application_deadline_on);
    if (item.application_deadline_kind === 'fixed' && saved) {
      kind = 'fixed'; deadline = {value:saved,precision:'day'};
      // A future deadline alone cannot distinguish open from not-yet-open.
      state = now >= endpointBoundary(deadline,true) ? 'closed' : 'unknown';
    } else if (item.application_deadline_kind === 'closed' && !item.application_deadline_on) state = 'closed';
    else if (item.application_deadline_kind === 'none' && !item.application_deadline_on) kind = 'none';
  }
  const end = deadline ? endpointBoundary(deadline,true) : null;
  return {state,deadline,deadlineKind:kind,group:state==='closed'?2:end!==null?0:1,order:end===null?Infinity:state==='closed'?-end:end};
}
function occurrences(item: PublicCurationItem): FilterOccurrence[] {
  const data = metadata(item);
  if (data) return data.schedule.status === 'known' ? data.schedule.value.occurrences : [];
  const start = day(item.event_start_on), end = day(item.event_end_on);
  return start && end && start<=end ? [{start:{value:start,precision:'day'},end:{value:end,precision:'day'}}] : [];
}
// Refresh at actual state transitions, without re-rendering date inputs every second.
export function nextExplorationTransition(items: readonly PublicCurationItem[], now: number): number | null {
  const boundaries: number[] = [];
  for (const item of items) {
    if (item.userCategory === 'program') {
      const data = metadata(item);
      if (data?.application.status === 'known' && data.application.value.start) boundaries.push(endpointBoundary(data.application.value.start));
      const deadline = programTiming(item,now).deadline;
      if (deadline) boundaries.push(endpointBoundary(deadline,true));
    } else if (item.userCategory === 'event') {
      for (const occurrence of occurrences(item)) boundaries.push(endpointBoundary(occurrence.start),endpointBoundary(occurrence.end,true));
    }
  }
  const next = Math.min(...boundaries.filter(boundary=>boundary>now));
  return Number.isFinite(next) ? next : null;
}
export type EventTiming = { state:'ongoing'|'upcoming'|'ended'|'unknown'; group:number; order:number; occurrence:FilterOccurrence|null };
export function eventTiming(item: PublicCurationItem, now: number): EventTiming {
  const all = occurrences(item);
  const active = all.filter(o => endpointBoundary(o.start)<=now && now<endpointBoundary(o.end,true));
  if (active.length) {
    const occurrence = [...active].sort((a,b)=>endpointBoundary(a.end,true)-endpointBoundary(b.end,true))[0];
    return {state:'ongoing',group:0,order:endpointBoundary(occurrence.end,true),occurrence};
  }
  const next = all.filter(o=>endpointBoundary(o.start)>now).sort((a,b)=>endpointBoundary(a.start)-endpointBoundary(b.start))[0];
  if (next) return {state:'upcoming',group:1,order:endpointBoundary(next.start),occurrence:next};
  const last = [...all].sort((a,b)=>endpointBoundary(b.end,true)-endpointBoundary(a.end,true))[0];
  return last ? {state:'ended',group:2,order:-endpointBoundary(last.end,true),occurrence:last} : {state:'unknown',group:3,order:Infinity,occurrence:null};
}
function matchesRegion(item: PublicCurationItem, data: ContentFilters|null, q: ExplorationQuery): boolean {
  if (!q.provinces.length) return true;
  if (!data) return false;
  if (item.userCategory === 'program' && data.delivery.status === 'known' && data.delivery.value === 'online') return true;
  if (item.userCategory === 'youth_space' && data.spaceKind.status === 'known' && data.spaceKind.value === 'news') return true;
  if (data.location.status !== 'known') return false;
  if (data.location.value.scope === 'nationwide') return true;
  return data.location.value.venues.some(v => {
    if (!q.provinces.includes(v.province)) return false;
    const sub = q.districts.filter(d => d.startsWith(v.province+':'));
    return !sub.length || (v.district!==null && sub.includes(`${v.province}:${v.district}`));
  });
}
export function matchesExploration(item: PublicCurationItem, q: ExplorationQuery, now: number): boolean {
  const data = metadata(item);
  if (q.topics.length && (!data || data.topic.status!=='known' || !q.topics.includes(data.topic.value))) return false;
  if (q.deliveries.length && (!data || data.delivery.status!=='known' || !q.deliveries.includes(data.delivery.value))) return false;
  if (q.audiences.length && (!data || data.audience.status!=='known' || !q.audiences.includes(data.audience.value))) return false;
  if (q.spaceKinds.length && (!data || data.spaceKind.status!=='known' || !q.spaceKinds.includes(data.spaceKind.value))) return false;
  if (q.states.length && !q.states.includes(programTiming(item,now).state)) return false;
  if (!matchesRegion(item,data,q)) return false;
  if (q.date) {
    const start=Date.parse(q.date+'T00:00:00+09:00'), end=start+DAY;
    if (!occurrences(item).some(o=>endpointBoundary(o.start)<end && endpointBoundary(o.end,true)>start)) return false;
  }
  return true;
}
function latest(a:PublicCurationItem,b:PublicCurationItem) {
  const ta=Date.parse(a.created_at),tb=Date.parse(b.created_at);
  const difference=(Number.isFinite(tb)?tb:0)-(Number.isFinite(ta)?ta:0);
  return difference || (a.id<b.id?-1:a.id>b.id?1:0);
}
export function exploreCurations(items: readonly PublicCurationItem[], category: FilterCategory, q: ExplorationQuery, now: number) {
  const seen=new Set<string>();
  const selected=items.filter(item=>{
    if(item.userCategory!==category || seen.has(item.id)) return false;
    seen.add(item.id);
    return matchesExploration(item,q,now);
  });
  return selected.sort((a,b)=>{
    if (q.sort==='latest' || category==='youth_space') return latest(a,b);
    const ta=category==='program'?programTiming(a,now):eventTiming(a,now),tb=category==='program'?programTiming(b,now):eventTiming(b,now);
    return ta.group-tb.group || (ta.order===tb.order?0:ta.order-tb.order) || latest(a,b);
  });
}
