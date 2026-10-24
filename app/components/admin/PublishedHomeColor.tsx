'use client';
import {useEffect,useRef,useState} from 'react';
import {homeCardPalette,type HomeTone} from '@/app/lib/homeCardPalette';
import {homeAnalysisLabel,homeColorDetail,homeToneNames,type HomeColorDetail} from '@/app/lib/home-colors/admin';
import {fieldClass,primaryButton,secondaryButton} from './ReviewEditors';

export default function PublishedHomeColor({id,disabled,onBlocked}:{id:string;disabled:boolean;onBlocked:(v:boolean)=>void}){
 const [item,setItem]=useState<HomeColorDetail|null>(null),[draft,setDraft]=useState<HomeTone>('default'),[editing,setEditing]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[uncertain,setUncertain]=useState(false);
 const sending=useRef(false);
 useEffect(()=>{onBlocked(editing||busy);return()=>onBlocked(false);},[editing,busy,onBlocked]);
 useEffect(()=>{
  const abort=new AbortController();
  void fetch(`/api/admin/review-home-color/${id}`,{cache:'no-store',credentials:'same-origin',signal:abort.signal}).then(async r=>{const data=await r.json();if(!r.ok)throw Error('read');const next=homeColorDetail(data.item,id);if(!abort.signal.aborted){setItem(next);setDraft(next.tone);}}).catch(()=>{if(!abort.signal.aborted)setError('저장된 배경색 정보를 확인하지 못했습니다.');});
  return()=>abort.abort();
 },[id]);
 async function reload(){
  if(sending.current)return;setBusy(true);setError('');setNotice('');
  try{const r=await fetch(`/api/admin/review-home-color/${id}`,{cache:'no-store',credentials:'same-origin'});const data=await r.json();if(!r.ok)throw Error('read');const next=homeColorDetail(data.item,id);setItem(next);setDraft(next.tone);setEditing(false);setUncertain(false);}
  catch{setError('저장된 배경색 정보를 확인하지 못했습니다.');}finally{setBusy(false);}
 }
 async function save(){
  if(!item||!item.canEdit||disabled||busy||sending.current||uncertain||draft===item.tone)return;
  sending.current=true;setBusy(true);setError('');setNotice('');
  try{
   const r=await fetch(`/api/admin/review-home-color/${id}`,{method:'POST',cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:item.revision,version:item.version,tone:draft,requestId:crypto.randomUUID()})});
   const data=await r.json().catch(()=>null);
   if(!r.ok){setError(data?.code==='conflict'?'다른 변경으로 저장 버전이 달라졌습니다. 선택은 유지했습니다.':data?.code==='signed_out'||data?.code==='forbidden'?'관리자 권한을 확인하지 못했습니다. 선택은 유지했습니다.':'저장 결과를 확인하지 못했습니다. 선택을 유지하며 자동 재시도하지 않습니다.');setUncertain(true);return;}
   const next=homeColorDetail(data?.item,id);
   if(next.revision!==item.revision||next.tone!==draft||!next.manual||next.choiceVersion!==item.choiceVersion+1||next.version===item.version)throw Error('unknown');
   setItem(next);setDraft(next.tone);setEditing(false);setNotice('선택한 배경색을 저장했습니다.');
  }catch{setError('저장 결과를 확인하지 못했습니다. 선택을 유지하며 자동 재시도하지 않습니다.');setUncertain(true);}
  finally{sending.current=false;setBusy(false);}
 }
 return <section className="my-6 border-y border-info-rule py-5" aria-label="홈 대표 카드 배경색" aria-busy={busy}>
  <h3 className="font-semibold">홈 대표 카드 배경색</h3>
  {item?<><p className="mt-2 leading-7 text-info-body">분석: {homeAnalysisLabel(item)}</p><p className="flex flex-wrap items-center gap-2 leading-7 text-info-body"><span aria-hidden="true" className="inline-block h-5 w-5 border border-info-rule" style={{backgroundColor:homeCardPalette[item.tone].main}}/>적용 색상: {homeToneNames[item.tone]}{item.manual?' · 운영자 지정':''}</p>
   {!editing?<button type="button" className={`${secondaryButton} mt-3`} disabled={disabled||busy||uncertain||!item.canEdit} onClick={()=>{setDraft(item.tone);setEditing(true);setError('');setNotice('');}}>색상 변경</button>:<form className="mt-4" onSubmit={e=>{e.preventDefault();void save();}}>
    <label className="block">적용할 색상<select className={`${fieldClass} mt-2 max-w-sm`} value={draft} disabled={disabled||busy||uncertain} onChange={e=>setDraft(e.target.value as HomeTone)}>{(Object.keys(homeToneNames) as HomeTone[]).map(key=><option value={key} key={key}>{homeToneNames[key]}</option>)}</select></label>
    <div className="mt-3 flex flex-wrap gap-2"><button type="submit" className={primaryButton} disabled={disabled||busy||uncertain||draft===item.tone}>{busy?'저장 중…':'색상 저장'}</button><button type="button" className={secondaryButton} disabled={busy} onClick={()=>{setDraft(item.tone);setEditing(false);if(!uncertain)setError('');}}>취소</button></div>
   </form>}
  </>:!error&&<p className="mt-2 text-info-muted">배경색 정보를 불러오는 중입니다.</p>}
  {error&&<p role="alert" className="mt-3 leading-7 text-info-status">{error}</p>}
  {notice&&<p role="status" className="mt-3 leading-7 text-info-body">{notice}</p>}
  {(uncertain||!item&&error)&&<button type="button" disabled={disabled||busy} className={`${secondaryButton} mt-3`} onClick={()=>void reload()}>{editing?'변경 취소·최신 결과 확인':'최신 결과 확인'}</button>}
 </section>;
}
