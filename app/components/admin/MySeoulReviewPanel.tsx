"use client";

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { myseoulItem } from '@/app/lib/review/myseoul-store';
import { myseoulReasonFields } from '@/app/lib/review/myseoul-contract';
import type { MySeoulCommand, MySeoulFacts, MySeoulIssue, MySeoulPeriod } from '@/app/lib/review/myseoul-contract';
import { buildMySeoulSave, mergeMySeoulDraft, myseoulArrayFields, myseoulChoices, myseoulFeeLabels, myseoulLabels, myseoulPatch, reviewPeriodAxes, visibleMySeoulFields } from '@/app/lib/review/myseoul-ui';
import type { MySeoulFee, MySeoulPeriods } from '@/app/lib/review/myseoul-ui';
import { failureText, sourceLink, statusText } from '@/app/lib/review/presentation';
import { fieldClass, primaryButton, secondaryButton } from './ReviewEditors';

type Item = ReturnType<typeof myseoulItem>;
class Failure extends Error {}
async function request(id: string, command?: MySeoulCommand, signal?: AbortSignal): Promise<Item> {
  const response = await fetch(`/api/admin/myseoul-review/${id}`, { cache: 'no-store', credentials: 'same-origin', signal,
    ...(command ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) } : {}) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Failure(data?.code ?? 'unavailable');
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
function FactEditor({ value, editable, axes, onChange }: { value: MySeoulFacts; editable: string[]; axes: ('application' | 'operation')[]; onChange: (next: MySeoulFacts) => void }) {
  const set = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  return <div className="space-y-6">{visibleMySeoulFields(editable, value).map(key => <div key={key}>
    {key === 'fees' || key === 'periods' ? <fieldset><legend className="mb-3 font-semibold">{myseoulLabels[key]}</legend>{key === 'fees' ? <FeeEditor value={value.fees as MySeoulFee[]} onChange={v => set(key, v)}/> : <PeriodEditor axes={axes} value={value.periods as MySeoulPeriods} onChange={v => set(key, v)}/>}</fieldset> : <>
      <label htmlFor={`myseoul-${key}`} className="block font-semibold">{myseoulLabels[key]}</label>
      {myseoulChoices[key] ? <select id={`myseoul-${key}`} className={fieldClass} value={Object.hasOwn(myseoulChoices[key], String(value[key])) ? String(value[key]) : ''} onChange={e => set(key, e.target.value)}>{['delivery_mode', 'activity_region'].includes(key) && <option value="" disabled>선택해 주세요</option>}{Object.entries(myseoulChoices[key]).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select> : <>
        <textarea id={`myseoul-${key}`} className={fieldClass} rows={key === 'description' ? 6 : 3} maxLength={key === 'description' ? 60000 : 4000} value={myseoulArrayFields.has(key) ? (value[key] as string[]).join('\n') : String(value[key])} onChange={e => set(key, myseoulArrayFields.has(key) ? e.target.value.split('\n') : e.target.value)}/>
        {myseoulArrayFields.has(key) && <p className="mt-1 text-sm text-info-muted">한 줄에 하나씩 입력해 주세요.</p>}
      </>}
    </>}
  </div>)}</div>;
}

function reviewGroups(item: Item) {
  const groups = new Map<string, { key: string; fields: string[]; reasons: Item['reasonGuidance'] }>();
  for (const reason of item.reasonGuidance) {
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
  const [busy, setBusy] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [excludeNote, setExcludeNote] = useState(''), [confirm, setConfirm] = useState(false);
  const sending = useRef(false), heading = useRef<HTMLHeadingElement>(null), message = useRef<HTMLDivElement>(null);
  const dirty = Boolean(item && draft && Object.keys(myseoulPatch(item.facts, draft, visibleMySeoulFields(item.editableFields, draft))).length);
  const unsaved = dirty || Boolean(excludeNote);
  const processed = item?.status !== 'open';
  useEffect(() => { onBlocked(busy || unsaved || confirm); return () => onBlocked(false); }, [busy, unsaved, confirm, onBlocked]);
  useEffect(() => { if (!unsaved) return; const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [unsaved]);
  function accept(next: Item) { setItem(next); setDraft(structuredClone(next.facts)); setExcludeNote(''); setConfirm(false); }
  useEffect(() => { const controller = new AbortController(); request(id, undefined, controller.signal).then(next => { accept(next); setError(''); }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Failure ? e.message : 'unavailable'); }).finally(() => { if (!controller.signal.aborted) setBusy(false); }); return () => controller.abort(); }, [id]);
  const loadedId = item?.id;
  useEffect(() => { if (loadedId) focus(heading.current); }, [loadedId]);
  useEffect(() => { if (error || notice) focus(message.current); }, [error, notice]);
  async function submit(command: MySeoulCommand) {
    if (sending.current) return; sending.current = true; setBusy(true); setError(''); setNotice('');
    try { const next = await request(id, command); accept(next);
      if (command.action === 'save_facts' && item && draft) { setDraft(mergeMySeoulDraft(item.facts, draft, next.facts, command.patch)); setExcludeNote(excludeNote); }
      onResult(next); setNotice(command.action === 'exclude' ? '서비스 범위상 제외 사유를 기록했습니다.' : '사실을 저장하고 다시 평가했습니다.'); }
    catch (e) { setError(e instanceof Failure ? e.message : 'unavailable'); setConfirm(false); }
    finally { sending.current = false; setBusy(false); }
  }
  async function reload() { if (sending.current) return; sending.current = true; setBusy(true); setError(''); try { const next = await request(id); accept(next); onResult(next); setNotice(''); } catch (e) { setError(e instanceof Failure ? e.message : 'unavailable'); } finally { sending.current = false; setBusy(false); } }
  const link = item ? sourceLink(item.source.url) : null;
  return <section aria-label="마이서울플러스 사실 검토" aria-busy={busy}>
    {(error || notice) && <div ref={message} tabIndex={-1} role={error ? 'alert' : 'status'} className="mb-6 scroll-mt-36 border-y border-info-rule py-4 leading-7"><p className={error ? 'text-info-status' : 'text-info-body'}>{error ? failureText[error] ?? failureText.unavailable : notice}</p>
      {error && <div className="mt-3 flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={busy} onClick={() => void reload()}>{unsaved ? '입력을 버리고 최신 내용 불러오기' : '최신 내용 다시 확인'}</button>{['signed_out', 'forbidden'].includes(error) && <Link prefetch={false} href="/ko/login?next=%2Fko%2Fadmin" className={secondaryButton}>로그인 상태 확인</Link>}</div>}</div>}
    {!item || !draft ? <p role="status" className="py-6 text-info-muted">{busy ? '마이서울플러스 항목을 불러오는 중입니다.' : '항목을 불러오지 못했습니다.'}</p> : <>
      <header className="border-b border-info-rule pb-5"><h2 ref={heading} tabIndex={-1} className="scroll-mt-36 break-keep text-2xl font-bold leading-snug">{item.source.title}</h2><p className="mt-3 text-info-status">마이서울플러스 · {statusText[item.status]}</p></header>
      <details className="my-6 border-b border-info-rule pb-5"><summary className="cursor-pointer py-3 font-semibold">원문 확인 · 읽기 전용</summary>{link && <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center underline underline-offset-4">공식 원문 열기 (새 창)</a>}<p className="mt-3 whitespace-pre-wrap break-words leading-7 text-info-body">{item.source.body || '저장된 본문이 없습니다.'}</p></details>
      {['closed', 'ended', 'not_started'].includes(item.result.application) && <p className="mb-6 text-info-status">{item.result.application === 'not_started' ? '아직 접수 전입니다.' : '접수 또는 운영이 종료된 항목입니다.'}</p>}
      <form onSubmit={e => { e.preventDefault(); try { void submit(buildMySeoulSave(item, draft)); } catch { setError('invalid_input'); } }}>
        <h3 className="mb-3 text-lg font-bold">남은 확인 사유 {item.result.reasons.length}개</h3>
        <div className="divide-y divide-info-rule">{reviewGroups(item).map(group => {
          const fields = visibleMySeoulFields(group.fields, draft);
          return <section key={group.key} className="py-6" aria-label={group.reasons.map(r => r.text).join(' ')}>
            {group.reasons.map(reason => <div key={reason.code} className="mb-4"><p className="font-semibold leading-7">{reason.text}</p>{!reason.supported && <p className="text-sm text-info-muted">현재 입력으로 해결할 수 없는 사유입니다.</p>}
              {!group.fields.includes('periods') && <IssueEvidence item={item} code={reason.code}/>}</div>)}
            {!processed && fields.length > 0 && <>
              <fieldset disabled={busy || confirm}><legend className="sr-only">확인한 사실 입력</legend><FactEditor value={draft} editable={fields} axes={reviewPeriodAxes(group.reasons.map(r => r.code))} onChange={setDraft}/></fieldset>
              <button type="button" className={`${secondaryButton} mt-4`} disabled={busy || confirm} onClick={() => { try { void submit(buildMySeoulSave(item, draft, fields, reviewPeriodAxes(group.reasons.map(r => r.code)))); } catch { setError('invalid_input'); } }}>이 값으로 확인·저장</button>
            </>}
          </section>;
        })}</div>
        {!processed && <>
          {dirty && <p className="mt-4 text-info-status">아직 저장하지 않은 입력이 있습니다.</p>}
          <div className="my-6 flex flex-wrap gap-3"><button type="submit" className={primaryButton} disabled={busy || confirm || !dirty}>{busy ? '저장 중…' : '변경한 사실 저장'}</button>{dirty && <button type="button" className={secondaryButton} disabled={busy} onClick={() => { accept(item); setError(''); }}>수정 취소</button>}</div>
          <p className="text-sm text-info-muted">저장 후 남은 사유를 다시 판단합니다. 요약·번역은 실행하지 않습니다.</p>
        </>}
      </form>
      {!processed && <section className="mt-6 border-t border-info-rule pt-5"><h3 className="font-bold">서비스 범위에서 제외</h3><label htmlFor="myseoul-exclude" className="mt-3 block font-semibold">제외 사유</label><textarea id="myseoul-exclude" className={fieldClass} rows={3} maxLength={4000} disabled={busy || confirm} value={excludeNote} onChange={e => setExcludeNote(e.target.value)}/><button type="button" className={`${secondaryButton} mt-4`} disabled={busy || dirty || !excludeNote.trim() || confirm} onClick={() => setConfirm(true)}>사유를 남기고 제외</button>{confirm && <div role="group" aria-label="제외 최종 확인" className="mt-4 border-y border-info-rule py-4"><p className="whitespace-pre-wrap break-words">이 항목을 서비스 범위에서 제외할까요? 기록할 사유: {excludeNote}</p><div className="mt-3 flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={busy} onClick={() => void submit({ action: 'exclude', revision: item.revision, version: item.version, note: excludeNote })}>확인하고 제외</button><button type="button" className={secondaryButton} disabled={busy} onClick={() => setConfirm(false)}>돌아가기</button></div></div>}</section>}

    </>}
  </section>;
}
