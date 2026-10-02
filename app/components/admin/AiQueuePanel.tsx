"use client";
import {useCallback,useEffect,useRef,useState} from "react";
import {aiSnapshot,aiStateText,aiFailureText,observeAi} from "@/app/lib/review/ai-queue";
import type {AiSnapshot,Observation} from "@/app/lib/review/ai-queue";
import {failureText} from "@/app/lib/review/presentation";
import {secondaryButton} from "./ReviewEditors";
const sources={youthcenter_policy:"온통청년 정책",youthcenter_content:"온통청년 콘텐츠",seoul_reservation:"서울 공공서비스예약"};
function time(value:string){return new Intl.DateTimeFormat("ko-KR",{timeZone:"Asia/Seoul",dateStyle:"medium",timeStyle:"short"}).format(new Date(value));}
export default function AiQueuePanel({active}:{active:boolean}){
 const [snapshot,setSnapshot]=useState<AiSnapshot|null>(null),[offset,setOffset]=useState(0);
 const [loading,setLoading]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
 const [mode,setMode]=useState("");
 const observation=useRef<Observation>({watched:new Map(),announced:new Set()});
 const flight=useRef<AbortController|null>(null),sequence=useRef(0);
 const load=useCallback(async(next:number)=>{
  flight.current?.abort();const controller=new AbortController();flight.current=controller;const request=++sequence.current;
  setLoading(true);setError("");setNotice("");
  try{
   const ids=[...observation.current.watched.keys()];
   const response=await fetch(`/api/admin/ai-queue?offset=${next}${ids.length?"&watch="+ids.join(","):""}`,{cache:"no-store",credentials:"same-origin",signal:controller.signal});
   const data=await response.json().catch(()=>null);
   if(!response.ok)throw new Error(data?.code??"unavailable");
   if(!["database","local-fixture"].includes(data?.mode))throw new Error("unavailable");
   const value=aiSnapshot(data);
   if(controller.signal.aborted||request!==sequence.current)return;
   if(value.observed.length!==ids.length||value.observed.some(j=>!ids.includes(j.jobId)))throw new Error("unavailable");
   setNotice(observeAi(observation.current,value));setSnapshot(value);setOffset(next);setMode(data.mode);
  }catch(e){if(!controller.signal.aborted&&request===sequence.current){
   const code=e instanceof Error?e.message:"unavailable";
   if(["signed_out","forbidden"].includes(code)){observation.current={watched:new Map(),announced:new Set()};setSnapshot(null);}
   setError(code);
  }}finally{if(!controller.signal.aborted&&request===sequence.current)setLoading(false);}
 },[]);
 useEffect(()=>{
  const timer=active?setTimeout(()=>{void load(0);},0):null;
  const currentFlight=flight;
  return()=>{if(timer!==null)clearTimeout(timer);currentFlight.current?.abort();};
 },[active,load]);
 return <section hidden={!active} aria-label="AI 작업 대기" aria-busy={loading} className="mt-5">
  <div className="flex flex-wrap items-start justify-between gap-4">
   <div><h2 className="text-xl font-bold">AI 작업 대기</h2><p className="mt-2 max-w-3xl leading-7 text-info-body">사실 검토 이후의 AI 상태를 확인합니다. 새로고침은 상태 조회만 수행합니다.</p></div>
   <button type="button" className={secondaryButton} disabled={loading} onClick={()=>void load(offset)}>{loading?"확인 중…":"새로고침"}</button>
  </div>
  <p className="mt-3 text-sm leading-6 text-info-muted">{snapshot?`갱신 기준: ${time(snapshot.checkedAt)} (한국 시간)`:"수동으로 최신 상태를 확인합니다."} 화면에서 확인한 작업의 완료만 안내합니다.</p>
  {mode==="local-fixture"&&<p className="mt-3 text-sm text-info-status">로컬 시험 데이터 · 실제 운영 상태가 아닙니다.</p>}
  {error&&<div role="alert" className="my-5 border-y border-info-rule py-4 leading-7"><p className="text-info-status">AI 작업 목록을 불러오지 못했습니다. {failureText[error]??failureText.unavailable}</p>{snapshot&&<p className="mt-2 text-info-muted">아래는 마지막으로 확인한 상태입니다. 새로고침으로 다시 확인해 주세요.</p>}</div>}
  {notice&&<p role="status" className="my-5 border-y border-info-rule py-4 leading-7 text-info-body">{notice}</p>}
  {loading&&!snapshot&&<p role="status" className="my-6 text-info-muted">AI 작업 상태를 불러오는 중입니다.</p>}
  {!loading&&!error&&snapshot&&!snapshot.items.length&&<p className="my-8 leading-7 text-info-muted">현재 AI 작업 대기 항목이 없습니다. 완료 결과는 AI 결과 후보 검토에서 확인할 수 있습니다.</p>}
  {snapshot&&<ul className="mt-6 divide-y divide-info-rule border-y border-info-rule">{snapshot.items.map(job=><li key={job.jobId} className="grid gap-3 py-5 sm:grid-cols-[minmax(0,1fr)_16rem]">
   <div className="min-w-0"><h3 className="break-keep font-semibold leading-7">{job.title}</h3><p className="mt-1 text-sm leading-6 text-info-muted">{sources[job.sourceName]}</p></div>
   <div className="min-w-0"><p className="font-semibold text-info-status">{aiStateText(job)}</p>
    {(job.status==="failed"||job.status==="queued"&&(job.retryCount>0||job.nextRetryAt))&&<p className="mt-1 break-words text-sm leading-6 text-info-body">{aiFailureText(job)}</p>}
    {job.status==="queued"&&job.nextRetryAt&&<p className="mt-1 text-sm leading-6 text-info-muted">다시 시도할 수 있는 시각: {time(job.nextRetryAt)} · 실행 시각은 보장되지 않습니다.</p>}
    {job.status==="claimed"&&job.leaseState!=="active"&&<p className="mt-1 text-sm leading-6 text-info-muted">기록된 처리 시간이 지났거나 확인이 필요합니다. 새로고침은 작업을 복구하지 않습니다.</p>}
   </div>
  </li>)}</ul>}
  {snapshot&&<div className="mt-5 flex flex-wrap gap-3"><button className={secondaryButton} disabled={loading||offset===0} onClick={()=>void load(Math.max(0,offset-25))}>이전 목록</button><button className={secondaryButton} disabled={loading||!snapshot.hasMore} onClick={()=>void load(offset+25)}>다음 목록</button></div>}
 </section>;
}
