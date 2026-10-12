import type {Period} from './program-contract';
import { ReviewFailure } from './contracts';
import type { RpcClient } from './database-store';
import { databaseItem } from './database-dto';
import { programItem } from './program-store';
import { myseoulItem } from './myseoul-store';
import { programLabels, displayProgramValue, displayProgramDate, periodLabels } from './program-ui';
import { myseoulLabels, displayMySeoulValue } from './myseoul-ui';
import { jobUuid } from './ai-queue';
import {filterValueLabel} from './filter-display';
import {filterKeys,filterLabels} from '../contentFilters';
import {factLabels,factValue} from './facts-guidance';
import type {FilterInfo} from './content-filter-store';
import {classificationDetail} from './classification';
import { sourceLink } from './presentation';
import {quickReasons} from './trash';
import type {QuickReason} from './trash';

export type AiReview = {
 jobId:string; sourceItemId:string; sourceName:string; title:string; revision:string; version:string;
 status:string; canRecheck:boolean; canExclude:boolean; recheckPending:boolean; note:string;
 source:{url:string|null;body:string}; values:{label:string;value:string}[];
};
export type AiRecheckCommand={revision:string;version:string;requestId:string} & ({action:'request_recheck'|'complete_recheck';note:string}|{action:'exclude';reasonCode:QuickReason});
export interface AiReviewStore {
 readonly mode:'database'|'local-fixture';
 get(jobId:string):Promise<AiReview>;
 execute(jobId:string,command:AiRecheckCommand,actor:string):Promise<AiReview>;
}
const hash=/^[a-f0-9]{64}$/;
function obj(x:unknown):Record<string,unknown>{if(!x||typeof x!=='object'||Array.isArray(x))throw new ReviewFailure('unavailable');return x as Record<string,unknown>;}
function text(x:unknown,max=60000){if(typeof x!=='string'||x.length>max)throw new ReviewFailure('unavailable');return x;}
export function aiRecheckCommand(raw:unknown):AiRecheckCommand {
 if(!raw||typeof raw!=='object'||Array.isArray(raw))throw new ReviewFailure('invalid_input');
 const v=obj(raw);
 if(v.action==='exclude'){
  if(Object.keys(v).sort().join(',')!=='action,reasonCode,requestId,revision,version'||!Object.hasOwn(quickReasons,String(v.reasonCode))||!hash.test(String(v.revision))||!hash.test(String(v.version))||!jobUuid.test(String(v.requestId)))throw new ReviewFailure('invalid_input');
  return {action:'exclude',revision:String(v.revision),version:String(v.version),requestId:String(v.requestId),reasonCode:v.reasonCode as QuickReason};
 }
 if(Object.keys(v).sort().join(',')!=='action,note,requestId,revision,version'||!['request_recheck','complete_recheck'].includes(String(v.action))||
 !hash.test(String(v.revision))||!hash.test(String(v.version))||!jobUuid.test(String(v.requestId))||typeof v.note!=='string'||v.note.length>1000)throw new ReviewFailure('invalid_input');
 return {action:v.action as 'request_recheck'|'complete_recheck',revision:String(v.revision),version:String(v.version),requestId:String(v.requestId),note:v.note.trim()};
}
export function aiReview(raw:unknown,jobId:string):AiReview {
 const v=obj(raw),id=text(v.sourceItemId,36),sourceName=text(v.sourceName,40),status=text(v.status,20);
 if(v.jobId!==jobId||!jobUuid.test(jobId)||!jobUuid.test(id)||!hash.test(text(v.revision,64))||!hash.test(text(v.version,64))||
 !['queued','claimed','failed','cancelled','completed'].includes(status)||typeof v.canRecheck!=='boolean'||typeof v.canExclude!=='boolean'||v.canExclude&&!['queued','cancelled'].includes(status)||typeof v.recheckPending!=='boolean'||
 v.canRecheck&&(status!=='queued'||v.recheckPending)||v.recheckPending&&status!=='cancelled')throw new ReviewFailure('unavailable');
 let source,values;let filterInfo:FilterInfo|undefined;
 if(sourceName==='seoul_reservation'){
  const item=programItem(v.review,id);source=item.source;filterInfo=item.filterInfo;
  values=Object.entries(programLabels).map(([k,label])=>({label,value:displayProgramValue(k as keyof typeof programLabels,item.facts[k as keyof typeof programLabels])}));
  values.push(...Object.entries(periodLabels).map(([k,label])=>({label,value:displayProgramDate((item.facts.periods as Record<string,Period>)[k])})));
 }else if(sourceName==='myseoul_program'){
  const item=myseoulItem(v.review,id);source=item.source;filterInfo=item.filterInfo;
  values=Object.entries(myseoulLabels).map(([k,label])=>({label,value:displayMySeoulValue(k,item.facts[k])}));
 }else if(['youthcenter_policy','youthcenter_content'].includes(sourceName)){
  const item=databaseItem(v.review,'facts',id);if(item.kind!=='facts'||item.source.name!==sourceName)throw new ReviewFailure('unavailable');source=item.source;filterInfo=item.filterInfo;
  values=Object.entries(factLabels).map(([k,label])=>({label,value:factValue(item.facts,k as keyof typeof item.facts)}));
 }else throw new ReviewFailure('unavailable');
 if(v.classification!==undefined&&v.classification!==null){
  const c=classificationDetail(v.classification,id);
  if(!c.active||c.revision!==v.revision)throw new ReviewFailure('unavailable');
  values=values.map(row=>({...row,label:`수집원 확인값 · ${row.label}`}));
  values.push(...Object.entries(factLabels).map(([k,label])=>({label:`현재 분류 확인값 · ${label}`,value:factValue(c.facts,k as keyof typeof c.facts)})));
  if(c.filters){const data=c.filters;values.push(...filterKeys.map(k=>({label:`현재 분류 필터 · ${filterLabels[k]}`,value:data[k].status==='unknown'?'저장된 값 없음':filterValueLabel(data,k)})));}
 }else if(filterInfo)values.push(...filterKeys.map(k=>({label:`공개 필터 · ${filterLabels[k]}`,value:filterInfo!.data[k].status==='unknown'?'저장된 값 없음':filterValueLabel(filterInfo!.data,k)})));
 const review=obj(v.review);
 if(review.revision!==v.revision||source.name!==sourceName)throw new ReviewFailure('unavailable');
 return {jobId,sourceItemId:id,sourceName,title:source.title,revision:String(v.revision),version:String(v.version),status,canRecheck:v.canRecheck,canExclude:v.canExclude,recheckPending:v.recheckPending,note:text(v.note,1000),source:{url:source.url===null?null:sourceLink(source.url),body:source.body},values};
}
export function aiReviewView(raw:unknown,jobId:string):AiReview {
 const v=obj(raw),source=obj(v.source);
 if(v.jobId!==jobId||!jobUuid.test(jobId)||!jobUuid.test(String(v.sourceItemId))||!hash.test(String(v.revision))||!hash.test(String(v.version))||
 !['youthcenter_policy','youthcenter_content','seoul_reservation','myseoul_program'].includes(String(v.sourceName))||
 !['queued','claimed','failed','cancelled','completed'].includes(String(v.status))||typeof v.canRecheck!=='boolean'||typeof v.canExclude!=='boolean'||v.canExclude&&!['queued','cancelled'].includes(String(v.status))||typeof v.recheckPending!=='boolean'||
 v.canRecheck&&(v.status!=='queued'||v.recheckPending)||v.recheckPending&&v.status!=='cancelled'||!Array.isArray(v.values)||v.values.length>60)throw new ReviewFailure('unavailable');
 return {jobId,sourceItemId:String(v.sourceItemId),sourceName:String(v.sourceName),title:text(v.title,500),revision:String(v.revision),version:String(v.version),status:String(v.status),canRecheck:v.canRecheck,canExclude:v.canExclude,recheckPending:v.recheckPending,note:text(v.note,1000),source:{url:source.url===null?null:sourceLink(text(source.url,2048)),body:text(source.body,200000)},values:v.values.map(row=>{const r=obj(row);return {label:text(r.label,100),value:text(r.value)};})};
}
export class DatabaseAiReviewStore implements AiReviewStore {
 readonly mode='database' as const;
 private client:RpcClient;
 constructor(client:RpcClient){this.client=client;}
 private async invoke(name:string,args:Record<string,unknown>){
  try{const {data,error}=await this.client.rpc(name,args);if(error)throw new ReviewFailure(error.code==='PT409'?'conflict':error.code==='PT422'?'invalid_input':error.code==='PT404'?'not_found':'unavailable');if(data===null)throw new ReviewFailure('unavailable');return data;}
  catch(e){if(e instanceof ReviewFailure)throw e;throw new ReviewFailure('unavailable');}
 }
 async get(jobId:string){return aiReview(await this.invoke('admin_ai_queue_review_detail',{p_job_id:jobId}),jobId);}
 async execute(jobId:string,c:AiRecheckCommand,actor:string){
  const result=aiReview(await this.invoke(c.action==='exclude'?'admin_ai_queue_exclude':c.action==='request_recheck'?'admin_ai_queue_request_recheck':'admin_ai_queue_complete_recheck',{
   p_job_id:jobId,p_revision:c.revision,p_version:c.version,p_request_id:c.requestId,...(c.action==='exclude'?{p_reason:c.reasonCode}:{p_note:c.note}),p_actor:actor}),jobId);
  if(result.revision!==c.revision||c.action==='request_recheck'&&!result.recheckPending||c.action==='complete_recheck'&&result.recheckPending||c.action==='exclude'&&(result.recheckPending||result.canExclude||result.status!=='cancelled'))throw new ReviewFailure('unavailable');
  return result;
 }
}
