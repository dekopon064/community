'use client';
import {useEffect,useRef,useState} from 'react';
import {provinceLabels} from '@/app/lib/contentFilters';
import {locationReport,locationResearchSchema} from '@/app/lib/review/location-research';
import type {LocationReport,LocationSnapshot} from '@/app/lib/review/location-research';
import type {ListItem} from '@/app/lib/review/contracts';
import {primaryButton,secondaryButton} from './ReviewEditors';

type Receipt={batchId:string;at:string;actor:string;stopped:boolean;results:{id:string;status:string;code:string}[]};
export async function locationRequest(body:unknown,request:typeof fetch=fetch){
  const response=await request('/api/admin/location-research',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json().catch(()=>null);
  if(!response.ok||!data)throw Error(data?.code==='conflict'?'다른 저장으로 항목이 변경됐습니다. 최신 값을 확인하세요.':'요청 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.');
  return data;
}
function download(value:unknown,name:string){
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export default function LocationResearchPanel({items,disabled,onBusy,onSaved}:{items:ListItem[];disabled:boolean;onBusy:(busy:boolean)=>void;onSaved:()=>void}){
  const [targets,setTargets]=useState<string[]>([]),[selected,setSelected]=useState<string[]>([]);
  const [report,setReport]=useState<LocationReport|null>(null),[receipts,setReceipts]=useState<Receipt[]>([]);
  const [attempted,setAttempted]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const sending=useRef(false),writeAttempted=useRef(false),generation=useRef(0),uncertain=useRef(new Set<string>());
  const available=items.filter(x=>x.sourceName==='seoul_reservation');
  const activeTargets=targets.filter(id=>available.some(item=>item.id===id));
  const processedIds=receipts.flatMap(r=>r.results).filter(r=>r.status!=='unprocessed').map(r=>r.id);
  useEffect(()=>{onBusy(busy);return()=>onBusy(false);},[busy,onBusy]);
  useEffect(()=>{if(!busy&&!selected.length)return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[busy,selected.length]);
  useEffect(()=>()=>{generation.current++;},[]);
  async function prepare(){
    if(disabled||sending.current||!activeTargets.length)return;sending.current=true;setBusy(true);setError('');setNotice('');
    try{
      const data=await locationRequest({action:'prepare',source:'seoul_reservation',ids:activeTargets});
      if(data.schema!==locationResearchSchema||!Array.isArray(data.items)||!data.items.length)throw Error('조사할 미확인 개최지역이 없습니다. 기존 값은 유지했습니다.');
      download({schema:locationResearchSchema,items:data.items as LocationSnapshot[]},'location-research-input.json');
      setNotice(`${data.items.length}건의 조사 대상을 내보냈습니다. 별도 조사 도구의 결과를 불러와 확인하세요.${data.skipped?.length?` 제외 ${data.skipped.length}건.`:''}`);
    }catch(e){setError(e instanceof Error?e.message:'조사 대상을 준비하지 못했습니다.');}
    finally{sending.current=false;setBusy(false);}
  }
  async function importFile(file:File|undefined){
    if(!file||sending.current||disabled)return;
    const current=++generation.current;setError('');
    try{
      if(file.size>2*1024*1024)throw Error();
      const next=locationReport(JSON.parse(await file.text()));
      if(uncertain.current.has(next.batchId))throw Error();
      if(current!==generation.current)return;
      setReport(next);setSelected([]);setReceipts([]);setNotice('');setAttempted(false);writeAttempted.current=false;
    }catch{if(current===generation.current)setError('조사 결과의 형식·공식 근거·지역 선택값을 확인하세요. 기존 제안과 입력은 유지했습니다.');}
  }
  async function apply(){
    if(disabled||sending.current||writeAttempted.current||!report||!selected.length)return;
    sending.current=true;writeAttempted.current=true;setAttempted(true);setBusy(true);setError('');setNotice('');
    try{
      const data=await locationRequest({action:'apply',report,ids:selected});
      if(data.batchId!==report.batchId||!Array.isArray(data.results)||typeof data.stopped!=='boolean'||
        data.results.length!==selected.length||new Set(data.results.map((x:{id:string})=>x.id)).size!==selected.length||
        data.results.some((x:{id:string;status:string})=>!selected.includes(x.id)||!['saved','skipped','failed','unknown','unprocessed'].includes(x.status)))throw Error('저장 응답을 확인하지 못했습니다. 다시 저장하지 말고 해당 항목의 최신 상태를 확인하세요.');
      setReceipts(old=>[...old,data]);setSelected([]);
      if(data.stopped)uncertain.current.add(report.batchId);
      else {writeAttempted.current=false;setAttempted(false);}
      setNotice(`저장 ${data.results.filter((x:{status:string})=>x.status==='saved').length}건.${data.stopped?' 응답 확인이 필요한 항목이 있어 중단했습니다.':''}`);
      onSaved();
    }catch(e){uncertain.current.add(report.batchId);setError(e instanceof Error?e.message:'저장 결과를 확인하지 못했습니다. 다시 저장하지 마세요.');}
    finally{sending.current=false;setBusy(false);}
  }
  const statusText:Record<string,string>={no_evidence:'공식 근거를 찾지 못했습니다.',ambiguous:'장소를 하나로 특정하지 못했습니다.',error:'조사 결과를 확인하지 못했습니다.'};
  const resultText:Record<string,string>={saved:'저장 완료',skipped:'최신 값 변경·편집 제한으로 건너뜀',failed:'처리 실패',unknown:'저장 결과 확인 필요',unprocessed:'중단으로 미처리'};
  return <details className="my-6 border-y border-info-rule py-3"><summary className="cursor-pointer py-3 font-semibold">개최지역 일괄 조사·제안 확인</summary>
    <p className="my-3 max-w-3xl leading-7 text-info-body">조사 대상을 내보내 별도 도구로 일괄 조사한 뒤 결과를 불러오세요. 공식 근거를 확인한 항목만 선택해 저장합니다. 기존 수동 입력도 계속 사용할 수 있습니다.</p>
    <details className="my-4"><summary className="cursor-pointer py-3 font-semibold">조사 대상 선택 · 현재 목록 {available.length}건</summary>
    <fieldset disabled={disabled||busy} className="my-4"><legend className="sr-only">현재 목록의 서울 예약 조사 대상</legend>
      <div className="my-2 flex flex-wrap gap-3"><button type="button" className={secondaryButton} onClick={()=>setTargets(available.map(x=>x.id))}>현재 목록 전체 선택</button><button type="button" className={secondaryButton} onClick={()=>setTargets([])}>선택 해제</button></div>
      {!available.length?<p className="mt-2 text-info-muted">현재 목록에 서울 예약 항목이 없습니다.</p>:<ul className="mt-2 divide-y divide-info-rule">{available.map(item=><li key={item.id}><label className="flex min-h-11 items-start gap-3 py-2"><input className="mt-1 size-5 shrink-0" type="checkbox" checked={targets.includes(item.id)} onChange={e=>setTargets(e.target.checked?[...targets,item.id]:targets.filter(id=>id!==item.id))}/><span className="min-w-0 break-words leading-7">{item.title}</span></label></li>)}</ul>}
    </fieldset>
    <button type="button" className={secondaryButton} disabled={disabled||busy||!activeTargets.length} onClick={()=>void prepare()}>선택 {activeTargets.length}건 조사 대상 내보내기</button></details>
    <label className="block text-sm font-medium">조사 결과 불러오기<input type="file" accept="application/json,.json" disabled={disabled||busy} className="mt-2 block max-w-full text-sm" onChange={e=>{void importFile(e.target.files?.[0]);e.currentTarget.value='';}}/></label>
    {busy&&<p role="status" className="my-4 text-info-muted">요청을 처리하고 있습니다.</p>}
    {notice&&<p role="status" className="my-4 leading-7 text-info-body">{notice}</p>}
    {error&&<p role="alert" className="my-4 leading-7 text-info-status">{error}</p>}
    {report&&<section className="mt-6" aria-label="조사된 개최지역 제안">
      <h3 className="text-lg font-semibold">준비된 제안 {report.items.length}건</h3>
      {report.mode==='synthetic'&&<p className="my-3 text-info-status">합성 조사 자료입니다. 실제 장소 조사 결과가 아니며 운영 저장에 사용할 수 없습니다.</p>}
      <ul className="mt-3 divide-y divide-info-rule border-y border-info-rule">{report.items.map(row=>{const result=receipts.flatMap(r=>r.results).find(x=>x.id===row.snapshot.id);return <li key={row.snapshot.id} className="py-5">
        <p className="break-words font-semibold leading-7">{row.snapshot.title}</p>
        {row.evidence?<><p className="mt-2 font-medium">{provinceLabels[row.evidence.province]} → {row.evidence.district}</p><p className="mt-2 break-words leading-7 text-info-body">{row.evidence.place} · <a className="underline underline-offset-4" href={row.evidence.url} target="_blank" rel="noopener noreferrer">공식 위치 안내</a></p><p className="mt-1 break-words text-sm leading-6 text-info-muted">{row.evidence.excerpt}</p>
          <label className="mt-2 flex min-h-11 items-center gap-3"><input className="size-5" type="checkbox" disabled={disabled||busy||attempted||processedIds.includes(row.snapshot.id)} checked={selected.includes(row.snapshot.id)} onChange={e=>setSelected(e.target.checked?[...selected,row.snapshot.id]:selected.filter(id=>id!==row.snapshot.id))}/>제안 반영<span className="sr-only">: {row.snapshot.title}</span></label></>:<p className="mt-2 leading-7 text-info-muted">{statusText[row.status]}</p>}
        {result&&<p className="mt-2 leading-7" role="status">{resultText[result.status]}</p>}
      </li>;})}</ul>
      <button type="button" className={`${primaryButton} mt-4`} disabled={disabled||busy||!selected.length||attempted} onClick={()=>void apply()}>확인한 {selected.length}건 개최지역 저장</button>
      {receipts.length>0&&<button type="button" className={`${secondaryButton} ml-3 mt-4`} onClick={()=>download({report,receipts},'location-research-receipt.json')}>근거·처리 결과 내려받기</button>}
      {attempted&&<p className="mt-3 text-sm leading-6 text-info-muted">이번 반영은 중단했습니다. 같은 요청을 반복하지 말고 해당 항목의 최신 상태를 확인하세요.</p>}
    </section>}
  </details>;
}
