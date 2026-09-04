const BODY_TRIM_RE = /^[ \t\n\r\u3000]+|[ \t\n\r\u3000]+$/g;

export const FEEDBACK_BODY_MIN = 10;
export const FEEDBACK_BODY_MAX = 1000;

export function normalizeFeedbackBody(body: string): string {
  return body.replace(BODY_TRIM_RE, "");
}

export function isFeedbackBodyLengthValid(normalized: string): boolean {
  return (
    normalized.length >= FEEDBACK_BODY_MIN &&
    normalized.length <= FEEDBACK_BODY_MAX
  );
}
