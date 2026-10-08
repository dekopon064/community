import type { SupabaseClient } from "@supabase/supabase-js";
import { verifiedAccount } from "../auth/profile";
import { privateResponse, authRedirect } from "../auth/http";
import { isSameOriginPost, authLocale, loginUrl, publicBrowseReturnTo } from "../auth/urls";
import { intentPath, isUuid, type IntentStore } from "./intent";
import { isUserCategory } from "../userCategories";
type Factory = () => Promise<SupabaseClient | null>;
const reply = (data: object, status = 200) => privateResponse(Response.json(data, { status }));
const errorReply = (e: { code?: string } | null) => reply({ error: e?.code === "PT404" ? "information_unavailable" : "request_failed" }, e?.code === "PT404" ? 404 : 503);
export async function savedRequest(request: Request, action: string, factory: Factory, intents: IntentStore) {
  const read = request.method === "GET" && ["state", "list"].includes(action);
  if (!read && (request.method !== "POST" || !isSameOriginPost(request))) return reply({ error: "forbidden" }, 403);
  if (!(read || ["save", "remove", "request", "resume", "cancel", "continue"].includes(action))) return reply({ error: "not_found" }, 404);
  let body: Record<string, unknown> = {};
  if (!read) {
    try { body = request.headers.get("content-type")?.includes("application/json") ? await request.json() : Object.fromEntries(await request.formData()); }
    catch { return reply({ error: "invalid_request" }, 400); }
    if (!body || Array.isArray(body) || typeof body !== "object" || Object.keys(body).some(k => !["id", "slug", "locale", "token", "next", "version"].includes(k))) return reply({ error: "invalid_request" }, 400);
  }
  const url = new URL(request.url);
  const locale = authLocale(read ? url.searchParams.get("locale") : body.locale);
  const id = read ? url.searchParams.get("id") : body.id;
  if (!["list", "cancel"].includes(action) && !isUuid(id)) return reply({ error: "invalid_request" }, 400);
  try {
    const client = await factory();
    const account = await verifiedAccount(client);
    if (action === "cancel") {
      const intent = intents.read();
      intents.clear();
      if (intent && client) {
        const { error } = await client.rpc("cancel_saved_information_intent", { p_intent_id: intent.token });
        if (error) return errorReply(error);
      }
      if (account.user && client) { const { error } = await client.rpc("cancel_saved_information_resume"); if (error) return errorReply(error); }
      if (!request.headers.get("content-type")?.includes("application/json")) return authRedirect(request, publicBrowseReturnTo(body.next, locale));
      return reply({ cancelled: true });
    }
    if (account.status === "unavailable" || !client) return reply({ error: "unavailable" }, 503);
    if (!account.user) {
      if (action !== "request") return reply({ error: "authentication_required" }, 401);
      if (typeof body.slug !== "string" || !body.slug || body.slug.length > 200 || /[\\/\u0000-\u0020\u007f]/.test(body.slug)) return reply({ error: "invalid_request" }, 400);
      const { data, error } = await client.from("curations").select("id,slug,user_category,is_published,title_ko,summary_ko,content_ko,title_ja,summary_ja,content_ja").eq("id", id).eq("slug", body.slug).maybeSingle();
      if (error) return errorReply(error);
      if (!data?.is_published || !isUserCategory(data.user_category) || (["title_ko", "summary_ko", "content_ko", "title_ja", "summary_ja", "content_ja"] as const).some(k => typeof data[k] !== "string" || !data[k].trim())) return reply({ error: "information_unavailable" }, 404);
      const prepared = await client.rpc("prepare_saved_information_intent", { p_curation_id: id });
      if (prepared.error) return errorReply(prepared.error);
      if (!isUuid(prepared.data?.token)) return reply({ error: "request_failed" }, 503);
      const intent = { token: prepared.data.token, id: id as string, slug: body.slug, locale, issuedAt: Date.now(), phase: "pending" as const };
      intents.write(intent);
      const login = new URL(loginUrl(locale, intentPath(intent)), url.origin); login.searchParams.set("saveIntent", intent.token);
      return reply({ loginUrl: login.pathname + login.search }, 401);
    }
    if (action === "continue") {
      const intent = intents.read();
      if (!intent || intent.phase !== "pending" || intent.token !== body.token || intent.id !== id) return reply({ error: "intent_expired" }, 409);
      intents.write({ ...intent, phase: "ready", accountId: account.user.id });
      const target = new URL(intentPath(intent), request.url); target.searchParams.set("saveIntent", intent.token);
      return authRedirect(request, target.pathname + target.search);
    }
    if (action === "resume") {
      const intent = intents.read();
      if (!intent || intent.phase !== "ready" || intent.token !== body.token || intent.id !== id || intent.accountId !== account.user.id) {
        if (!intent || intent.token === body.token) intents.clear();
        return reply({ error: "intent_expired" }, 409);
      }
      intents.clear();
      const { data, error } = await client.rpc("resume_saved_information", { p_intent_id: intent.token, p_curation_id: intent.id });
      if (error) return errorReply(error);
      if (data?.outcome === "saved" && data.saved === true) return reply(data);
      return reply({ error: data?.outcome === "unavailable" ? "information_unavailable" : data?.outcome === "failed" ? "save_after_login_failed" : "intent_expired" }, data?.outcome === "failed" ? 503 : 409);
    }
    if (action === "list") {
      const offset = Number(url.searchParams.get("offset") ?? "0");
      if (!Number.isInteger(offset) || offset < 0 || offset > 100000) return reply({ error: "invalid_request" }, 400);
      const { data, error } = await client.rpc("list_saved_information", { p_locale: locale, p_limit: 25, p_offset: offset });
      return error ? errorReply(error) : reply(data);
    }
    const rpc = action === "state" ? "saved_information_state" : action === "remove" ? "remove_saved_information" : "save_information";
    const saving = rpc === "save_information";
    if (saving && (typeof body.version !== "string" || !/^(0|[1-9][0-9]{0,18})$/.test(body.version))) return reply({ error: "state_changed" }, 409);
    const { data, error } = await client.rpc(rpc, { p_curation_id: id, ...(saving ? { p_version: body.version } : {}) });
    if (error) return errorReply(error);
    return data?.outcome === "stale" ? reply({ ...data, error: "state_changed" }, 409) : reply(data);
  } catch { return reply({ error: "request_failed" }, 503); }
}
