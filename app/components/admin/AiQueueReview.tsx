'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {aiReviewView} from '@/app/lib/review/ai-review';
import type {AiReview,AiRecheckCommand} from '@/app/lib/review/ai-review';
import {failureText} from '@/app/lib/review/presentation';
import {fieldClass,primaryButton,secondaryButton} from './ReviewEditors';

export default function AiQueueReview({jobId,onClose,onBusy,onChanged,onReview}:{jobId:string;onClose:()=>void;onBusy:(blocked:boolean)=>void;onChanged:()=>void;onReview:(item:AiReview)=>void}){
 const [item,setItem]=useState<AiReview|null>(null),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[note,setNote]=useState(''),[error,setError]=useState(''),[unknown,setUnknown]=useState(false),[confirm,setConfirm]=useState<AiRecheckCommand['action']|null>(null),[notice,setNotice]=useState('');
 const flight=useRef(false),epoch=useRef(0),heading=useRef<HTMLHeadingElement>(null),confirmButton=useRef<HTMLButtonElement>(null),trigger=useRef<HTMLButtonElement|null>(null);
 const load=useCallback(async()=>{
  const seq=++epoch.current;setLoading(true);setError('');
  try{const r=await fetch(`/api/admin/ai-queue/${jobId}`,{credentials:'same-origin',cache:'no-store'}),data=await r.json().catch(()=>null);if(!r.ok)throw Error(data?.code??'unavailable');if(!['database','local-fixture'].includes(data?.mode))throw Error('unavailable');const next=aiReviewView(data.item,jobId);if(seq!==epoch.current)return;setItem(next);setNote(previous=>next.recheckPending&&previous.trim()===next.note?'':previous);setUnknown(false);setConfirm(null);}
  catch(e){if(seq===epoch.current){const code=e instanceof Error?e.message:'unavailable';if(['signed_out','forbidden'].includes(code))setItem(null);setError(code);}}
  finally{if(seq===epoch.current)setLoading(false);}
 },[jobId]);
 useEffect(()=>{const lifecycle=epoch;const timer=setTimeout(()=>{void load();heading.current?.focus();},0);return()=>{clearTimeout(timer);lifecycle.current++;};},[load]);
 useEffect(()=>{onBusy(busy||loading||Boolean(note)||Boolean(confirm)||unknown);return()=>onBusy(false);},[busy,loading,note,confirm,unknown,onBusy]);
 useEffect(()=>{if(!note&&!unknown)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[note,unknown]);
 useEffect(()=>{if(confirm)confirmButton.current?.focus();},[confirm]);
 function cancel(){setConfirm(null);trigger.current?.focus();}
 async function save(){
  if(!item||!confirm||busy||unknown||flight.current)return;
  flight.current=true;setBusy(true);setError('');setNotice('');
  const action=confirm;
  try{
   const r=await fetch(`/api/admin/ai-queue/${jobId}`,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,revision:item.revision,version:item.version,requestId:crypto.randomUUID(),note:action==='complete_recheck'?'원문·최신 확인값 재검토 완료':note.trim()})});
   const data=await r.json().catch(()=>null);if(!r.ok)throw Error(data?.code??'unavailable');
   if(!['database','local-fixture'].includes(data?.mode))throw Error('unavailable');
   const next=aiReviewView(data.item,jobId);
   if(next.sourceItemId!==item.sourceItemId||next.revision!==item.revision||action==='request_recheck'&&!next.recheckPending||action==='complete_recheck'&&next.recheckPending)throw Error('unavailable');
   setItem(next);setNote('');setConfirm(null);setNotice(action==='request_recheck'?'AI 대기를 보류하고 재검토로 보냈습니다. 기존 값은 보존했습니다.':'재검토 완료를 저장했습니다. AI 대기 여부는 서버 판정에 따르며 AI는 실행하지 않았습니다.');onChanged();heading.current?.focus();
  }catch(e){const code=e instanceof Error?e.message:'unavailable';if(['signed_out','forbidden'].includes(code))setItem(null);setError(code);setConfirm(null);setUnknown(true);}
  finally{flight.current=false;setBusy(false);}
 }
 return <section className="mt-8 min-w-0 border-y border-info-rule py-6" aria-label="AI 대기 항목 원문·확인값" aria-busy={busy||loading}>
  <div className="flex flex-wrap items-start justify-between gap-3"><h3 ref={heading} tabIndex={-1} className="min-w-0 scroll-mt-36 break-words text-xl font-bold">{item?.title??'원문·확인값'}</h3><button type="button" className={secondaryButton} disabled={busy||Boolean(note)||unknown} onClick={onClose}>닫기</button></div>
  {loading&&<p role="status" className="mt-4">원문과 확인값을 불러오는 중입니다.</p>}
  {error&&<div role="alert" className="mt-4 leading-7 text-info-status"><p>{failureText[error]??failureText.unavailable}</p><p>입력은 유지됩니다. 자동 재전송은 하지 않습니다.</p></div>}
  {notice&&<p role="status" className="mt-4 leading-7 text-info-body">{notice}</p>}
  {item&&<>
   <p className="mt-3 leading-7 text-info-status">{item.recheckPending?'재검토 중 · AI 대기 보류':item.status==='claimed'?'AI 처리 중 · 재검토 전환 불가':item.canRecheck?'AI 작업 대기 · 실행 전 확인':'현재 상태에서는 재검토 전환 불가'}</p>
   <details className="mt-5 border-b border-info-rule pb-5"><summary className="min-h-11 cursor-pointer py-2 font-semibold">원문 확인 · 읽기 전용</summary>{item.source.url&&<a href={item.source.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center underline underline-offset-4">공식 원문 열기 (새 창)</a>}<p className="mt-3 max-w-3xl whitespace-pre-wrap break-words leading-7 text-info-body">{item.source.body||'저장된 본문이 없습니다.'}</p></details>
   <h4 className="mt-6 font-bold">현재 확인값</h4><p className="mt-2 text-sm leading-6 text-info-muted">값이 저장되어 있다는 표시이며, 모든 검토가 완료됐다는 뜻은 아닙니다.</p>
   <dl className="mt-3 divide-y divide-info-rule">{item.values.map((row,i)=><div key={i} className="grid min-w-0 gap-2 py-3 sm:grid-cols-[11rem_minmax(0,1fr)]"><dt className="font-semibold">{row.label}</dt><dd className="min-w-0 whitespace-pre-wrap break-words leading-7 text-info-body">{row.value}</dd></div>)}</dl>
   {item.recheckPending?<div className="mt-6 border-t border-info-rule pt-5"><p className="whitespace-pre-wrap break-words leading-7">재검토 사유: {item.note}</p><p className="mt-2 text-sm leading-6 text-info-muted">필요한 값은 사실 검토에서 수정한 뒤 이 화면의 최신 값을 다시 확인하세요. 사실 저장만으로 보류를 해제하지 않습니다.</p><div className="mt-4 flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={busy||unknown} onClick={()=>onReview(item)}>사실 검토에서 수정</button><button type="button" className={primaryButton} disabled={busy||loading||unknown} onClick={e=>{trigger.current=e.currentTarget;setConfirm('complete_recheck');}}>재검토 완료</button></div></div>:item.canRecheck&&<div className="mt-6 border-t border-info-rule pt-5"><label htmlFor={`recheck-note-${jobId}`} className="font-semibold">재검토 사유</label><textarea id={`recheck-note-${jobId}`} className={fieldClass} rows={3} maxLength={1000} disabled={busy||unknown} value={note} onChange={e=>setNote(e.target.value)}/><p className="mt-2 text-sm leading-6 text-info-muted">재검토로 보내면 AI 대기를 보류합니다. 원문·확인값·후보는 보존합니다.</p><div className="mt-4 flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={busy||loading||unknown||!note.trim()} onClick={e=>{trigger.current=e.currentTarget;setConfirm('request_recheck');}}>AI 대기 보류·재검토로 보내기</button>{note&&<button type="button" className={secondaryButton} disabled={busy||unknown} onClick={()=>setNote('')}>사유 입력 취소</button>}</div></div>}
  </>}
  {note&&item&&!item.canRecheck&&<div className="mt-4 border-t border-info-rule pt-4"><p className="whitespace-pre-wrap break-words leading-7">보존한 사유 입력: {note}</p><p className="mt-2 text-sm text-info-muted">서버의 재검토 사유와 다릅니다. 입력을 취소한 뒤 현재 검토를 계속할 수 있습니다.</p><button type="button" className={`${secondaryButton} mt-3`} disabled={busy||unknown} onClick={()=>setNote('')}>보존한 사유 입력 취소</button></div>}
  <button type="button" className={`${secondaryButton} mt-5`} disabled={busy||loading} onClick={()=>void load()}>입력을 유지하고 최신 상태 확인</button>
  {confirm&&<div role="group" aria-label="재검토 최종 확인" className="mt-5 border-y border-info-rule py-5" onKeyDown={e=>{if(e.key==='Escape'&&!busy)cancel();}}><p className="leading-7">{confirm==='request_recheck'?'AI 대기를 보류하고 재검토로 보낼까요?':'원문과 최신 확인값의 재검토를 마칠까요? 남은 확인 사유가 있으면 AI는 계속 차단됩니다.'}</p><div className="mt-4 flex flex-wrap gap-3"><button ref={confirmButton} type="button" className={secondaryButton} disabled={busy} onClick={cancel}>취소</button><button type="button" className={primaryButton} disabled={busy} onClick={()=>void save()}>{busy?'저장 중…':'확인하고 저장'}</button></div></div>}
 </section>;
}
