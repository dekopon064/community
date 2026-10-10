"use client";
import {useEffect,useRef,useState} from 'react';
import type {MySeoulCommand} from '@/app/lib/review/myseoul-contract';
import type {myseoulItem} from '@/app/lib/review/myseoul-store';
import {fieldClass,primaryButton,secondaryButton} from './ReviewEditors';

export default function MySeoulResidenceReview({item,disabled,regionExcludeDisabled=false,onDirty,onSave,onRegionExclude}:{item:ReturnType<typeof myseoulItem>;disabled:boolean;regionExcludeDisabled?:boolean;onDirty:(dirty:boolean)=>void;onSave:(command:MySeoulCommand)=>void;onRegionExclude:(trigger:HTMLButtonElement)=>void}) {
  const initialRestricted=['capital','includes_capital','noncapital_only'].includes(String(item.facts.residence_scope));
  const [restricted,setRestricted]=useState(initialRestricted),[scope,setScope]=useState(initialRestricted?String(item.facts.residence_scope):'capital');
  const [condition,setCondition]=useState(String(item.facts.residence)),[evidence,setEvidence]=useState((item.facts.residence_evidence as string[]).join('\n'));
  const [editEvidence,setEditEvidence]=useState(false),[unknown,setUnknown]=useState(false);
  const pending=useRef<{key:string;id:string}|null>(null);
  // Choosing the exclusion route is an action selection, not a fact edit.
  // Any edited condition/evidence still blocks exclusion until cancelled.
  const changed=condition!==item.facts.residence || evidence!==(item.facts.residence_evidence as string[]).join('\n') || !(restricted&&scope==='noncapital_only')&&(restricted!==initialRestricted || restricted&&scope!==item.facts.residence_scope);
  useEffect(()=>{onDirty(changed);return ()=>onDirty(false);},[changed,onDirty]);
  function save() {
    const body={action:'confirm_residence' as const,revision:item.revision,version:item.version,restricted,scope:restricted?scope:'',condition:restricted?condition:'',evidence:restricted?evidence.split('\n').map(s=>s.trim()).filter(Boolean):[]};
    const key=JSON.stringify(body);if(pending.current?.key!==key)pending.current={key,id:crypto.randomUUID()};
    onSave({...body,requestId:pending.current.id});
  }
  return <div className="space-y-4">
    <p className="text-sm leading-6">원문의 참여 대상과 신청 조건을 확인해 주세요. 개최 지역 필터와는 별개입니다.</p>
    {Boolean(item.facts.residence) && <p className="whitespace-pre-wrap text-sm">현재 거주 조건: {String(item.facts.residence)}</p>}
    <label className="flex min-h-11 items-center gap-3 font-semibold"><input type="checkbox" checked={restricted} disabled={disabled} onChange={e=>{setRestricted(e.target.checked);setUnknown(false);}}/>거주 지역 제한 있음</label>
    {restricted ? <div className="space-y-4">
      <label className="block font-semibold" htmlFor="residence-scope">참가 가능한 지역<select id="residence-scope" className={fieldClass} value={scope} disabled={disabled} onChange={e=>setScope(e.target.value)}><option value="capital">수도권 내 거주 조건 있음</option><option value="includes_capital">수도권을 포함하는 참가 조건</option><option value="noncapital_only">비수도권 주민만 참가 가능</option></select></label>
      {scope==='noncapital_only' ? <><p>비수도권 주민 전용은 대상 지역 제외로 처리합니다. 확인한 다른 입력을 먼저 저장하거나 취소해 주세요.</p><button type="button" className={secondaryButton} disabled={disabled||regionExcludeDisabled||changed} onClick={e=>onRegionExclude(e.currentTarget)}>대상 지역이 아님 · 제외 확인</button></> : <>
        <label htmlFor="residence-condition" className="block font-semibold">제한 조건<textarea id="residence-condition" className={fieldClass} rows={2} maxLength={4000} value={condition} disabled={disabled} onChange={e=>setCondition(e.target.value)}/></label>
        {evidence.trim() && !editEvidence && <p className="whitespace-pre-wrap text-sm">원문 근거: {evidence}</p>}
        <button type="button" className={secondaryButton} disabled={disabled} onClick={()=>setEditEvidence(v=>!v)}>{editEvidence?'근거 입력 접기':'원문 근거 수정·보충'}</button>
        {(editEvidence||!evidence.trim()) && <label htmlFor="residence-evidence" className="block font-semibold">원문에서 확인한 근거<textarea id="residence-evidence" className={fieldClass} rows={2} maxLength={4000} value={evidence} disabled={disabled} onChange={e=>setEvidence(e.target.value)}/></label>}
      </>}
    </div> : <p className="text-sm leading-6">확인·저장을 눌러야 제한 없음 판단이 기록됩니다. 원문에 제한 없음이 명시되었다는 사실로 저장하지 않습니다.</p>}
    <div className="flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={disabled||unknown||restricted&&(scope==='noncapital_only'||!condition.trim()||!evidence.trim())} onClick={save}>{restricted?'거주 조건 확인·저장':'제한 없음으로 판단 · 확인·저장'}</button><button type="button" className={secondaryButton} disabled={disabled} onClick={()=>setUnknown(true)}>판단할 수 없음</button></div>
    {changed && <><p className="font-semibold" role="status">미저장 변경 · 거주 조건</p><button type="button" className={secondaryButton} disabled={disabled} onClick={()=>{setRestricted(initialRestricted);setScope(initialRestricted?String(item.facts.residence_scope):'capital');setCondition(String(item.facts.residence));setEvidence((item.facts.residence_evidence as string[]).join('\n'));setUnknown(false);}}>거주 조건 입력 취소</button></>}
    {unknown && <><p role="status">판단 불가 · 검토 상태를 유지합니다.</p><button type="button" className={secondaryButton} disabled={disabled} onClick={()=>setUnknown(false)}>원문 다시 확인하고 판단</button></>}
  </div>;
}
