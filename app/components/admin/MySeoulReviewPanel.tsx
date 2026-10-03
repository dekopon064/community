"use client";

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ReviewFailure } from '@/app/lib/review/contracts';
import { myseoulItem } from '@/app/lib/review/myseoul-store';
import type { MySeoulCommand, MySeoulFacts, MySeoulField, MySeoulIssue, MySeoulPeriod } from '@/app/lib/review/myseoul-contract';
import { buildMySeoulSave, displayMySeoulValue, myseoulArrayFields, myseoulChoices, myseoulFeeLabels, myseoulLabels, myseoulPatch } from '@/app/lib/review/myseoul-ui';
import type { MySeoulFee, MySeoulPeriods } from '@/app/lib/review/myseoul-ui';
import { actionText, failureText, sourceLink, statusText } from '@/app/lib/review/presentation';
import { programOutcome } from '@/app/lib/review/program-ui';
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

function PeriodEditor({ value, onChange }: { value: MySeoulPeriods; onChange: (next: MySeoulPeriods) => void }) {
  return <div className="space-y-6"><p className="text-sm leading-6 text-info-muted">신청 기간과 운영 기간을 구분합니다. 날짜만 있는 종료일은 해당일을 포함합니다. 시간을 확인하지 못했다면 날짜 기준으로 유지하세요.</p>
    {(['application', 'operation'] as const).map(axis => <fieldset key={axis} className="space-y-4"><legend className="font-semibold">{axis === 'application' ? '신청 기간' : '운영 기간'}</legend>
      {value[axis].map((period, index) => {
        const prefix = `myseoul-${axis}-${index}`;
        const update = (patch: Partial<MySeoulPeriod>) => onChange({ ...value, [axis]: value[axis].map((p, i) => i === index ? { ...p, ...patch, origin: 'operator' } : p) });
        return <div key={index} className="space-y-3 border-b border-info-rule pb-4">
          <label className="block" htmlFor={`${prefix}-raw`}>확인한 일정의 원문 근거<textarea id={`${prefix}-raw`} className={fieldClass} rows={2} maxLength={4000} value={period.raw} onChange={e => update({ raw: e.target.value })}/></label>
          <div className="grid gap-3 sm:grid-cols-2"><label htmlFor={`${prefix}-label`}>일정 이름<input id={`${prefix}-label`} className={fieldClass} maxLength={100} value={period.label} onChange={e => update({ label: e.target.value })}/></label>
            <label htmlFor={`${prefix}-status`}>일정 확인 상태<select id={`${prefix}-status`} className={fieldClass} value={period.status} onChange={e => update({ status: e.target.value })}><option value="ok">날짜 확인됨</option><option value="missing">원문에 없음</option><option value="unparsed">표현 확인 필요</option></select></label></div>
          {period.endpoints.map((endpoint, n) => <div key={n} className="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
            <label htmlFor={`${prefix}-${n}-precision`}>{n === 0 ? '시작' : '종료'} 기준<select id={`${prefix}-${n}-precision`} className={fieldClass} value={endpoint.precision} onChange={e => update({ endpoints: period.endpoints.map((v, j) => j === n ? { value: '', precision: e.target.value as 'day' | 'minute' } : v) })}><option value="day">날짜</option><option value="minute">날짜·시각 (한국 시간)</option></select></label>
            <label htmlFor={`${prefix}-${n}-value`}>{n === 0 ? '시작' : '종료'} 값<input id={`${prefix}-${n}-value`} className={fieldClass} type={endpoint.precision === 'day' ? 'date' : 'datetime-local'} step={endpoint.precision === 'minute' ? 60 : undefined} value={endpoint.precision === 'day' ? endpoint.value : endpoint.value.slice(0, 16)} onChange={e => update({ endpoints: period.endpoints.map((v, j) => j === n ? { ...v, value: e.target.value && v.precision === 'minute' ? `${e.target.value}:00+09:00` : e.target.value } : v) })}/></label>
          </div>)}
          <div className="flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={period.endpoints.length >= 2} onClick={() => update({ endpoints: [...period.endpoints, { value: '', precision: 'day' }] })}>날짜 입력 추가</button>
            <button type="button" className={secondaryButton} disabled={!period.endpoints.length} onClick={() => update({ endpoints: period.endpoints.slice(0, -1) })}>마지막 날짜 제거</button>
            <button type="button" className={secondaryButton} onClick={() => onChange({ ...value, [axis]: value[axis].filter((_, i) => i !== index) })}>이 일정 제거</button></div>
        </div>;
      })}
      <button type="button" className={secondaryButton} disabled={value[axis].length >= 50} onClick={() => onChange({ ...value, [axis]: [...value[axis], { raw: '', label: axis === 'application' ? '신청기간' : '운영기간', origin: 'operator', status: 'ok', endpoints: [{ value: '', precision: 'day' }, { value: '', precision: 'day' }] }] })}>확인한 일정 추가</button>
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
function FactEditor({ value, editable, onChange }: { value: MySeoulFacts; editable: string[]; onChange: (next: MySeoulFacts) => void }) {
  const set = (key: string, next: unknown) => onChange({ ...value, [key]: next });
  return <div className="space-y-6">{(Object.keys(myseoulLabels) as MySeoulField[]).filter(key => editable.includes(key)).map(key => <div key={key}>
    {key === 'fees' || key === 'periods' ? <fieldset><legend className="mb-3 font-semibold">{myseoulLabels[key]}</legend>{key === 'fees' ? <FeeEditor value={value.fees as MySeoulFee[]} onChange={v => set(key, v)}/> : <PeriodEditor value={value.periods as MySeoulPeriods} onChange={v => set(key, v)}/>}</fieldset> : <>
      <label htmlFor={`myseoul-${key}`} className="block font-semibold">{myseoulLabels[key]}</label>
      {myseoulChoices[key] ? <select id={`myseoul-${key}`} className={fieldClass} value={String(value[key])} onChange={e => set(key, e.target.value)}>{Object.entries(myseoulChoices[key]).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select> : <>
        <textarea id={`myseoul-${key}`} className={fieldClass} rows={key === 'description' ? 6 : 3} maxLength={key === 'description' ? 60000 : 4000} value={myseoulArrayFields.has(key) ? (value[key] as string[]).join('\n') : String(value[key])} onChange={e => set(key, myseoulArrayFields.has(key) ? e.target.value.split('\n') : e.target.value)}/>
        {myseoulArrayFields.has(key) && <p className="mt-1 text-sm text-info-muted">한 줄에 하나씩 입력해 주세요.</p>}
      </>}
    </>}
  </div>)}</div>;
}

export default function MySeoulReviewPanel({ id, onBlocked, onResult }: { id: string; onBlocked: (blocked: boolean) => void; onResult: (next: Item) => void }) {
  const [item, setItem] = useState<Item | null>(null), [draft, setDraft] = useState<MySeoulFacts | null>(null);
  const [busy, setBusy] = useState(true), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [note, setNote] = useState(''), [excludeNote, setExcludeNote] = useState(''), [resolve, setResolve] = useState<string[]>([]), [confirm, setConfirm] = useState(false);
  const sending = useRef(false), heading = useRef<HTMLHeadingElement>(null), message = useRef<HTMLDivElement>(null);
  const dirty = Boolean(item && draft && Object.keys(myseoulPatch(item.facts, draft, item.editableFields)).length);
  const unsaved = dirty || Boolean(note || excludeNote || resolve.length);
  const processed = item?.status !== 'open';
  useEffect(() => { onBlocked(busy || unsaved || confirm); return () => onBlocked(false); }, [busy, unsaved, confirm, onBlocked]);
  useEffect(() => { if (!unsaved) return; const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [unsaved]);
  function accept(next: Item) { setItem(next); setDraft(structuredClone(next.facts)); setNote(''); setExcludeNote(''); setResolve([]); setConfirm(false); }
  useEffect(() => { const controller = new AbortController(); request(id, undefined, controller.signal).then(next => { accept(next); setError(''); }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Failure ? e.message : 'unavailable'); }).finally(() => { if (!controller.signal.aborted) setBusy(false); }); return () => controller.abort(); }, [id]);
  const loadedId = item?.id;
  useEffect(() => { if (loadedId) focus(heading.current); }, [loadedId]);
  useEffect(() => { if (error || notice) focus(message.current); }, [error, notice]);
  async function submit(command: MySeoulCommand) {
    if (sending.current) return; sending.current = true; setBusy(true); setError(''); setNotice('');
    try { const next = await request(id, command); accept(next); onResult(next); setNotice(command.action === 'exclude' ? '서비스 범위상 제외 사유를 기록했습니다.' : '사실을 저장하고 다시 평가했습니다. AI는 실행하지 않았습니다.'); }
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
      <section aria-label="현재 판정" className="mb-6 border-b border-info-rule pb-5"><h3 className="font-bold">현재 판정</h3><p className="mt-2 text-info-status">{programOutcome(item.result.decision)}</p><p className="mt-2 text-info-body">현재 신청 상태: {({ open: '신청 가능', closed: '접수 종료', not_started: '접수 전', ended: '운영 종료', unknown: '확인 필요' } as Record<string, string>)[item.result.application] ?? '확인 필요'}</p><p className="mt-2 leading-7 text-info-muted">AI 처리: {({ blocked: '대기 차단', queued: '대기 중', claimed: '처리 중', completed: '처리 완료', failed: '처리 실패', cancelled: '대기 취소' } as Record<string, string>)[item.aiStatus]} · 사실 저장은 요약·번역을 실행하지 않습니다.</p><p className="mt-2 text-sm text-info-muted">사실 버전 {String(item.factsVersion)}</p></section>
      <section aria-label="남은 확인 사유" className="mb-6"><h3 className="font-bold">남은 확인 사유 {item.result.reasons.length}개</h3><ul className="mt-2 divide-y divide-info-rule">{item.reasonGuidance.map(reason => <li key={reason.code} className="py-3"><p className="leading-7 text-info-body">{reason.text}</p>{!reason.supported && <p className="text-sm text-info-muted">현재 입력 계약으로 해소할 수 없는 사유입니다.</p>}{(item.facts.issues as MySeoulIssue[]).filter(i => i.code === reason.code).map(i => <p key={i.code} className="mt-1 whitespace-pre-wrap break-words text-sm text-info-muted">{i.evidence.join('\n')}</p>)}</li>)}</ul></section>
      <details className="mb-6 border-b border-info-rule pb-5"><summary className="cursor-pointer py-3 font-semibold">저장된 사실 · 현재 값과 최초 추출값</summary><dl className="space-y-4">{(Object.keys(myseoulLabels) as MySeoulField[]).map(key => <div key={key}><dt className="font-semibold">{myseoulLabels[key]}</dt><dd className="mt-1 whitespace-pre-wrap break-words text-info-body">현재: {displayMySeoulValue(key, item.facts[key])}</dd><dd className="mt-1 whitespace-pre-wrap break-words text-sm text-info-muted">최초: {displayMySeoulValue(key, item.observedFacts[key])}</dd></div>)}{Object.entries({ age: '연령', companion: '동반 조건', language: '진행 언어', meeting_evidence: '집결 안내', early_close_evidence: '조기 마감 안내' }).map(([key, label]) => <div key={key}><dt className="font-semibold">{label}</dt><dd className="whitespace-pre-wrap break-words text-info-body">{displayMySeoulValue(key, item.facts[key])}</dd></div>)}</dl></details>
      {!processed && <form onSubmit={e => { e.preventDefault(); try { void submit(buildMySeoulSave(item, draft, note, resolve)); } catch (failure) { setError(failure instanceof ReviewFailure ? 'invalid_input' : 'unavailable'); } }}>
        <p className="mb-5 text-sm leading-6 text-info-muted">열린 사유에 필요한 사실만 수정할 수 있습니다. 값 변경만으로 사유가 해소되지는 않으며 서버가 다시 판단합니다.</p>
        <fieldset disabled={busy || confirm}><legend className="sr-only">확인한 사실 입력</legend><FactEditor value={draft} editable={item.editableFields} onChange={setDraft}/></fieldset>
        <fieldset disabled={busy || confirm} className="mt-6"><legend className="font-semibold">근거를 확인한 사유</legend>{item.reasonGuidance.filter(r => r.supported).map(r => <label key={r.code} className="flex min-h-11 items-start gap-3 py-2 leading-6"><input type="checkbox" className="mt-1 size-5 shrink-0" checked={resolve.includes(r.code)} onChange={e => setResolve(e.target.checked ? [...resolve, r.code] : resolve.filter(c => c !== r.code))}/>{r.text}</label>)}</fieldset>
        <label htmlFor="myseoul-note" className="mt-6 block font-semibold">사실 수정·판단 근거 (필수)</label><textarea id="myseoul-note" className={fieldClass} disabled={busy || confirm} rows={3} maxLength={4000} required value={note} onChange={e => setNote(e.target.value)}/>
        {unsaved && <p className="mt-4 text-info-status">아직 저장하지 않은 입력이 있습니다.</p>}
        <div className="my-6 flex flex-wrap gap-3"><button type="submit" className={primaryButton} disabled={busy || confirm || !dirty || !note.trim()}>{busy ? '저장 중…' : '사실 저장·재평가'}</button>{unsaved && <button type="button" className={secondaryButton} disabled={busy} onClick={() => { accept(item); setError(''); }}>수정 취소</button>}</div>
      </form>}
      {!processed && <section className="mt-6 border-t border-info-rule pt-5"><h3 className="font-bold">서비스 범위에서 제외</h3><label htmlFor="myseoul-exclude" className="mt-3 block font-semibold">제외 사유</label><textarea id="myseoul-exclude" className={fieldClass} rows={3} maxLength={4000} disabled={busy || confirm} value={excludeNote} onChange={e => setExcludeNote(e.target.value)}/><button type="button" className={`${secondaryButton} mt-4`} disabled={busy || dirty || Boolean(note || resolve.length) || !excludeNote.trim() || confirm} onClick={() => setConfirm(true)}>사유를 남기고 제외</button>{confirm && <div role="group" aria-label="제외 최종 확인" className="mt-4 border-y border-info-rule py-4"><p className="whitespace-pre-wrap break-words">이 항목을 서비스 범위에서 제외할까요? 기록할 사유: {excludeNote}</p><div className="mt-3 flex flex-wrap gap-3"><button type="button" className={primaryButton} disabled={busy} onClick={() => void submit({ action: 'exclude', revision: item.revision, version: item.version, note: excludeNote })}>확인하고 제외</button><button type="button" className={secondaryButton} disabled={busy} onClick={() => setConfirm(false)}>돌아가기</button></div></div>}</section>}
      <details className="mt-6 border-t border-info-rule pt-4" open={item.history.length > 0}><summary className="cursor-pointer py-3 font-semibold">최근 처리 이력</summary>{item.history.length ? <ul className="divide-y divide-info-rule">{item.history.map((h, i) => <li key={i} className="py-3"><p className="font-semibold">{actionText[h.action] ?? '사실 검토 처리'} · {new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(h.at))}</p><p className="mt-1 whitespace-pre-wrap break-words text-info-body">{h.note}</p></li>)}</ul> : <p className="text-info-muted">아직 처리 이력이 없습니다.</p>}</details>
    </>}
  </section>;
}
