'use client';

import { useEffect, useState } from 'react';
import type { CandidateContent } from '@/app/lib/review/contracts';
import { sourceLink } from '@/app/lib/review/presentation';
import { secondaryButton } from './ReviewEditors';

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

type PatchField = 'contentKo' | 'contentJa' | 'titleJa';
type Issue = Draft['diagnostic'] & {
  stage: string;
  disposition: 'change' | 'equivalent' | 'needs_review';
  field?: PatchField;
  before?: string;
  after?: string;
  evidence?: string;
  summaryPatch?: boolean;
};
type Review = { source: string; issues: Issue[] };
type CandidateDetail = { evidence: Evidence | null; review: Review | null };
const fieldNames = { contentKo: '한국어 본문', contentJa: '일본어 본문', titleJa: '일본어 제목' };

const checkNames: Record<string, string> = {
  cell_date_time: '일정표 날짜·시간', period_date_time: '기간 날짜·시간',
  calendar_session_date: '회차 날짜', calendar_session_clock: '회차 시간',
  per_session: '회차당 조건', per_person: '1인당 조건', quantity: '인원·수량',
  fee_amount: '요금', fee_role: '요금 항목', translation_currency: '번역 통화',
  participation_constraint: '참가 조건', official_link: '공식 링크',
};
const reasonNames: Record<string, string> = {
  mismatch: '불일치', missing: '누락', added: '추가', missing_or_mismatched: '누락 또는 불일치',
  unexpected_yen: '엔화 표기 감지',
};
const locationNames: Record<string, string> = { table: '표', row: '행', column: '열', line: '줄', item: '항목' };

function comparisonValue(value?: DiagnosticValue): string {
  if (value == null || (Array.isArray(value) && value.length === 0)) return '없음';
  if (!Array.isArray(value)) return String(value);
  if (value[0] === 'time' && value.slice(1).every(part => typeof part === 'number')) {
    return value.slice(1).map(part => String(part).padStart(2, '0')).join(':');
  }
  if (value[0] === 'date' && value.length === 4 && typeof value[2] === 'number' && typeof value[3] === 'number') {
    return [typeof value[1] === 'number' ? value[1] + '년' : null, value[2] + '월', value[3] + '일'].filter(Boolean).join(' ');
  }
  return value.map(comparisonValue).join(' · ');
}

function replaceOnce(text: string, before: string, after: string) {
  const index = text.indexOf(before);
  return index < 0 || text.indexOf(before, index + 1) >= 0 ? null :
    text.slice(0, index) + after + text.slice(index + before.length);
}

export function applySeoulReviewPatch(content: CandidateContent, issue: Issue): CandidateContent | null {
  const { field, before, after, summaryPatch } = issue;
  if (issue.disposition !== 'change' || !field || !before || !after || !(field in fieldNames)) return null;
  const changed = replaceOnce(content[field], before, after);
  if (changed === null) return null;
  const next = { ...content, [field]: changed };
  if (summaryPatch) {
    const key = field === 'contentKo' ? 'summaryKo' : 'summaryJa';
    const summary = replaceOnce(content[key], before, after);
    if (summary === null) return null;
    next[key] = summary;
  }
  return next;
}

export function SeoulCandidateFindings({ review, content, onChange, disabled }: {
  review: Review; content: CandidateContent; onChange?: (value: CandidateContent) => void; disabled?: boolean;
}) {
  return <>
    <h3 className="font-semibold">AI 오류·수정 검토</h3>
    <p className="mt-2 text-sm">저장본과 원문을 비교해 주세요. 제안을 적용하거나 아래 편집기에서 직접 수정할 수 있습니다. 변경한 내용은 후보 저장 후 게시할 수 있습니다.</p>
    {review.source && <details className="mt-3">
      <summary className="font-semibold">수집된 원문 근거 보기</summary>
      <p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm">{review.source}</p>
    </details>}
    <ol className="mt-3 space-y-4">
      {review.issues.map((issue, index) => {
        const patched = applySeoulReviewPatch(content, issue);
        return <li key={index} className="border-t border-info-rule pt-3 text-sm leading-6">
          <p className="font-semibold">{issue.stage === 'korean_validation' ? '한국어' : '일본어'} · {checkNames[issue.rule ?? ''] ?? issue.rule} · {reasonNames[issue.reason ?? ''] ?? issue.reason}</p>
          {issue.location && <p>{Object.entries(issue.location).map(([key, value]) => locationNames[key] ?
            key === 'table' ? '표 ' + value : key === 'row' && value === 0 ? '머리글' : value + locationNames[key] : String(value)).join(' · ')}</p>}
          {('expected' in issue || 'actual' in issue) && <p className="break-words">
            기대값 {comparisonValue(issue.expected)} / 검사값 {comparisonValue(issue.actual)}
          </p>}
          {issue.disposition === 'change' && issue.field ? <>
            <p className="mt-2 font-semibold">AI 수정 제안 · {fieldNames[issue.field]}</p>
            <dl className="whitespace-pre-wrap break-words">
              <div><dt className="inline font-semibold">수정 전 </dt><dd className="inline">{issue.before}</dd></div>
              <div><dt className="inline font-semibold">수정 후 </dt><dd className="inline">{issue.after}</dd></div>
            </dl>
            {onChange && <button type="button" className={secondaryButton} disabled={disabled || patched === null}
              onClick={() => { if (patched) onChange(patched); }}>수정안 적용</button>}
          </> : <p className="mt-2">{issue.disposition === 'equivalent' ?
            '뜻이 같은 표현으로 제안됨 · 기존 문구 유지' : '근거 부족 또는 안전한 수정안 없음 · 운영자 확인 필요'}</p>}
          {issue.evidence && <p className="whitespace-pre-wrap break-words"><strong>원문 근거 </strong>{issue.evidence}</p>}
        </li>;
      })}
    </ol>
  </>;
}

export function SeoulCandidateCorrection({ id, content, onChange, disabled }: {
  id: string; content: CandidateContent; onChange?: (value: CandidateContent) => void; disabled?: boolean;
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
  if (!detail?.evidence && !detail?.review) return null;
  return <section aria-label="AI 오류·수정 기록" className="my-5 border-y border-info-rule py-4">
    {detail.evidence && <CorrectionComparison detail={detail.evidence}/>}
    {detail.review && <SeoulCandidateFindings review={detail.review} content={content} onChange={onChange} disabled={disabled}/>}
  </section>;
}


const outcomeText: Record<string, string> = {
  validated: '재검증 통과 · 후보 검토 대기',
  validation_failed: '재검증 실패 · 비공개 초안 유지',
  translation_missing: '한국어 검증 통과 · 대응하는 일본어 결과가 필요합니다.',
  invalid_suggestion: '수정 제안이 요청 범위에 맞지 않아 비공개 초안을 유지했습니다.',
};

export function SeoulFailedDraft({ jobId, sourceItemId }: { jobId: string; sourceItemId: string }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [loaded, setLoaded] = useState(false);
  const endpoint = '/api/admin/seoul-ai-correction/' + jobId;

  async function read() {
    setPending(true);
    try {
      const response = await fetch(endpoint, { cache: 'no-store' });
      if (!response.ok) throw new Error();
      const data = await response.json();
      setDraft(data.draft ?? null);
      setLoaded(true);
      setMessage('');
    } catch {
      setMessage('비공개 초안을 불러오지 못했습니다.');
    } finally { setPending(false); }
  }

  return <section aria-label="비공개 실패 초안" className="mt-6 border-t border-info-rule py-4">
    <h4 className="font-semibold">비공개 실패 초안</h4>
    <p className="mt-2 break-all text-sm">항목 ID {sourceItemId} · 작업 ID {jobId}</p>
    <button type="button" className={secondaryButton} disabled={pending} onClick={() => void read()}>
      {loaded ? '최신 상태 확인' : '실패 초안 보기'}
    </button>
    {message && <p role="status" className="mt-2">{message}</p>}
    {loaded && !draft && <p className="mt-2">이 작업에 저장된 AI 결과가 없습니다.</p>}
    {draft && <>
      <p className="mt-2">{draft.stage} · {draft.diagnostic.rule} · {draft.diagnostic.reason}</p>
      {draft.diagnostic.location && <p>{Object.entries(draft.diagnostic.location).map(([key, value]) => key + ' ' + value).join(' · ')}</p>}
      {('expected' in draft.diagnostic || 'actual' in draft.diagnostic) && <dl className="mt-2 text-sm">
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

