"use client";
import {reviewOverview,ReviewStatus} from './ReviewStates';

import { FilterInputs, filterSaveBody, saveFilterRequest, filterValueLabel, reviewFilterLabel, filterCategoryLabels, SavedFilterValues, confirmedFilterFields, changedFilterFields } from './FilterReviewPanel';
import { filterLabels, parseContentFilters } from '@/app/lib/contentFilters';
import type { ContentFilters, FilterKey } from '@/app/lib/contentFilters';
import { assertMySeoulFilterContinuation, factsFromFilterSelection, mergeMySeoulFilters, myseoulFilterFields } from '@/app/lib/review/myseoul-filter-ui';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { myseoulItem } from '@/app/lib/review/myseoul-store';
import { myseoulReasonFields, myseoulGuidance, myseoulCommand } from '@/app/lib/review/myseoul-contract';
import type { MySeoulCommand, MySeoulFacts, MySeoulIssue, MySeoulPeriod } from '@/app/lib/review/myseoul-contract';
import { buildMySeoulSave, mergeMySeoulDraft, myseoulArrayFields, myseoulChoices, myseoulFeeLabels, myseoulLabels, myseoulPatch, reviewPeriodAxes, visibleMySeoulFields } from '@/app/lib/review/myseoul-ui';
import type { MySeoulFee, MySeoulPeriods } from '@/app/lib/review/myseoul-ui';
import { failureText, sourceLink, statusText } from '@/app/lib/review/presentation';
import { myseoulErrorMessage } from '@/app/lib/review/myseoul-errors';
import { fieldClass, primaryButton, secondaryButton } from './ReviewEditors';
import ClassificationPanel from './ClassificationPanel';
import { RestoredMySeoulFacts } from './RestoredMySeoulFacts';
import MySeoulResidenceReview from './MySeoulResidenceReview';
import {quickReasons} from '@/app/lib/review/trash';
import type {QuickReason} from '@/app/lib/review/trash';

type Item = ReturnType<typeof myseoulItem>;
export function myseoulReviewReasons(item:Item) {
  const reasons=[...item.reasonGuidance];
  for(const key of item.filterInfo?.missing??[]) {
    const code=`content_filter:${key}`;
    if(!reasons.some(r=>r.code===code))reasons.push({code,text:myseoulGuidance(code),supported:false});
  }
  return reasons;
}
class Failure extends Error {
  constructor(code: string, readonly fields?: unknown) { super(code); }
}
async function request(id: string, command?: MySeoulCommand, signal?: AbortSignal): Promise<Item> {
  const response = await fetch(`/api/admin/myseoul-review/${id}`, { cache: 'no-store', credentials: 'same-origin', signal,
    ...(command ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) } : {}) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Failure(data?.code ?? 'unavailable', data?.fields);
  if (data?.mode !== 'database') throw new Failure('unavailable');
  try { return myseoulItem(data.item, id); } catch { throw new Failure('unavailable'); }
}
function focus(node: HTMLElement | null) { node?.focus({ preventScroll: true }); node?.scrollIntoView({ block: 'start' }); }

function PeriodEditor({ value, axes, onChange }: { value: MySeoulPeriods; axes: ('application' | 'operation')[]; onChange: (next: MySeoulPeriods) => void }) {
  return <div className="space-y-6"><p className="text-sm leading-6 text-info-muted">신청 기간과 교육·행사의 실제 일정을 구분해 입력해 주세요.</p>
    {axes.map(axis => <fieldset key={axis} className="space-y-4"><legend className="font-semibold">{axis === 'application' ? '신청 기간' : '운영 일정'}</legend>
      {value[axis].map((period, index) => {
        const prefix = `myseoul-${axis}-${index}`;
        const endpoints = period.endpoints.length ? period.endpoints : [{ value: '', precision: 'day' as const }, { value: '', precision: 'day' as const }];
        const update = (next: MySeoulPeriod['endpoints']) => onChange({ ...value, [axis]: value[axis].map((p, i) => i === index ? { ...p, endpoints: next, status: next.every(e => e.value) ? 'ok' : 'unparsed', origin: 'operator' } : p) });
        return <div key={index} className="space-y-3 border-b border-info-rule pb-5">
          <p className="text-sm font-semibold">{period.origin === 'header' ? '상단 안내' : period.origin === 'body' ? '본문 안내' : '확인한 일정'}{value[axis].length > 1 ? ` ${index + 1}` : ''}</p>
          {period.raw && <p className="whitespace-pre-wrap break-words leading-7 text-info-body">{period.raw}</p>}
          {period.status !== 'ok' && <p className="text-sm text-info-status">이 안내의 날짜·시간을 확인해 아래에 입력해 주세요.</p>}
          <div className="grid gap-4 sm:grid-cols-2">{endpoints.map((endpoint, n) => <fieldset key={n} className="min-w-0 space-y-2"><legend className="font-semibold">{n === 0 ? '시작' : '종료'}</legend>
            <label className="block" htmlFor={`${prefix}-${n}-date`}>날짜<input id={`${prefix}-${n}-date`} type="date" className={fieldClass} value={endpoint.value.slice(0, 10)} onChange={e => update(endpoints.map((v, j) => j !== n ? v : { ...v, value: e.target.value ? v.precision === 'minute' ? `${e.target.value}T${v.value.slice(11,16) || '00:00'}:00+09:00` : e.target.value : '' }))}/></label>
            <label className="block" htmlFor={`${prefix}-${n}-time`}>시각 (원문에 있을 때만)<input id={`${prefix}-${n}-time`} type="time" step={60} className={fieldClass} disabled={!endpoint.value} value={endpoint.precision === 'minute' ? endpoint.value.slice(11,16) : ''} onChange={e => update(endpoints.map((v, j) => j !== n ? v : { precision: e.target.value ? 'minute' : 'day', value: e.target.value ? `${v.value.slice(0,10)}T${e.target.value}:00+09:00` : v.value.slice(0,10) }))}/></label>
          </fieldset>)}</div>
          {value[axis].length > 1 && <button type="button" className={secondaryButton} onClick={() => onChange({ ...value, [axis]: value[axis].filter((_, i) => i !== index) })}>별도 일정이 아닌 이 안내 제거</button>}
        </div>;
      })}
      {!value[axis].length && <button type="button" className={secondaryButton} onClick={() => onChange({ ...value, [axis]: [{ raw: '', label: axis === 'application' ? '신청기간' : '운영기간', origin: 'operator', status: 'unparsed', endpoints: [{ value: '', precision: 'day' }, { value: '', precision: 'day' }] }] })}>날짜·시간 입력</button>}
      <p className="text-sm leading-6 text-info-muted">시각이 없는 종료일은 당일을 포함합니다. 전체 기간·반별 일정·집결 안내는 서로 다른 정보이므로 합치지 마세요.</p>
    </fieldset>)}
  </div>;
}
function FeeEditor({ value, onChange }: { value: MySeoulFee[]; onChange: (next: MySeoulFee[]) => void }) {
  return <div className="space-y-4"><p className="text-sm leading-6 text-info-muted">수강료와 별도 비용을 각각 기록합니다. 원문이 불명확한 금액을 나누거나 합계를 만들지 마세요.</p>
    {value.map((fee, index) => <div key={index} className="grid gap-3 border-b border-info-rule pb-4 sm:grid-cols-[10rem_minmax(0,1fr)]">
      <label htmlFor={`myseoul-fee-${index}-kind`}>비용 항목<select id={`myseoul-fee-${index}-kind`} className={fieldClass} value={fee.component} onChange={e => onChange(value.map((f, i) => i === index ? { ...f, component: e.target.value } : f))}>{Object.entries(myseoulFeeLabels).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select></label>
      <label htmlFor={`myseoul-fee-${index}-evidence`}>금액·조건의 원문 근거<textarea id={`myseoul-fee-${index}-evidence`} className={fieldClass} rows={2} maxLength={4000} value={fee.evidence.join('\n')} onChange={e => onChange(value.map((f, i) => i === index ? { ...f, evidence: e.target.value.split('\n') } : f))}/></label>
      <button type="button" className={secondaryButton} onClick={() => onChange(value.filter((_, i) => i !== index))}>이 비용 항목 제거</button>
    </div>)}<button type="button" className={secondaryButton} disabled={value.length >= 200} onClick={() => onChange([...value, { component: 'extra_fee', evidence: [''] }])}>확인한 비용 항목 추가</button>
  </div>;
}
function FactEditor({ value, editable, axes, sharedFields = [], onChange }: { value: MySeoulFacts; editable: string[]; axes: ('application' | 'operation')[]; sharedFields?: string[]; onChange: (next: MySeoulFacts) => void }) {
  const set = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  return <div className="space-y-6">{visibleMySeoulFields(editable, value).map(key => <div key={key}>
    {sharedFields.includes(key) ? <p className="text-sm leading-6 text-info-body">{myseoulLabels[key]}: {myseoulChoices[key]?.[String(value[key])] ?? '미확인'} · {key === 'public_category' ? '분류 변경에서 필수값과 함께 확인합니다.' : '해당 입력과 원문 근거를 함께 확인합니다.'}</p> : key === 'fees' || key === 'periods' ? <fieldset><legend className="mb-3 font-semibold">{myseoulLabels[key]}</legend>{key === 'fees' ? <FeeEditor value={value.fees as MySeoulFee[]} onChange={v => set(key, v)}/> : <PeriodEditor axes={axes} value={value.periods as MySeoulPeriods} onChange={v => set(key, v)}/>}</fieldset> : <>
      <label htmlFor={`myseoul-${key}`} className="block font-semibold">{myseoulLabels[key]}</label>
      {myseoulChoices[key] ? <select id={`myseoul-${key}`} className={fieldClass} value={Object.hasOwn(myseoulChoices[key], String(value[key])) && value[key]!=='unknown' ? String(value[key]) : 'unknown'} onChange={e => set(key, e.target.value)}><option value="unknown" disabled>선택해 주세요</option>{Object.entries(myseoulChoices[key]).filter(([k])=>k!=='unknown').map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select> : <>
        <textarea id={`myseoul-${key}`} className={fieldClass} rows={key === 'description' ? 6 : 3} maxLength={key === 'description' ? 60000 : 4000} value={myseoulArrayFields.has(key) ? (value[key] as string[]).join('\n') : String(value[key])} onChange={e => set(key, myseoulArrayFields.has(key) ? e.target.value.split('\n') : e.target.value)}/>
        {myseoulArrayFields.has(key) && <p className="mt-1 text-sm text-info-muted">한 줄에 하나씩 입력해 주세요.</p>}
      </>}
      {key === 'residence_scope' && <p className="mt-2 text-sm leading-6 text-info-muted">참가 자격과 서비스 수용 여부를 확인하는 값입니다. 공개 개최 지역 필터에는 쓰이지 않습니다. 성남시 주민 전용 등 실제 조건은 아래 거주 조건과 원문 근거에 남겨 주세요. 미표기를 제한 없음으로 선택하지 마세요.</p>}
      {key === 'venue' && <p className="mt-2 text-sm leading-6 text-info-muted">원문의 장소 안내를 보존합니다. 위 시·도·시·군·구 선택은 공개 필터에 사용되며 원문 인용을 대신하지 않습니다.</p>}
    </>}
  </div>)}</div>;
}

function reviewGroups(item: Item) {
  const groups = new Map<string, { key: string; fields: string[]; reasons: Item['reasonGuidance'] }>();
  for (const reason of item.reasonGuidance.filter(r=>r.code!=='category_unresolved' && !(r.code==='activity_region_unknown'&&item.filterInfo))) {
    const fields = myseoulReasonFields(reason.code).filter(k => item.editableFields.includes(k) && !(k === 'periods' && ['application_state_unknown','source_fact_conflict:status'].includes(reason.code) && item.result.reasons.some(r => r !== reason.code && reviewPeriodAxes([r]).length)));
    const axes = reviewPeriodAxes([reason.code]);
    const key = fields.includes('periods') ? `periods:${axes.join(',')}` : fields.slice().sort().join(',') || reason.code;
    const group = groups.get(key) ?? { key, fields, reasons: [] };
    group.reasons.push(reason); groups.set(key, group);
  }
  return [...groups.values()];
}
function IssueEvidence({ item, code }: { item: Item; code: string }) {
  const field = code.split(':')[1];
  const conflicts = (item.facts.conflicts as { field: string; header: string[]; body: string[] }[]).filter(c => c.field === field);
  if (conflicts.length) return <dl className="mt-2 space-y-2 text-info-body">{conflicts.map((c, i) => <div key={i}><dt className="font-semibold">상단 안내</dt><dd className="whitespace-pre-wrap break-words">{c.header.join('\n')}</dd><dt className="mt-2 font-semibold">본문 안내</dt><dd className="whitespace-pre-wrap break-words">{c.body.join('\n')}</dd></div>)}</dl>;
  const evidence = (item.facts.issues as MySeoulIssue[]).filter(i => i.code === code).flatMap(i => i.evidence);
  return evidence.length ? <p className="mt-2 whitespace-pre-wrap break-words leading-7 text-info-body">{[...new Set(evidence)].join('\n')}</p> : null;
}

export default function MySeoulReviewPanel({ id, onBlocked, onResult }: { id: string; onBlocked: (blocked: boolean) => void; onResult: (next: Item) => void }) {
  const [item, setItem] = useState<Item | null>(null), [draft, setDraft] = useState<MySeoulFacts | null>(null);
  const [filterDraft, setFilterDraft] = useState<ContentFilters | null>(null), [pendingRepeat, setPendingRepeat] = useState(false), [filterReset, setFilterReset] = useState(0);
  const [filterError, setFilterError] = useState(''), [filterNotice, setFilterNotice] = useState('');
  const [operationBusy, setBusy] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [errorDetail, setErrorDetail] = useState('');
  const [excludeNote, setExcludeNote] = useState(''), [confirm, setConfirm] = useState(false);
  const [classificationBlocked,setClassificationBlocked]=useState(false),[classificationActive,setClassificationActive]=useState(false);
  const [editingFilter,setEditingFilter]=useState<FilterKey|null>(null);
  const [residenceDirty,setResidenceDirty]=useState(false),[excludeReason,setExcludeReason]=useState<QuickReason|'custom'>('custom');
  const [residenceReset,setResidenceReset]=useState(0);
  const [bodyChecked,setBodyChecked]=useState(false);
  const exclusionTrigger=useRef<HTMLButtonElement|null>(null);
  const restoreExclusionFocus=useRef(false);
  useEffect(()=>{if(!confirm&&restoreExclusionFocus.current){restoreExclusionFocus.current=false;exclusionTrigger.current?.focus();}},[confirm]);
  function cancelExclusion(){if(busy)return;restoreExclusionFocus.current=true;setConfirm(false);}
  const pendingExclude=useRef<{key:string;id:string}|null>(null);
  const filterRegion = useRef<HTMLElement>(null);
  const sending = useRef(false), heading = useRef<HTMLHeadingElement>(null), message = useRef<HTMLDivElement>(null);
  const dirty = Boolean(item && draft && Object.keys(myseoulPatch(item.facts, draft, visibleMySeoulFields(item.editableFields, draft))).length);
  const filterDirty = Boolean(item?.filterInfo && filterDraft && JSON.stringify(filterDraft) !== JSON.stringify(item.filterInfo.data)) || pendingRepeat;
  const busy = operationBusy || classificationBlocked;
  const unsaved = dirty || filterDirty || residenceDirty || bodyChecked || editingFilter!==null || Boolean(excludeNote);
  const bodyPending=Boolean(item?.result.reasons.includes('attachment_dependent'));
  const processed = item?.status !== 'open';
  const categoryChanged = Boolean(item && draft && item.facts.public_category !== draft.public_category);
  useEffect(() => { onBlocked(busy || unsaved || confirm); return () => onBlocked(false); }, [busy, unsaved, confirm, onBlocked]);
  useEffect(() => { if (!unsaved) return; const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [unsaved]);
  function accept(next: Item) { setBodyChecked(false);setResidenceDirty(false);setResidenceReset(k=>k+1);setItem(next); setDraft(structuredClone(next.facts)); setFilterDraft(next.filterInfo ? structuredClone(next.filterInfo.data) : null); setPendingRepeat(false); setFilterReset(k => k + 1); setEditingFilter(null); setFilterError(''); setFilterNotice(''); setExcludeNote(''); setConfirm(false); }
  function showFailure(e: unknown) { setError(e instanceof Error ? e.message : 'unavailable'); setErrorDetail(myseoulErrorMessage(e)); }
  useEffect(() => { const controller = new AbortController(); request(id, undefined, controller.signal).then(next => { accept(next); setError(''); }).catch(e => { if (!controller.signal.aborted) showFailure(e); }).finally(() => { if (!controller.signal.aborted) setBusy(false); }); return () => controller.abort(); }, [id]);
  const loadedId = item?.id;
  useEffect(() => { if (loadedId) focus(heading.current); }, [loadedId]);
  useEffect(() => { if (error || notice) focus(message.current); }, [error, notice]);
  async function submit(command: MySeoulCommand) {
    if (sending.current || editingFilter!==null) return; sending.current = true; setBusy(true); setError(''); setNotice('');
    try { const next = await request(id, command);
      if ((command.action === 'save_facts' || command.action === 'confirm_residence' || command.action==='confirm_body') && item && draft) {
        const patch=command.action==='save_facts'?command.patch:command.action==='confirm_body'?{description:command.description}:command.restricted?{residence_scope:command.scope,residence:command.condition,residence_evidence:command.evidence}:{};
        if(command.action==='confirm_body')setBodyChecked(false);
        if(command.action==='confirm_residence')setResidenceDirty(false);
        setItem(next); setConfirm(false); setDraft(mergeMySeoulDraft(item.facts, draft, next.facts, patch));
        if (patch.public_category && next.filterInfo && next.filterInfo.data.category === patch.public_category) {
          setFilterDraft(structuredClone(next.filterInfo.data)); setPendingRepeat(false); setFilterReset(k=>k+1);
        } else if (item.filterInfo && filterDraft && next.filterInfo) setFilterDraft(mergeMySeoulFilters(item.filterInfo.data, filterDraft, next.filterInfo.data));
        else if (next.filterInfo) setFilterDraft(structuredClone(next.filterInfo.data));
      } else accept(next);
      onResult(next); setNotice(command.action === 'exclude' ? '제외 사유를 기록하고 휴지통으로 이동했습니다. 72시간 이내에 복원할 수 있습니다.' : '사실을 저장하고 다시 평가했습니다.'); }
    catch (e) { showFailure(e); setConfirm(false); }
    finally { sending.current = false; setBusy(false); }
  }
  async function exclude() {
    if (!item || sending.current || dirty || filterDirty || residenceDirty || bodyChecked || editingFilter!==null) return;
    const body={action:'exclude',id,revision:item.revision,version:item.version,reasonCode:excludeReason,note:excludeReason==='custom'?excludeNote:''};
    const key=JSON.stringify(body);if(pendingExclude.current?.key!==key)pendingExclude.current={key,id:crypto.randomUUID()};
    sending.current=true;setBusy(true);setError('');setNotice('');
    try {
      const response=await fetch('/api/admin/review-trash',{method:'POST',cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,requestId:pendingExclude.current.id})});
      const data=await response.json().catch(()=>null);
      if(!response.ok)throw new Failure(data?.code??'unavailable');
      if(data?.mode!=='database')throw new Failure('unavailable');
      const next=myseoulItem(data.item,id);accept(next);onResult(next);setNotice('제외 사유를 기록하고 공통 휴지통으로 이동했습니다. 72시간 이내에 복원할 수 있습니다.');
    } catch(e){showFailure(e);setConfirm(false);} finally{sending.current=false;setBusy(false);}
  }
  async function reload() { if (sending.current) return; sending.current = true; setBusy(true); setError(''); try { const next = await request(id); accept(next); onResult(next); setNotice(''); } catch (e) { showFailure(e); } finally { sending.current = false; setBusy(false); } }
  async function readLatestPreservingInput() {
    if (sending.current || !item || !draft) return;
    sending.current = true; setBusy(true);
    try {
      const next = await request(id);
      // A changed source/category requires explicit discard, not an implicit
      // rebase of operator confirmations onto different source evidence.
      if (next.revision !== item.revision || (residenceDirty||bodyChecked) && next.version!==item.version || next.filterInfo?.data.category !== item.filterInfo?.data.category) {
        setFilterError('원문 버전 또는 공개 카테고리가 바뀌었습니다. 입력은 유지합니다. 입력을 버리고 최신 내용 불러오기로 새 원문을 확인해 주세요.');
        return;
      }
      setItem(next); setDraft(mergeMySeoulDraft(item.facts, draft, next.facts, {}));
      if (item.filterInfo && filterDraft && next.filterInfo) setFilterDraft(mergeMySeoulFilters(item.filterInfo.data, filterDraft, next.filterInfo.data));
      onResult(next); setFilterError(''); setFilterNotice('최신 저장 상태를 읽기로 확인했습니다. 미저장 입력은 유지했으며 쓰기 요청은 보내지 않았습니다.');
    } catch { setFilterError('최신 저장 상태를 읽지 못했습니다. 입력은 유지하며 쓰기는 재시도하지 않습니다.'); }
    finally { sending.current = false; setBusy(false); }
  }
  const filterFields = item?.filterInfo ? [...new Set([...myseoulFilterFields(item.filterInfo, item.editableFields),...(filterDraft?changedFilterFields(item.filterInfo.data,filterDraft):[])])] : [];
  const neededFilters=[...(item?.filterInfo?.missing??[]),...(item?.result.reasons.includes('activity_region_unknown')?['location']:[]),...(item?.result.reasons.includes('delivery_mode_unknown')?['delivery']:[])];
  const displayedFilterFields=filterFields.filter(k=>!item?.filterInfo||!confirmedFilterFields(item.filterInfo).includes(k)||neededFilters.includes(k)||(filterDraft&&changedFilterFields(item.filterInfo.data,filterDraft).includes(k)));
  const sharedFields = [...(item?.editableFields.includes('public_category') ? ['public_category'] : []), ...(item?.filterInfo ? [...(filterFields.includes('delivery') ? ['delivery_mode'] : []), ...(filterFields.includes('location') ? ['activity_region'] : [])] : [])];
  function selectFilters(next: ContentFilters) {
    if (!item || !draft || !filterDraft) return;
    setDraft(factsFromFilterSelection(draft, filterDraft, next, item.editableFields)); setFilterDraft(next); setFilterError(''); setFilterNotice('');
  }
  async function saveSelections() {
    if (sending.current || !item?.filterInfo || !draft || !filterDraft || pendingRepeat || editingFilter!==null) return;
    if (categoryChanged) { setFilterError('카테고리 변경을 사실 저장으로 먼저 확인해 주세요. 기존 분류의 필터는 저장하지 않습니다.'); return; }
    const invalid = filterRegion.current?.querySelector<HTMLInputElement>('input:invalid,select:invalid');
    if (invalid) { invalid.reportValidity(); setFilterError('선택한 추가 입력을 완료해 주세요. 입력은 유지하며 저장하지 않습니다.'); return; }
    // Validate every selected filter before the atomic confirmation or legacy saves.
    let selected: ContentFilters;
    try { selected = parseContentFilters(filterDraft); filterSaveBody(item.filterInfo, item.version, selected, filterFields); }
    catch { setFilterError('선택값·지역·날짜 형식을 확인해 주세요. 아무 값도 저장하지 않았으며 입력을 유지합니다.'); return; }
    sending.current = true; setBusy(true); setFilterError(''); setFilterNotice(''); setError(''); setNotice('');
    let current = item, desired = selected, factsSaved = false, filtersSaved = false;
    try {
      const placeConfirmation = item.result.reasons.includes('activity_region_unknown') && selected.location.status === 'known' && selected.location.value.scope === 'specific';
      const mapped = factsFromFilterSelection(draft, item.filterInfo.data, selected, item.editableFields);
      if (placeConfirmation) {
        const patch=Object.fromEntries(Object.entries(myseoulPatch(item.facts,mapped,item.editableFields)).filter(([k])=>!['delivery_mode','activity_region','venue','activity_evidence','public_category','purpose'].includes(k)));
        const body=filterSaveBody(item.filterInfo,item.version,selected,[...new Set([...filterFields,'location' as const])]);
        const command=myseoulCommand({action:'confirm_activity',...body,patch});
        const next=await request(id,command);
        if(next.revision!==item.revision||!next.filterInfo||next.filterInfo.data.category!==selected.category||body.fields.some(k=>JSON.stringify(next.filterInfo!.data[k])!==JSON.stringify(selected[k])))throw new Error('저장 응답의 원문·분류·필터값을 확인하지 못했습니다. 입력은 유지하며 최신 상태를 읽기로 확인해 주세요.');
        setItem(next);setDraft(mergeMySeoulDraft(item.facts,draft,next.facts,{...patch,delivery_mode:next.facts.delivery_mode,activity_region:next.facts.activity_region}));
        if(next.filterInfo)setFilterDraft(structuredClone(next.filterInfo.data));setPendingRepeat(false);onResult(next);
        setFilterNotice('개최 지역 확인과 공개 필터 저장을 함께 완료하고 남은 확인사항을 다시 판단했습니다.');return;
      }
      if (dirty || placeConfirmation) {
        const fields = placeConfirmation ? [...new Set([...Object.keys(myseoulPatch(item.facts,mapped,item.editableFields)), ...['delivery_mode','activity_region','venue'].filter(k=>item.editableFields.includes(k))])] : undefined;
        const command = buildMySeoulSave(item, mapped, fields);
        current = await request(id, command); factsSaved = true;
        setItem(current); setDraft(command.action === 'save_facts' ? mergeMySeoulDraft(item.facts, draft, current.facts, command.patch) : structuredClone(current.facts)); onResult(current);
        if (current.filterInfo) { desired = mergeMySeoulFilters(item.filterInfo.data, selected, current.filterInfo.data); setFilterDraft(desired); }
        setFilterNotice('사실 저장 완료 · 공개 필터는 아직 저장하지 않았습니다.');
      }
      assertMySeoulFilterContinuation({ revision: item.revision, category: selected.category }, current);
      const info = current.filterInfo!;
      const saved = await saveFilterRequest(id, filterSaveBody(info, current.version, desired, filterFields));
      filtersSaved = true; setItem({ ...current, version: saved.version, filterInfo: saved }); setFilterDraft(structuredClone(saved.data)); setPendingRepeat(false);
      setFilterNotice('공개 필터 저장 완료 · 남은 확인사항을 다시 읽는 중입니다.');
      const next = await request(id); setItem(next); setDraft(mergeMySeoulDraft(current.facts, dirty ? current.facts : draft, next.facts, {}));
      if (next.filterInfo) setFilterDraft(structuredClone(next.filterInfo.data)); onResult(next);
      setFilterNotice(factsSaved ? '사실 저장과 공개 필터 저장을 각각 완료하고 남은 확인사항을 다시 읽었습니다.' : '공개 필터를 저장하고 남은 확인사항을 다시 읽었습니다.');
    } catch (e) {
      setFilterError(`${filtersSaved ? '공개 필터 저장은 완료됐지만 이후 조회에 실패했습니다.' : factsSaved ? '사실 저장은 완료됐지만 공개 필터 저장을 완료 확인하지 못했습니다.' : '저장 완료를 확인하지 못했습니다.'} ${e instanceof Failure ? myseoulErrorMessage(e) : e instanceof Error ? e.message : ''} 입력은 유지하며 자동 재시도하지 않습니다.`);
    } finally { sending.current = false; setBusy(false); }
  }
  const link = item ? sourceLink(item.source.url) : null;
  return <section aria-label="마이서울플러스 사실 검토" aria-busy={busy}>
    {(error || notice) && <div ref={message} tabIndex={-1} role={error ? 'alert' : 'status'} className="mb-6 scroll-mt-36 border-y border-info-rule py-4 leading-7"><p className={error ? 'text-info-status' : 'text-info-body'}>{error ? errorDetail || failureText.unavailable : notice}</p>
      {error && <div className="mt-3 flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={busy} onClick={() => void reload()}>{unsaved ? '입력을 버리고 최신 내용 불러오기' : '최신 내용 다시 확인'}</button>{['signed_out', 'forbidden'].includes(error) && <Link prefetch={false} href="/ko/login?next=%2Fko%2Fadmin" className={secondaryButton}>로그인 상태 확인</Link>}</div>}</div>}
    {!item || !draft ? <p role="status" className="py-6 text-info-muted">{busy ? '마이서울플러스 항목을 불러오는 중입니다.' : '항목을 불러오지 못했습니다.'}</p> : <>
      <header className="border-b border-info-rule pb-5"><h2 ref={heading} tabIndex={-1} className="scroll-mt-36 break-keep text-2xl font-bold leading-snug">{item.source.title}</h2><p className="mt-3 text-info-status">마이서울플러스 · {statusText[item.status]}</p></header>
      <ClassificationPanel key={id+item.version} id={id} disabled={operationBusy||unsaved||confirm} onBlocked={setClassificationBlocked} onActive={setClassificationActive} onSaved={async()=>{const next=await request(id);accept(next);onResult(next);}} overview={<section className={reviewOverview} aria-label="이번에 확인할 사항"><h3 className="font-bold">이번에 확인할 사항 · {myseoulReviewReasons(item).length}개</h3><ul className="mt-3 space-y-2">{myseoulReviewReasons(item).map(r=>{const filterKey=r.code.startsWith('content_filter:')?r.code.slice(15):r.code==='activity_region_unknown'?'location':r.code==='delivery_mode_unknown'?'delivery':null;return <li key={r.code}><button type="button" data-classification-open={r.code==='category_unresolved'?true:undefined} className="min-h-11 py-2 text-left font-semibold underline underline-offset-4" onClick={()=>{const node=filterKey?document.querySelector<HTMLElement>(`[data-filter-key="${filterKey}"]`):document.getElementById(`myseoul-issue-${r.code}`);(node?.querySelector<HTMLElement>('input,select,textarea')??node?.closest('section')?.querySelector<HTMLElement>('input,select,textarea')??node)?.focus();node?.scrollIntoView({block:'center'});}}>{r.code==='activity_region_unknown'?'개최지의 수도권 여부':filterKey&&filterDraft?reviewFilterLabel(filterDraft,filterKey as keyof typeof filterLabels):r.text} · 확인 필요</button></li>;})}</ul></section>} reference={<details className="my-6 border-b border-info-rule pb-5"><summary className="cursor-pointer py-3 font-semibold">원문 확인 · 읽기 전용</summary>{link && <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center underline underline-offset-4">공식 원문 열기 (새 창)</a>}<p className="mt-3 whitespace-pre-wrap break-words leading-7 text-info-body">{item.source.body || '저장된 본문이 없습니다.'}</p></details>}/>

      {item.restoredReviewPending && !processed && <section className="my-6 border-b border-info-rule pb-5" aria-label="복원한 사실 확인"><h3 className="font-semibold">휴지통에서 복원한 항목입니다.</h3><p className="mt-2 text-info-body">현재 사실과 원문을 확인해 주세요. 복원만으로 AI를 실행하거나 게시하지 않습니다.</p><RestoredMySeoulFacts facts={item.facts}/><button type="button" className={`${secondaryButton} mt-3`} disabled={busy || confirm || unsaved} onClick={() => void submit({ action: 'save_facts', revision: item.revision, version: item.version, patch: {}, confirmRestored: true })}>저장된 사실로 확인·저장</button></section>}

      {['closed', 'ended', 'not_started'].includes(item.result.application) && <p className="mb-6 text-info-status">{item.result.application === 'not_started' ? '아직 접수 전입니다.' : '접수 또는 운영이 종료된 항목입니다.'}</p>}
      {item.filterInfo && filterDraft && !processed && !classificationActive && <section ref={filterRegion} className="my-6 border-y border-info-rule py-6" aria-label="공개 필터 확인">
        <h3 className="text-lg font-bold">{filterCategoryLabels[item.filterInfo.data.category]} 필터 확인</h3>
        <p className="my-3 text-sm leading-6 text-info-muted">원문을 확인하고 공개 필터와 같은 선택값으로 입력합니다. 진행 방식·개최지 선택은 수정 가능한 사실의 수도권 판정에도 연결합니다. 참가 거주 조건은 아래 사실·근거에서 확인합니다.</p>
        {filterDraft.delivery.status === 'known' && !filterFields.includes('delivery') && <p className="mb-3 text-sm text-info-body">확인된 진행 방식: {filterValueLabel(filterDraft, 'delivery')} · 현재 사실 확인 대상이 아니므로 변경하지 않습니다.</p>}
        {filterDraft.delivery.status === 'known' && filterDraft.delivery.value === 'online' && <p className="mb-4 text-sm leading-6 text-info-body">온라인 진행 · 실제 개최 지역은 해당 없음입니다. 참가 자격의 거주 조건과는 구분합니다.</p>}
        <FilterInputs key={filterReset} data={filterDraft} fields={displayedFilterFields.filter(k=>k!==editingFilter)} onChange={selectFilters} disabled={busy || confirm || categoryChanged || editingFilter!==null} onPending={setPendingRepeat} missing={neededFilters} saved={item.filterInfo.data} confirmed={confirmedFilterFields(item.filterInfo)}/>
        <SavedFilterValues key={`saved-${filterReset}`} saved={item.filterInfo.data} data={filterDraft} onChange={selectFilters} disabled={busy||confirm||categoryChanged} missing={neededFilters} confirmed={confirmedFilterFields(item.filterInfo)} version={item.version} onEditing={setEditingFilter}/>
        {dirty && <p className="mt-3 text-sm leading-6 text-info-status">먼저 저장할 사실: {Object.keys(myseoulPatch(item.facts, draft, visibleMySeoulFields(item.editableFields, draft))).map(k => myseoulLabels[k as keyof typeof myseoulLabels]).join(' · ')}</p>}
        <p className="mt-3 text-sm leading-6 text-info-muted">{item.result.reasons.includes('activity_region_unknown')&&filterDraft.location.status==='known'&&filterDraft.location.value.scope==='specific'?'선택한 실제 개최 지역을 원문과 대조한 뒤 확인·저장해 주세요. 개최 지역 확인과 공개 필터를 함께 저장합니다. 시설명·상세주소를 다시 입력하지 않습니다.':'사실과 공개 필터는 별도 저장입니다. 사실 저장 후 반환된 최신 버전으로 필터를 저장하며, 두 번째 저장이 실패하면 첫 저장을 취소하지 않습니다.'} 요약·번역·AI 실행 요청은 보내지 않습니다.</p>
        {(filterError || filterNotice) && <p role={filterError ? 'alert' : 'status'} className="mt-4 leading-7 text-info-status">{filterError || filterNotice}</p>}
        {filterError && <div className="mt-3 flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={busy} onClick={() => void readLatestPreservingInput()}>입력을 유지하고 저장 상태 확인</button><button type="button" className={secondaryButton} disabled={busy} onClick={() => void reload()}>입력을 버리고 최신 내용 불러오기</button></div>}
        {filterDraft.category !== item.filterInfo.data.category && <p role="alert" className="mt-3 text-info-status">공개 카테고리가 바뀌었습니다. 입력을 보존했습니다. 아래 취소로 최신 분류의 입력을 다시 확인해 주세요.</p>}
        {pendingRepeat && <p role="status" className="mt-3 text-info-status">편집한 반복 조건으로 회차를 만든 뒤 저장해 주세요.</p>}
        {filterFields.length > 0 && <div className="mt-5 flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={busy || confirm || residenceDirty || pendingRepeat || editingFilter!==null || categoryChanged || filterDraft.category !== item.filterInfo.data.category} onClick={() => void saveSelections()}>{classificationBlocked ? '분류 검토 중…' : busy ? '저장 중…' : dirty ? '사실 저장 후 공개 필터 저장' : '공개 필터 확인·저장'}</button>{filterDirty && <button type="button" className={secondaryButton} disabled={busy||editingFilter!==null} onClick={() => { setFilterDraft(structuredClone(item.filterInfo!.data)); setDraft({ ...draft, ...Object.fromEntries(sharedFields.map(k => [k, item.facts[k]])) }); setPendingRepeat(false); setFilterReset(k => k + 1); setFilterError(''); setFilterNotice(''); }}>공개 필터 입력 취소</button>}</div>}
      </section>}
      <form onSubmit={e => { e.preventDefault(); try { if(bodyPending&&draft.description!==item.facts.description){setError('invalid_input');setErrorDetail('이미지 원문 확인 항목에서 설명과 확인을 함께 저장해 주세요.');return;} void submit(buildMySeoulSave(item, draft)); } catch (e) { showFailure(e); } }}>

        <div className="divide-y divide-info-rule">{reviewGroups(item).filter(group=>!group.reasons.every(r=>r.code.startsWith('content_filter:'))).map(group => {
          const fields = visibleMySeoulFields(group.fields, draft);
          return <section key={group.key}  tabIndex={-1} className="py-6 scroll-mt-36" aria-label={group.reasons.map(r => { const key = r.code.slice('content_filter:'.length) as keyof typeof filterLabels; return r.code.startsWith('content_filter:') && Object.hasOwn(filterLabels, key) ? `공개 필터: ${filterDraft ? reviewFilterLabel(filterDraft,key) : filterLabels[key]}` : r.text; }).join(' ')}>
            {group.reasons.map(reason => { const filterKey = reason.code.startsWith('content_filter:') ? reason.code.slice('content_filter:'.length) as keyof typeof filterLabels : null; const filterReason = filterKey && Object.hasOwn(filterLabels, filterKey); return <div key={reason.code} id={`myseoul-issue-${reason.code}`} tabIndex={-1} className="mb-4 scroll-mt-36"><p className="font-semibold leading-7">{reason.code === 'restored_review_pending' ? '복원한 사실을 다시 확인해 주세요.' : filterReason ? `공개 필터의 ${filterDraft ? reviewFilterLabel(filterDraft,filterKey!) : filterLabels[filterKey!]} 항목을 확인해 주세요.` : reason.text}</p>{!reason.supported && reason.code !== 'restored_review_pending' && !filterReason && <p className="text-sm text-info-muted">현재 입력으로 해결할 수 없는 사유입니다.</p>}
              {!group.fields.includes('periods') && <IssueEvidence item={item} code={reason.code}/>}</div>; })}
            {!processed && group.reasons.some(r=>r.code==='online_residence_unknown') ? <MySeoulResidenceReview key={id+item.revision+residenceReset} item={item} regionExcludeDisabled={Boolean(excludeNote)} disabled={busy||confirm||editingFilter!==null||dirty||filterDirty||bodyChecked} onDirty={setResidenceDirty} onSave={c=>void submit(c)} onRegionExclude={trigger=>{if(excludeNote||dirty||filterDirty||residenceDirty||bodyChecked||busy)return;exclusionTrigger.current=trigger;setExcludeReason('region_not_suitable');setConfirm(true);document.getElementById('myseoul-exclusion')?.scrollIntoView({block:'center'});}}/> : !processed && fields.length > 0 && <>
              <fieldset disabled={busy || confirm || residenceDirty || editingFilter!==null}><legend className="sr-only">확인한 사실 입력</legend><FactEditor value={draft} editable={fields} axes={reviewPeriodAxes(group.reasons.map(r => r.code))} sharedFields={sharedFields} onChange={setDraft}/></fieldset>
              {group.reasons.some(r=>r.code==='attachment_dependent') ? <>
                {item.bodyReview.imageUrl&&<a href={item.bodyReview.imageUrl} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block underline underline-offset-4">저장된 이미지 원문 열기 (새 창)</a>}
                <p className="mt-3 text-sm leading-6 text-info-body">이미지에서 확인한 내용을 설명으로 보완합니다. 수집된 원문과 검토자가 보완한 설명은 구분해 보존합니다.</p>
                <label className="mt-3 flex items-start gap-2"><input type="checkbox" className="mt-1" checked={bodyChecked} disabled={busy||confirm||residenceDirty||editingFilter!==null} onChange={e=>setBodyChecked(e.target.checked)}/>이미지 원문을 확인하고 위 설명을 보완했습니다.</label>
                <button type="button" className={`${secondaryButton} mt-4`} disabled={busy||confirm||residenceDirty||editingFilter!==null||!bodyChecked||String(draft.description).trim().length<20} onClick={()=>{try{void submit(myseoulCommand({action:'confirm_body',revision:item.revision,version:item.version,description:draft.description,confirmed:bodyChecked}));}catch(e){showFailure(e);}}}>설명·이미지 원문 확인 저장</button>
              </> : <button type="button" className={`${secondaryButton} mt-4`} disabled={busy || confirm || residenceDirty || editingFilter!==null} onClick={() => { try { void submit(buildMySeoulSave(item, draft, fields, reviewPeriodAxes(group.reasons.map(r => r.code)))); } catch (e) { showFailure(e); } }}>이 값으로 확인·저장</button>}
            </>}
          </section>;
        })}</div>
        {!processed && <>
          {dirty && <p className="mt-4 text-info-status">아직 저장하지 않은 입력이 있습니다.</p>}
          <div className="my-6 flex flex-wrap gap-3"><button type="submit" className={primaryButton} disabled={busy || confirm || residenceDirty || editingFilter!==null || !dirty}>{classificationBlocked ? '분류 검토 중…' : busy ? '저장 중…' : '변경한 사실 저장'}</button>{dirty && <button type="button" className={secondaryButton} disabled={busy} onClick={() => { accept(item); setError(''); }}>사실·공개 필터 입력 취소</button>}</div>
          <p className="text-sm text-info-muted">저장 후 남은 사유를 다시 판단합니다. 요약·번역은 실행하지 않습니다.</p>
        </>}
      </form>
      {item.residenceReview.confirmed && <p role="status" className="my-4 flex flex-wrap items-center gap-2 font-semibold">거주 조건 <ReviewStatus needed={false} confirmed changed={false}/><span>{item.residenceReview.basis==='operator_no_restriction'?'검토자 제한 없음 판단':'원문 근거 확인'}</span></p>}
      {item.activityReview.confirmed&&!item.result.reasons.includes('activity_region_unknown')&&<p role="status" className="my-4 flex items-center gap-2 font-semibold">개최 지역 <ReviewStatus needed={false} confirmed changed={filterDirty}/></p>}
      {item.bodyReview.confirmed&&!bodyPending&&<p role="status" className="my-4 flex items-center gap-2 font-semibold">이미지 원문·보완 설명 <ReviewStatus needed={false} confirmed changed={draft.description!==item.facts.description}/></p>}
      {!processed && <section id="myseoul-exclusion" className="mt-6 border-t border-info-rule pt-5"><h3 className="font-bold">서비스 범위에서 제외</h3>
        <div className="mt-3 flex flex-wrap gap-3">{Object.entries(quickReasons).map(([code,label])=><button key={code} type="button" className={secondaryButton} disabled={busy||dirty||filterDirty||residenceDirty||bodyChecked||editingFilter!==null||Boolean(excludeNote)||confirm} onClick={e=>{exclusionTrigger.current=e.currentTarget;setExcludeReason(code as QuickReason);setConfirm(true);}}>{label} · 제외</button>)}</div>
        <label htmlFor="myseoul-exclude" className="mt-4 block font-semibold">기타 제외 사유</label><textarea id="myseoul-exclude" className={fieldClass} rows={3} maxLength={4000} disabled={busy||confirm} value={excludeNote} onChange={e=>setExcludeNote(e.target.value)}/>
        <button type="button" className={`${secondaryButton} mt-4`} disabled={busy||editingFilter!==null||dirty||filterDirty||residenceDirty||bodyChecked||!excludeNote.trim()||confirm} onClick={e=>{exclusionTrigger.current=e.currentTarget;setExcludeReason('custom');setConfirm(true);}}>사유를 남기고 제외</button>
        {confirm && <div role="group" aria-label="제외 최종 확인" className="mt-4 border-y border-info-rule py-4" onKeyDown={e=>{if(e.key==='Escape')cancelExclusion();}}><p className="whitespace-pre-wrap break-words">이 항목을 제외하고 휴지통으로 이동할까요? 기록할 사유: {excludeReason==='custom'?excludeNote:quickReasons[excludeReason]}</p><p className="mt-2 text-sm">원문 기록은 보존하며 72시간 이내에 복원할 수 있습니다.</p><div className="mt-3 flex flex-wrap gap-3"><button autoFocus type="button" className={secondaryButton} disabled={busy} onClick={cancelExclusion}>취소</button><button type="button" className={primaryButton} disabled={busy||dirty||filterDirty||residenceDirty||bodyChecked} onClick={()=>void exclude()}>확인하고 제외</button></div></div>}
      </section>}

    </>}
  </section>;
}
