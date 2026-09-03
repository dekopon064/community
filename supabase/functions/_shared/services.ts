import type { AppConfig } from "./env.ts";
import { isPlainObject } from "./http.ts";
import type { SubmitFields } from "./validation.ts";

const RPC_TIMEOUT_MS = 8000;
const TELEGRAM_TIMEOUT_MS = 3000;
const UUID_RE =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

function rpcHeaders(config: AppConfig): Headers {
  const headers = new Headers();
  headers.set("apikey", config.secret);
  headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");
  if (config.secretKind === "legacy") {
    headers.set("Authorization", `Bearer ${config.secret}`);
  }
  return headers;
}

async function callRpc(config: AppConfig, name: "submit_feedback" | "delete_feedback", payload: Record<string, unknown>): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), RPC_TIMEOUT_MS);
  try {
    const response = await fetch(`${config.supabaseUrl}/rest/v1/rpc/${name}`, {
      method: "POST",
      headers: rpcHeaders(config),
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      return null;
    }
    try {
      return await response.json();
    } catch {
      return null;
    }
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function singleRow(data: unknown): Record<string, unknown> | null {
  if (!Array.isArray(data) || data.length !== 1) {
    return null;
  }
  const row = data[0];
  if (!isPlainObject(row)) {
    return null;
  }
  return row;
}

export type SubmitRpcResult =
  | { ok: true; outcome: "inserted"; submissionId: string }
  | { ok: true; outcome: "rate_limited" }
  | { ok: true; outcome: "rejected" }
  | { ok: false };

export type DeleteRpcResult =
  | { ok: true; outcome: "processed" }
  | { ok: true; outcome: "rate_limited" }
  | { ok: false };

export async function submitFeedbackRpc(
  config: AppConfig,
  fields: SubmitFields,
  receiptHmac: string,
  rateHmac: string,
): Promise<SubmitRpcResult> {
  const data = await callRpc(config, "submit_feedback", {
    p_locale: fields.locale,
    p_feedback_type: fields.feedbackType,
    p_topic: fields.topic,
    p_body: fields.body,
    p_privacy_consent: true,
    p_age_gate_accepted: true,
    p_contact_consent: fields.contactConsent,
    p_email: fields.email,
    p_privacy_notice_version: config.privacyNoticeVersion,
    p_receipt_hmac: receiptHmac,
    p_rate_hmac: rateHmac,
  });

  const row = singleRow(data);
  if (row === null) {
    return { ok: false };
  }

  const outcome = row.outcome;
  if (outcome === "inserted") {
    if (typeof row.submission_id !== "string" || !UUID_RE.test(row.submission_id)) {
      return { ok: false };
    }
    return { ok: true, outcome: "inserted", submissionId: row.submission_id };
  }
  if (outcome === "rate_limited") {
    return { ok: true, outcome: "rate_limited" };
  }
  if (outcome === "rejected") {
    return { ok: true, outcome: "rejected" };
  }
  return { ok: false };
}

export async function deleteFeedbackRpc(
  config: AppConfig,
  receiptHmac: string,
  rateHmac: string,
): Promise<DeleteRpcResult> {
  const data = await callRpc(config, "delete_feedback", {
    p_receipt_hmac: receiptHmac,
    p_rate_hmac: rateHmac,
  });

  const row = singleRow(data);
  if (row === null) {
    return { ok: false };
  }
  if (row.outcome === "processed") {
    return { ok: true, outcome: "processed" };
  }
  if (row.outcome === "rate_limited") {
    return { ok: true, outcome: "rate_limited" };
  }
  return { ok: false };
}

function telegramText(args: {
  submissionId: string;
  submittedAt: string;
  locale: string;
  feedbackType: string;
  topic: string | null;
  contactConsent: boolean;
}): string {
  const topic = args.topic === null ? "-" : args.topic;
  const contact = args.contactConsent ? "true" : "false";
  return [
    "feedback inserted",
    `id ${args.submissionId}`,
    `time ${args.submittedAt}`,
    `locale ${args.locale}`,
    `type ${args.feedbackType}`,
    `topic ${topic}`,
    `contact_consent ${contact}`,
  ].join("\n");
}

export async function notifyTelegramInserted(
  config: AppConfig,
  args: {
    submissionId: string;
    submittedAt: string;
    locale: string;
    feedbackType: string;
    topic: string | null;
    contactConsent: boolean;
  },
): Promise<boolean> {
  if (config.telegram === null) {
    return true;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TELEGRAM_TIMEOUT_MS);
  try {
    const response = await fetch(
      `https://api.telegram.org/bot${config.telegram.botToken}/sendMessage`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: config.telegram.chatId,
          text: telegramText(args),
        }),
        signal: controller.signal,
      },
    );
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
