import type {WorkerRun} from '../../lib/pc-worker/contracts';

type Props = {
  run?: WorkerRun;
  awaiting: boolean;
  uncertain: boolean;
  disabled: boolean;
  onReviewCandidates: () => void;
};

export function AiRunProgress({run, awaiting, uncertain, disabled, onReviewCandidates}: Props) {
  if (!run && !awaiting) return null;
  const counts = run?.counts;
  const total = counts?.selected;
  const created = counts?.completed ?? 0;
  const skipped = counts?.unavailable_skipped ?? 0;
  // Older workers only include individual failure receipts in the final report.
  const failed = counts?.confirmed_failed ?? run?.failures?.filter(row => row.terminationConfirmed).length ?? 0;
  const confirmed = created + skipped + failed;
  const unknown = uncertain || run?.state === 'unknown';
  const running = !unknown && (awaiting || run?.state === 'running');
  const finished = !unknown && (run?.state === 'completed' || run?.state === 'partial' ||
    (run?.state === 'failed' && total !== undefined && total > 0 && confirmed === total));
  const moving = running && (total === undefined || total === 1 && confirmed === 0);
  const width = total ? `${Math.min(100, 100 * confirmed / total)}%` : undefined;
  let title = 'AI 처리 중단';
  if (unknown) title = run?.state === 'unknown' ? 'AI 처리 중단 · 결과 확인 필요' : '실행 상태 확인 필요';
  else if (running) title = total === undefined ? '실행 대상 확인 중' : 'AI 처리 중';
  else if (finished) title = total === 0 ? '실행 가능한 항목 없음' : 'AI 처리 완료';
  else if (run?.state === 'auth_required') title = 'AI 처리 중단 · Pro 인증 필요';
  const tone = running ? 'text-blue-700 [[data-theme=dark]_&]:text-blue-300' : finished
    ? 'text-emerald-800 [[data-theme=dark]_&]:text-emerald-300' : 'text-amber-800 [[data-theme=dark]_&]:text-amber-300';
  const summary = [
    total !== undefined && `후보 생성 ${created}건`,
    failed > 0 && `정식 실패 ${failed}건`,
    skipped > 0 && `건너뜀 ${skipped}건`,
    !!counts?.state_unknown && `결과 불명 ${counts.state_unknown}건`,
    !running && !finished && run?.state !== 'running' && counts?.unprocessed !== undefined && `미처리 ${counts.unprocessed}건`,
  ].filter(Boolean).join(' · ');
  return <div className="rounded-lg border border-info-rule bg-info-surface px-4 py-3">
    <div role="status" className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <strong className={tone}>{title}</strong>
      {total !== undefined && total > 0 && <span className="text-sm tabular-nums text-info-body">{confirmed} / {total}건 확정</span>}
    </div>
    {(moving || width) && <div role="progressbar" aria-label="AI 항목 처리 진행률" aria-valuemin={0}
      aria-valuemax={total} aria-valuenow={moving ? undefined : confirmed}
      aria-valuetext={moving ? title : `${total}건 중 ${confirmed}건 확정`}
      className={`mt-2 h-2.5 overflow-hidden rounded-full bg-info-rule ${tone}`}>
      <div className={`h-full rounded-full bg-current ${moving ? 'ai-run-indeterminate w-1/3' : 'motion-safe:transition-[width]'}`}
        style={moving ? undefined : {width}}/>
    </div>}
    {summary && <p className="mt-2 text-sm text-info-body">{summary}</p>}
    {unknown && run?.state !== 'unknown' && <p className="mt-2 text-sm text-info-body">PC 연결 영역에서 최신 실행 상태를 확인해 주세요.</p>}
    {finished && created > 0 && <button type="button" disabled={disabled} onClick={onReviewCandidates}
      className="mt-1 min-h-11 font-semibold text-ink underline underline-offset-4 disabled:opacity-50">AI 결과 후보 검토로 이동</button>}
  </div>;
}
