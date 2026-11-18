'use client';

import type { CandidateItem } from '@/app/lib/review/contracts';
import { actionText, sourceLink } from '@/app/lib/review/presentation';
import { candidatePeriodText } from '@/app/lib/review/candidate-display';
import { filterKeys } from '@/app/lib/contentFilters';
import { CandidateFilterComparison, reviewFilterLabel } from './FilterReviewPanel';

export function CandidateSource({source}: {source: CandidateItem['source']}) {
  const url = sourceLink(source.url);
  return <section aria-label="후보 원문" className="mt-3 mb-6">
    {url && <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center underline underline-offset-4">공식 원문 열기 (새 창)</a>}
    <details><summary className="min-h-11 cursor-pointer py-2 font-semibold">수집 당시 원문 보기</summary>
      <p className="mt-2 text-sm leading-6 text-info-muted">수집해 보존한 원문입니다. 현재 공식 페이지의 내용과 다를 수 있습니다.</p>
      <p className="mt-3 whitespace-pre-wrap break-words leading-7 text-info-body">{source.body || '저장된 원문 본문이 없습니다.'}</p>
    </details>
  </section>;
}

export function RegistrationLink() {
  return <button type="button" className="mt-2 inline-flex min-h-11 items-center text-sm underline underline-offset-4" onClick={() => {
    const details = document.getElementById('candidate-registration') as HTMLDetailsElement | null;
    if (!details) return;
    details.open = true;
    details.querySelector('summary')?.focus({preventScroll:true});
    details.scrollIntoView({block:'start'});
  }}>등록 정보·변경 이력에서 확인</button>;
}

export function CandidateFilterAlert({item}: {item: CandidateItem}) {
  const info = item.filterInfo;
  if (!info || !info.changed && info.canPublish) return null;
  const changed = filterKeys.filter(k => JSON.stringify(info.approved[k]) !== JSON.stringify(info.current[k])).map(k => reviewFilterLabel(info.current,k));
  return <section aria-label="탐색 정보 확인 필요" role="status" className="mb-6 text-info-status">
    <h3 className="font-semibold">{info.changed ? '후보 반영 후 탐색 정보가 변경되었습니다' : '게시 전 탐색 정보 확인이 필요합니다'}</h3>
    {info.changed && <p className="mt-2 leading-7">{changed.length ? `변경 항목: ${changed.join(' · ')}.` : '변경된 세부 항목을 특정할 수 없습니다.'} 후보 내용과 현재 확정값을 대조한 뒤 수정 저장해 주세요. 생성 당시 입력은 보존됩니다.</p>}
    {!info.canPublish && <p className="mt-2 leading-7">현재 탐색 정보로는 게시할 수 없습니다.</p>}
    <RegistrationLink/>
  </section>;
}

export function CandidateRegistration({item, local}: {item: CandidateItem; local: boolean}) {
  return <details id="candidate-registration" key={item.id} className="my-7 scroll-mt-24 border-t border-info-rule pt-3">
    <summary className="min-h-11 cursor-pointer py-2 font-semibold">등록 정보·변경 이력</summary>
    <div className="space-y-6 py-4">
      {item.programInfo ? <section aria-label="기간·사실 버전" className="text-sm leading-7">
        <h3 className="mb-2 font-semibold">신청·운영 기간과 사실 버전</h3>
        <p className="break-words">신청 기간: {candidatePeriodText(item.programInfo.applicationPeriod)}</p>
        <p className="break-words">운영 기간: {candidatePeriodText(item.programInfo.operatingPeriod)}</p>
        <p className="mt-2 text-info-muted">후보 입력 사실 버전 {item.programInfo.inputFactsVersion} · 현재 사실 버전 {item.programInfo.currentFactsVersion}</p>
      </section> : item.period && <p className="text-sm leading-7">기존 기간 표시: {candidatePeriodText(item.period)}</p>}
      {item.filterInfo && <CandidateFilterComparison info={item.filterInfo} expanded/>}
      <section aria-label="저장·처리 이력"><h3 className="font-semibold">저장·처리 이력 ({item.history.length})</h3>
        {item.publishedAt && <p className="mt-2 text-sm">{local ? '시험 게시' : '게시'} 시각: {candidatePeriodText(item.publishedAt)}</p>}
        {item.history.length ? <ol className="divide-y divide-info-rule">{item.history.map((entry,index) => <li key={index} className="py-4 text-sm leading-6">
          <p className="font-semibold">{entry.changeLabel ?? actionText[entry.action] ?? '처리 기록'} · {candidatePeriodText(entry.at)}</p>
          <p className="break-all text-info-muted">작업 계정: {entry.actor}</p>
          {entry.note && <p className="mt-1 whitespace-pre-wrap break-words text-info-body">{entry.note}</p>}
        </li>)}</ol> : <p className="mt-2 text-sm text-info-muted">아직 저장·처리 이력이 없습니다.</p>}
      </section>
    </div>
  </details>;
}
