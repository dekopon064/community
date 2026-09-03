import type { AppConfig } from "./env.ts";

const TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const TURNSTILE_TIMEOUT_MS = 5000;
const MAX_FORWARDED_HOP_CHARS = 45;
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const RECEIPT_DOMAIN = "machimoa.feedback.receipt.v1";
const RATE_DOMAIN = "machimoa.feedback.rate.v1";
const IPV4_RE =
  /^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;

function isIpv4(value: string): boolean {
  return IPV4_RE.test(value);
}

function isHextet(value: string): boolean {
  return /^[0-9a-fA-F]{1,4}$/.test(value);
}

function isIpv6(value: string): boolean {
  if (value.length === 0 || value.length > MAX_FORWARDED_HOP_CHARS) {
    return false;
  }
  if (value.includes(":::")) {
    return false;
  }

  let head = value;
  let ipv4Tail = false;
  const lastColon = value.lastIndexOf(":");
  if (lastColon >= 0) {
    const tail = value.slice(lastColon + 1);
    if (tail.includes(".")) {
      if (!isIpv4(tail)) {
        return false;
      }
      ipv4Tail = true;
      head = value.slice(0, lastColon);
    }
  }

  const compressions = head.split("::");
  if (compressions.length > 2) {
    return false;
  }

  const groups: string[] = [];
  const parseSide = (side: string): string[] | null => {
    if (side.length === 0) {
      return [];
    }
    const parts = side.split(":");
    for (const part of parts) {
      if (!isHextet(part)) {
        return null;
      }
    }
    return parts;
  };

  if (compressions.length === 1) {
    const parts = parseSide(compressions[0]);
    if (parts === null) {
      return false;
    }
    groups.push(...parts);
    const expected = ipv4Tail ? 6 : 8;
    return groups.length === expected;
  }

  const left = parseSide(compressions[0]);
  const right = parseSide(compressions[1]);
  if (left === null || right === null) {
    return false;
  }
  const used = left.length + right.length + (ipv4Tail ? 2 : 0);
  return used < 8;
}

function isIpLiteral(value: string): boolean {
  if (value.length === 0 || value.length > MAX_FORWARDED_HOP_CHARS) {
    return false;
  }
  return isIpv4(value) || isIpv6(value);
}

function trimHop(value: string): string {
  let start = 0;
  let end = value.length;
  while (start < end && (value.charCodeAt(start) === 32 || value.charCodeAt(start) === 9)) {
    start += 1;
  }
  while (end > start && (value.charCodeAt(end - 1) === 32 || value.charCodeAt(end - 1) === 9)) {
    end -= 1;
  }
  return value.slice(start, end);
}

export function rateIdentity(req: Request, config: AppConfig): string | null {
  if (!config.hosted) {
    return config.localRateId;
  }

  const header = req.headers.get("x-forwarded-for");
  if (header === null) {
    return null;
  }
  const firstComma = header.indexOf(",");
  const hop = trimHop(firstComma === -1 ? header : header.slice(0, firstComma));
  if (!isIpLiteral(hop)) {
    return null;
  }
  return hop;
}

function asBufferSource(bytes: Uint8Array): ArrayBuffer {
  const copy = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(copy).set(bytes);
  return copy;
}

export async function hmacSha256(secret: Uint8Array, message: Uint8Array): Promise<Uint8Array | null> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      asBufferSource(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const signature = await crypto.subtle.sign("HMAC", key, asBufferSource(message));
    const bytes = new Uint8Array(signature);
    if (bytes.byteLength !== 32) {
      return null;
    }
    return bytes;
  } catch {
    return null;
  }
}

export function toByteaLiteral(bytes: Uint8Array): string {
  let hex = "";
  for (let i = 0; i < bytes.byteLength; i += 1) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return `\\x${hex}`;
}

function encodeCrockford26(bytes: Uint8Array): string {
  let bits = 0;
  let buffer = 0;
  let output = "";
  for (let i = 0; i < bytes.byteLength; i += 1) {
    buffer = (buffer << 8) | bytes[i];
    bits += 8;
    while (bits >= 5) {
      const index = (buffer >>> (bits - 5)) & 31;
      output += CROCKFORD[index];
      bits -= 5;
      buffer &= (1 << bits) - 1;
    }
  }
  if (bits > 0) {
    output += CROCKFORD[(buffer << (5 - bits)) & 31];
  }
  return output;
}

export function generateReceiptCode(): string | null {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const encoded = encodeCrockford26(bytes);
  if (encoded.length !== 26) {
    return null;
  }
  return encoded;
}

export async function receiptHmac(
  secret: Uint8Array,
  canonicalReceipt: string,
): Promise<Uint8Array | null> {
  const message = new TextEncoder().encode(`${RECEIPT_DOMAIN}\u0000${canonicalReceipt}`);
  return await hmacSha256(secret, message);
}

export async function rateHmac(
  secret: Uint8Array,
  action: "submit" | "delete",
  identity: string,
): Promise<Uint8Array | null> {
  const message = new TextEncoder().encode(`${RATE_DOMAIN}\u0000${action}\u0000${identity}`);
  return await hmacSha256(secret, message);
}

export type TurnstileResult =
  | { ok: true }
  | { ok: false; error: "validation_failed" | "turnstile_unavailable" };

type SiteverifyBody = {
  success?: unknown;
  hostname?: unknown;
  action?: unknown;
};

export async function verifyTurnstile(args: {
  secret: string;
  token: string;
  expectedHostname: string;
  expectedAction: string;
  remoteip: string | null;
}): Promise<TurnstileResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TURNSTILE_TIMEOUT_MS);
  try {
    const form = new FormData();
    form.set("secret", args.secret);
    form.set("response", args.token);
    if (args.remoteip !== null && isIpLiteral(args.remoteip)) {
      form.set("remoteip", args.remoteip);
    }

    const response = await fetch(TURNSTILE_URL, {
      method: "POST",
      body: form,
      signal: controller.signal,
    });

    if (!response.ok) {
      return { ok: false, error: "turnstile_unavailable" };
    }

    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      return { ok: false, error: "turnstile_unavailable" };
    }

    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: "turnstile_unavailable" };
    }

    const body = parsed as SiteverifyBody;
    if (body.success !== true) {
      return { ok: false, error: "validation_failed" };
    }
    if (body.hostname !== args.expectedHostname || body.action !== args.expectedAction) {
      return { ok: false, error: "validation_failed" };
    }
    return { ok: true };
  } catch {
    return { ok: false, error: "turnstile_unavailable" };
  } finally {
    clearTimeout(timer);
  }
}
