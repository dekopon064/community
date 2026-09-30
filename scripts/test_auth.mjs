import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { createServer } from "node:http";
import { createHmac } from "node:crypto";
import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server.js";

// Node's TypeScript stripping does not resolve extensionless relative imports.
registerHooks({ resolve(specifier, context, nextResolve) {
  try { return nextResolve(specifier, context); }
  catch (error) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/i.test(specifier)) return nextResolve(`${specifier}.ts`, context);
    throw error;
  }
} });

const { safeReturnTo, siteOrigin, providerErrorNotice } = await import("../app/lib/auth/urls.ts");
assert.equal(providerErrorNotice("#error=access_denied&error_description=DO_NOT_ECHO"), "cancelled");
assert.equal(providerErrorNotice("#error=server_error"), "failed");
assert.equal(providerErrorNotice("#normal-section"), null);
const { startSocialLogin, finishSocialLogin, readLoginState, endLogin } = await import("../app/lib/auth/handlers.ts");
const { kakaoLoginEnabled } = await import("../app/lib/auth/config.ts");
const { refreshLogin } = await import("../app/lib/auth/proxy.ts");
const { parseAdminIds, verifyAdminAccess, requireVerifiedAdmin, AdminAccessError, adminAccessFailure } = await import("../app/lib/auth/admin-policy.ts");
const { mayCacheResponse } = await import("../app/lib/serviceWorkerCachePolicy.ts");

const user = { id: "00000000-0000-4000-8000-000000000001", aud: "authenticated", role: "authenticated", email: "local-test@example.invalid", app_metadata: { provider: "google" }, user_metadata: {}, created_at: new Date().toISOString() };
const regularUser = { ...user, id: "00000000-0000-4000-8000-000000000002", email: "local-regular@example.invalid" };
const secret = "local-test-only-not-a-production-secret";
const key = "local-test-publishable-key";
function token(exp = Math.floor(Date.now() / 1000) + 3600, sub = user.id) {
  const parts = [{ alg: "HS256", typ: "JWT" }, { sub, aud: "authenticated", role: "authenticated", exp, iat: Math.floor(Date.now() / 1000) }].map((value) => Buffer.from(JSON.stringify(value)).toString("base64url"));
  return parts.join(".") + "." + createHmac("sha256", secret).update(parts.join(".")).digest("base64url");
}
function validToken(value) {
  if (!value) return false;
  const [header, payload, signature] = value.split(".");
  return signature === createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
}
let refreshes = 0;
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://localhost");
  response.setHeader("Content-Type", "application/json");
  let body = "";
  for await (const chunk of request) body += chunk;
  if (url.pathname === "/rest/v1/curations") return response.end("[]");
  if (url.pathname === "/auth/v1/token") {
    const form = JSON.parse(body);
    if (form.auth_code === "bad" || (url.searchParams.get("grant_type") === "refresh_token" && form.refresh_token !== "local-refresh")) {
      response.statusCode = 400;
      return response.end(JSON.stringify({ code: "refresh_token_not_found", msg: "Invalid local test credentials" }));
    }
    if (url.searchParams.get("grant_type") === "refresh_token") refreshes++;
    const account = form.auth_code === "local-regular-code" ? regularUser : user;
    return response.end(JSON.stringify({ access_token: token(undefined, account.id), token_type: "bearer", expires_in: 3600, refresh_token: "local-refresh", user: account }));
  }
  if (url.pathname === "/auth/v1/user") {
    if (!validToken(request.headers.authorization?.replace("Bearer ", ""))) {
      response.statusCode = 401;
      return response.end(JSON.stringify({ code: "bad_jwt", msg: "Invalid local test token" }));
    }
    const payload = JSON.parse(Buffer.from(request.headers.authorization.split(".")[1], "base64url"));
    return response.end(JSON.stringify(payload.sub === regularUser.id ? regularUser : user));
  }
  if (url.pathname === "/auth/v1/logout") return response.end("{}");
  // This fake provider route is only for a local browser smoke test. It is
  // deliberately not represented as verification of any real OAuth provider.
  if (url.pathname === "/auth/v1/authorize") {
    const callback = new URL(url.searchParams.get("redirect_to"));
    if (!["localhost", "127.0.0.1"].includes(callback.hostname)) { response.statusCode = 400; return response.end("{}"); }
    if (process.argv.includes("--serve")) {
      response.setHeader("Content-Type", "text/html; charset=utf-8");
      const adminCallback = new URL(callback); adminCallback.searchParams.set("code", "local-test-code");
      const regularCallback = new URL(callback); regularCallback.searchParams.set("code", "local-regular-code");
      const href = (url) => url.href.replaceAll("&", "&amp;").replaceAll('"', "&quot;");
      return response.end(`<main><h1>로컬 가짜 인증 계정 선택</h1><p>실제 소셜 로그인이 아닌 로컬 시험입니다.</p><p><a href="${href(adminCallback)}">가짜 운영자 계정</a></p><p><a href="${href(regularCallback)}">가짜 일반 계정</a></p></main>`);
    }
    callback.searchParams.set("code", "local-test-code");
    response.writeHead(302, { Location: callback.href });
    return response.end();
  }
  response.statusCode = 404;
  response.end("{}");
});
await new Promise((resolve) => server.listen(process.argv.includes("--serve") ? 54329 : 0, "127.0.0.1", resolve));
const backend = `http://127.0.0.1:${server.address().port}`;

if (process.argv.includes("--serve")) {
  console.log(`Local fake Auth/empty public-data server: ${backend}`);
} else {
  try {
    const site = "http://localhost:3100";
    const jar = new Map();
    let cookieWrites = [];
    const factory = async () => createServerClient(backend, key, {
      cookieOptions: { httpOnly: true, sameSite: "lax" },
      cookies: {
        getAll: () => [...jar].map(([name, value]) => ({ name, value })),
        setAll: (values) => {
          cookieWrites.push(...values);
          for (const { name, value, options } of values) {
            if (options.maxAge === 0) jar.delete(name); else jar.set(name, value);
          }
        },
      },
    });
    const post = (path, next = "/ja/info?region=seoul#details", origin = site, provider) => new Request(site + path, { method: "POST", headers: { Origin: origin }, body: new URLSearchParams({ locale: "ja", next, ...(provider === undefined ? {} : { provider }) }) });
    function noCache(response) {
      assert.match(response.headers.get("cache-control"), /private.*no-store/);
      assert.equal(mayCacheResponse(response), false);
    }
    for (const bad of ["https://evil.test", "//evil.test", "/\\evil.test", "/ko/%5c/evil", "/ko/%252e%252e/auth/start", "/ko/%252525252f", "/api/auth/logout", "/ko/login", "/ko/info\r\nX: y", "/ja/%ZZ", "javascript:alert(1)"]) assert.equal(safeReturnTo(bad, "ja"), "/ja", bad);
    assert.equal(safeReturnTo("/ja/info?region=seoul#details", "ko"), "/ja/info?region=seoul#details");
    assert.equal(siteOrigin(site + "/api/auth/start"), site);
    assert.equal(siteOrigin("https://attacker.test/api/auth/start"), null);
    assert.equal(siteOrigin("https://attacker.test/api/auth/start", "https://community.example"), null);
    assert.equal(siteOrigin("https://community.example/api/auth/start", "https://community.example"), "https://community.example");
    assert.equal((await startSocialLogin(post("/api/auth/start", "/ja", "https://evil.test"), factory)).status, 403);
    assert.equal((await endLogin(post("/api/auth/logout", "/ja", "https://evil.test"), factory)).status, 403);
    const malformed = new Request(site + "/api/auth/start", { method: "POST", headers: { Origin: site, "Content-Type": "application/json" }, body: "{}" });
    assert.equal((await startSocialLogin(malformed, factory)).status, 400);
    for (const value of [undefined, "", "false", "TRUE", " true ", "1", "true"]) {
      if (value === undefined) delete process.env.MACHIMOA_KAKAO_LOGIN_ENABLED;
      else process.env.MACHIMOA_KAKAO_LOGIN_ENABLED = value;
      assert.equal(kakaoLoginEnabled(), value === "true");
    }
    delete process.env.MACHIMOA_KAKAO_LOGIN_ENABLED;
    let unsupportedCalls = 0;
    const deniedFactory = async () => { unsupportedCalls++; throw new Error("must not reach Auth"); };
    for (const provider of ["", "naver", "line", "custom:line", "service_role", "GOOGLE", "https://evil.test"]) {
      const denied = await startSocialLogin(post("/api/auth/start", "/ko/admin", site, provider), deniedFactory, undefined, true);
      assert.equal(denied.status, 400); noCache(denied);
    }
    const duplicate = post("/api/auth/start", "/ko/admin", site, "google");
    const duplicateForm = new URLSearchParams(await duplicate.text()); duplicateForm.append("provider", "kakao");
    const duplicateResponse = await startSocialLogin(new Request(duplicate.url, { method: "POST", headers: { Origin: site }, body: duplicateForm }), deniedFactory, undefined, true);
    assert.equal(duplicateResponse.status, 400); noCache(duplicateResponse);
    const disabledKakao = await startSocialLogin(post("/api/auth/start", "/ko/admin", site, "kakao"), deniedFactory);
    assert.match(disabledKakao.headers.get("location"), /notice=unavailable/);
    assert.equal(new URL(disabledKakao.headers.get("location")).searchParams.get("next"), "/ko/admin");
    noCache(disabledKakao); assert.equal(unsupportedCalls, 0);
    assert.deepEqual(await (await readLoginState(factory, false)).json(), { status: "signed_out" });
    assert.deepEqual(await verifyAdminAccess(factory, user.id), { status: "signed_out" });
    const anonymousAdminPage = new NextRequest(site + "/ko/admin");
    noCache((await refreshLogin(anonymousAdminPage))(NextResponse.next()));
    assert.equal(safeReturnTo("/ko/admin", "ko"), "/ko/admin");
    assert.equal(parseAdminIds(undefined).size, 0);
    assert.equal(parseAdminIds("  ").size, 0);
    assert.equal(parseAdminIds(`${user.id.toUpperCase()}, ${user.id}`).size, 1);
    for (const bad of ["*", `${user.id},`, `${user.id},bad`, "00000000-0000-0000-0000-000000000000"]) assert.equal(parseAdminIds(bad), null);
    const start = await startSocialLogin(post("/api/auth/start"), factory);
    noCache(start);
    const authorize = new URL(start.headers.get("location"));
    assert.equal(authorize.origin, backend);
    assert.equal(authorize.searchParams.get("provider"), "google");
    assert.equal(authorize.searchParams.has("scope"), false);
    assert.ok(authorize.searchParams.get("code_challenge"));
    const callback = new URL(authorize.searchParams.get("redirect_to"));
    assert.equal(callback.origin, site);
    assert.equal(callback.pathname, "/api/auth/callback");
    assert.ok(cookieWrites.some((cookie) => cookie.name.endsWith("-code-verifier") && cookie.options.httpOnly));
    const explicitGoogle = await startSocialLogin(post("/api/auth/start", "/ja", site, "google"), factory);
    assert.equal(new URL(explicitGoogle.headers.get("location")).searchParams.get("provider"), "google");
    assert.equal(new URL(explicitGoogle.headers.get("location")).searchParams.has("scope"), false);
    const kakao = await startSocialLogin(post("/api/auth/start", "/ko/admin", site, "kakao"), factory, undefined, true);
    noCache(kakao);
    const kakaoAuthorize = new URL(kakao.headers.get("location"));
    assert.equal(kakaoAuthorize.searchParams.get("provider"), "kakao");
    assert.equal(kakaoAuthorize.searchParams.get("scope"), "profile_nickname,profile_image");
    assert.equal(kakaoAuthorize.searchParams.has("scopes"), false);
    assert.ok(kakaoAuthorize.searchParams.get("code_challenge"));
    const injectedForm = new URLSearchParams({ locale: "ko", next: "/ko", provider: "kakao", scope: "account_email", scopes: "openid", queryParams: "account_email" });
    const injected = await startSocialLogin(new Request(site + "/api/auth/start", { method: "POST", headers: { Origin: site }, body: injectedForm }), factory, undefined, true);
    const injectedAuthorize = new URL(injected.headers.get("location"));
    assert.equal(injectedAuthorize.searchParams.get("scope"), "profile_nickname,profile_image");
    assert.equal(injectedAuthorize.searchParams.has("scopes"), false); noCache(injected);
    const kakaoCallback = new URL(kakaoAuthorize.searchParams.get("redirect_to"));
    assert.equal(kakaoCallback.pathname, "/api/auth/callback");
    assert.equal(kakaoCallback.searchParams.get("next"), "/ko/admin");
    const kakaoCancel = await finishSocialLogin(new Request(kakaoCallback.href + "&error=access_denied&error_description=DO_NOT_ECHO"), factory);
    assert.match(kakaoCancel.headers.get("location"), /notice=cancelled/);
    assert.ok(!kakaoCancel.headers.get("location").includes("DO_NOT_ECHO")); noCache(kakaoCancel);
    // Email-less Kakao account: verified sub still determines admin membership.
    const kakaoUser = { ...regularUser, email: undefined, app_metadata: { provider: "kakao" } };
    const kakaoFactory = async () => ({ auth: {
      exchangeCodeForSession: async () => ({ error: null }),
      getClaims: async () => ({ data: { claims: { sub: kakaoUser.id } }, error: null }),
    } });
    kakaoCallback.searchParams.set("code", "local-kakao-code");
    const kakaoFinish = await finishSocialLogin(new Request(kakaoCallback), kakaoFactory);
    assert.equal(kakaoFinish.headers.get("location"), site + "/ko/admin"); noCache(kakaoFinish);
    assert.deepEqual(await (await readLoginState(kakaoFactory, true)).json(), { status: "signed_in" });
    assert.deepEqual(await verifyAdminAccess(kakaoFactory, user.id), { status: "forbidden" });
    // Restore the matching Google PKCE verifier before the SDK code exchange.
    await startSocialLogin(post("/api/auth/start"), factory);
    const cancelled = await finishSocialLogin(new Request(callback.href + "&error=access_denied&error_description=secret"), factory);
    noCache(cancelled);
    assert.match(cancelled.headers.get("location"), /notice=cancelled/);
    assert.ok(!cancelled.headers.get("location").includes("secret"));
    callback.searchParams.set("code", "local-test-code");
    const result = await finishSocialLogin(new Request(callback), factory);
    noCache(result);
    assert.equal(result.headers.get("location"), site + "/ja/info?region=seoul#details");
    assert.ok(cookieWrites.some((cookie) => /-auth-token(?:\.\d+)?$/.test(cookie.name) && cookie.options.httpOnly));
    assert.deepEqual(await (await readLoginState(factory, true)).json(), { status: "signed_in" });
    // A new client with the persisted cookies verifies identity independently.
    assert.equal((await (await factory()).auth.getClaims()).data.claims.sub, user.id);
    const sessionCookie = [...jar].find(([name]) => /-auth-token$/.test(name));
    assert.ok(sessionCookie);
    const otherId = "00000000-0000-4000-8000-000000000002";
    assert.deepEqual(await verifyAdminAccess(factory, user.id), { status: "admin", userId: user.id });
    assert.deepEqual(await requireVerifiedAdmin(factory, `${otherId}, ${user.id.toUpperCase()}`), { userId: user.id });
    for (const empty of [undefined, "", " ", otherId]) assert.deepEqual(await verifyAdminAccess(factory, empty), { status: "forbidden" });
    assert.deepEqual(await verifyAdminAccess(factory, `${user.id},typo`), { status: "configuration_error" });
    const cookieData = JSON.parse(Buffer.from(sessionCookie[1].slice(7), "base64url"));
    const alteredProfile = { ...cookieData, user: { ...cookieData.user, id: otherId, role: "admin", user_metadata: { admin: true }, app_metadata: { role: "admin" } } };
    jar.set(sessionCookie[0], "base64-" + Buffer.from(JSON.stringify(alteredProfile)).toString("base64url"));
    assert.deepEqual(await verifyAdminAccess(factory, otherId), { status: "forbidden" });
    jar.set(sessionCookie[0], sessionCookie[1]);
    // A guarded operation cannot run after any denied or failed verification.
    let protectedCalls = 0;
    async function guardedOperation(client, ids) { await requireVerifiedAdmin(client, ids); protectedCalls++; }
    await assert.rejects(() => guardedOperation(factory, otherId), (error) => error instanceof AdminAccessError && error.status === "forbidden");
    await assert.rejects(() => guardedOperation(factory, `${user.id},typo`), (error) => error.status === "configuration_error");
    await assert.rejects(() => guardedOperation(async () => null, user.id), (error) => error.status === "auth_unavailable");
    await assert.rejects(() => guardedOperation(async () => { throw new Error("private diagnostic"); }, user.id), (error) => error.status === "auth_unavailable");
    const noSession = async () => ({ auth: { getClaims: async () => ({ data: null, error: null }) } });
    await assert.rejects(() => guardedOperation(noSession, user.id), (error) => error.status === "signed_out");
    assert.equal(protectedCalls, 0);
    await guardedOperation(factory, user.id);
    assert.equal(protectedCalls, 1);
    for (const [status, expected] of [["signed_out", 401], ["forbidden", 403], ["auth_unavailable", 503], ["configuration_error", 503]]) {
      const response = adminAccessFailure(new AdminAccessError(status));
      assert.equal(response.status, expected);
      noCache(response);
      assert.deepEqual(await response.json(), { status });
    }
    const sanitized = adminAccessFailure(new Error("private diagnostic"));
    assert.ok(!(await sanitized.text()).includes("private diagnostic"));
    const expired = { ...JSON.parse(Buffer.from(sessionCookie[1].slice(7), "base64url")), access_token: token(1), expires_at: 1 };
    jar.set(sessionCookie[0], "base64-" + Buffer.from(JSON.stringify(expired)).toString("base64url"));
    process.env.NEXT_PUBLIC_SUPABASE_URL = backend;
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = key;
    const req = new NextRequest(site + "/ja/info", { headers: { cookie: [...jar].map(([name, value]) => `${name}=${value}`).join("; ") } });
    const finish = await refreshLogin(req);
    const rewritten = finish(NextResponse.rewrite(new URL("/ja/info", site), { request: { headers: req.headers } }));
    noCache(rewritten);
    assert.ok(refreshes > 0);
    assert.ok(rewritten.cookies.getAll().some(({ name }) => /-auth-token/.test(name)));
    assert.ok(rewritten.headers.get("x-middleware-request-cookie").includes(req.cookies.get(sessionCookie[0]).value));
    // Forged sessions never become signed-in, even with a valid-looking sub.
    const forged = { ...expired, access_token: token().replace(/.$/, "x"), expires_at: Math.floor(Date.now() / 1000) + 3600 };
    jar.set(sessionCookie[0], "base64-" + Buffer.from(JSON.stringify(forged)).toString("base64url"));
    assert.equal((await (await readLoginState(factory, true)).json()).status, "expired");
    assert.notEqual((await verifyAdminAccess(factory, user.id)).status, "admin");
    jar.clear();
    const badCallback = await finishSocialLogin(new Request(site + "/api/auth/callback?code=bad&next=//evil.test"), factory);
    assert.match(badCallback.headers.get("location"), /^http:\/\/localhost:3100\/ko\/login\?/);
    await startSocialLogin(post("/api/auth/start"), factory);
    await finishSocialLogin(new Request(callback), factory);
    assert.equal((await (await readLoginState(factory, true)).json()).status, "signed_in");
    cookieWrites = [];
    const signedOut = await endLogin(post("/api/auth/logout"), factory);
    noCache(signedOut);
    assert.match(signedOut.headers.get("location"), /notice=signed_out/);
    assert.ok(cookieWrites.some((cookie) => /-auth-token/.test(cookie.name) && cookie.options.maxAge === 0));
    assert.ok(![...jar.keys()].some((name) => /-auth-token/.test(name)));
    assert.deepEqual(await (await readLoginState(factory, false)).json(), { status: "signed_out" });
    const unavailable = await readLoginState(async () => { throw new Error("private diagnostic"); }, true);
    assert.equal(unavailable.status, 503);
    assert.deepEqual(await unavailable.json(), { status: "unavailable" });
    console.log("Google/Kakao Auth + admin checks passed: provider allowlist/rollout gate, PKCE, cookies, server UUID verification, fail-closed guard, forged profiles/tokens, refresh/rewrite, return paths, CSRF, notices, logout and no-store. Local fake Auth only; no real provider login.");
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}
