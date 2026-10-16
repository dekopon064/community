import { districtChoices, provinceLabels, parseContentFilters } from '../contentFilters';
import type { ContentFilters } from '../contentFilters';
import { ReviewFailure } from './contracts';

// Research never grants write authority. Imported proposals are operator input;
// the server re-reads both review and filter preconditions before every save.
export const locationResearchSchema = 'location-research-v1' as const;
export const locationBatchLimit = 25;
export type LocationSnapshot = {
  id: string; source: string; title: string; description: string;
  revision: string; version: string; factsToken: string; factsVersion: number; filterVersion: number;
};
export type LocationEvidence = { place: string; url: string; excerpt: string; province: keyof typeof provinceLabels; district: string };
export type LocationProposal = {
  snapshot: LocationSnapshot; status: 'suggested' | 'no_evidence' | 'ambiguous' | 'error';
  evidence: LocationEvidence | null;
};
export type LocationReport = { schema: typeof locationResearchSchema; batchId: string; createdAt: string; mode:'research'|'synthetic'; items: LocationProposal[] };
export const locationId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new ReviewFailure('invalid_input');
  return v as Record<string, unknown>;
};
function exact(o: Record<string, unknown>, keys: string[]) {
  if (Object.keys(o).sort().join() !== [...keys].sort().join()) throw new ReviewFailure('invalid_input');
}
function text(v: unknown, max: number) {
  if (typeof v !== 'string' || !v.trim() || v.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v)) throw new ReviewFailure('invalid_input');
  return v;
}
export function locationIds(v: unknown): string[] {
  if (!Array.isArray(v) || !v.length || v.length > locationBatchLimit || v.some(id => !locationId(id)) || new Set(v).size !== v.length) throw new ReviewFailure('invalid_input');
  return v;
}
export function locationSnapshot(v: unknown): LocationSnapshot {
  const o = object(v);
  exact(o, ['id','source','title','description','revision','version','factsToken','factsVersion','filterVersion']);
  if (!locationId(o.id) || !hash(o.revision) || !hash(o.version) || !hash(o.factsToken) ||
      !Number.isSafeInteger(o.factsVersion) || Number(o.factsVersion) < 1 || !Number.isSafeInteger(o.filterVersion) || Number(o.filterVersion) < 1) throw new ReviewFailure('invalid_input');
  return { id:o.id, source:text(o.source,80), title:text(o.title,500), description:text(o.description,60000),
    revision:o.revision, version:o.version, factsToken:o.factsToken, factsVersion:Number(o.factsVersion), filterVersion:Number(o.filterVersion) };
}
export function officialLocationUrl(v: unknown): string {
  const raw = text(v,2048);
  let u: URL; try { u = new URL(raw); } catch { throw new ReviewFailure('invalid_input'); }
  // Government hosts are an initial supported authority set, not proof that
  // arbitrary text on that host verifies a venue. Matching evidence is required.
  if (u.protocol !== 'https:' || u.username || u.password || u.port || !/^[a-z0-9.-]+\.go\.kr$/.test(u.hostname) ||
      /(?:token|secret|api[_-]?key|authorization|password|code)=/i.test(u.search) || raw.includes('\\')) throw new ReviewFailure('invalid_input');
  return raw;
}
const compact = (s: string) => s.normalize('NFKC').replace(/[\s·ㆍ,()[\]「」『』]/g,'');
export function meetingPlaces(description:string):string[] {
  return [...description.matchAll(/(?:^|\n)[^\p{L}\p{N}\n]*(?:만나는\s*(?:장소|곳)|모이는\s*(?:장소|곳)|집결\s*(?:장소|지))\s*(?:\*{1,2}|__)?\s*[:：]\s*(?:\*{1,2}|__)?([^\n]+)/gu)]
    .map(m=>m[1].trim()).filter(Boolean);
}
export function locationReport(v: unknown): LocationReport {
  const o = object(v); exact(o,['schema','batchId','createdAt','mode','items']);
  if (o.schema !== locationResearchSchema || !['research','synthetic'].includes(String(o.mode)) || !locationId(o.batchId) || typeof o.createdAt !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{3})?Z$/.test(o.createdAt) || !Number.isFinite(Date.parse(o.createdAt)) || !Array.isArray(o.items)) throw new ReviewFailure('invalid_input');
  const items = o.items.map(raw => {
    const row=object(raw); exact(row,['snapshot','status','evidence']);
    const snapshot=locationSnapshot(row.snapshot);
    if (!['suggested','no_evidence','ambiguous','error'].includes(String(row.status))) throw new ReviewFailure('invalid_input');
    let evidence: LocationEvidence | null = null;
    if (row.status === 'suggested') {
      const e=object(row.evidence);exact(e,['place','url','excerpt','province','district']);
      const province=e.province as keyof typeof provinceLabels, district=text(e.district,40), place=text(e.place,200), excerpt=text(e.excerpt,1500);
      const meetings=meetingPlaces(snapshot.description);
      const hasMeetingMention=/(?:만나는\s*(?:장소|곳)|모이는\s*(?:장소|곳)|집결\s*(?:장소|지))/.test(snapshot.description);
      const sourceLines=snapshot.description.split('\n').filter(line=>compact(line).includes(compact(place)));
      if (!Object.hasOwn(districtChoices,province) || !districtChoices[province].includes(district) || !compact(snapshot.description).includes(compact(place)) ||
          !compact(excerpt).includes(compact(place)) || !excerpt.includes(district) || !excerpt.includes(provinceLabels[province]) ||
          (hasMeetingMention&&!meetings.length) ||
          (meetings.length>0&&(new Set(meetings.map(compact)).size!==1||!compact(meetings[0]).includes(compact(place)))) ||
          (!meetings.length&&sourceLines.length>0&&sourceLines.every(line=>/(?:기관\s*주소|문의처|주차장\s*(?:주소|위치)|오시는\s*길)\s*[:：]/.test(line)))) throw new ReviewFailure('invalid_input');
      evidence={place,url:officialLocationUrl(e.url),excerpt,province,district};
    } else if (row.evidence !== null) throw new ReviewFailure('invalid_input');
    return {snapshot,status:row.status as LocationProposal['status'],evidence};
  });
  locationIds(items.map(x=>x.snapshot.id));
  return {schema:locationResearchSchema,batchId:o.batchId,createdAt:o.createdAt,mode:o.mode as LocationReport['mode'],items};
}
export function proposedLocation(e: LocationEvidence): ContentFilters['location'] {
  // Do not invent a street address from a district-level match.
  return {status:'known',value:{scope:'specific',venues:[{province:e.province,district:e.district,facility:e.place,address:''}]}};
}
export function locationData(data: ContentFilters, e: LocationEvidence): ContentFilters {
  return parseContentFilters({...data,location:proposedLocation(e)});
}
