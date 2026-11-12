import type { CandidateContent } from './contracts';
import type { ReviewIssue } from '@/app/components/admin/SeoulCandidateFindings';

// Same narrow currency vocabulary as the worker. Ordinary 円滑/円満 are not money.
export const yenExpression = /[￥¥]|[\d０-９一二三四五六七八九十百千万億兆〇零]+(?:[,.，．]\d+)*\s*円|日本円|円建て|円換算|(?<![\p{L}\p{N}_])円(?![\p{L}\p{N}_])/u;
export function currentYenLines(content: CandidateContent) {
  return ([['titleJa', content.titleJa], ['contentJa', content.contentJa]] as const)
    .flatMap(([field, text]) => text.split('\n').filter(line => yenExpression.test(line)).map(text => ({ field, text })));
}

export const reviewOutcomes: Record<string, string> = {
  equivalent: 'AI는 원문과 같은 의미로 판단했습니다. 문구를 수정하지 않았습니다.',
  change: '원문에 있는 근거와 연결된 수정 제안입니다.',
  ai_needs_review: 'AI가 확인 보류로 응답했습니다. 연결된 원문과 현재 문구를 비교해 주세요.',
  evidence_not_matched: 'AI가 제시한 근거가 저장 원문과 정확히 일치하지 않아 제안을 반영하지 않았습니다.',
  unsafe_patch: '수정 위치·범위 또는 본문 형식을 안전하게 보존할 수 없어 제안을 반영하지 않았습니다.',
  overlapping_patch: '수정 제안끼리 같은 문구 범위가 겹쳐 반영하지 않았습니다.',
  duplicate_finding: '같은 검사에 응답이 중복돼 수정 제안을 반영하지 않았습니다.',
  invalid_response: '수정 응답의 형식이 맞지 않아 제안을 반영하지 않았습니다.',
  invalid_decision: '수정 응답의 판단 구분을 확인할 수 없어 제안을 반영하지 않았습니다.',
  provider_declined: 'AI가 사용할 수 있는 수정 결과를 반환하지 않았습니다.',
  no_finding: '이 검사에 대한 개별 AI 검토 결과가 응답에 없었습니다.',
};
export function reviewOutcomeText(issue: ReviewIssue) {
  return reviewOutcomes[issue.reviewOutcome ?? ''] ?? (issue.disposition === 'equivalent'
    ? reviewOutcomes.equivalent : '당시 AI 검토의 세부 결과가 기록되지 않았습니다. 근거 부족 또는 실제 오류로 단정할 수 없습니다.');
}
export function historicalHint(issue: ReviewIssue) {
  if (issue.rule === 'cell_date_time') return '과거 검사는 축약 시각·날짜를 놓칠 수 있었습니다. 현재 한국어와 일본어의 일정 날짜·시간을 비교하세요.';
  if (issue.rule === 'quantity') return '과거 검사는 「に満たない」를 ‘미만’으로 읽지 못했습니다. 현재 인원수와 이상·이하·미만 조건을 비교하세요.';
  return '현재 문구에 연결할 기록이 부족합니다. 과거 위치를 현재 위치로 사용하지 않습니다.';
}
