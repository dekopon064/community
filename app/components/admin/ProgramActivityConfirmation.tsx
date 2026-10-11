'use client';
import {useEffect,useRef,useState} from 'react';
import {FilterInputs} from './FilterReviewPanel';
import {ReviewStatus} from './ReviewStates';
import {programCommand} from '@/app/lib/review/program-contract';
import type {ProgramCommand} from '@/app/lib/review/program-contract';
import type {programItem} from '@/app/lib/review/program-store';
import {fieldClass,primaryButton,secondaryButton} from './ReviewEditors';

type Item=ReturnType<typeof programItem>;
export default function ProgramActivityConfirmation({item,disabled,onBlocked,onSubmit}:{item:Item;disabled:boolean;onBlocked:(v:boolean)=>void;onSubmit:(v:ProgramCommand)=>Promise<void>}) {
 const [data,setData]=useState(()=>structuredClone(item.filterInfo!.data));
 const [note,setNote]=useState(''),[checked,setChecked]=useState(false),[error,setError]=useState('');
 const [openedVersion,setOpenedVersion]=useState(item.version);
 const sending=useRef(false);
 const dirty=checked||Boolean(note)||JSON.stringify(data)!==JSON.stringify(item.filterInfo!.data);
 useEffect(()=>{onBlocked(dirty);return()=>onBlocked(false);},[dirty,onBlocked]);
 useEffect(()=>{if(!dirty)return;const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue='';};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[dirty]);
 const stale=openedVersion!==item.version;
 const reset=()=>{setData(structuredClone(item.filterInfo!.data));setNote('');setChecked(false);setError('');setOpenedVersion(item.version);};
 return <form id="program-activity-confirm" tabIndex={-1} className="my-7 scroll-mt-36 border-y border-info-rule py-6" aria-label="실제 개최 지역 확인" onKeyDown={e=>{if(e.key==='Escape'&&!disabled){e.preventDefault();reset();e.currentTarget.focus();}}} onSubmit={async e=>{
   e.preventDefault();if(disabled||stale||sending.current||!checked)return;
   let command;try{command=programCommand({action:'confirm_activity',revision:item.revision,version:item.version,factsVersion:item.factsVersion,filterVersion:item.filterInfo!.filterVersion,filters:{location:data.location,delivery:data.delivery},note});}catch{setError('실제 진행 방식과 서울·인천·경기 개최 지역, 확인 근거를 입력해 주세요. 입력은 유지합니다.');return;}
   sending.current=true;setError('');try{await onSubmit(command);}finally{sending.current=false;}
 }}>
 <h3 className="font-bold">실제 개최 지역 확인 <ReviewStatus needed confirmed={false} changed={false}/></h3>
 <p className="my-3 text-sm leading-6 text-info-body">원문에서 확인한 진행 방식과 개최 지역을 저장합니다. 기존 값이 같아도 확인 기록을 남길 수 있습니다.</p>
 <FilterInputs data={data} fields={['delivery','location']} onChange={setData} disabled={disabled||stale} missing={['location']} saved={item.filterInfo!.data} prefix="program-activity"/>
 <label htmlFor="program-activity-note" className="mt-5 block font-semibold">개최 지역 확인 근거</label>
 <textarea id="program-activity-note" className={fieldClass} rows={2} required maxLength={4000} disabled={disabled} value={note} onChange={e=>setNote(e.target.value)}/>
 <label className="mt-4 flex min-h-11 items-start gap-3 leading-7"><input type="checkbox" className="mt-2 size-5 shrink-0" disabled={disabled} checked={checked} onChange={e=>setChecked(e.target.checked)}/>원문과 대조해 실제 개최 지역을 확인했습니다.</label>
 {error&&<p role="alert" className="mt-3 text-info-status">{error}</p>}
 {stale&&<p role="alert" className="mt-3 text-info-status">저장 버전이 변경되어 입력을 보존했습니다. 최신 값을 확인한 뒤 입력을 취소하고 다시 확인해 주세요.</p>}
 <div className="mt-4 flex flex-wrap gap-3"><button className={primaryButton} type="submit" disabled={disabled||stale||!checked||!note.trim()}>개최 지역 확인·저장</button>{(dirty||stale)&&<button type="button" className={secondaryButton} disabled={disabled} onClick={reset}>입력 취소</button>}</div>
 <p className="mt-3 text-sm leading-6 text-info-muted">선택만으로 확인 완료가 되지 않습니다. 개최 지역 확인과 해당 필터는 함께 저장하며, 다른 사실·필터 저장은 기존 절차를 사용합니다.</p>
 </form>;
}
