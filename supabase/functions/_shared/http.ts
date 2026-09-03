import { hostedRegionAllowed, type AppConfig } from "./env.ts";

export const MAX_BODY_BYTES = 16384;

export type ErrorCode =
  | "method_not_allowed"
  | "origin_denied"
  | "payload_too_large"
  | "unsupported_media_type"
  | "invalid_json"
  | "validation_failed"
  | "privacy_notice_outdated"
  | "turnstile_unavailable"
  | "rate_limited"
  | "temporary_error";

export type FunctionName = "submit-feedback" | "delete-feedback";

export type RequestLog = {
  request_id: string;
  at: string;
  fn: FunctionName;
  ok: boolean;
  error?: ErrorCode | "telegram_failed";
};

const JSON_CONTENT_TYPE = "application/json; charset=utf-8";

export function newRequestId(): string {
  return crypto.randomUUID();
}

export function logRequest(entry: RequestLog): void {
  console.log(JSON.stringify(entry));
}

export function allowedOrigin(
  req: Request,
  allowedOrigins: ReadonlySet<string>,
): string | null {
  const origin = req.headers.get("origin");
  if (origin === null || origin.length === 0 || origin === "null") {
    return null;
  }
  if (!allowedOrigins.has(origin)) {
    return null;
  }
  return origin;
}

function baseHeaders(origin: string | null): Headers {
  const headers = new Headers();
  headers.set("Cache-Control", "no-store");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Content-Type", JSON_CONTENT_TYPE);
  headers.set("Vary", "Origin");
  if (origin !== null) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "content-type");
  }
  return headers;
}

export function jsonResponse(
  status: number,
  body: Record<string, unknown>,
  origin: string | null,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: baseHeaders(origin),
  });
}

export function errorResponse(
  status: number,
  error: ErrorCode,
  origin: string | null,
): Response {
  return jsonResponse(status, { ok: false, error }, origin);
}

export function noContent(origin: string): Response {
  return new Response(null, {
    status: 204,
    headers: baseHeaders(origin),
  });
}

export function parseJsonMediaType(contentType: string | null): boolean {
  if (contentType === null) {
    return false;
  }
  const parts = contentType.split(";").map((part) => part.trim());
  if (parts.length === 0) {
    return false;
  }
  const mediaType = parts[0].toLowerCase();
  if (mediaType !== "application/json") {
    return false;
  }
  for (let i = 1; i < parts.length; i += 1) {
    const param = parts[i];
    if (param.length === 0) {
      return false;
    }
    const eq = param.indexOf("=");
    if (eq <= 0) {
      return false;
    }
    const name = param.slice(0, eq).trim().toLowerCase();
    if (name !== "charset") {
      return false;
    }
  }
  return true;
}

type ContentLengthResult =
  | { kind: "absent" }
  | { kind: "invalid" }
  | { kind: "too_large" }
  | { kind: "ok"; value: number };

function exceedsMaxBodyBytes(digits: string): boolean {
  let value = 0;
  for (let i = 0; i < digits.length; i += 1) {
    value = value * 10 + (digits.charCodeAt(i) - 48);
    if (value > MAX_BODY_BYTES) {
      return true;
    }
  }
  return false;
}

function parseBoundedDecimal(digits: string): number {
  let value = 0;
  for (let i = 0; i < digits.length; i += 1) {
    value = value * 10 + (digits.charCodeAt(i) - 48);
  }
  return value;
}

export function inspectContentLength(header: string | null): ContentLengthResult {
  if (header === null) {
    return { kind: "absent" };
  }
  if (header.length === 0 || !/^[0-9]+$/.test(header)) {
    return { kind: "invalid" };
  }
  if (exceedsMaxBodyBytes(header)) {
    return { kind: "too_large" };
  }
  return { kind: "ok", value: parseBoundedDecimal(header) };
}

function concatBytes(chunks: Uint8Array[], total: number): Uint8Array {
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

export type ReadBodyResult =
  | { ok: true; value: unknown }
  | { ok: false; error: ErrorCode; status: number };

export async function readCappedJsonObject(req: Request): Promise<ReadBodyResult> {
  const length = inspectContentLength(req.headers.get("content-length"));
  if (length.kind === "invalid") {
    return { ok: false, error: "payload_too_large", status: 400 };
  }
  if (length.kind === "too_large") {
    return { ok: false, error: "payload_too_large", status: 413 };
  }

  const stream = req.body;
  if (stream === null) {
    if (length.kind === "ok" && length.value !== 0) {
      return { ok: false, error: "payload_too_large", status: 400 };
    }
    return { ok: false, error: "invalid_json", status: 400 };
  }

  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      if (value.byteLength === 0) {
        continue;
      }
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) {
        await reader.cancel();
        return { ok: false, error: "payload_too_large", status: 413 };
      }
      chunks.push(value);
    }
  } catch {
    try {
      await reader.cancel();
    } catch {
      // ignore cancel failure
    }
    return { ok: false, error: "invalid_json", status: 400 };
  }

  if (length.kind === "ok" && total !== length.value) {
    return { ok: false, error: "payload_too_large", status: 400 };
  }

  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(concatBytes(chunks, total));
  } catch {
    return { ok: false, error: "invalid_json", status: 400 };
  }

  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, error: "invalid_json", status: 400 };
  }
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function gateRequest(
  req: Request,
  config: AppConfig,
  fn: FunctionName,
  requestId: string,
): Promise<
  | { ok: true; origin: string; body: Record<string, unknown> }
  | { ok: false; response: Response }
> {
  const origin = allowedOrigin(req, config.allowedOrigins);
  const method = req.method.toUpperCase();

  if (method === "OPTIONS") {
    if (origin === null) {
      logRequest({
        request_id: requestId,
        at: new Date().toISOString(),
        fn,
        ok: false,
        error: "origin_denied",
      });
      return {
        ok: false,
        response: errorResponse(403, "origin_denied", null),
      };
    }
    return { ok: false, response: noContent(origin) };
  }

  if (method !== "POST") {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: "method_not_allowed",
    });
    return {
      ok: false,
      response: errorResponse(405, "method_not_allowed", origin),
    };
  }

  if (origin === null) {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: "origin_denied",
    });
    return {
      ok: false,
      response: errorResponse(403, "origin_denied", null),
    };
  }

  if (!parseJsonMediaType(req.headers.get("content-type"))) {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: "unsupported_media_type",
    });
    return {
      ok: false,
      response: errorResponse(415, "unsupported_media_type", origin),
    };
  }

  if (!hostedRegionAllowed(config)) {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: "temporary_error",
    });
    return {
      ok: false,
      response: errorResponse(503, "temporary_error", origin),
    };
  }

  const body = await readCappedJsonObject(req);
  if (!body.ok) {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: body.error,
    });
    return {
      ok: false,
      response: errorResponse(body.status, body.error, origin),
    };
  }

  if (!isPlainObject(body.value)) {
    logRequest({
      request_id: requestId,
      at: new Date().toISOString(),
      fn,
      ok: false,
      error: "invalid_json",
    });
    return {
      ok: false,
      response: errorResponse(400, "invalid_json", origin),
    };
  }

  return { ok: true, origin, body: body.value };
}
