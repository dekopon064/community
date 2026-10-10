'use client';
import {ReviewStatus, reviewAttention} from './ReviewStates';
import { useEffect, useRef, useState } from 'react';
import { districtChoices, eventTopics, programTopics, provinceLabels, filterLabels, filterKeys, parseContentFilters, expandFilterRecurrence } from '@/app/lib/contentFilters';
import type { ContentFilters, FilterKey, FilterEndpoint, FilterField, FilterApplication, FilterOccurrence, FilterSchedule } from '@/app/lib/contentFilters';
import type { FilterInfo, CandidateFilterInfo } from '@/app/lib/review/content-filter-store';
import { filterDetail } from '@/app/lib/review/content-filter-store';
import { fieldClass, primaryButton, secondaryButton } from './ReviewEditors';
import { categories } from '@/app/lib/review/presentation';

const unknown={status:'unknown',value:null} as const,na={status:'not_applicable',value:null} as const;
export function categoryFilterFields(data:ContentFilters):FilterKey[] {
  return data.category==='program'?['topic','delivery','audience','location','application']:data.category==='event'?['topic','location','schedule']:['spaceKind','location'];
}
export function confirmedFilterFields(info:FilterInfo):FilterKey[] {
  return categoryFilterFields(info.data).filter(k=>!info.missing.includes(k)&&(info.origins[k]==='operator'||info.origins[k]==='confirmed_facts'));
}
export function changedFilterFields(saved:ContentFilters,draft:ContentFilters):FilterKey[] {
  return categoryFilterFields(draft).filter(k=>JSON.stringify(saved[k])!==JSON.stringify(draft[k]));
}
const known=<T,>(value:T):FilterField<T>=>({status:'known',value});
export const filterCategoryLabels=categories;
export const reviewFilterLabel=(data:ContentFilters,key:FilterKey)=>key==='location'?(data.category==='youth_space'?'소재 지역':'개최 지역'):filterLabels[key];
export function filterReviewFields(info:FilterInfo):FilterKey[] {
  const order:FilterKey[]=info.data.category==='program'?['topic','delivery','audience','location','application']:info.data.category==='event'?['topic','location','schedule']:['spaceKind','location'];
  return order.filter(k=>info.missing.includes(k)
    ||(k==='delivery'&&info.data.category==='program'&&info.missing.includes('location'))
    ||(k==='spaceKind'&&info.data.category==='youth_space'&&info.missing.includes('location'))
    ||(k==='application'&&info.missing.length>0&&info.data.category==='program'
      &&info.data.application.status==='known'&&info.data.application.value.start===null));
}
export function filterSaveBody(info:FilterInfo,version:string,data:ContentFilters,fields:FilterKey[]) {
  return {revision:info.revision,version,filterVersion:info.filterVersion,data:parseContentFilters(data),fields};
}
export async function saveFilterRequest(id:string,body:ReturnType<typeof filterSaveBody>,request:typeof fetch=fetch) {
  const response=await request(`/api/admin/review-filters/${id}`,{method:'POST',cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json().catch(()=>null);
  if(!response.ok)throw Error(result?.code==='conflict'?'다른 저장이나 처리로 입력 버전이 변경됐습니다. 입력을 유지한 상태로 최신 항목을 확인해 주세요.':result?.fields?.filters??'저장 결과를 확인하지 못했습니다. 입력은 유지했으며 자동 재시도하지 않습니다.');
  let saved;try{saved=filterDetail(result?.item,id);}catch{throw Error('저장 결과를 확인하지 못했습니다. 입력을 유지하며 자동 재시도하지 않습니다.');}
  if(saved.revision!==body.revision||saved.filterVersion<=body.filterVersion||body.fields.some(k=>JSON.stringify(saved.data[k])!==JSON.stringify(body.data[k])))throw Error('저장 결과를 확인하지 못했습니다. 입력을 유지하며 자동 재시도하지 않습니다.');
  return saved;
}
function EndpointInput({label,value,onChange,disabled}:{label:string;value:FilterEndpoint|null;onChange:(v:FilterEndpoint|null)=>void;disabled:boolean}) {
  const precision=value?.precision??'day';
  return <fieldset disabled={disabled} className="grid gap-2 sm:grid-cols-2"><legend className="mb-2 font-medium">{label}</legend>
    <label>날짜<input type="date" className={fieldClass} value={value?.value.slice(0,10)??''} onChange={e=>onChange(e.target.value?{value:precision==='day'?e.target.value:`${e.target.value}T${(value?.value.length===25?value.value.slice(11,19):'')}+09:00`,precision}:null)}/></label>
    <label className="flex min-h-11 items-center gap-3"><input type="checkbox" disabled={!value} checked={precision!=='day'} onChange={e=>{if(value)onChange(e.target.checked?{value:`${value.value.slice(0,10)}T+09:00`,precision:'minute'}:{value:value.value.slice(0,10),precision:'day'});}}/>시간 입력 (선택)</label>
    {precision!=='day'&&<label>시각 (한국 시간)<input required type="time" step={precision==='second'?1:60} className={fieldClass} value={value?.value.length===25?value.value.slice(11,precision==='second'?19:16):''} onChange={e=>{if(value){const p=e.target.value.length===8?'second':'minute';onChange({precision:p,value:`${value.value.slice(0,10)}T${e.target.value}${e.target.value.length===5?':00':''}+09:00`});}}}/></label>}
  </fieldset>;
}
function ReceptionStatus({value,onChange,disabled}:{value:FilterApplication['sourceStatus'];onChange:(v:FilterApplication['sourceStatus'])=>void;disabled:boolean}) {
  const [expanded,setExpanded]=useState(value!=='unknown');
  return <div className="space-y-2">
    <label className="flex min-h-11 items-center gap-3"><input type="checkbox" disabled={disabled} checked={expanded||value!=='unknown'} onChange={e=>{setExpanded(e.target.checked);if(!e.target.checked)onChange('unknown');}}/>접수 상태 직접 지정</label>
    {(expanded||value!=='unknown')&&<><label className="block">접수 상태<select required className={fieldClass} disabled={disabled} value={value==='unknown'?'':value} onChange={e=>onChange(e.target.value as FilterApplication['sourceStatus'])}><option value="" disabled>선택해 주세요</option><option value="not_started">신청 전</option><option value="open">접수 중</option><option value="closed">마감</option></select></label><p className="text-sm leading-6 text-info-muted">체크를 해제하면 별도 접수 상태 지정을 제거합니다. 마감일 판정은 유지됩니다.</p></>}
  </div>;
}
function ScheduleInput({value,onChange,disabled,onPending}:{value:FilterField<FilterSchedule>;onChange:(v:FilterField<FilterSchedule>)=>void;disabled:boolean;onPending?:(v:boolean)=>void;missing?:string[];saved?:ContentFilters;prefix?:string;confirmed?:string[]}) {
  const schedule=value.status==='known'?value.value:null;
  const recurrence=schedule?.recurrence;
  const [repeat,setRepeat]=useState({from:recurrence?.from??'',through:recurrence?.through??'',weekdays:recurrence?.weekdays??[] as number[],exceptions:recurrence?.exceptions.join(', ')??'',precision:recurrence?.precision??'day',startTime:recurrence?.startTime??'',endTime:recurrence?.endTime??''});
  const [error,setError]=useState('');
  const editRepeat=(next:typeof repeat)=>{setRepeat(next);onPending?.(true);};
  const empty:FilterOccurrence={start:{value:'',precision:'day'},end:{value:'',precision:'day'}};
  const set=(next:FilterSchedule)=>onChange(known(next));
  return <div className="space-y-4">
    <label className="block">개최 구간<select aria-label="개최 구간 구분" className={fieldClass} disabled={disabled} value={schedule?.kind??''} onChange={e=>e.target.value?set({kind:e.target.value as FilterSchedule['kind'],occurrences:[empty],recurrence:null}):onChange(unknown)}><option value="" disabled>선택해 주세요</option><option value="continuous">연속 개최 기간</option><option value="occurrences">떨어진 개별 회차</option></select></label>
    {schedule?.occurrences.map((o,i)=><fieldset key={i} disabled={disabled} className="space-y-3 border-t border-info-rule pt-4"><legend className="font-semibold">{schedule.kind==='continuous'?'전체 개최 기간':`${i+1}회차`}</legend><EndpointInput label="시작" value={o.start.value?o.start:null} disabled={disabled} onChange={v=>set({...schedule,recurrence:null,occurrences:schedule.occurrences.map((x,n)=>n===i?{...x,start:v??empty.start}:x)})}/><EndpointInput label="종료 (날짜만 있으면 당일 포함)" value={o.end.value?o.end:null} disabled={disabled} onChange={v=>set({...schedule,recurrence:null,occurrences:schedule.occurrences.map((x,n)=>n===i?{...x,end:v??empty.end}:x)})}/>{schedule.kind==='occurrences'&&schedule.occurrences.length>1&&<button className={secondaryButton} type="button" onClick={()=>set({...schedule,recurrence:null,occurrences:schedule.occurrences.filter((_,n)=>n!==i)})}>이 회차 제거</button>}</fieldset>)}
    {schedule?.kind==='occurrences'&&<><button type="button" className={secondaryButton} disabled={disabled||schedule.occurrences.length>=200} onClick={()=>set({...schedule,recurrence:null,occurrences:[...schedule.occurrences,empty]})}>회차 추가</button><details className="border-t border-info-rule pt-3"><summary className="cursor-pointer py-3 font-semibold">기간·요일이 확인된 반복 일정 입력</summary><p className="mb-3 text-sm leading-6 text-info-muted">확인한 연도·기간·요일·예외일만 사용합니다. 입력 후 실제 회차를 확인해 주세요.</p><fieldset disabled={disabled} className="grid gap-3 sm:grid-cols-2"><label>기간 시작<input type="date" className={fieldClass} value={repeat.from} onChange={e=>editRepeat({...repeat,from:e.target.value})}/></label><label>기간 종료<input type="date" className={fieldClass} value={repeat.through} onChange={e=>editRepeat({...repeat,through:e.target.value})}/></label><div className="sm:col-span-2 flex flex-wrap gap-4">{['일','월','화','수','목','금','토'].map((label,n)=><label key={n} className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={repeat.weekdays.includes(n)} onChange={e=>editRepeat({...repeat,weekdays:e.target.checked?[...repeat.weekdays,n].sort():repeat.weekdays.filter(x=>x!==n)})}/>{label}요일</label>)}</div><label>예외 날짜 (쉼표로 구분)<input className={fieldClass} placeholder="2026-10-10, 2026-10-24" value={repeat.exceptions} onChange={e=>editRepeat({...repeat,exceptions:e.target.value})}/></label><label className="flex min-h-11 items-center gap-3"><input type="checkbox" checked={repeat.precision!=='day'} onChange={e=>editRepeat({...repeat,precision:e.target.checked?'minute':'day',startTime:'',endTime:''})}/>시간 입력 (선택)</label>{repeat.precision!=='day'&&<><label>시작 시각<input type="time" step={repeat.precision==='second'?1:60} className={fieldClass} value={repeat.startTime} onChange={e=>editRepeat({...repeat,startTime:e.target.value})}/></label><label>종료 시각<input type="time" step={repeat.precision==='second'?1:60} className={fieldClass} value={repeat.endTime} onChange={e=>editRepeat({...repeat,endTime:e.target.value})}/></label></>}</fieldset><button type="button" disabled={disabled} className={`${secondaryButton} mt-3`} onClick={()=>{try{const expanded=expandFilterRecurrence({...repeat,exceptions:repeat.exceptions.split(',').map(x=>x.trim()).filter(Boolean),startTime:repeat.precision==='day'?null:repeat.startTime,endTime:repeat.precision==='day'?null:repeat.endTime});set({kind:'occurrences',...expanded});onPending?.(false);setError('');}catch{setError('기간·요일·시각·예외 날짜를 확인해 주세요. 회차는 변경하지 않았습니다.');}}}>확인한 조건으로 회차 만들기</button>{error&&<p role="alert" className="mt-3 text-info-status">{error}</p>}</details></>}
  </div>;
}
export function FilterInputs({data,fields,onChange,disabled,onPending,missing=fields,saved,prefix="review",confirmed=[]}:{data:ContentFilters;fields:FilterKey[];onChange:(d:ContentFilters)=>void;disabled:boolean;onPending?:(v:boolean)=>void;missing?:string[];saved?:ContentFilters;prefix?:string;confirmed?:string[]}) {
  const set=(key:FilterKey,value:ContentFilters[FilterKey])=>onChange({...data,[key]:value});
  const select=(key:'topic'|'delivery'|'audience'|'spaceKind',options:Record<string,string>)=><select aria-label={reviewFilterLabel(data,key)} className={fieldClass} disabled={disabled} value={data[key].status==='known'?data[key].value:''} onChange={e=>{const v=e.target.value?known(e.target.value):unknown;const next={...data,[key]:v};if(key==='delivery')next.location=e.target.value==='online'?na:data.location.status==='not_applicable'?unknown:data.location;if(key==='spaceKind')next.location=e.target.value==='news'?na:data.location.status==='not_applicable'?unknown:data.location;onChange(next as ContentFilters);}}><option value="" disabled>선택해 주세요</option>{Object.entries(options).map(([v,label])=><option key={v} value={v}>{label}</option>)}</select>;
  return <div className="space-y-6">{fields.map(key=><fieldset key={key} id={`${prefix}-filter-${key}`} data-filter-key={key} tabIndex={-1} disabled={disabled} className="scroll-mt-36 min-w-0"><legend className="sr-only">{reviewFilterLabel(data,key)}</legend><div className={missing.includes(key)?`mb-4 ${reviewAttention}`:"mb-2"}><div className="flex flex-wrap items-center gap-y-2 font-semibold">{reviewFilterLabel(data,key)} <ReviewStatus needed={missing.includes(key)} confirmed={confirmed.includes(key)} changed={Boolean(saved && JSON.stringify(saved[key])!==JSON.stringify(data[key]))}/></div>{missing.includes(key)&&<p className="mt-2 font-semibold leading-6">{data[key].status==='unknown'?`${reviewFilterLabel(data,key)} 값을 원문에서 확인하여 입력해 주세요.`:"기존 값과 원문 근거를 대조한 뒤 확인·저장해 주세요."}</p>}</div>
    {key==='topic'&&select(key,data.category==='program'?programTopics:eventTopics)}
    {key==='delivery'&&select(key,{online:'온라인',onsite:'오프라인',mixed:'혼합'})}
    {key==='audience'&&<>{select(key,{children:'어린이 프로그램',other:'이외'})}<p className="mt-2 text-sm leading-6 text-info-muted">이외는 성인 전용 또는 연령 제한 없음을 뜻하지 않습니다.</p></>}
    {key==='spaceKind'&&select(key,{introduction:'공간 소개',news:'관련 소식'})}
    {key==='location'&&(data.location.status==='not_applicable'?<p className="text-info-muted">이 항목에는 지역 입력이 해당되지 않습니다.</p>:<><select aria-label="지역 범위" className={fieldClass} value={data.location.status==='known'?data.location.value.scope:''} onChange={e=>set(key,e.target.value?known({scope:e.target.value as 'specific'|'nationwide',venues:e.target.value==='specific'?[{province:'' as keyof typeof provinceLabels,district:null,facility:'',address:''}]:[]}):unknown)}><option value="" disabled>선택해 주세요</option><option value="specific">{reviewFilterLabel(data,'location')}</option><option value="nationwide">실제 전국 이용</option></select><p className="mt-2 text-sm leading-6 text-info-muted">거주 자격·기관 주소·집결 장소와 구분합니다. 원문에서 확인된 시·도까지만 지정해도 됩니다. 확인되지 않은 구·시설명·주소를 만들지 마세요.</p>{data.location.status==='known'&&data.location.value.scope==='specific'&&<div className="mt-4 space-y-5">{data.location.value.venues.map((v,i)=><div key={i} className="grid gap-3 sm:grid-cols-2">{(()=>{const loc=data.location;if(loc.status!=='known')return null;const edit=(patch:Partial<typeof v>)=>set(key,known({...loc.value,venues:loc.value.venues.map((x,n)=>n===i?{...x,...patch}:x)}));return <><label>시·도<select className={fieldClass} value={v.province} onChange={e=>edit({province:e.target.value as typeof v.province,district:null})}><option value="" disabled>선택해 주세요</option>{Object.entries(provinceLabels).map(([code,label])=><option key={code} value={code}>{label}</option>)}</select></label><label>시·군·구 (선택)<select className={fieldClass} value={v.district??''} onChange={e=>edit({district:e.target.value||null})}><option value="" disabled>선택해 주세요</option>{(districtChoices[v.province]??[]).map(d=><option key={d}>{d}</option>)}</select>{v.district&&<button type="button" className={`${secondaryButton} mt-2`} onClick={()=>edit({district:null})}>시·군·구 선택 해제</button>}</label><label>시설명 (선택)<input className={fieldClass} maxLength={200} value={v.facility} onChange={e=>edit({facility:e.target.value})}/></label><label>상세 주소 (선택)<input className={fieldClass} maxLength={500} value={v.address} onChange={e=>edit({address:e.target.value})}/></label>{loc.value.venues.length>1&&<button type="button" className={secondaryButton} onClick={()=>set(key,known({...loc.value,venues:loc.value.venues.filter((_,n)=>n!==i)}))}>이 장소 제거</button>}</>;})()}</div>)}<button type="button" className={secondaryButton} disabled={data.location.value.venues.length>=20} onClick={()=>{if(data.location.status==='known')set(key,known({...data.location.value,venues:[...data.location.value.venues,{province:'' as keyof typeof provinceLabels,district:null,facility:'',address:''}]}));}}>{data.category==='youth_space'?'소재지 추가':'개최지 추가'}</button></div>}</>)}
    {key==='application'&&(()=>{const a:FilterApplication=data.application.status==='known'?data.application.value:{deadlineKind:'fixed',start:null,end:null,sourceStatus:'unknown'};const edit=(patch:Partial<FilterApplication>)=>set(key,known({...a,...patch}));return <div className="space-y-4"><label className="block">마감 정보<select className={fieldClass} value={data.application.status==='known'?a.deadlineKind:''} onChange={e=>e.target.value?edit({deadlineKind:e.target.value as 'fixed'|'none',end:e.target.value==='none'?null:a.end}):set(key,unknown)}><option value="" disabled>선택해 주세요</option><option value="fixed">확인된 마감일 있음</option><option value="none">원래 마감일 없음</option></select></label><p className="text-sm leading-6 text-info-muted">날짜만 입력하면 마감일 당일까지 포함합니다. 원문에 시간이 있으면 선택 입력할 수 있습니다. 기존 사실의 신청기간과 다른 날짜를 입력하지 마세요.</p><EndpointInput label="신청 시작 (확인된 경우)" value={a.start} disabled={disabled} onChange={v=>edit({start:v})}/>{a.deadlineKind==='fixed'&&<EndpointInput label="신청 마감" value={a.end} disabled={disabled} onChange={v=>edit({end:v})}/>}<ReceptionStatus value={a.sourceStatus} disabled={disabled} onChange={sourceStatus=>edit({sourceStatus})}/></div>;})()}
    {key==='schedule'&&<ScheduleInput value={data.schedule} onChange={v=>set(key,v)} disabled={disabled} onPending={onPending}/>}
  </fieldset>)}</div>;
}
export function SavedFilterValues({saved,data,onChange,disabled,missing,confirmed,version,onEditing}:{saved:ContentFilters;data:ContentFilters;onChange:(v:ContentFilters)=>void;disabled:boolean;missing:string[];confirmed:FilterKey[];version:string;onEditing:(key:FilterKey|null)=>void}) {
  const [editing,setEditing]=useState<FilterKey|null>(null),[working,setWorking]=useState<ContentFilters|null>(null),[openedVersion,setOpenedVersion]=useState(''),[pending,setPending]=useState(false),[error,setError]=useState('');
  const region=useRef<HTMLDetailsElement>(null);
  function close(key:FilterKey){setEditing(null);setWorking(null);setPending(false);setError('');onEditing(null);region.current?.querySelector<HTMLButtonElement>(`[data-edit-filter="${key}"]`)?.focus();}
  const stale=Boolean(editing&&openedVersion!==version);
  return <details ref={region} className="mt-5" onToggle={e=>{if(editing&&!e.currentTarget.open)e.currentTarget.open=true;}}><summary className="cursor-pointer py-3 font-semibold">현재 저장값 확인·수정</summary>
    <p className="mb-3 text-sm leading-6 text-info-muted">변경 적용은 검토 초안에 반영합니다. 실제 저장은 아래 확인·저장 버튼으로 진행합니다. 사실·기간과 충돌하는 변경은 기존 서버 검증에 따라 거절될 수 있습니다.</p>
    <dl>{categoryFilterFields(data).filter(k=>saved[k].status!=='not_applicable'||data[k].status!=='not_applicable').map(key=>{
      const changed=JSON.stringify(saved[key])!==JSON.stringify(data[key]);
      return <div key={key} className="border-t border-info-rule py-4" data-saved-filter={key}><dt className="flex flex-wrap items-center justify-between gap-3"><span className="font-semibold">{reviewFilterLabel(data,key)}<ReviewStatus needed={missing.includes(key)} confirmed={confirmed.includes(key)} changed={changed}/></span><button type="button" data-edit-filter={key} aria-label={`${reviewFilterLabel(data,key)} 수정`} className={secondaryButton} disabled={disabled||editing!==null} onClick={()=>{setEditing(key);setWorking(structuredClone(data));setOpenedVersion(version);setPending(false);setError('');onEditing(key);}}>수정</button></dt>
        <dd className="mt-2 min-w-0 break-words text-sm leading-6"><p>저장값: {filterValueLabel(saved,key)}</p>{changed&&<p className="mt-2 font-semibold text-info-body">변경할 값: {filterValueLabel(data,key)}</p>}
        {editing===key&&working&&<div className="mt-4 space-y-4" role="group" aria-label={`${reviewFilterLabel(data,key)} 편집`} onKeyDown={e=>{if(e.key==='Escape'&&!disabled){e.preventDefault();e.stopPropagation();close(key);}}}><FilterInputs key={key} data={working} fields={[key]} onChange={setWorking} disabled={disabled||stale} onPending={setPending} missing={missing.includes(key)?[key]:[]} saved={saved} confirmed={confirmed} prefix="saved-edit"/>
          {stale&&<p role="alert" className="text-info-status">저장 버전이 변경됐습니다. 입력을 보존했습니다. 취소 후 최신 저장값을 확인하여 다시 수정해 주세요.</p>}
          {error&&<p role="alert" className="text-info-status">{error}</p>}
          <div className="flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={disabled||stale||pending} onClick={()=>{try{const invalid=region.current?.querySelector<HTMLInputElement>('input:invalid,select:invalid');if(invalid){invalid.reportValidity();setError('선택한 추가 입력을 완료해 주세요. 입력은 유지합니다.');return;}onChange(parseContentFilters(working));close(key);}catch{setError('선택값·지역·날짜 형식을 확인해 주세요. 입력은 유지하며 저장하지 않습니다.');}}}>변경 적용</button><button type="button" className={secondaryButton} disabled={disabled} onClick={()=>close(key)}>취소</button></div>
          <p className="text-info-muted">변경 적용 전에는 기존 초안을 유지합니다. 취소하면 이번 편집만 취소합니다.</p>
        </div>}</dd></div>;
    })}</dl></details>;
}

export default function FilterReviewPanel({id,version,info,disabled,onBlocked,onSaved}:{id:string;version:string;info:FilterInfo;disabled:boolean;onBlocked:(v:boolean)=>void;onSaved:()=>Promise<void>}) {
  const [draft,setDraft]=useState(()=>structuredClone(info.data)),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const sending=useRef(false);
  const [pendingRepeat,setPendingRepeat]=useState(false),[resetKey,setResetKey]=useState(0);
  const [editing,setEditing]=useState<FilterKey|null>(null);
  const fields=[...new Set([...filterReviewFields(info),...changedFilterFields(info.data,draft)])];
  const dirty=pendingRepeat||JSON.stringify(draft)!==JSON.stringify(info.data);
  useEffect(()=>{onBlocked(busy||dirty||editing!==null);return()=>onBlocked(false);},[busy,dirty,editing,onBlocked]);
  useEffect(()=>{if(!dirty&&editing===null)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty,editing]);

  return <section className="my-8 border-y border-info-rule py-6" aria-label="탐색 필터 확인"><h3 className="text-lg font-bold">{filterCategoryLabels[info.data.category]} 필터 확인</h3><p className="my-3 text-sm leading-6 text-info-muted">저장된 원문과 현재 사실을 확인한 뒤 선택합니다. 해당 카테고리의 값을 선택합니다. 다른 사실 확인사항은 그대로 유지합니다.</p>
    <form onSubmit={async e=>{e.preventDefault();if(sending.current||disabled||editing!==null)return;if(pendingRepeat){setError('편집한 반복 조건으로 회차를 만든 뒤 저장해 주세요. 입력은 유지합니다.');return;}let body;try{body=filterSaveBody(info,version,draft,fields);}catch{setError('선택값·지역·날짜 형식을 확인해 주세요. 입력은 유지했습니다.');return;}sending.current=true;setBusy(true);setError('');try{await saveFilterRequest(id,body);await onSaved();}catch(e){setError(e instanceof Error?e.message:'저장 결과를 확인하지 못했습니다. 입력을 유지합니다.');}finally{setBusy(false);sending.current=false;}}}>
      <FilterInputs key={resetKey} onPending={setPendingRepeat} data={draft} fields={fields.filter(k=>k!==editing)} onChange={setDraft} disabled={disabled||busy||editing!==null} missing={info.missing} saved={info.data} confirmed={confirmedFilterFields(info)}/>
      <SavedFilterValues key={`saved-${resetKey}`} saved={info.data} data={draft} onChange={setDraft} disabled={disabled||busy} missing={info.missing} confirmed={confirmedFilterFields(info)} version={version} onEditing={setEditing}/>
      {error&&<p role="alert" className="mt-4 leading-7 text-info-status">{error}</p>}
      <div className="mt-5 flex flex-wrap gap-3"><button type="submit" className={primaryButton} disabled={disabled||busy||editing!==null||!fields.length}>{busy?'저장 중…':'이 값으로 확인·저장'}</button>{dirty&&<button type="button" className={secondaryButton} disabled={busy||editing!==null} onClick={()=>{setDraft(structuredClone(info.data));setPendingRepeat(false);setResetKey(k=>k+1);setError('');}}>입력 취소</button>}</div>
    </form>
  </section>;
}

export function filterValueLabel(data:ContentFilters,key:FilterKey):string {
 const f=data[key];if(f.status!=='known')return f.status==='unknown'?'입력 전':'해당 없음';
 if(key==='topic'){const options:Record<string,string>=data.category==='program'?programTopics:eventTopics;return options[String(f.value)]??String(f.value);}
 if(key==='delivery')return {online:'온라인',onsite:'오프라인',mixed:'혼합'}[String(f.value) as 'online'];
 if(key==='audience')return f.value==='children'?'어린이 프로그램':'이외';
 if(key==='spaceKind')return f.value==='introduction'?'공간 소개':'관련 소식';
 if(key==='location'&&data.location.status==='known'){const v=data.location.value;return v.scope==='nationwide'?'실제 전국 이용':v.venues.map(x=>[provinceLabels[x.province],x.district??'시·도까지만 지정',x.facility,x.address].filter(Boolean).join(' · ')).join(' / ');}
 if(key==='application'&&data.application.status==='known'){const a=data.application.value;return `${a.start?.value??'시작 미확인'} → ${a.deadlineKind==='none'?'원래 마감일 없음':a.end?.value??'마감 미확인'} · ${ {not_started:'신청 전',open:'접수 중',closed:'마감',unknown:'접수 상태 별도 지정 없음'}[a.sourceStatus]}`;}
 if(key==='schedule'&&data.schedule.status==='known')return data.schedule.value.occurrences.map(o=>o.start.value===o.end.value?o.start.value:`${o.start.value} ~ ${o.end.value}`).join(' / ');
 return '미확인';
}
export function CandidateFilterComparison({info}:{info:CandidateFilterInfo}) {
 const fields=filterKeys.filter(k=>[info.input,info.approved,info.current].some(d=>d[k].status!=='not_applicable'));
 return <section className="my-6 border-y border-info-rule py-4" aria-label="후보의 탐색 정보"><h3 className="font-semibold">탐색 정보</h3><p className="mt-2 leading-7 text-info-body">생성 당시 버전 {info.inputVersion} · 후보에 반영된 버전 {info.approvedVersion} · 현재 확정 버전 {info.currentVersion}</p>{info.changed&&<p role="status" className="mt-2 text-info-status">생성 후 탐색 정보가 변경됐습니다. 후보 내용과 현재 확정값을 확인한 뒤 수정 저장하면 현재 탐색 정보도 후보에 반영됩니다. 생성 당시 입력은 보존됩니다.</p>}<details className="mt-3"><summary className="cursor-pointer py-3 font-semibold">생성 당시·후보·현재 탐색값 비교</summary><dl>{fields.map(k=><div key={k} className="border-t border-info-rule py-4"><dt className="font-semibold">{reviewFilterLabel(info.current,k)}</dt><dd className="mt-2 grid gap-3 sm:grid-cols-3">{(['input','approved','current'] as const).map((stage,i)=><p key={stage} className="min-w-0 break-words text-sm leading-6"><span className="block text-info-muted">{['생성 당시 입력','후보 반영값','현재 확정값'][i]}</span>{filterValueLabel(info[stage],k)}</p>)}</dd></div>)}</dl></details></section>;
}
