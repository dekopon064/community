import "server-only";
import { cookies } from "next/headers";
import { INTENT_COOKIE, INTENT_TTL_SECONDS, readIntent, type IntentStore } from "./intent";
export async function intentCookies(): Promise<IntentStore> {
  const store = await cookies();
  const opts = { path: "/", httpOnly: true, sameSite: "lax" as const, secure: process.env.NODE_ENV === "production" };
  return { read: () => readIntent(store.get(INTENT_COOKIE)?.value), write: i => store.set(INTENT_COOKIE, encodeURIComponent(JSON.stringify(i)), { ...opts, maxAge: Math.max(1, Math.ceil((i.issuedAt + INTENT_TTL_SECONDS * 1000 - Date.now()) / 1000)) }), clear: () => store.set(INTENT_COOKIE, "", { ...opts, maxAge: 0 }) };
}
