const JSON_CONTENT_TYPE = "application/json; charset=utf-8";
const FETCH_TIMEOUT_MS = 25000;
const FUNCTION_REGION_QUERY = "forceFunctionRegion=ap-northeast-2";

const ERROR_CODES = [
  "method_not_allowed",
  "origin_denied",
  "payload_too_large",
  "unsupported_media_type",
  "invalid_json",
  "validation_failed",
  "privacy_notice_outdated",
  "turnstile_unavailable",
  "rate_limited",
  "temporary_error",
] as const;

export type FeedbackErrorCode = (typeof ERROR_CODES)[number];

export type SubmitFeedbackRequest = {
  feedback_type: "hard_to_find_life_info" | "product_opinion" | "other_inquiry";
  body: string;
  locale: "ko" | "ja";
  privacy_consent: true;
  age_confirmed: true;
  privacy_notice_version: string;
  turnstile_token: string;
  topic?: "housing" | "identity" | "work" | "education" | "welfare" | "participation" | "other";
  contact_consent: boolean;
  email?: string;
  honeypot?: string;
};

export type DeleteFeedbackRequest = {
  receipt_code: string;
  turnstile_token: string;
  honeypot?: string;
};

export type SubmitFeedbackResult =
  | { ok: true; outcome: "inserted"; receiptCode: string }
  | { ok: false; error: FeedbackErrorCode };

export type DeleteFeedbackResult =
  | { ok: true; outcome: "processed" }
  | { ok: false; error: FeedbackErrorCode };

const RECEIPT_DISPLAY_RE =
  /^[0-9A-HJKMNP-TV-Z]{5}(?:-[0-9A-HJKMNP-TV-Z]{5}){3}-[0-9A-HJKMNP-TV-Z]{6}$/;

const ERROR_CODE_SET = new Set<string>(ERROR_CODES);

function supabaseOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (typeof raw !== "string" || raw.length === 0) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not configured");
  }
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not a valid URL");
  }
}

function functionUrl(name: "submit-feedback" | "delete-feedback"): string {
  return `${supabaseOrigin()}/functions/v1/${name}?${FUNCTION_REGION_QUERY}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseErrorCode(value: unknown): FeedbackErrorCode {
  if (typeof value === "string" && ERROR_CODE_SET.has(value)) {
    return value as FeedbackErrorCode;
  }
  return "temporary_error";
}

async function postJson(
  url: string,
  payload: Record<string, unknown>,
): Promise<{ status: number; body: unknown }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": JSON_CONTENT_TYPE },
      body: JSON.stringify(payload),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });

    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }

    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  } finally {
    clearTimeout(timer);
  }
}

function buildSubmitPayload(input: SubmitFeedbackRequest): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    feedback_type: input.feedback_type,
    body: input.body,
    locale: input.locale,
    privacy_consent: true,
    age_confirmed: true,
    privacy_notice_version: input.privacy_notice_version,
    turnstile_token: input.turnstile_token,
    contact_consent: input.contact_consent,
  };

  if (input.topic) {
    payload.topic = input.topic;
  }

  if (input.contact_consent) {
    payload.email = input.email;
  }

  if (typeof input.honeypot === "string" && input.honeypot.length > 0) {
    payload.honeypot = input.honeypot;
  }

  return payload;
}

export async function submitFeedback(
  input: SubmitFeedbackRequest,
): Promise<SubmitFeedbackResult> {
  const { status, body } = await postJson(
    functionUrl("submit-feedback"),
    buildSubmitPayload(input),
  );

  if (!isRecord(body)) {
    return { ok: false, error: "temporary_error" };
  }

  if (status === 200 && body.ok === true && body.outcome === "inserted") {
    if (
      typeof body.receipt_code === "string" &&
      RECEIPT_DISPLAY_RE.test(body.receipt_code)
    ) {
      return { ok: true, outcome: "inserted", receiptCode: body.receipt_code };
    }
    return { ok: false, error: "temporary_error" };
  }

  if (body.ok === false) {
    return { ok: false, error: parseErrorCode(body.error) };
  }

  return { ok: false, error: "temporary_error" };
}

export async function deleteFeedback(
  input: DeleteFeedbackRequest,
): Promise<DeleteFeedbackResult> {
  const payload: Record<string, unknown> = {
    receipt_code: input.receipt_code,
    turnstile_token: input.turnstile_token,
  };
  if (typeof input.honeypot === "string" && input.honeypot.length > 0) {
    payload.honeypot = input.honeypot;
  }

  const { status, body } = await postJson(
    functionUrl("delete-feedback"),
    payload,
  );

  if (!isRecord(body)) {
    return { ok: false, error: "temporary_error" };
  }

  if (status === 200 && body.ok === true && body.outcome === "processed") {
    return { ok: true, outcome: "processed" };
  }

  if (body.ok === false) {
    return { ok: false, error: parseErrorCode(body.error) };
  }

  return { ok: false, error: "temporary_error" };
}
