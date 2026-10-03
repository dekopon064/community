import { ReviewFailure } from "./contracts";
import type { RpcClient } from "./database-store";

export const aiErrors: Record<string,string> = {
 ai_or_enqueue_failed:"AI 결과를 준비하지 못했습니다.",ai_blocked_cost_cap:"AI 비용 한도 때문에 작업을 진행하지 못했습니다.",
 ai_cost_bound_breach:"AI 비용 제한을 확인해야 합니다.",ai_refusal:"AI가 결과 생성을 거절했습니다.",
 ai_schema_error:"AI 결과 형식을 확인해야 합니다.",ai_timeout:"AI 응답 시간이 초과되었습니다.",
 ai_network:"AI 서비스 연결에 실패했습니다.",ai_http_429:"AI 서비스의 요청 한도에 도달했습니다.",
 ai_http_400:"AI 요청 형식을 확인해야 합니다.",ai_http_401:"AI 서비스 인증 설정을 확인해야 합니다.",
 ai_http_403:"AI 서비스 접근 권한을 확인해야 합니다.",ai_http_404:"AI 서비스 설정을 확인해야 합니다.",
 ai_http_4xx:"AI 요청을 처리하지 못했습니다.",ai_http_5xx:"AI 서비스에 일시적인 문제가 있습니다.",
 ai_unexpected_thinking:"AI 응답 구성을 확인해야 합니다.",ai_call_budget:"AI 호출 한도에 도달했습니다.",
 ai_sampling_forbidden:"AI 생성 설정을 확인해야 합니다."
};
export type AiJob = {
 jobId:string;sourceItemId:string;revision:string;currentRevision:boolean;
 status:"queued"|"claimed"|"failed"|"completed"|"cancelled";
 title:string;sourceName:"youthcenter_policy"|"youthcenter_content"|"seoul_reservation"|"myseoul_program";
 completedAt:string|null;retryCount:number;nextRetryAt:string|null;
 leaseState:"none"|"active"|"expired"|"unknown";errorCode:string|null;
 resultState:"ready"|"missing"|"processed"|"source_changed"|"input_changed"|"unavailable"|null;
};
export type ObservedJob=AiJob|{jobId:string;status:"missing"};
export type AiSnapshot={checkedAt:string;items:AiJob[];observed:ObservedJob[];hasMore:boolean};
export interface AiQueueStore{readonly mode:"database"|"local-fixture";read(offset:number,watch:string[]):Promise<AiSnapshot>}
export const jobUuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function object(x:unknown):Record<string,unknown>{if(!x||typeof x!=="object"||Array.isArray(x))throw new ReviewFailure("unavailable");return x as Record<string,unknown>;}
function str(x:unknown,max:number){if(typeof x!=="string"||x.length>max)throw new ReviewFailure("unavailable");return x;}
function timestamp(x:unknown):string {const s=str(x,64);if(Number.isNaN(Date.parse(s)))throw new ReviewFailure("unavailable");return s;}
function nullableTime(x:unknown){return x===null?null:timestamp(x);}
function parseJob(x:unknown):AiJob{
 const o=object(x),jobId=str(o.jobId,36),sourceItemId=str(o.sourceItemId,36),revision=str(o.revision,64);
 if(!jobUuid.test(jobId)||!jobUuid.test(sourceItemId)||!/^[a-f0-9]{64}$/.test(revision)||
 typeof o.currentRevision!=="boolean"||!["queued","claimed","failed","completed","cancelled"].includes(String(o.status))||
 !["youthcenter_policy","youthcenter_content","seoul_reservation","myseoul_program"].includes(String(o.sourceName))||
 !Number.isSafeInteger(o.retryCount)||(o.retryCount as number)<0||
 !["none","active","expired","unknown"].includes(String(o.leaseState))||
 o.resultState!==null&&!["ready","missing","processed","source_changed","input_changed","unavailable"].includes(String(o.resultState)))
 throw new ReviewFailure("unavailable");
 const completedAt=nullableTime(o.completedAt);
 if(o.status==="completed"&&completedAt===null||o.resultState==="ready"&&(o.status!=="completed"||!o.currentRevision))throw new ReviewFailure("unavailable");
 // Only explicit known codes leave the server adapter; never project raw errors.
 const errorCode=typeof o.errorCode==="string"&&Object.hasOwn(aiErrors,o.errorCode)?o.errorCode:null;
 return {jobId,sourceItemId,revision,currentRevision:o.currentRevision,status:o.status as AiJob["status"],
 title:str(o.title,500),sourceName:o.sourceName as AiJob["sourceName"],completedAt,retryCount:o.retryCount as number,
 nextRetryAt:nullableTime(o.nextRetryAt),leaseState:o.leaseState as AiJob["leaseState"],errorCode,resultState:o.resultState as AiJob["resultState"]};
}
export function aiSnapshot(x:unknown):AiSnapshot{
 const o=object(x);
 if(!Array.isArray(o.items)||o.items.length>25||!Array.isArray(o.observed)||o.observed.length>100||typeof o.hasMore!=="boolean")throw new ReviewFailure("unavailable");
 const items=o.items.map(parseJob);
 if(items.some(j=>!j.currentRevision||!["queued","claimed","failed"].includes(j.status))||new Set(items.map(j=>j.jobId)).size!==items.length)throw new ReviewFailure("unavailable");
 const observed=o.observed.map(x=>{const v=object(x);if(v.status==="missing"){const id=str(v.jobId,36);if(!jobUuid.test(id))throw new ReviewFailure("unavailable");return {jobId:id,status:"missing" as const};}return parseJob(v);});
 if(new Set(observed.map(j=>j.jobId)).size!==observed.length)throw new ReviewFailure("unavailable");
 return {checkedAt:timestamp(o.checkedAt),items,observed,hasMore:o.hasMore};
}
export class DatabaseAiQueueStore implements AiQueueStore{
 readonly mode="database" as const;
 private client:RpcClient;
 constructor(client:RpcClient){this.client=client;}
 async read(offset:number,watch:string[]){
  try{const {data,error}=await this.client.rpc("admin_review_ai_queue",{p_offset:offset,p_limit:25,p_watch:watch});
   if(error)throw new ReviewFailure(error.code==="PT422"?"invalid_input":"unavailable");
   const value=aiSnapshot(data);
   if(value.observed.length!==new Set(watch).size||value.observed.some(j=>!watch.includes(j.jobId)))throw new ReviewFailure("unavailable");
   return value;
  }catch(e){if(e instanceof ReviewFailure)throw e;throw new ReviewFailure("unavailable");}
 }
}
export function aiStateText(j:AiJob){
 if(j.status==="claimed")return j.leaseState==="active"?"AI 처리 중":"처리 상태 확인 필요";
 if(j.status==="failed")return "최종 실패";
 if(j.status==="queued")return j.retryCount>0||j.nextRetryAt?"재시도 대기":"AI 작업 대기";
 return j.status==="completed"?"AI 작업 완료":"취소됨";
}
export function aiFailureText(j:AiJob){return j.errorCode&&Object.hasOwn(aiErrors,j.errorCode)?aiErrors[j.errorCode]:"실패 이유를 확인할 수 없습니다.";}
export type Observation={watched:Map<string,AiJob>;announced:Set<string>};
export function observeAi(state:Observation,snapshot:AiSnapshot):string{
 let ready=0,missing=0,changed=0,processed=0,cancelled=0;
 for(const job of snapshot.observed){
  const old=state.watched.get(job.jobId);if(!old)continue;
  if(job.status==="missing"){state.watched.delete(job.jobId);changed++;continue;}
  if(job.sourceItemId!==old.sourceItemId||job.revision!==old.revision){state.watched.delete(job.jobId);changed++;continue;}
  if(job.status==="completed"){
   const key=job.jobId+":"+job.revision+":"+job.completedAt;
   if(!state.announced.has(key)){state.announced.add(key);
    if(job.resultState==="ready")ready++;else if(job.resultState==="missing"||job.resultState==="unavailable")missing++;
    else if(job.resultState==="processed")processed++;else changed++;
   }state.watched.delete(job.jobId);
  }else if(!job.currentRevision){state.watched.delete(job.jobId);changed++;}
  else if(job.status==="cancelled"){state.watched.delete(job.jobId);cancelled++;}
 }
 for(const job of snapshot.items){state.watched.set(job.jobId,job);}
 // Session-only bounded observation; no persistent read receipts or polling.
 while(state.watched.size>100)state.watched.delete(state.watched.keys().next().value!);
 const messages=[];
 if(ready)messages.push(ready===1?"AI 작업이 완료되었습니다. AI 결과 후보 검토에서 확인하세요.":`AI 작업 ${ready}건이 완료되었습니다. AI 결과 후보 검토에서 확인하세요.`);
 if(missing)messages.push(`완료된 작업 ${missing}건의 검토할 결과를 확인할 수 없습니다.`);
 if(processed)messages.push(`완료된 작업 ${processed}건의 결과는 이미 처리되었습니다.`);
 if(changed)messages.push(`확인 중이던 작업 ${changed}건의 원문·입력 또는 상태가 달라졌습니다. 최신 상태를 확인해 주세요.`);
 if(cancelled)messages.push(`확인 중이던 AI 작업 ${cancelled}건이 취소되었습니다.`);
 return messages.join(" ");
}
