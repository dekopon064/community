import type { SupabaseClient } from "@supabase/supabase-js";
import { startSocialLogin, finishSocialLogin, endLogin } from "../auth/handlers";
import { authLocale, safeReturnTo, isSameOriginPost } from "../auth/urls";
import { verifiedAccount } from "../auth/profile";
import { authRedirect } from "../auth/http";
import { matchesIntent, type IntentStore } from "./intent";
type Factory = () => Promise<SupabaseClient | null>;
export async function startWithSave(request: Request, factory: Factory, intents: IntentStore, origin?: string, kakao = false) {
  if (!isSameOriginPost(request)) return startSocialLogin(request, factory);
  const form = await request.clone().formData().catch(() => null), intent = intents.read();
  const matched = intent?.phase === "pending" && matchesIntent(intent, form?.get("saveIntent"), form?.get("next"));
  if (!matched) {
    intents.clear();
    // Starting ordinary login deliberately cancels the old save-purpose nonce.
    if (intent) {
      const client = await factory().catch(() => null);
      if (client) await client.rpc("cancel_saved_information_intent", { p_intent_id: intent.token }).then(() => {}, () => {});
    }
  }
  const response = await startSocialLogin(request, factory, origin, kakao, matched ? intent!.token : undefined);
  const target = response.headers.get("location");
  if (matched && (!target || new URL(target, request.url).origin === new URL(request.url).origin)) intents.clear();
  return response;
}
export async function finishWithSave(request: Request, factory: Factory, intents: IntentStore, origin?: string) {
  const response = await finishSocialLogin(request, factory, origin), url = new URL(request.url);
  const next = safeReturnTo(url.searchParams.get("next"), authLocale(url.searchParams.get("locale")));
  const intent = intents.read(), token = url.searchParams.get("saveIntent");
  const success = response.headers.get("location") === new URL(next, request.url).href;
  if (!matchesIntent(intent, token, next)) {
    if (token && success) { const target = new URL(next, request.url); target.searchParams.set("saveResult", "intent_expired"); return authRedirect(request, target.pathname + target.search); }
    return response;
  }
  if (!success) { intents.clear(); return response; }
  const account = await verifiedAccount(await factory().catch(() => null));
  if (!account.user || intent?.phase !== "pending") {
    intents.clear(); const target = new URL(next, request.url); target.searchParams.set("saveResult", "save_after_login_failed"); return authRedirect(request, target.pathname + target.search);
  }
  intents.write({ ...intent, phase: "ready", accountId: account.user.id });
  const target = new URL(next, request.url); target.searchParams.set("saveIntent", intent.token);
  // Callback GET only prepares a cookie; no saved RPC is called here.
  return authRedirect(request, target.pathname + target.search);
}
export async function logoutWithSave(request: Request, factory: Factory, intents: IntentStore) {
  if (!isSameOriginPost(request)) return endLogin(request, factory);
  const intent = intents.read();
  intents.clear();
  const client = await factory().catch(() => null), account = await verifiedAccount(client);
  if (client && intent) await client.rpc("cancel_saved_information_intent", { p_intent_id: intent.token }).then(() => {}, () => {});
  // Auth logout remains possible during a saving-service outage.
  if (client && account.user) await client.rpc("cancel_saved_information_resume").then(() => {}, () => {});
  return endLogin(request, async () => client);
}
