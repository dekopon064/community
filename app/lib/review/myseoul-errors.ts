import { ReviewFailure } from './contracts';
import { failureText } from './presentation';

// Only these authored messages may cross the RPC -> browser error boundary.
const saveMessages: Record<string, string> = {
  myseoul_no_resolved_fact: '확인한 값은 같지만 남은 확인 사유가 해소되지 않아 저장되지 않았습니다. 입력은 유지됩니다. 확인할 항목과 저장 조건을 다시 확인해 주세요.',
  myseoul_field_read_only: '현재 확인 사유에서 수정할 수 없는 항목이 포함되어 저장되지 않았습니다. 입력은 유지됩니다. 최신 내용을 다시 확인해 주세요.',
  myseoul_period_axis_read_only: '현재 확인 대상이 아닌 신청 기간 또는 운영 일정이 포함되어 저장되지 않았습니다. 입력은 유지됩니다. 최신 내용을 다시 확인해 주세요.',
  invalid_myseoul_date: '일정의 날짜가 유효하지 않아 저장되지 않았습니다. 입력한 날짜를 확인해 주세요.',
  invalid_myseoul_period_order: '일정의 종료가 시작보다 빨라 저장되지 않았습니다. 시작·종료 날짜와 시각을 확인해 주세요.',
};
const unknownCondition = '저장 조건 때문에 요청이 거부되었지만 정확한 원인은 확인하지 못했습니다. 입력은 유지됩니다. 최신 내용을 다시 확인해 주세요.';

export function myseoulRpcFailure(error: { code?: string; message?: string }) {
  const code = error.code === 'PT409' ? 'conflict' : error.code === 'PT422' ? 'invalid_input' : error.code === 'PT404' ? 'not_found' : 'unavailable';
  return new ReviewFailure(code, code === 'invalid_input' ? { form: saveMessages[error.message ?? ''] ?? unknownCondition } : undefined);
}

export function myseoulErrorMessage(error: unknown): string {
  const e = error instanceof Error ? error as Error & { code?: string; fields?: unknown } : null;
  const code = e?.code ?? e?.message ?? 'unavailable';
  const form = e?.fields && typeof e.fields === 'object' && 'form' in e.fields ? e.fields.form : undefined;
  if (code === 'invalid_input' && typeof form === 'string' && [...Object.values(saveMessages), unknownCondition].includes(form)) return form;
  return failureText[code] ?? failureText.unavailable;
}
