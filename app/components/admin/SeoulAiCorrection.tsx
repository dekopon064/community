'use client';

import { useCallback, useEffect, useState } from 'react';
import type { CandidateContent } from '@/app/lib/review/contracts';
import { sourceLink } from '@/app/lib/review/presentation';
import { secondaryButton } from './ReviewEditors';
import { SeoulCandidateFindings, type CandidateReview } from './SeoulCandidateFindings';
export { SeoulCandidateFindings, applySeoulReviewPatch } from './SeoulCandidateFindings';

import { rangeConflict, recordedWeekTable } from '@/app/lib/review/seoul-session-decision';
import failureLabels from '@/app/lib/pc-worker/failure-labels.json' with {type:'json'};

const labels = { ko: '한국어 요약', jaTitle: '일본어 제목', ja: '일본어 본문' } as const;
type Field = keyof typeof labels;
type Evidence = { field: Field; before: string; after: string | null; evidence: string; sourceUrl: string | null };
type DiagnosticValue = string | number | boolean | null | DiagnosticValue[];
type Draft = {
  id: string; stage: string; output: Partial<Record<Field, string>>;
  diagnostic: { rule?: string; reason?: string; location?: Record<string, string | number>;
    expected?: DiagnosticValue; actual?: DiagnosticValue };
  requested: boolean; started: boolean; outcome: string | null;
  field: Field | null; before: string | null; after: string | null; evidence: string | null;
};

export function CorrectionComparison({ detail }: { detail: Evidence }) {
  const url = sourceLink(detail.sourceUrl ?? '');
  return <div className="mt-3 text-sm leading-6">
    <p className="font-semibold">AI 수정 · {labels[detail.field]}</p>
    <dl className="mt-2 space-y-2">
      <div><dt className="font-semibold">수정 전</dt><dd className="whitespace-pre-wrap break-words">{detail.before}</dd></div>
      <div><dt className="font-semibold">수정 후</dt><dd className="whitespace-pre-wrap break-words">{detail.after}</dd></div>
      <div><dt className="font-semibold">원문 근거</dt><dd className="whitespace-pre-wrap break-words">{detail.evidence}</dd></div>
    </dl>
    {url && <a className="inline-flex min-h-11 items-center underline underline-offset-4" href={url} target="_blank" rel="noopener noreferrer">공식 원문 열기 (새 창)</a>}
  </div>;
}

type CandidateDetail = { evidence: Evidence | null; review: CandidateReview | null };

export function SeoulCandidateCorrection({ id, content, savedContent = content, onChange, disabled }: {
  id: string; content: CandidateContent; savedContent?: CandidateContent; onChange?: (value: CandidateContent) => void; disabled?: boolean;
}) {
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/admin/seoul-ai-correction/' + id + '?view=candidate', {
      cache: 'no-store', signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (!controller.signal.aborted) setDetail(data);
    }).catch(() => { if (!controller.signal.aborted) setUnavailable(true); });
    return () => controller.abort();
  }, [id]);
  if (unavailable) return <p role="status" className="text-sm text-info-status">AI 오류·수정 기록을 확인하지 못했습니다.</p>;
  if (!detail?.evidence && !detail?.review?.issues.length) return null;
  return <section aria-label="AI 결과 검토" className="my-5 border-y border-info-rule py-4">
    {detail.evidence && <CorrectionComparison detail={detail.evidence}/>}
    {Boolean(detail.review?.issues.length) && detail.review && <SeoulCandidateFindings review={detail.review} content={content} savedContent={savedContent} onChange={onChange} disabled={disabled}/>}
  </section>;
}


const outcomeText: Record<string, string> = {
  validated: '재검증 통과 · 후보 검토 대기',
  validation_failed: '재검증 실패 · 비공개 초안 유지',
  translation_missing: '한국어 검증 통과 · 대응하는 일본어 결과가 필요합니다.',
  invalid_suggestion: '수정 제안이 요청 범위에 맞지 않아 비공개 초안을 유지했습니다.',
};

export function SeoulFailedDraft({ jobId, sourceItemId, programDraft = false, canRecheck = false }: { canRecheck?: boolean; programDraft?: boolean; jobId: string; sourceItemId: string }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [snapshot, setSnapshot] = useState<{description:string;observed:string;code:string} | null>(null);
  const endpoint = '/api/admin/seoul-ai-correction/' + jobId + (programDraft ? '?view=private-draft' : '?view=failed-schedule');
  const read = useCallback(async (signal?: AbortSignal) => {
    setPending(true);
    try {
      const response = await fetch(endpoint, { cache: 'no-store', signal });
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (signal?.aborted) return;
      setSnapshot(data.snapshot ?? null);
      setDraft(programDraft ? data.draft ?? null : data.snapshot?.draft ?? null);
      setLoaded(true);
      setMessage('');
    } catch {
      if (!signal?.aborted) {
        setDraft(null); setSnapshot(null); setLoaded(false);
        setMessage('비공개 실패 기록을 불러오지 못했습니다.');
      }
    } finally { if (!signal?.aborted) setPending(false); }
  }, [endpoint, programDraft]);
  useEffect(() => {
    if (programDraft) return;
    const controller = new AbortController();
    void read(controller.signal);
    return () => controller.abort();
  }, [programDraft, read]);

  const clash = snapshot && rangeConflict(snapshot.description);
  const date = clash && draft?.diagnostic.rule === 'calendar_weekday'
    && draft.diagnostic.expected === '월화수목금토일'.indexOf(clash.expected)+1
    && draft.diagnostic.actual === '월화수목금토일'.indexOf(clash.actual)+1 ? clash : null;
  const table = snapshot?.code === 'ai_schema_error' ? recordedWeekTable(snapshot.description) : null;
  return <section aria-label="비공개 실패 초안" className="mt-6 border-t border-info-rule py-4">
    <h4 className="font-semibold">{programDraft ? '비공개 실패 초안' : '실패 원인과 다음 행동'}</h4>
    <p className="mt-2 break-all text-sm">항목 ID {sourceItemId} · 작업 ID {jobId}</p>
    <button type="button" className={secondaryButton} disabled={pending} onClick={() => void read()}>
      {loaded ? '최신 상태 확인' : programDraft ? '실패 초안 보기' : '실패 기록 확인'}
    </button>
    {message && <p role="status" className="mt-2">{message}</p>}
    {!programDraft && pending && <p role="status">실패 기록을 확인하고 있습니다.</p>}
    {loaded && !draft && <p className="mt-2">{snapshot || programDraft ? '이 작업에 보존된 비공개 AI 초안이 없습니다.' : '이전 실행의 입력·초안 기록을 확인할 수 없습니다.'}</p>}
    {loaded && !draft && table && <div className="mt-2 space-y-1">
      <p>요약 호출 전 입력 점검 · 시간 / 요일 표</p>
      <p>{table.grouped ? '평일과 주말의 회차가 줄 단위로 저장됐습니다. 두 열의 값이 모든 회차에 있으면 현재 규칙으로 읽을 수 있습니다. 공식 표와 일치하면 값 수정 없이 재검토할 수 있습니다.' :
        '요일별 셀 위치를 확인해 주세요. 원문 표와 대조해 빈칸을 포함한 시간표를 확인한 프로그램 설명에 입력할 수 있습니다.'}</p>
      {table.rows.filter(row=>row.cells.length !== table.headers.length).map(row=>
        <p key={row.time}>{row.time} · 요일 {table.headers.length}열 중 회차 값 {row.cells.length}개 · 빈칸 위치 미확인</p>)}
      <details><summary>당시 입력의 시간표 보기</summary>
        <p>{table.headers.join(' / ')}</p>{table.rows.map((row,i)=><p key={i}>{row.time} · {row.cells.join(' / ')}</p>)}
      </details>
      <p>세부 단계가 저장되지 않은 과거 작업은 당시 입력에서 확인되는 단서만 표시합니다.</p>
    </div>}
    {date && <div className="mt-3 space-y-1">
      <p className="font-semibold">{date.date} · 안내 {date.actual}요일 / 달력 {date.expected}요일</p>
      <p>{snapshot?.observed.includes(date.line.trim()) ? '수집 원문의 전체 운영 안내' : '실패 당시 확인한 프로그램 설명'}</p>
      <blockquote>{date.line}</blockquote>
      {snapshot?.description.split(/\r?\n/).filter(line=>/(?:답사|회차|해설)\s*일시(?:는|[:：])/.test(line)).map((line,i)=><p key={i}>회차 안내 · {line}</p>)}
      <p>재검토로 보낸 뒤 사실 검토에서 ‘이번 회차 일시 사용’을 선택하거나 ‘확인한 프로그램 설명’과 같은 문구가 있는 명시 조건을 직접 편집하세요. 판단이 어려우면 재검토에 보류할 수 있습니다.</p>
    </div>}
    {loaded && !programDraft && canRecheck && <a className="inline-block py-2 underline" href={"#recheck-"+jobId}>재검토 선택으로 이동</a>}
    {draft && !programDraft && <p className="mt-2">보존 결과 · 한국어 {draft.output.ko ? '있음' : '없음'} · 일본어 {draft.output.ja ? '있음' : '없음'}</p>}
    {draft && <>
      <p className="mt-2">{failureLabels.stage[draft.stage as keyof typeof failureLabels.stage] ?? draft.stage} · {failureLabels.rule[draft.diagnostic.rule as keyof typeof failureLabels.rule] ?? draft.diagnostic.rule} · {failureLabels.reason[draft.diagnostic.reason as keyof typeof failureLabels.reason] ?? draft.diagnostic.reason}</p>
      {!date && draft.diagnostic.location && <p>{Object.entries(draft.diagnostic.location).map(([key, value]) =>
          ({field:'검사 필드',row:'행',column:'열',table:'표',line:'줄',item:'항목'}[key] ?? key) + ' ' + value).join(' · ')}</p>}
      {!date && ('expected' in draft.diagnostic || 'actual' in draft.diagnostic) && <dl className="mt-2 text-sm">
        <div><dt className="inline font-semibold">기대값 </dt><dd className="inline break-words">{JSON.stringify(draft.diagnostic.expected ?? null)}</dd></div>
        <div><dt className="inline font-semibold">검사값 </dt><dd className="inline break-words">{JSON.stringify(draft.diagnostic.actual ?? null)}</dd></div>
      </dl>}
      {Object.entries(draft.output).map(([field, value]) => <details key={field} className="mt-2">
        <summary>{labels[field as Field]}</summary><p className="whitespace-pre-wrap break-words">{value}</p>
      </details>)}
      {draft.requested && <div className="mt-3">
        <p>{draft.outcome ? outcomeText[draft.outcome] : draft.started ? '수정 작업 결과 확인 중' : '기존 수정 요청 대기'}</p>
        {draft.after && <p className="whitespace-pre-wrap break-words">수정 제안 {draft.after}</p>}
      </div>}
    </>}
  </section>;
}

