import { districtChoices, provinceLabels, parseContentFilters } from '../contentFilters';
import type { ContentFilters } from '../contentFilters';
import { ReviewFailure } from './contracts';
import { sourceLink, quoteLink, sourceRegionConflict } from './location-evidence';
export { meetingPlaces } from './location-evidence';

// Research never grants write authority. Imported proposals are operator input;
// the server re-reads both review and filter preconditions before every save.
export const locationResearchSchema = 'location-research-v1' as const;
export const locationBatchLimit = 25;
// Optional local diagnostic; public save API still uses invalid_input only.
export class LocationValidationFailure extends ReviewFailure {
  constructor(readonly reason:string){super('invalid_input');}
}
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
      const [sourceLinked,sourceRole]=sourceLink(snapshot.title,snapshot.description,place);
      const checks:[boolean,string][]=[
        [Object.hasOwn(districtChoices,province)&&Boolean(districtChoices[province]?.includes(district)),'proposal_region_invalid'],
        [sourceLinked,sourceRole==='meeting_multiple'?'proposal_meeting_mismatch':sourceRole==='meeting_not_explicit'?'proposal_meeting_not_explicit':'proposal_place_not_in_description'],
        [!sourceRegionConflict(snapshot.description,place,provinceLabels[province],district),'proposal_source_region_conflict'],
        [quoteLink(place,excerpt,provinceLabels[province],district),'proposal_place_not_in_quote'],
        [excerpt.includes(district),'proposal_district_not_in_quote'],
        [excerpt.includes(provinceLabels[province]),'proposal_province_not_in_quote'],
      ];
      for(const [ok,reason] of checks)if(!ok)throw new LocationValidationFailure(reason);
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
