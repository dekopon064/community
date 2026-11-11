'use client';

import { useState } from 'react';
import type { CandidateContent } from '@/app/lib/review/contracts';
import { secondaryButton } from './ReviewEditors';

type Value = string | number | boolean | null | Value[];
type Field = 'contentKo' | 'contentJa' | 'titleJa';
export type ReviewIssue = {
  stage: string; rule?: string; reason?: string;
  location?: Record<string, string | number>; expected?: Value; actual?: Value;
  disposition: 'change' | 'equivalent' | 'needs_review';
  field?: Field; before?: string; after?: string; evidence?: string; summaryPatch?: boolean;
};
export type CandidateReview = { source: string; issues: ReviewIssue[] };
const fields = { contentKo: '한국어 본문', contentJa: '일본어 본문', titleJa: '일본어 제목' };
const checks: Record<string, string> = {
  cell_date_time: '일정표 날짜·시간', period_date_time: '기간 날짜·시간', clock: '시간',
  calendar_session_date: '회차 날짜', calendar_session_clock: '회차 시간',
  per_session: '회차당 조건', per_person: '1인당 조건', quantity: '인원·수량',
  fee_amount: '요금', fee_role: '요금 항목', translation_currency: '번역 통화',
  participation_constraint: '참가 조건', official_link: '공식 링크',
};
const reasons: Record<string, string> = {
  mismatch: '기준 자료와 다른 값이 감지됐습니다.',
  missing: '기준 자료의 조건이 결과에서 누락된 것으로 감지됐습니다.',
  added: '기준 자료에서 인식하지 못한 조건이 결과에 추가된 것으로 감지됐습니다.',
  missing_or_mismatched: '조건이 누락됐거나 다른 값으로 표현된 것으로 감지됐습니다.',
  unexpected_yen: '번역에서 엔화로 해석될 수 있는 표기가 감지됐습니다.',
};
export function issueField(issue: ReviewIssue): Field | null {
  if (issue.field && issue.field in fields) return issue.field;
  if (issue.location?.field === 'body') return issue.stage === 'korean_validation' ? 'contentKo' : 'contentJa';
  if (issue.location?.field === 'title' && issue.stage === 'japanese_validation') return 'titleJa';
  return null;
}
function replaceOnce(text: string, before: string, after: string) {
  const at = text.indexOf(before);
  return at < 0 || text.indexOf(before, at + 1) >= 0 ? null : text.slice(0, at) + after + text.slice(at + before.length);
}
export function applySeoulReviewPatch(content: CandidateContent, issue: ReviewIssue): CandidateContent | null {
  const { field, before, after, summaryPatch } = issue;
  if (issue.disposition !== 'change' || !field || !before || !after || before === after || !(field in fields)) return null;
  if (after.includes(before) && content[field].includes(after)) return null;
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

// Historical coordinates are diagnostic context only. Match recorded text uniquely;
// never interpret old list/table/line numbers as positions in an edited candidate.
function surroundingLine(text: string, needle?: string): string | null {
  if (!needle) return null;
  const at = text.indexOf(needle);
  if (at < 0 || text.indexOf(needle, at + 1) >= 0) return null;
  if (needle.includes('\n')) return needle;
  const end = text.indexOf('\n', at + needle.length);
  return text.slice(text.lastIndexOf('\n', at - 1) + 1, end < 0 ? text.length : end)
    .replace(/^( *)(?:[-+*]\s+|\d+[.)]\s+)/, '').trim();
}
export function issueExcerpt(content: CandidateContent, issue: ReviewIssue): string | null {
  const field = issueField(issue);
  if (!field) return null;
  const text = content[field];
  const surrounding = surroundingLine(text, issue.before) ?? surroundingLine(text, issue.after);
  if (surrounding !== null) return surrounding;
  return null;
}
export function groupReviewIssues(issues: ReviewIssue[], saved: CandidateContent) {
  const groups: { issue: ReviewIssue; occurrences: ReviewIssue[] }[] = [];
  const keys = new Map<string, number>();
  for (const issue of issues) {
    // Changes stay separate: their individual replacement safety must be retained.
    const excerpt = issueExcerpt(saved, issue);
    const key = issue.disposition === 'change' || !excerpt ? null : JSON.stringify([
      issue.stage, issue.rule, issue.reason, issue.disposition, issue.evidence,
      issue.expected, issue.actual, issueField(issue), excerpt,
    ]);
    const prior = key === null ? undefined : keys.get(key);
    if (prior !== undefined) groups[prior].occurrences.push(issue);
    else { if (key !== null) keys.set(key, groups.length); groups.push({ issue, occurrences: [issue] }); }
  }
  return groups;
}
export function reviewSaveState(issue: ReviewIssue, content: CandidateContent, saved: CandidateContent, applied?: CandidateContent) {
  const field = issueField(issue);
  if (!field) return '문구 위치 확인 필요';
  const summary = field === 'contentKo' ? 'summaryKo' : 'summaryJa';
  const equal = (a: CandidateContent, b: CandidateContent) => a[field] === b[field] && (!issue.summaryPatch || a[summary] === b[summary]);
  if (!equal(content, saved)) return applied && equal(content, applied) ? '편집기에 반영됨 · 저장 전' : '직접 편집 또는 다른 변경 · 저장 전';
  if (issue.disposition === 'change') {
    const inverse = applySeoulReviewPatch(saved, { ...issue, before: issue.after, after: issue.before });
    if (inverse) return '후보에 저장됨 · 제안 문구와 일치';
    return applySeoulReviewPatch(saved, issue) ? 'AI 수정 제안 · 미적용' : '저장본 · 제안 위치 확인 필요';
  }
  return '저장본과 같음 · 변경 없음';
}
function locationText(issue: ReviewIssue) {
  const loc = issue.location;
  if (!loc) return '위치 기록 없음';
  if (loc.table) return `표 ${loc.table}${loc.row === 0 ? ' · 머리글' : loc.row ? ` · ${loc.row}행` : ''}${loc.column ? ` · ${loc.column}열` : ''}`;
  if (loc.item) return `목록 ${loc.item}번째 항목`;
  if (loc.line) return `${loc.line}번째 줄`;
  return '세부 위치 기록 없음';
}
function readableValue(value?: Value): string | null {
  if (typeof value === 'number') return String(value);
  if (!Array.isArray(value)) return null;
  if (value[0] === 'time' && value.length === 3) return value.slice(1).map(n => String(n).padStart(2, '0')).join(':');
  if (value[0] === 'date' && value.length === 4) return `${typeof value[1] === 'number' ? `${value[1]}년 ` : ''}${value[2]}월 ${value[3]}일`;
  return null;
}
function ChangedText({ text, other }: { text: string; other: string }) {
  let start = 0, end = 0;
  while (start < Math.min(text.length, other.length) && text[start] === other[start]) start++;
  while (end < Math.min(text.length, other.length) - start && text[text.length - 1 - end] === other[other.length - 1 - end]) end++;
  return <>{text.slice(0, start)}<strong className="underline decoration-2 underline-offset-4">{text.slice(start, text.length - end)}</strong>{end ? text.slice(-end) : ''}</>;
}
function editAt(field: Field, excerpt: string | null) {
  const root = document.getElementById(field);
  if (!root) return;
  const editable = root instanceof HTMLTextAreaElement ? root : root.querySelector<HTMLTextAreaElement>('textarea');
  if (editable) {
    editable.focus();
    const at = excerpt ? editable.value.indexOf(excerpt) : -1;
    if (at >= 0) editable.setSelectionRange(at, at + excerpt!.length);
    editable.scrollIntoView({ block: 'center' });
    return;
  }
  const leaves = Array.from(root.querySelectorAll<HTMLElement>('[data-editor-leaf]'));
  const matches = excerpt ? leaves.filter(node => node.textContent?.includes(excerpt)) : [];
  const target = (excerpt && leaves.find(node => node.textContent === excerpt)) || (matches.length === 1 ? matches[0] : leaves[0]);
  target?.focus();
  target?.scrollIntoView({ block: 'center' });
}

export function SeoulCandidateFindings({ review, content, savedContent = content, onChange, disabled }: {
  review: CandidateReview; content: CandidateContent; savedContent?: CandidateContent;
  onChange?: (value: CandidateContent) => void; disabled?: boolean;
}) {
  const [applied, setApplied] = useState<Record<number, CandidateContent>>({});
  const [kept, setKept] = useState<Record<number, boolean>>({});
  const groups = groupReviewIssues(review.issues, savedContent);
  const actionable = groups.map((group, index) => ({ ...group, index })).filter(g => g.issue.disposition !== 'equivalent');
  const history = groups.filter(g => g.issue.disposition === 'equivalent');
  const count = (d: ReviewIssue['disposition']) => groups.filter(g => g.issue.disposition === d).length;
  return <>
    <h3 className="text-lg font-bold">AI 결과 검토</h3>
    <p className="mt-2 text-sm leading-6">수정 제안 {count('change')}개 · 근거 확인 필요 {count('needs_review')}개</p>
    {actionable.length > 0 ? <p className="mt-2 max-w-prose text-sm leading-6">아래 수정 제안과 확인이 필요한 내용을 원문과 비교해 주세요. 수정안을 적용하거나 직접 편집했다면 ‘수정 저장’ 후 게시 여부를 결정합니다.</p>
      : <p className="mt-2 max-w-prose text-sm leading-6">이 검사 기록에서 추가로 수정할 사항은 없습니다. 별도 수정·저장 없이 본문 최종 검토 후 게시 여부를 결정할 수 있습니다.</p>}
    <ol className="mt-6 space-y-8">
      {actionable.map(({ issue, occurrences, index }) => {
        const field = issueField(issue);
        const patched = applySeoulReviewPatch(content, issue);
        const excerpt = issueExcerpt(content, issue);
        const originalLine = field ? surroundingLine(savedContent[field], issue.before) : null;
        const suggestion = originalLine && issue.before && issue.after ? replaceOnce(originalLine, issue.before, issue.after) :
          (field ? surroundingLine(savedContent[field], issue.after) : null) ?? issue.after;
        const state = reviewSaveState(issue, content, savedContent, applied[index]);
        return <li key={index} className="min-w-0 border-t border-info-rule pt-5 text-sm leading-7">
          <h4 className="text-base font-bold">{checks[issue.rule ?? ''] ?? '내용 확인'} · {issue.disposition === 'change' ? 'AI 수정 제안' : issue.disposition === 'equivalent' ? '문구 유지' : '근거 확인 필요'}</h4>
          <p className="text-info-muted">{field ? fields[field] : issue.stage === 'korean_validation' ? '한국어 결과' : '일본어 결과'} · {occurrences.length > 1 ? `${occurrences.length}곳에서 같은 내용 감지` : `검사 당시 위치: ${locationText(issue)}`}</p>
          <p className="mt-3 font-semibold">왜 확인이 필요한가요?</p>
          <p className="max-w-prose">{reasons[issue.reason ?? ''] ?? '검사에서 확인이 필요한 표현을 감지했습니다. 검사 상세와 원문을 함께 확인해 주세요.'} 검사의 감지 결과이며, 실제 오류인지는 원문과 비교해 판단합니다.</p>
          {readableValue(issue.expected) !== null && readableValue(issue.actual) !== null && <p className="mt-2 font-semibold">검사 비교 · 기준 {readableValue(issue.expected)} / 결과 {readableValue(issue.actual)}</p>}
          <dl className="mt-4">
            <dt className="font-semibold">수집된 원문 근거</dt>
            <dd className="mt-1 whitespace-pre-wrap break-words">{issue.evidence || '이 검사에 연결된 원문 인용이 없습니다. 아래 수집된 원문 전체와 직접 대조해 주세요.'}</dd>
          </dl>
          <div className="mt-5 grid min-w-0 gap-5 md:grid-cols-2">
            <div className="min-w-0"><p className="font-semibold">현재 후보 문구</p>
              <p className="mt-2 whitespace-pre-wrap break-words" lang={!excerpt || field === 'contentKo' ? 'ko' : 'ja'}>{excerpt ? issue.disposition === 'change' && suggestion ? <ChangedText text={excerpt} other={suggestion}/> : excerpt : '현재 본문에서 검사 당시 문구를 특정할 수 없습니다. 과거 위치로 다른 문장을 표시하지 않습니다. 본문 전체와 원문을 대조해 주세요.'}</p>
              {excerpt && !issue.before && <p className="mt-1 text-xs text-info-muted">기록된 문구와 일치하는 현재 본문을 표시합니다.</p>}
              {!excerpt && field && <details className="mt-2"><summary className="min-h-11 cursor-pointer py-2">현재 필드 전체 보기</summary><p className="max-h-64 overflow-auto whitespace-pre-wrap break-words" lang={field === 'contentKo' ? 'ko' : 'ja'}>{content[field]}</p></details>}
            </div>
            <div className="min-w-0"><p className="font-semibold">{issue.disposition === 'change' ? 'AI 수정 제안' : 'AI 검토 결과'}</p>
              <p className="mt-2 whitespace-pre-wrap break-words" lang={issue.disposition === 'change' && field !== 'contentKo' ? 'ja' : 'ko'}>{issue.disposition === 'change' && suggestion ? <ChangedText text={suggestion} other={originalLine ?? issue.before ?? ''}/> : issue.disposition === 'equivalent' ? '원문과 같은 의미로 판단해 문구를 유지했습니다. AI가 수정한 부분은 없습니다.' : '근거가 부족하거나 안전한 수정안을 만들지 못했습니다. 원문을 확인해 직접 편집하거나 보류할 수 있습니다.'}</p>
            </div>
          </div>
          {issue.disposition === 'change' && issue.before && issue.after && <details className="mt-3">
            <summary className="min-h-11 cursor-pointer py-2 font-semibold">수정 전후 비교</summary>
            <div className="grid gap-5 md:grid-cols-2"><div><p className="font-semibold">제안 당시 수정 전</p><p className="whitespace-pre-wrap break-words"><ChangedText text={issue.before} other={issue.after}/></p></div><div><p className="font-semibold">제안 문구</p><p className="whitespace-pre-wrap break-words"><ChangedText text={issue.after} other={issue.before}/></p></div></div>
          </details>}
          <p role="status" className="mt-4 font-semibold">{kept[index] && state === 'AI 수정 제안 · 미적용' ? '현재 문구 유지 선택 · 문구 변경 없음' : state}</p>
          {onChange && <div className="mt-3 flex flex-wrap gap-2">
            {issue.disposition === 'change' && <button type="button" className={secondaryButton} disabled={disabled || !patched} onClick={() => {
              if (patched && !disabled) { setApplied(old => ({ ...old, [index]: patched })); setKept(old => ({ ...old, [index]: false })); onChange(patched); }
            }}>수정안 적용</button>}
            {field && <button type="button" className={secondaryButton} disabled={disabled} onClick={() => editAt(field, excerpt)}>{excerpt ? '본문에서 직접 편집' : '본문 전체에서 확인·편집'}</button>}
            {issue.disposition === 'change' && patched && <button type="button" className={secondaryButton} disabled={disabled} onClick={() => setKept(old => ({ ...old, [index]: true }))}>현재 문구 유지</button>}
          </div>}
          {kept[index] && <p className="mt-2 text-xs text-info-muted">이 화면에서의 선택이며 별도 확인 이력은 저장하지 않습니다. 수정안은 계속 선택할 수 있습니다.</p>}
          <details className="mt-3"><summary className="min-h-11 cursor-pointer py-2 text-info-muted">검사 상세{occurrences.length > 1 ? ` · ${occurrences.length}곳` : ''}</summary>
            <p>검사 {issue.rule} · 사유 {issue.reason}</p>
            {occurrences.map((occurrence, n) => <p key={n}>{locationText(occurrence)}</p>)}
            <p className="break-words">기준 자료 추출값 {JSON.stringify(issue.expected ?? null)} / 결과 추출값 {JSON.stringify(issue.actual ?? null)}</p>
            <p>추출값은 내부 비교 형식입니다. 빈 값은 원문에 조건이 없다는 뜻으로 단정할 수 없습니다.</p>
          </details>
        </li>;
      })}
    </ol>
    {history.length > 0 && <details className="mt-6 border-t border-info-rule pt-3">
      <summary className="min-h-11 cursor-pointer py-2 font-semibold">수정 불필요 · 참고 이력 {count('equivalent')}개</summary>
      <p className="mt-2 max-w-prose text-sm leading-6">자동 검사가 감지했지만 AI가 원문과 같은 의미로 판단해 문구를 유지한 기록입니다. 이 기록에 대한 별도 수정·저장은 필요하지 않습니다. 본문 최종 검토는 그대로 진행해 주세요.</p>
      <ul className="mt-4 space-y-5 text-sm leading-7">
        {history.map(({ issue, occurrences }, index) => <li key={index} className="border-t border-info-rule pt-4">
          <h4 className="font-semibold">{checks[issue.rule ?? ''] ?? '내용 검사'} · AI 판단: 수정 불필요</h4>
          <p className="mt-2">원문과 같은 의미로 판단해 문구를 유지했습니다. AI가 수정한 부분은 없습니다.</p>
          <p className="mt-2 whitespace-pre-wrap break-words"><strong>당시 확인한 원문 근거</strong><br/>{issue.evidence || '저장된 원문 인용이 없습니다.'}</p>
          <details className="mt-2 text-info-muted">
            <summary className="min-h-11 cursor-pointer py-2">당시 검사 기록</summary>
            <p>{reasons[issue.reason ?? ''] ?? '내용 차이가 감지됐습니다.'}</p>
            <p>검사 {issue.rule} · 사유 {issue.reason}</p>
            {occurrences.map((occurrence, n) => <p key={n}>검사 당시 위치: {locationText(occurrence)}</p>)}
            <p>위치는 과거 기록이며 현재 본문의 위치를 뜻하지 않습니다.</p>
            <p className="break-words">기준 자료 추출값 {JSON.stringify(issue.expected ?? null)} / 결과 추출값 {JSON.stringify(issue.actual ?? null)}</p>
          </details>
        </li>)}
      </ul>
    </details>}
    {review.source && <details className="mt-6 border-t border-info-rule pt-3"><summary className="min-h-11 cursor-pointer py-2 font-semibold">수집된 원문 전체 보기</summary><p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-sm leading-7">{review.source}</p></details>}
  </>;
}
