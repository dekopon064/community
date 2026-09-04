import type { AppConfig } from "./env.ts";

export const FEEDBACK_TYPES = [
  "hard_to_find_life_info",
  "product_opinion",
  "other_inquiry",
] as const;

export const TOPICS = [
  "housing",
  "identity",
  "work",
  "education",
  "welfare",
  "participation",
  "other",
] as const;

export const LOCALES = ["ko", "ja"] as const;

export type FeedbackType = (typeof FEEDBACK_TYPES)[number];
export type Topic = (typeof TOPICS)[number];
export type Locale = (typeof LOCALES)[number];

const SUBMIT_KEYS = new Set([
  "feedback_type",
  "body",
  "locale",
  "privacy_consent",
  "age_confirmed",
  "privacy_notice_version",
  "turnstile_token",
  "topic",
  "honeypot",
]);

const DELETE_KEYS = new Set(["receipt_code", "turnstile_token", "honeypot"]);

const BODY_TRIM_RE = /^[ \t\n\r\u3000]+|[ \t\n\r\u3000]+$/g;
const CROCKFORD_RE = /^[0-9A-HJKMNP-TV-Z]{26}$/;

export type SubmitFields = {
  locale: Locale;
  feedbackType: FeedbackType;
  topic: Topic | null;
  body: string;
  turnstileToken: string;
};

export type DeleteFields = {
  receiptCanonical: string | null;
  turnstileToken: string;
};

export type FieldResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: "validation_failed" | "privacy_notice_outdated" };

function hasDisallowedKeys(body: Record<string, unknown>, allowed: Set<string>): boolean {
  return Object.keys(body).some((key) => !allowed.has(key));
}

function honeypotFilled(value: unknown): boolean | "invalid" {
  if (value === undefined) {
    return false;
  }
  if (typeof value !== "string") {
    return "invalid";
  }
  return value.length > 0;
}

function isTurnstileToken(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 2048;
}

export function normalizeFeedbackBody(body: string): string {
  return body.replace(BODY_TRIM_RE, "");
}

export function canonicalizeReceiptInput(raw: string): string | null {
  let start = 0;
  let end = raw.length;
  while (start < end) {
    const code = raw.charCodeAt(start);
    if (code === 32 || code === 9 || code === 10 || code === 13 || code === 45) {
      start += 1;
      continue;
    }
    break;
  }
  while (end > start) {
    const code = raw.charCodeAt(end - 1);
    if (code === 32 || code === 9 || code === 10 || code === 13 || code === 45) {
      end -= 1;
      continue;
    }
    break;
  }

  let canonical = "";
  for (let i = start; i < end; i += 1) {
    const ch = raw[i];
    if (ch === "-") {
      continue;
    }
    canonical += ch;
  }
  canonical = canonical.toUpperCase();
  if (!CROCKFORD_RE.test(canonical)) {
    return null;
  }
  return canonical;
}

export function parseSubmitBody(
  body: Record<string, unknown>,
  config: AppConfig,
): FieldResult<SubmitFields> {
  if (hasDisallowedKeys(body, SUBMIT_KEYS)) {
    return { ok: false, error: "validation_failed" };
  }

  const honeypot = honeypotFilled(body.honeypot);
  if (honeypot === "invalid" || honeypot === true) {
    return { ok: false, error: "validation_failed" };
  }

  const privacyNoticeVersion = body.privacy_notice_version;
  if (typeof privacyNoticeVersion !== "string") {
    return { ok: false, error: "validation_failed" };
  }
  if (privacyNoticeVersion !== config.privacyNoticeVersion) {
    return { ok: false, error: "privacy_notice_outdated" };
  }

  if (body.privacy_consent !== true || body.age_confirmed !== true) {
    return { ok: false, error: "validation_failed" };
  }

  const locale = body.locale;
  if (locale !== "ko" && locale !== "ja") {
    return { ok: false, error: "validation_failed" };
  }

  const feedbackType = body.feedback_type;
  if (
    feedbackType !== "hard_to_find_life_info" &&
    feedbackType !== "product_opinion" &&
    feedbackType !== "other_inquiry"
  ) {
    return { ok: false, error: "validation_failed" };
  }

  let topic: Topic | null = null;
  if (body.topic !== undefined && body.topic !== null) {
    if (
      body.topic !== "housing" &&
      body.topic !== "identity" &&
      body.topic !== "work" &&
      body.topic !== "education" &&
      body.topic !== "welfare" &&
      body.topic !== "participation" &&
      body.topic !== "other"
    ) {
      return { ok: false, error: "validation_failed" };
    }
    topic = body.topic;
  }

  if (typeof body.body !== "string") {
    return { ok: false, error: "validation_failed" };
  }
  const normalizedBody = normalizeFeedbackBody(body.body);
  if (normalizedBody.length < 10 || normalizedBody.length > 1000) {
    return { ok: false, error: "validation_failed" };
  }

  if (!isTurnstileToken(body.turnstile_token)) {
    return { ok: false, error: "validation_failed" };
  }

  return {
    ok: true,
    value: {
      locale,
      feedbackType,
      topic,
      body: normalizedBody,
      turnstileToken: body.turnstile_token,
    },
  };
}

export function parseDeleteBody(body: Record<string, unknown>): FieldResult<DeleteFields> {
  if (hasDisallowedKeys(body, DELETE_KEYS)) {
    return { ok: false, error: "validation_failed" };
  }

  const honeypot = honeypotFilled(body.honeypot);
  if (honeypot === "invalid" || honeypot === true) {
    return { ok: false, error: "validation_failed" };
  }

  if (!isTurnstileToken(body.turnstile_token)) {
    return { ok: false, error: "validation_failed" };
  }

  if (typeof body.receipt_code !== "string") {
    return { ok: false, error: "validation_failed" };
  }

  return {
    ok: true,
    value: {
      receiptCanonical: canonicalizeReceiptInput(body.receipt_code),
      turnstileToken: body.turnstile_token,
    },
  };
}

export function hyphenateReceipt(canonical: string): string {
  return `${canonical.slice(0, 5)}-${canonical.slice(5, 10)}-${canonical.slice(10, 15)}-${canonical.slice(15, 20)}-${canonical.slice(20)}`;
}
