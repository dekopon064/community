import { filterKeys, parseContentFilters, contentFilterSchema, programApplicationComplete } from '../contentFilters';
import type { ContentFilters, FilterKey } from '../contentFilters';
import { ReviewFailure } from './contracts';
import type { RpcClient } from './database-store';
export type FilterInfo = { schema: typeof contentFilterSchema; revision: string; filterVersion: number; data: ContentFilters; missing: FilterKey[]; origins: Partial<Record<FilterKey,'automatic'|'operator'|'source_change'|'confirmed_facts'>> };
export type CandidateFilterInfo = { schema: typeof contentFilterSchema; inputVersion: number; approvedVersion: number; currentVersion: number; inputRevision:string; approvedRevision:string; currentRevision:string; input: ContentFilters; approved: ContentFilters; current: ContentFilters; changed: boolean; canPublish: boolean };
export type FilterDetail = FilterInfo & { id: string; version: string; editable: boolean };
function obj(v: unknown): Record<string,unknown> { if(!v || typeof v!=='object' || Array.isArray(v)) throw new ReviewFailure('unavailable');return v as Record<string,unknown>; }
function version(v: unknown): number {if(!Number.isSafeInteger(v) || Number(v)<1) throw new ReviewFailure('unavailable');return Number(v);}
function hash(v: unknown): string {if(typeof v!=='string' || !/^[a-f0-9]{64}$/.test(v)) throw new ReviewFailure('unavailable');return v;}
export function filterInfo(v: unknown, revision: string): FilterInfo | undefined {
  if(v===undefined || v===null) return undefined;
  try {
    const o=obj(v), origins=obj(o.origins);
    if(o.schema!==contentFilterSchema || hash(o.revision)!==revision || !Array.isArray(o.missing) || o.missing.some(k=>!filterKeys.includes(k)) || new Set(o.missing).size!==o.missing.length || Object.keys(origins).some(k=>!filterKeys.includes(k as FilterKey)) || Object.values(origins).some(x=>!['automatic','operator','source_change','confirmed_facts'].includes(String(x)))) throw Error();
    return {schema:contentFilterSchema,revision,filterVersion:version(o.filterVersion),data:parseContentFilters(o.data),missing:o.missing as FilterKey[],origins:origins as FilterInfo['origins']};
  } catch {throw new ReviewFailure('unavailable');}
}
export function candidateFilterInfo(v: unknown): CandidateFilterInfo | undefined {
  if(v===undefined || v===null) return undefined;
  try {
    const o=obj(v), inputVersion=version(o.inputVersion),approvedVersion=version(o.approvedVersion),currentVersion=version(o.currentVersion),inputRevision=hash(o.inputRevision),approvedRevision=hash(o.approvedRevision),currentRevision=hash(o.currentRevision);
    if(o.schema!==contentFilterSchema || typeof o.changed!=='boolean' || typeof o.canPublish!=='boolean' || o.changed!==(approvedVersion!==currentVersion || approvedRevision!==currentRevision) || (o.changed && o.canPublish)) throw Error();
    return {schema:contentFilterSchema,inputVersion,approvedVersion,currentVersion,inputRevision,approvedRevision,currentRevision,input:parseContentFilters(o.input),approved:parseContentFilters(o.approved),current:parseContentFilters(o.current),changed:o.changed,canPublish:o.canPublish};
  } catch {throw new ReviewFailure('unavailable');}
}
export function filterDetail(v: unknown,id: string): FilterDetail {
  const o=obj(v), info=filterInfo(v,hash(o.revision));
  if(o.id!==id || !info || typeof o.editable!=='boolean') throw new ReviewFailure('unavailable');
  return {...info,id,version:hash(o.version),editable:o.editable};
}
export function filterCommand(raw: unknown) {
  try {
    const o=obj(raw);
    if(Object.keys(o).sort().join(',')!=='data,fields,filterVersion,revision,version' || !Array.isArray(o.fields) || !o.fields.length || o.fields.some(k=>!filterKeys.includes(k)) || new Set(o.fields).size!==o.fields.length) throw Error();
    const data=parseContentFilters(o.data);
    if(o.fields.includes('application')&&!programApplicationComplete(data)) throw Error();
    return {revision:hash(o.revision),version:hash(o.version),filterVersion:version(o.filterVersion),fields:o.fields as FilterKey[],data};
  } catch {throw new ReviewFailure('invalid_input',{filters:'분류·지역·날짜의 선택값과 형식을 확인해 주세요.'});}
}
export class ContentFilterStore {
  private client: RpcClient;
  constructor(client: RpcClient) { this.client = client; }
  private async invoke(name: string,args: Record<string,unknown>) {
    try {
      const {data,error}=await this.client.rpc(name,args);
      if(error) {
        if(error.code==='PT409') throw new ReviewFailure('conflict');
        if(error.code==='PT404') throw new ReviewFailure('not_found');
        if(error.code==='PT422' && ['invalid_content_filters','content_filter_category_changed','content_filter_facts_mismatch'].includes(error.message??'')) throw new ReviewFailure('invalid_input',{filters:'기존 사실과 분류·지역·날짜의 선택값을 확인해 주세요.'});
        throw new ReviewFailure('unavailable');
      }
      if(data==null) throw new ReviewFailure('unavailable');return data;
    } catch(e) {if(e instanceof ReviewFailure) throw e;throw new ReviewFailure('unavailable');}
  }
  async get(id: string) {return filterDetail(await this.invoke('admin_content_filter_detail',{p_id:id}),id);}
  async save(id: string,c: ReturnType<typeof filterCommand>,actor: string) {
    const patch=Object.fromEntries(c.fields.map(k=>[k,c.data[k]]));
    return filterDetail(await this.invoke('admin_content_filter_save',{p_id:id,p_revision:c.revision,p_version:c.version,p_filter_version:c.filterVersion,p_patch:patch,p_actor:actor}),id);
  }
}
