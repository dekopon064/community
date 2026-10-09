// Real SSR SDK against loopback fake Auth/RPC only. No env files or provider calls.
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { createServer } from "node:http";
import { createHmac, randomUUID } from "node:crypto";
import { createServerClient } from "@supabase/ssr";

registerHooks({ resolve(s, c, next) {
  try { return next(s, c); } catch (e) {
    if (s.startsWith(".") && !/\.[a-z]+$/i.test(s)) return next(s + ".ts", c);
    throw e;
  }
} });
const { startSocialLogin, finishSocialLogin, readLoginState } = await import("../app/lib/auth/handlers.ts");
const { lineLoginEnabled } = await import("../app/lib/auth/config.ts");
const { startWithSave, finishWithSave, logoutWithSave } = await import("../app/lib/saved/auth-flow.ts");
const { savedRequest } = await import("../app/lib/saved/handlers.ts");
const { readIntent } = await import("../app/lib/saved/intent.ts");
const { verifyAdminAccess } = await import("../app/lib/auth/admin-policy.ts");
const { profileResponse } = await import("../app/lib/auth/profile.ts");

let checks = 0, externalRequests = 0;
const eq = (a, b, label) => { assert.deepEqual(a, b, label); checks++; };
const site = "http://127.0.0.1:3197";
const A = "00000000-0000-4000-8000-000000000011", B = "00000000-0000-4000-8000-000000000012";
const id = "10000000-0000-4000-8000-000000000001";
const secret = "synthetic-line-only", key = "synthetic-publishable-key";
const users = new Map([A, B].map(uid => [uid, { id: uid, aud: "authenticated", role: "authenticated",
  // No email; editable profile flags do not grant admin privileges.
  app_metadata: { provider: "custom:line", providers: ["custom:line"] },
  user_metadata: { name: "合成 LINE 利用者", admin: true }, created_at: "2026-10-09T00:00:00Z" }]));
const row = { id, slug: "synthetic-event", user_category: "event", is_published: true,
  title_ko: "합성 행사", summary_ko: "합성 요약", content_ko: "합성 내용",
  title_ja: "テストイベント", summary_ja: "要約テスト", content_ja: "本文テスト" };
const issue = uid => {
  const parts = [{ alg: "HS256", typ: "JWT" }, { sub: uid, aud: "authenticated", role: "authenticated",
    iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 3600 }].map(v => Buffer.from(JSON.stringify(v)).toString("base64url"));
  return parts.join(".") + "." + createHmac("sha256", secret).update(parts.join(".")).digest("base64url");
};
function owner(raw) {
  try {
    const [h, p, sig] = raw.split(".");
    if (sig !== createHmac("sha256", secret).update(h + "." + p).digest("base64url")) return null;
    const claims = JSON.parse(Buffer.from(p, "base64url"));
    return claims.exp > Date.now() / 1000 && users.has(claims.sub) ? claims.sub : null;
  } catch { return null; }
}
let rejectUser = false, resumeCalls = 0, tokenCalls = 0;
const consumed = new Set(), rpcCalls = [];
const server = createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json");
  let raw = ""; for await (const chunk of req) raw += chunk;
  const u = new URL(req.url, site), body = raw ? JSON.parse(raw) : {};
  const uid = owner(req.headers.authorization?.replace(/^Bearer /, ""));
  const send = (value, status = 200) => { res.statusCode = status; res.end(JSON.stringify(value)); };
  if (u.pathname === "/auth/v1/token") {
    tokenCalls++;
    const userId = body.auth_code === "line-a" ? A : body.auth_code === "line-b" ? B : body.refresh_token?.replace(/^fake-/, "");
    if (!users.has(userId) || !body.code_verifier && !body.refresh_token) return send({ code: "bad_code", msg: "Synthetic failure" }, 400);
    return send({ access_token: issue(userId), refresh_token: "fake-" + userId, expires_in: 3600,
      token_type: "bearer", user: users.get(userId) });
  }
  if (u.pathname === "/auth/v1/user") return uid && !rejectUser ? send(users.get(uid)) : send({ code: "bad_jwt" }, 401);
  if (u.pathname === "/auth/v1/logout") return send({});
  if (u.pathname === "/rest/v1/curations") return send(row);
  const name = u.pathname.replace("/rest/v1/rpc/", "");
  rpcCalls.push(name);
  if (name === "prepare_saved_information_intent") return send({ token: randomUUID() });
  if (name === "cancel_saved_information_intent" || name === "cancel_saved_information_resume") return send({ cancelled: true });
  if (name === "resume_saved_information" && uid) {
    resumeCalls++;
    if (consumed.has(body.p_intent_id)) return send({ outcome: "expired" });
    consumed.add(body.p_intent_id);
    return send({ id: body.p_curation_id, saved: true, version: "0", outcome: "saved" });
  }
  return send({ code: "42501" }, 401);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const backend = `http://127.0.0.1:${server.address().port}`;
const originalFetch = globalThis.fetch;
globalThis.fetch = (input, init) => {
  const u = new URL(input instanceof Request ? input.url : input);
  if (u.origin !== backend) { externalRequests++; throw new Error("External request blocked by local test"); }
  return originalFetch(input, init);
};
const jar = new Map(); let cookieWrites = [], intent = null;
const store = { read: () => readIntent(intent ? encodeURIComponent(JSON.stringify(intent)) : undefined),
  write: value => { intent = value; }, clear: () => { intent = null; } };
const factory = async () => createServerClient(backend, key, { cookieOptions: { httpOnly: true, sameSite: "lax" },
  cookies: { getAll: () => [...jar].map(([name, value]) => ({ name, value })), setAll: values => {
    cookieWrites.push(...values);
    for (const { name, value, options } of values) { if (options.maxAge === 0) jar.delete(name); else jar.set(name, value); }
  } } });
const post = (provider = "line", next = "/ja/info/synthetic-event", extra = {}, origin = site) => new Request(site + "/api/auth/start", {
  method: "POST", headers: { Origin: origin }, body: new URLSearchParams({ locale: "ja", next, provider, ...extra }) });
const noCache = r => { assert.match(r.headers.get("cache-control"), /private.*no-store/); checks++; };
const savedPost = (action, body) => new Request(site + "/api/saved/" + action, {
  method: "POST", headers: { Origin: site, "Content-Type": "application/json" }, body: JSON.stringify(body) });
async function start(next = "/ja/info/synthetic-event", extra = {}) {
  const r = await startWithSave(post("line", next, extra), factory, store, undefined, true, true);
  noCache(r); const auth = new URL(r.headers.get("location"));
  eq(auth.origin, backend); eq(auth.searchParams.get("provider"), "custom:line");
  const callback = new URL(auth.searchParams.get("redirect_to"));
  eq(callback.pathname, "/api/auth/callback"); return { r, auth, callback };
}
async function callback(cb, code = "line-a") { cb.searchParams.set("code", code); const r = await finishWithSave(new Request(cb), factory, store); noCache(r); return r; }
async function prepare() {
  jar.clear(); intent = null;
  const r = await savedRequest(savedPost("request", { id, slug: row.slug, locale: "ja" }), "request", factory, store);
  eq(r.status, 401); eq(store.read().phase, "pending"); return store.read();
}
const originalGate = process.env.MACHIMOA_LINE_LOGIN_ENABLED;
try {
  for (const value of [undefined, "", "false", "TRUE", " true ", "1", "true"]) {
    if (value === undefined) delete process.env.MACHIMOA_LINE_LOGIN_ENABLED; else process.env.MACHIMOA_LINE_LOGIN_ENABLED = value;
    eq(lineLoginEnabled(), value === "true", "strict rollout setting");
  }
  let deniedCalls = 0;
  const denied = async () => { deniedCalls++; throw new Error("Auth must not be called"); };
  const disabled = await startSocialLogin(post(), denied);
  noCache(disabled); eq(new URL(disabled.headers.get("location")).searchParams.get("notice"), "unavailable");
  eq((await startSocialLogin(post("line", "/ja", {}, "https://evil.invalid"), denied, undefined, true, undefined, true)).status, 403);
  for (const name of ["custom:line", "custom:evil", "LINE", "naver", "", "https://evil.invalid"]) {
    const r = await startSocialLogin(post(name), denied, undefined, true, undefined, true); eq(r.status, 400); noCache(r);
  }
  const duplicateBody = new URLSearchParams({ provider: "line", locale: "ja" }); duplicateBody.append("provider", "google");
  eq((await startSocialLogin(new Request(site + "/api/auth/start", { method: "POST", headers: { Origin: site }, body: duplicateBody }), denied, undefined, true, undefined, true)).status, 400);
  eq(deniedCalls, 0);

  const { auth, callback: cb } = await start("/ja/info?region=seoul#details", { scopes: "email", scope: "email", queryParams: "admin" });
  eq(auth.searchParams.get("scopes"), "openid profile"); eq(auth.searchParams.get("ui_locales"), "ja");
  eq(auth.searchParams.has("scope"), false); eq(auth.searchParams.has("queryParams"), false);
  assert.ok(auth.searchParams.get("code_challenge")); checks++;
  assert.ok(cookieWrites.some(c => c.name.endsWith("-code-verifier") && c.options.httpOnly && c.options.sameSite === "lax")); checks++;
  eq(cb.searchParams.get("next"), "/ja/info?region=seoul#details");
  const finished = await callback(cb); eq(finished.headers.get("location"), site + "/ja/info?region=seoul#details");
  eq((await (await readLoginState(factory, true)).json()).status, "signed_in");
  eq((await (await profileResponse(await factory(), true)).json()).displayName, "合成 LINE 利用者");
  eq((await verifyAdminAccess(factory, B)).status, "forbidden", "LINE/profile flags cannot grant admin");
  eq(resumeCalls, 0, "ordinary callback cannot save");
  const ko = await startSocialLogin(new Request(site + "/api/auth/start", { method: "POST", headers: { Origin: site }, body: new URLSearchParams({ provider: "line", locale: "ko", next: "//evil.invalid" }) }), factory, undefined, true, undefined, true);
  const koAuth = new URL(ko.headers.get("location")); eq(koAuth.searchParams.get("ui_locales"), "ko");
  eq(new URL(koAuth.searchParams.get("redirect_to")).searchParams.get("next"), "/ko");

  for (const provider of ["google", "kakao"]) {
    const r = await startSocialLogin(post(provider), factory, undefined, true, undefined, true);
    const u = new URL(r.headers.get("location")); eq(u.searchParams.get("provider"), provider);
    eq(u.searchParams.get("scope"), provider === "kakao" ? "profile_nickname,profile_image" : null);
    eq(u.searchParams.has("scopes"), false);
  }
  const outage = await startSocialLogin(post(), async () => null, undefined, true, undefined, true);
  eq(new URL(outage.headers.get("location")).searchParams.get("notice"), "unavailable");
  const refusal = await startSocialLogin(post(), async () => ({ auth: { signInWithOAuth: async () => ({ data: { url: null }, error: { message: "DO_NOT_ECHO" } }) } }), undefined, true, undefined, true);
  eq(new URL(refusal.headers.get("location")).searchParams.get("notice"), "failed");
  eq(refusal.headers.get("location").includes("DO_NOT_ECHO"), false);

  const pending = await prepare();
  const saveStart = await start("/ja/info/synthetic-event", { saveIntent: pending.token });
  eq(saveStart.callback.searchParams.get("saveIntent"), pending.token);
  const saveFinish = await callback(saveStart.callback);
  eq(store.read().phase, "ready"); eq(store.read().accountId, A); eq(resumeCalls, 0);
  eq(new URL(saveFinish.headers.get("location")).searchParams.get("saveIntent"), pending.token);
  const resumed = await savedRequest(savedPost("resume", { id, token: pending.token }), "resume", factory, store);
  noCache(resumed); eq((await resumed.json()).saved, true); eq(resumeCalls, 1);
  eq((await savedRequest(savedPost("resume", { id, token: pending.token }), "resume", factory, store)).status, 409); eq(resumeCalls, 1);

  const switching = await prepare();
  const switchStart = await start("/ja/info/synthetic-event", { saveIntent: switching.token });
  await callback(switchStart.callback);
  // A second validated LINE session may not consume A's prepared save.
  const bStart = await startSocialLogin(post(), factory, undefined, true, undefined, true);
  const bCallback = new URL(new URL(bStart.headers.get("location")).searchParams.get("redirect_to")); bCallback.searchParams.set("code", "line-b");
  await finishSocialLogin(new Request(bCallback), factory);
  eq((await savedRequest(savedPost("resume", { id, token: switching.token }), "resume", factory, store)).status, 409); eq(resumeCalls, 1);

  for (const scenario of ["cancel", "bad_code", "verify_failed"]) {
    const p = await prepare(); const s = await start("/ja/info/synthetic-event", { saveIntent: p.token });
    if (scenario === "cancel") { s.callback.searchParams.set("error", "access_denied"); s.callback.searchParams.set("error_description", "DO_NOT_ECHO"); }
    else s.callback.searchParams.set("code", scenario === "bad_code" ? "bad" : "line-a");
    const before = tokenCalls; rejectUser = scenario === "verify_failed";
    const r = await finishWithSave(new Request(s.callback), factory, store); rejectUser = false;
    noCache(r); eq(new URL(r.headers.get("location")).searchParams.get("notice"), scenario === "cancel" ? "cancelled" : "failed");
    eq(r.headers.get("location").includes("DO_NOT_ECHO"), false); eq(store.read(), null); eq(resumeCalls, 1);
    if (scenario === "cancel") eq(tokenCalls, before);
  }
  const expired = await prepare(); intent.issuedAt -= 901000;
  const expiredStart = await start("/ja/info/synthetic-event", { saveIntent: expired.token });
  eq(expiredStart.callback.searchParams.has("saveIntent"), false); await callback(expiredStart.callback); eq(resumeCalls, 1);
  cookieWrites = [];
  const logout = await logoutWithSave(post(), factory, store); noCache(logout);
  eq(new URL(logout.headers.get("location")).searchParams.get("notice"), "signed_out");
  eq((await (await readLoginState(factory, false)).json()).status, "signed_out"); eq(store.read(), null);
  assert.ok(cookieWrites.some(c => /-auth-token/.test(c.name) && c.options.maxAge === 0)); checks++;
  eq(rpcCalls.some(n => /link|merge|admin/.test(n)), false);
  eq(externalRequests, 0);
  console.log(JSON.stringify({ checks, fakeAuth: true, emailOptionalAccount: true, saveResumeCalls: resumeCalls, externalRequests, actualLineOAuth: false }));
} finally {
  if (originalGate === undefined) delete process.env.MACHIMOA_LINE_LOGIN_ENABLED; else process.env.MACHIMOA_LINE_LOGIN_ENABLED = originalGate;
  globalThis.fetch = originalFetch;
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
}
