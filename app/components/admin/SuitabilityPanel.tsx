'use client';
import {useEffect,useRef,useState} from 'react';
import type {WorkerRun} from '@/app/lib/pc-worker/contracts';
import {workerSources} from '@/app/lib/pc-worker/contracts';
import type {SuitabilityReport, SuitabilityRow} from '@/app/lib/review/suitability';
import {primaryButton,secondaryButton} from './ReviewEditors';

const groups = {exclude:'제외 권장',check:'확인 필요',keep:'적합 제안'} as const;
const outcomes = {moved:'이동 완료',skipped:'상태·버전 변경으로 건너뜀',failed:'이동 실패',unknown:'결과 불명',unprocessed:'미처리'} as const;
type Outcome = keyof typeof outcomes;
function canSelect(row:SuitabilityRow, result?:Outcome) {
  return row.state==='done' && !row.moved && (!result || result==='failed' || result==='unprocessed');
}
const endpoint = '/api/admin/suitability';
async function readReport(id?:string,signal?:AbortSignal):Promise<SuitabilityReport|null> {
  const response = await fetch(endpoint+(id?'?run='+id:''),{cache:'no-store',credentials:'same-origin',signal});
  if (!response.ok) throw Error('read_failed');
  const {report} = await response.json();
  if (report && (!Array.isArray(report.items) || (id && report.id!==id))) throw Error('invalid_report');
  return report;
}

export default function SuitabilityPanel({locked,disabled,run,start}:{locked:boolean;disabled:boolean;run?:WorkerRun;start:()=>void}) {
  const [report,setReport] = useState<SuitabilityReport|null>(null);
  const [checked,setChecked] = useState<string[]>([]);
  const [confirm,setConfirm] = useState(false);
  const [saving,setSaving] = useState(false);
  const [results,setResults] = useState<Record<string,Outcome>>({});
  const [lastBatch,setLastBatch] = useState<string[]>([]);
  const [notice,setNotice] = useState('');
  const [refresh,setRefresh] = useState(0);
  const submitting = useRef(false);
  const startPending = useRef(false);
  const requestId = run?.requestId;
  const active = run?.state==='running';
  useEffect(()=>{
    startPending.current=false;
    setChecked([]); setConfirm(false); setResults({}); setLastBatch([]);
  },[requestId]);
  useEffect(()=>{ if(!locked) startPending.current=false; },[locked]);
  useEffect(()=>{
    const controller = new AbortController();
    if (active) return;
    readReport(requestId,controller.signal).then(value=>{
      if (!controller.signal.aborted) {
        setReport(value);setNotice('');
        const moved = new Set(value?.items.filter(row=>row.moved).map(row=>row.id));
        setChecked(old=>old.filter(id=>!moved.has(id)));
      }
    }).catch(()=>{if(!controller.signal.aborted) setNotice('점검 결과를 읽지 못했습니다. 결과를 다시 확인해 주세요.');});
    return ()=>controller.abort();
  },[requestId,active,refresh]);
  const items = report?.items ?? [];
  const selected = items.filter(row=>checked.includes(row.id) && canSelect(row,results[row.id]));
  const counts = {moved:0,failed:0,unprocessed:0,skipped:0,unknown:0};
  const movedIds = new Set(items.filter(row=>row.moved).map(row=>row.id));
  for(const id of lastBatch) {
    const outcome = results[id];
    if(outcome) counts[outcome==='unknown' && movedIds.has(id) ? 'moved' : outcome]++;
  }
  const busy = disabled || saving || active || !!(requestId && report?.id!==requestId);
  async function move() {
    if(!report || busy || submitting.current || !confirm || !selected.length) return;
    submitting.current=true; setSaving(true); setConfirm(false);
    const updates:Record<string,Outcome>={};
    try {
      for(const row of selected) {
        try {
          const params=new URLSearchParams({run:report.id,item:row.id,request:crypto.randomUUID()});
          const reply=await fetch(endpoint+'?'+params,{method:'POST',credentials:'same-origin',cache:'no-store'});
          if(!reply.ok) {
            if([401,403,422].includes(reply.status)) {updates[row.id]='failed';break;}
            throw Error('unconfirmed');
          }
          const data=await reply.json();
          if(data.id!==row.id || !['moved','skipped','failed'].includes(data.result)) throw Error('unconfirmed');
          updates[row.id]=data.result;
        } catch {
          updates[row.id]='unknown';
          break;
        }
      }
      const batchIds = selected.map(row=>row.id);
      for(const id of batchIds) updates[id] ??= 'unprocessed';
      setResults(old=>({...old,...updates}));
      setLastBatch(batchIds);
      setChecked(old=>old.filter(id=>updates[id]!=='moved' && updates[id]!=='skipped'));
      setRefresh(n=>n+1); // read-only reconciliation, including a lost POST response
    } finally {submitting.current=false;setSaving(false);}
  }
  function display(row:SuitabilityRow) {
    const result=row.moved?'moved':results[row.id];
    return <li key={row.id} className="space-y-1 border-b border-info-rule py-3">
      <label className="flex items-baseline gap-2 font-semibold"><input type="checkbox" disabled={busy || confirm || !canSelect(row,result)}
        checked={!row.moved && checked.includes(row.id)} onChange={e=>setChecked(old=>e.target.checked?[...old,row.id]:old.filter(id=>id!==row.id))}/>{row.title}</label>
      <p className="text-sm text-info-muted">{workerSources[row.source]} · {row.key} · {row.queue==='facts'?'사람 사실 review':'AI 작업 대기'}{row.reused?' · 기존 판정':''}{result?' · '+outcomes[result]:''}</p>
      <p>{row.decision?.clause} · {row.decision?.reason}</p>
      {row.decision?.quote && <blockquote className="border-l-2 border-info-rule pl-3">{row.decision.quote}</blockquote>}
      {row.decision?.question && <p>확인할 점　{row.decision.question}</p>}
      {row.decision?.note && <p>참고　{row.decision.note}</p>}
    </li>;
  }
  return <section aria-label="콘텐츠 적합성 점검" className="mt-5 space-y-3 border-t border-info-rule pt-4">
    <div className="flex flex-wrap items-center gap-2"><button type="button" disabled={locked || saving || active} className={primaryButton} onClick={()=>{
      if(startPending.current) return; startPending.current=true;start();
    }}>미판정 콘텐츠 적합성 점검</button>
    <button type="button" className={secondaryButton} disabled={saving || active} onClick={()=>setRefresh(n=>n+1)}>점검 결과 다시 확인</button></div>
    {active && <p role="status">적합성 점검 중 · 새 판정 {run?.counts.classified??0}건</p>}
    {run?.code==='policy_unavailable' && <p role="alert">Drive에서 최신 확정 지침을 읽지 못했습니다. 판정을 시작하지 않았습니다.</p>}
    {run && !active && ['stopped','unknown','failed','auth_required','partial'].includes(run.state) && run.code!=='policy_unavailable' &&
      <p role="alert">점검 결과 확인이 필요합니다. 완료된 판정은 아래에서 확인할 수 있습니다.</p>}
    {run?.state==='auth_required' && <p role="status">PC 실행기의 Pro 계정 연결을 확인해 주세요. 호출 전 항목은 미판정으로 남습니다.</p>}
    {notice && <p role="alert">{notice}</p>}
    {report && !active && (!requestId || report.id===requestId) && <>
      <p>확정 지침 {report.policy} · 조회 {new Date(report.readAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} (한국시간)</p>
      {items.length>0 && <p>{Object.entries(workerSources).map(([source,label])=>{
        const rows=items.filter(row=>row.source===source);
        return rows.length ? label+' '+rows.length+'건 (기존 판정 '+rows.filter(row=>row.reused).length+'건)' : '';
      }).filter(Boolean).join(' · ')}</p>}
      {!items.length && <p>점검 대상이 없습니다.</p>}
      {items.some(row=>row.decision && !row.moved) && <p className="text-sm text-info-muted">휴지통으로 옮길 항목만 체크하세요.</p>}
      {Object.entries(groups).map(([group,label])=>{
        const rows=items.filter(row=>row.decision?.group===group);
        return rows.length>0 && <div key={group}><h3 className="font-semibold">{label} {rows.length}건</h3><ul>{rows.map(display)}</ul></div>;
      })}
      {items.some(row=>row.state!=='done') && <details><summary>판정 미확정 {items.filter(row=>row.state!=='done').length}건</summary>
        <ul>{items.filter(row=>row.state!=='done').map(row=><li key={row.id}>{row.title} · {row.state==='waiting'?'미처리':'응답·저장 확인 필요'}</li>)}</ul></details>}
      {lastBatch.length>0 && <p role="status">최근 이동 요청 {lastBatch.length}건 · 이동 성공 {counts.moved}건 · 실패 {counts.failed}건 · 미처리 {counts.unprocessed}건
        {counts.skipped>0 && ' · 상태·버전 변경으로 건너뜀 '+counts.skipped+'건'}
        {counts.unknown>0 && ' · 결과 불명 '+counts.unknown+'건 (점검 결과 다시 확인)'}</p>}
      {items.some(row=>row.state==='done' && !row.moved) && <button type="button" className={secondaryButton} disabled={busy || confirm || !selected.length}
        onClick={()=>setConfirm(true)}>선택한 {selected.length}건 휴지통으로 이동</button>}
      {confirm && <div role="group" aria-label="선택한 콘텐츠 제외 확인"><p>아래 항목을 ‘서비스에 적합하지 않음’으로 제외합니다. AI 대기 작업도 함께 중지됩니다.</p>
        <ul>{selected.map(row=><li key={row.id}>{row.title}</li>)}</ul>
        <button type="button" className={secondaryButton} onClick={()=>setConfirm(false)}>취소</button>
        <button type="button" className={primaryButton} disabled={busy} onClick={()=>void move()}>확인하고 이동</button></div>}
    </>}
  </section>;
}
