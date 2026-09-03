export type SecretKind = "current" | "legacy";

type DenoRuntime = {
  env: {
    get(name: string): string | undefined;
  };
  serve(handler: (req: Request) => Response | Promise<Response>): void;
};

export function getDeno(): DenoRuntime | null {
  const runtime = (globalThis as { Deno?: DenoRuntime }).Deno;
  if (runtime === undefined || typeof runtime.env?.get !== "function") {
    return null;
  }
  return runtime;
}

export type TelegramConfig = {
  botToken: string;
  chatId: string;
};

export type AppConfig = {
  supabaseUrl: string;
  secret: string;
  secretKind: SecretKind;
  allowedOrigins: ReadonlySet<string>;
  privacyNoticeVersion: string;
  turnstileSecret: string;
  turnstileHostname: string;
  turnstileSubmitAction: string;
  turnstileDeleteAction: string;
  receiptHmacSecret: Uint8Array;
  rateHmacSecret: Uint8Array;
  hosted: boolean;
  localRateId: string | null;
  telegram: TelegramConfig | null;
};

const PRODUCTION_TURNSTILE_HOSTNAME = "community-app-drab.vercel.app";
const PRODUCTION_TURNSTILE_SUBMIT_ACTION = "feedback_submit";
const PRODUCTION_TURNSTILE_DELETE_ACTION = "feedback_delete";
const LOCAL_TURNSTILE_ACTION = "test";
const MIN_HMAC_SECRET_BYTES = 32;
const CURRENT_SECRET_PREFIX = "sb_secret_";

function readEnv(name: string): string | undefined {
  const runtime = getDeno();
  if (runtime === null) {
    return undefined;
  }
  const value = runtime.env.get(name);
  if (value === undefined) {
    return undefined;
  }
  return value;
}

function utf8Bytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function secretsEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.byteLength !== b.byteLength) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.byteLength; i += 1) {
    diff |= a[i] ^ b[i];
  }
  return diff === 0;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLegacyJwt(value: string): boolean {
  const parts = value.split(".");
  return parts.length === 3 && parts.every((part) => part.length > 0);
}

function classifySecret(value: string): SecretKind | null {
  if (value.startsWith(CURRENT_SECRET_PREFIX) && value.length > CURRENT_SECRET_PREFIX.length) {
    return "current";
  }
  if (isLegacyJwt(value)) {
    return "legacy";
  }
  return null;
}

function parseSecretKeysJson(raw: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) {
    return null;
  }
  const defaultKey = parsed["default"];
  if (typeof defaultKey !== "string" || defaultKey.length === 0) {
    return null;
  }
  return defaultKey;
}

function parseAllowedOrigins(raw: string): ReadonlySet<string> | null {
  const origins = raw
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  if (origins.length === 0) {
    return null;
  }
  for (const origin of origins) {
    if (origin === "*" || origin.includes("*")) {
      return null;
    }
    try {
      const url = new URL(origin);
      if (url.origin !== origin) {
        return null;
      }
    } catch {
      return null;
    }
  }
  return new Set(origins);
}

function resolveSecret(): { secret: string; kind: SecretKind } | null {
  const secretKeysRaw = readEnv("SUPABASE_SECRET_KEYS");
  if (secretKeysRaw !== undefined) {
    const fromJson = parseSecretKeysJson(secretKeysRaw);
    if (fromJson === null) {
      return null;
    }
    const kind = classifySecret(fromJson);
    if (kind === null) {
      return null;
    }
    return { secret: fromJson, kind };
  }

  const localCurrent = readEnv("SUPABASE_SECRET_KEY");
  if (localCurrent !== undefined && localCurrent.length > 0) {
    const kind = classifySecret(localCurrent);
    if (kind === null) {
      return null;
    }
    return { secret: localCurrent, kind };
  }

  const legacy = readEnv("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy !== undefined && legacy.length > 0) {
    const kind = classifySecret(legacy);
    if (kind === null) {
      return null;
    }
    return { secret: legacy, kind };
  }

  return null;
}

function optionalTelegram(): TelegramConfig | null {
  const botToken = readEnv("TELEGRAM_BOT_TOKEN");
  const chatId = readEnv("TELEGRAM_CHAT_ID");
  if (botToken === undefined && chatId === undefined) {
    return null;
  }
  if (
    botToken === undefined ||
    chatId === undefined ||
    botToken.length === 0 ||
    chatId.length === 0
  ) {
    return null;
  }
  return { botToken, chatId };
}

export function loadConfig(): AppConfig | null {
  const hosted = (readEnv("DENO_DEPLOYMENT_ID") ?? "").length > 0;

  const supabaseUrl = readEnv("SUPABASE_URL");
  if (supabaseUrl === undefined || supabaseUrl.length === 0) {
    return null;
  }
  try {
    const url = new URL(supabaseUrl);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
  } catch {
    return null;
  }

  const resolvedSecret = resolveSecret();
  if (resolvedSecret === null) {
    return null;
  }

  const allowedOriginsRaw = readEnv("FEEDBACK_ALLOWED_ORIGINS");
  if (allowedOriginsRaw === undefined) {
    return null;
  }
  const allowedOrigins = parseAllowedOrigins(allowedOriginsRaw);
  if (allowedOrigins === null) {
    return null;
  }

  const privacyNoticeVersion = readEnv("FEEDBACK_PRIVACY_NOTICE_VERSION");
  if (privacyNoticeVersion === undefined || privacyNoticeVersion.length === 0) {
    return null;
  }

  const turnstileSecret = readEnv("TURNSTILE_SECRET_KEY");
  const turnstileHostname = readEnv("FEEDBACK_TURNSTILE_HOSTNAME");
  const turnstileSubmitAction = readEnv("FEEDBACK_TURNSTILE_SUBMIT_ACTION");
  const turnstileDeleteAction = readEnv("FEEDBACK_TURNSTILE_DELETE_ACTION");
  if (
    turnstileSecret === undefined ||
    turnstileSecret.length === 0 ||
    turnstileHostname === undefined ||
    turnstileHostname.length === 0 ||
    turnstileSubmitAction === undefined ||
    turnstileSubmitAction.length === 0 ||
    turnstileDeleteAction === undefined ||
    turnstileDeleteAction.length === 0
  ) {
    return null;
  }

  if (hosted) {
    if (
      turnstileHostname !== PRODUCTION_TURNSTILE_HOSTNAME ||
      turnstileSubmitAction !== PRODUCTION_TURNSTILE_SUBMIT_ACTION ||
      turnstileDeleteAction !== PRODUCTION_TURNSTILE_DELETE_ACTION
    ) {
      return null;
    }
  } else if (
    turnstileSubmitAction !== LOCAL_TURNSTILE_ACTION ||
    turnstileDeleteAction !== LOCAL_TURNSTILE_ACTION
  ) {
    return null;
  }

  const receiptSecretRaw = readEnv("FEEDBACK_RECEIPT_HMAC_SECRET");
  const rateSecretRaw = readEnv("FEEDBACK_RATE_HMAC_SECRET");
  if (receiptSecretRaw === undefined || rateSecretRaw === undefined) {
    return null;
  }
  const receiptHmacSecret = utf8Bytes(receiptSecretRaw);
  const rateHmacSecret = utf8Bytes(rateSecretRaw);
  if (
    receiptHmacSecret.byteLength < MIN_HMAC_SECRET_BYTES ||
    rateHmacSecret.byteLength < MIN_HMAC_SECRET_BYTES ||
    secretsEqual(receiptHmacSecret, rateHmacSecret)
  ) {
    return null;
  }

  let localRateId: string | null = null;
  const localRateIdRaw = readEnv("FEEDBACK_LOCAL_RATE_ID");
  if (!hosted) {
    if (
      localRateIdRaw === undefined ||
      localRateIdRaw.length === 0 ||
      localRateIdRaw.length > 256
    ) {
      return null;
    }
    localRateId = localRateIdRaw;
  }

  return {
    supabaseUrl,
    secret: resolvedSecret.secret,
    secretKind: resolvedSecret.kind,
    allowedOrigins,
    privacyNoticeVersion,
    turnstileSecret,
    turnstileHostname,
    turnstileSubmitAction,
    turnstileDeleteAction,
    receiptHmacSecret,
    rateHmacSecret,
    hosted,
    localRateId,
    telegram: optionalTelegram(),
  };
}

export function hostedRegionAllowed(config: AppConfig): boolean {
  if (!config.hosted) {
    return true;
  }
  return readEnv("SB_REGION") === "ap-northeast-2";
}
