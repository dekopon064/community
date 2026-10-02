import { safeReturnTo, type AuthLocale } from "../auth/urls";
export const INTENT_COOKIE = "machimoa-save-intent";
export const INTENT_TTL_SECONDS = 900;
export const isUuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
export type SaveIntent = { token: string; id: string; slug: string; locale: AuthLocale; issuedAt: number; phase: "pending" | "ready"; accountId?: string };
export interface IntentStore { read(): SaveIntent | null; write(intent: SaveIntent): void; clear(): void }
export function intentPath(i: SaveIntent) { return `/${i.locale}/info/${encodeURIComponent(i.slug)}`; }
export function readIntent(raw?: string, now = Date.now()): SaveIntent | null {
  try {
    const d = JSON.parse(decodeURIComponent(raw ?? ""));
    if (!isUuid(d.token) || !isUuid(d.id) || typeof d.slug !== "string" || !d.slug || d.slug.length > 200 || /[\\/\u0000-\u0020\u007f]/.test(d.slug) || !["ko", "ja"].includes(d.locale) || !["pending", "ready"].includes(d.phase) || !Number.isSafeInteger(d.issuedAt) || d.issuedAt > now + 5000 || now - d.issuedAt >= INTENT_TTL_SECONDS * 1000 || (d.phase === "ready" && !isUuid(d.accountId))) return null;
    return d;
  } catch { return null; }
}
export function matchesIntent(i: SaveIntent | null, token: unknown, next: unknown) { return !!i && i.token === token && safeReturnTo(next, i.locale) === intentPath(i); }
