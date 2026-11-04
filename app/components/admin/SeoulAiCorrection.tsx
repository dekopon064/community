'use client';

import { useEffect, useState } from 'react';
import type { CandidateContent } from '@/app/lib/review/contracts';
import { sourceLink } from '@/app/lib/review/presentation';
import { secondaryButton } from './ReviewEditors';
import { SeoulCandidateFindings, type CandidateReview } from './SeoulCandidateFindings';
export { SeoulCandidateFindings, applySeoulReviewPatch } from './SeoulCandidateFindings';

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
  if (!detail?.evidence && !detail?.review) return null;
  return <section aria-label="AI 결과 검토" className="my-5 border-y border-info-rule py-4">
    {detail.evidence && <CorrectionComparison detail={detail.evidence}/>}
    {detail.review && <SeoulCandidateFindings review={detail.review} content={content} savedContent={savedContent} onChange={onChange} disabled={disabled}/>}
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

