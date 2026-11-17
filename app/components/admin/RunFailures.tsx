import {failureLines} from '../../lib/pc-worker/failure-detail';
import {workerSources} from '../../lib/pc-worker/contracts';
import type {WorkerRun} from '../../lib/pc-worker/contracts';
import labels from '../../lib/pc-worker/failure-labels.json';

function stopReason(run:WorkerRun){
  if(run.code==='provider_not_reusable')return '다음 항목의 AI 호출 준비를 확인하지 못했습니다.';
  if(run.code!=='state_unknown')return null;
  const last=run.failures?.findLast(row=>row.flow==='stopped');
  switch(last?.stopStage){
    case 'failure_termination': return '정식 실패 저장 결과를 확인할 수 없어 전체 실행을 중단했습니다.';
    case 'candidate_completion': return '후보 저장 결과를 확인할 수 없어 전체 실행을 중단했습니다.';
    case 'claim': return '작업 선점 또는 입력 상태를 확인할 수 없어 전체 실행을 중단했습니다.';
    case 'summary': case 'translation': case 'correction': return labels.stage[last.stopStage]+' 결과를 확인할 수 없어 전체 실행을 중단했습니다.';
    default: return '처리 결과를 확인할 수 없어 전체 실행을 중단했습니다.';
  }
}
export function RunFailures({run}:{run:WorkerRun}){
  const stop=stopReason(run);
  return <>
    {stop&&<p className="mt-2 text-sm text-info-status">{stop}</p>}
    {!!run.failures?.length&&<details className="mt-3" open={run.failures.length<=3}>
      <summary className="cursor-pointer font-semibold">항목별 실패 진단 {run.failures.length}건</summary>
      <ol className="mt-2 space-y-3">{run.failures.map(row=><li key={row.sequence} className="border-t border-info-rule pt-2">
        <p className="font-semibold">{row.sequence}번째 · {workerSources[row.source]}</p>
        <p className="text-xs break-all">항목 ID {row.sourceItemId}</p>
        {failureLines(row.detail).map((line,i)=><p key={i}>{line}</p>)}
        <p>{row.terminationConfirmed?'정식 실패 저장 확인':'정식 실패 저장 미확인'} · {row.flow==='continued'?'다음 항목 처리 진행':row.flow==='last'?'마지막 항목':'전체 중단'}</p>
      </li>)}</ol>
    </details>}
  </>;
}
