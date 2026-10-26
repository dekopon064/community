"use client";
import { createContext,useContext,useEffect,useRef,useState } from 'react';
import type { ReactNode } from 'react';
import { PcWorkerClient } from '@/app/lib/pc-worker/client';
import type { PcWorkerView } from '@/app/lib/pc-worker/client';
import { workerSources,workerCatalog } from '@/app/lib/pc-worker/contracts';
import type { WorkerCommand,WorkerRun } from '@/app/lib/pc-worker/contracts';
import { fieldClass,primaryButton,secondaryButton } from './ReviewEditors';
const stateText={running:'처리 중',completed:'완료',partial:'일부 실패',failed:'실패',stopped:'처리 중단',unknown:'결과 확인 필요',auth_required:'Pro 인증 확인 필요'};
const countText:Record<string,string>={scanned:'조회',target:'선별',existing_skipped:'기존 중복',new_saved:'신규 저장',
  review_waiting:'사람 검토 대기',ai_waiting:'AI 대기',failed:'실패',invalid_id_count:'잘못된 식별값',status_excluded:'상태 제외',
  audience_excluded:'대상 제외',request_count:'HTTP 요청',requests:'HTTP 요청',selected:'선택',completed:'후보 생성',
  unavailable_skipped:'현재 처리 불가·건너뜀',state_skipped:'상태 건너뜀',state_unknown:'결과 불명',unprocessed:'미처리',
  other_source:'다른 수집원',eligible:'실행 가능',inserted:'신규',updated:'갱신',unchanged:'변경 없음',excluded:'제외',created:'신규',skipped:'건너뜀',total:'전체',duplicates:'중복',review:'사람 검토',ai:'AI 대기',
  discovered:'목록 발견',new:'신규 발견',known:'기존 확인',closed_skipped:'마감 제외',processed:'상세 처리',pending_remaining:'상세 미처리',carried_selected:'이전 미처리 선택',list_pages:'목록 페이지',selected_sources:'선택 수집원',completed_sources:'완료 수집원',unprocessed_sources:'미처리 수집원',processed_items:'진행',chunks_total:'전체 묶음',chunks_done:'완료 묶음',snapshot_read_pages:'목록 확인'};
const errorText:Record<string,string>={signed_out:'관리자 로그인 상태를 다시 확인해 주세요.',forbidden:'운영자 권한을 확인해 주세요.',
  wrong_origin:'허용된 관리자 페이지에서 연결해 주세요.',worker_busy:'PC에서 다른 작업을 처리하고 있습니다.',
  connection_expired:'PC 연결이 만료됐습니다. 다시 연결해 주세요.',invalid_capability:'실행기와 관리자 서버의 프로젝트·연결 설정을 확인해 주세요.',
  result_unknown:'실행 결과를 확인하지 못했습니다. 다시 실행하지 않고 최신 상태만 조회합니다.',
  worker_unavailable:'PC 연결을 확인하지 못했습니다. 실행기와 브라우저의 로컬 네트워크 접근 허용 상태를 확인해 주세요.'};
const initial:PcWorkerView={connection:'off',sending:false,busy:false,unknown:false,run:null,error:''};
type Control={view:PcWorkerView;runs:Partial<Record<WorkerCommand['kind'],WorkerRun>>;connect:()=>void;refresh:()=>void;run:(command:WorkerCommand)=>void};
const WorkerContext=createContext<Control|null>(null);
function useWorker(){const value=useContext(WorkerContext);if(!value)throw Error('pc_worker_context_required');return value;}
export function PcWorkerProvider({children}:{children:ReactNode}){
  const [view,setView]=useState(initial),[runs,setRuns]=useState<Control['runs']>({});
  const client=useRef<PcWorkerClient|null>(null);
  useEffect(()=>{const value=new PcWorkerClient(next=>{setView(next);if(next.run){const run=next.run;setRuns(old=>({...old,[run.command.kind]:run}));}});client.current=value;return()=>{value.dispose();client.current=null;};},[]);
  useEffect(()=>{
    if(view.connection!=='ready'||view.run?.state!=='running'||view.unknown)return;
    const timer=setInterval(()=>void client.current?.refresh(),2000);return()=>clearInterval(timer);
  },[view.connection,view.run?.state,view.unknown]);
  return <WorkerContext.Provider value={{view,runs,connect:()=>void client.current?.connect(),refresh:()=>void client.current?.refresh(),run:command=>void client.current?.run(command)}}>{children}</WorkerContext.Provider>;
}
function locked(view:PcWorkerView,disabled:boolean){return disabled||view.sending||view.busy||view.unknown||view.connection!=='ready';}
export default function PcWorkerPanel({disabled=false}:{disabled?:boolean}){
  const {view,connect,refresh,run}=useWorker();const [source,setSource]=useState('all');
  return <div className="mb-6 border-y border-info-rule py-4">
    <section aria-label="PC 연결" className="space-y-3">
      <p className="max-w-3xl text-sm leading-6 text-info-body">실행기를 켠 같은 PC의 브라우저에서 수동으로 실행합니다. 휴대폰에서는 이 PC에 직접 연결할 수 없습니다.</p>
      <div className="flex flex-wrap items-center gap-3"><p role="status" className="font-semibold text-info-body">{view.connection==='connecting'?'PC 연결 확인 중…':view.connection==='ready'?view.unknown?'PC 작업 결과 확인 필요':view.busy?'PC 작업 처리 중':'PC 연결됨':'PC 실행기를 연결해 주세요'}</p>
        <button type="button" className={secondaryButton} disabled={view.sending} onClick={connect}>{view.connection==='ready'?'PC 다시 연결':'PC 연결'}</button>
        {view.connection==='ready'&&<button type="button" className={secondaryButton} disabled={view.sending} onClick={refresh}>최신 실행 상태 확인</button>}
      </div>
      {view.error&&<p role="alert" className="leading-7 text-info-status">{errorText[view.error]??errorText.worker_unavailable}</p>}
    </section>
    <section aria-label="수집" className="mt-5 space-y-3 border-t border-info-rule pt-4">
      <h2 className="font-semibold">수집</h2>
      <div className="flex flex-wrap items-end gap-3"><label className="block min-w-0 flex-1 text-sm font-semibold">수집원<select className={fieldClass} value={source} disabled={view.sending||view.busy} onChange={e=>setSource(e.target.value)}><option value="all">전체 수집원</option>{workerCatalog.map(row=><option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
        <button type="button" className={primaryButton} disabled={locked(view,disabled)} onClick={()=>run({source,kind:'collect',limit:1})}>수집 실행</button></div>
      <p className="text-sm leading-6 text-info-muted">선택한 수집원을 1회 수집합니다. 전체는 아래 순서대로 실행하며, 실패·응답 불명에서는 남은 수집을 중단합니다. 수집만으로 AI를 실행하지 않습니다.</p>
      <ul className="space-y-1 text-sm leading-6 text-info-muted">{workerCatalog.filter(row=>source==='all'||row.id===source).map(row=><li key={row.id}>{row.label}: {row.collectionHint}</li>)}</ul>
      {disabled&&<p className="text-sm text-info-status">편집·저장 중인 내용을 먼저 정리해 주세요.</p>}
      <RunResult kind="collect"/>
    </section>
  </div>;
}
export function PcAiRunPanel({disabled=false}:{disabled?:boolean}){
  const {view,run}=useWorker();const [limit,setLimit]=useState<WorkerCommand['limit']>(1);
  return <section aria-label="AI 실행" className="my-5 space-y-3 border-y border-info-rule py-4">
    <h3 className="font-semibold">AI 실행</h3>
    <div className="flex flex-wrap items-end gap-3"><label className="block text-sm font-semibold">AI 처리 건수<select className={fieldClass} value={limit} disabled={view.sending||view.busy} onChange={e=>setLimit(e.target.value==='all'?'all':Number(e.target.value))}>{[1,5,10,25].map(value=><option key={value} value={value}>{value}</option>)}<option value="all">전체</option></select></label>
      <button type="button" className={primaryButton} disabled={locked(view,disabled)} onClick={()=>run({source:'all',kind:'ai',limit})}>AI 실행</button></div>
    <p className="max-w-3xl text-sm leading-6 text-info-muted">선택한 건수까지 처리합니다. 숫자 선택은 대기 목록 첫 25건에서, 전체는 시작 시 확인한 실행 가능한 항목을 고정해 25건씩 처리합니다. 실행 중 새 항목은 추가하지 않습니다. 건별 요약·번역은 각각 최대 1회, 후보 생성까지만 진행합니다.</p>
    <p className="text-sm leading-6 text-info-muted">서울 예약은 재시도 없는 항목별 실패 종료를 사용합니다. My서울+는 기존 실패 처리 계약을 유지하고 실패 시 이번 실행을 중단합니다. 공통 오류·응답 불명은 전체 중단합니다.</p>
    {view.connection!=='ready'&&<p className="text-sm text-info-status">검토 관리 상단에서 PC를 먼저 연결해 주세요.</p>}
    {disabled&&<p className="text-sm text-info-status">편집·저장 중인 내용을 먼저 정리해 주세요.</p>}
    <RunResult kind="ai"/>
  </section>;
}
function Counts({counts}:{counts:Record<string,number>}){
  return <ul className="mt-2 flex flex-wrap gap-x-6 gap-y-2 text-sm text-info-body">{Object.entries(counts).map(([key,value])=>countText[key]&&<li key={key}>{countText[key]} {value}{key.endsWith('_sources')||key.startsWith('chunks_')?'개':['list_pages','snapshot_read_pages'].includes(key)?'페이지':['requests','request_count'].includes(key)?'회':'건'}</li>)}</ul>;
}
function RunResult({kind}:{kind:WorkerCommand['kind']}){
  const {runs}=useWorker(),run=runs[kind];if(!run)return null;
  const counts=kind==='collect'&&run.sourceResults?.length?Object.fromEntries(Object.entries(run.counts).filter(([key])=>key.endsWith('_sources'))):run.counts;
  return <section aria-label={`최근 ${kind==='collect'?'수집':'AI'} 실행 결과`} aria-live="polite" className="border-t border-info-rule pt-4">
    <h3 className="font-semibold">{kind==='ai'?'AI 대기 항목':run.command.source==='all'?'전체 수집원':workerSources[run.command.source]} · {stateText[run.state]}</h3>
    {run.state==='auth_required'?<p className="mt-2 text-sm leading-6 text-info-status">기존 Pro 로그인 경로에서 인증을 확인해 주세요. 이 화면에서는 로그인을 자동으로 열거나 AI를 다시 호출하지 않습니다.</p>:<Counts counts={counts}/>}
    {!!run.sourceResults?.length&&<ul className="mt-3 space-y-3">{run.sourceResults.map(row=><li key={row.source}><p className="text-sm font-semibold">{workerSources[row.source]} · {stateText[row.state]}</p><Counts counts={row.counts}/></li>)}</ul>}
    {run.code==='queue_snapshot_changed'&&<p className="mt-2 text-sm leading-6 text-info-status">대상 확인 중 목록이 바뀌어 AI를 시작하지 않았습니다. 최신 목록을 확인한 뒤 새 실행을 요청해 주세요.</p>}
    {run.code==='queue_snapshot_invalid'&&<p className="mt-2 text-sm leading-6 text-info-status">대기 목록의 페이지·식별값을 확인하지 못해 AI를 시작하지 않았습니다.</p>}
    {run.code==='queue_snapshot_limit'&&<p className="mt-2 text-sm leading-6 text-info-status">대기 목록 확인의 안전 범위를 넘어 AI를 시작하지 않았습니다. 일부만 처리한 것을 전체 완료로 표시하지 않습니다.</p>}
    {run.code==='common_failure'&&<p className="mt-2 text-sm leading-6 text-info-status">공통 오류가 확인되어 나머지 항목을 실행하지 않았습니다.</p>}
    {run.code==='contract_unavailable'&&<p className="mt-2 text-sm leading-6 text-info-status">실행기의 연결 설정과 AI_PROVIDER=chatgpt_plan 설정을 확인해 주세요. 다른 API로 전환하지 않았습니다.</p>}
    {run.code==='retry_registered'&&<p className="mt-2 text-sm leading-6 text-info-status">기존 worker가 재시도 상태를 반환해 이번 실행을 중단했습니다. 같은 항목을 다시 호출하지 않습니다.</p>}
    <p className="mt-2 text-sm leading-6 text-info-muted">검토 목록은 기존 새로고침으로 확인해 주세요. 실행 기록이 없다는 표시만으로 이전 작업 완료를 판단하지 마세요.</p>
  </section>;
}
