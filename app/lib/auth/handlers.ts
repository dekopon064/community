import type { SupabaseClient } from "@supabase/supabase-js";
import { authLocale, isSameOriginPost, loginUrl, safeReturnTo, siteOrigin } from "./urls";
import { authRedirect, privateResponse } from "./http";

type AuthClient = { auth: Pick<SupabaseClient["auth"], "signInWithOAuth" | "exchangeCodeForSession" | "getClaims" | "signOut"> };
type ClientFactory = () => Promise<AuthClient | null>;

export async function startSocialLogin(request: Request, createClient: ClientFactory, configuredOrigin?: string, kakaoEnabled = false, saveIntent?: string, lineEnabled = false) {
  if (!isSameOriginPost(request)) return privateResponse(new Response(null, { status: 403 }));
  const form = await request.formData().catch(() => null);
  if (!form) return privateResponse(new Response(null, { status: 400 }));
  const locale = authLocale(form.get("locale"));
  const next = safeReturnTo(form.get("next"), locale);
  // Missing provider preserves existing Google-only forms and open browser tabs.
  const providers = form.getAll("provider");
  const provider = providers.length === 0 ? "google" : providers[0];
  if (providers.length > 1 || (provider !== "google" && provider !== "kakao" && provider !== "line")) {
    return privateResponse(new Response(null, { status: 400 }));
  }
  if (provider === "kakao" && !kakaoEnabled) return authRedirect(request, loginUrl(locale, next, "unavailable"));
  if (provider === "line" && !lineEnabled) return authRedirect(request, loginUrl(locale, next, "unavailable"));
  const origin = siteOrigin(request.url, configuredOrigin);
  if (!origin) return authRedirect(request, loginUrl(locale, next, "unavailable"));
  try {
    const client = await createClient();
    if (!client) return authRedirect(request, loginUrl(locale, next, "unavailable"));
    const callback = new URL("/api/auth/callback", origin);
    callback.searchParams.set("locale", locale);
    callback.searchParams.set("next", next);
    if (saveIntent) callback.searchParams.set("saveIntent", saveIntent);
    const { data, error } = await client.auth.signInWithOAuth({
      provider: provider === "line" ? "custom:line" : provider, options: {
        redirectTo: callback.href, skipBrowserRedirect: true,
        // Supabase's Kakao defaults include account_email even with email optional.
        // `scopes` only adds to those defaults; the provider's singular `scope`
        // replaces them. Keep this server-owned and independent of form input.
        ...(provider === "kakao" ? { queryParams: { scope: "profile_nickname,profile_image" } } : {}),
        // Supabase owns the OAuth2 code exchange and userinfo lookup. Configure
        // custom:line with email_optional:true and only openid/profile scopes.
        ...(provider === "line" ? { scopes: "openid profile", queryParams: { ui_locales: locale } } : {}),
      },
    });
    if (error || !data.url) return authRedirect(request, loginUrl(locale, next, "failed"));
    return privateResponse(new Response(null, { status: 303, headers: { Location: data.url } }));
  } catch {
    return authRedirect(request, loginUrl(locale, next, "failed"));
  }
}

export async function finishSocialLogin(request: Request, createClient: ClientFactory, configuredOrigin?: string) {
  const url = new URL(request.url);
  const locale = authLocale(url.searchParams.get("locale"));
  const next = safeReturnTo(url.searchParams.get("next"), locale);
  if (!siteOrigin(request.url, configuredOrigin)) return authRedirect(request, loginUrl(locale, next, "unavailable"));
  // Provider descriptions are untrusted and must never be echoed into the page.
  if (url.searchParams.has("error")) {
    const notice = url.searchParams.get("error") === "access_denied" ? "cancelled" : "failed";
    return authRedirect(request, loginUrl(locale, next, notice));
  }
  const code = url.searchParams.get("code");
  if (!code) return authRedirect(request, loginUrl(locale, next, "failed"));
  try {
    const client = await createClient();
    if (!client) return authRedirect(request, loginUrl(locale, next, "unavailable"));
    const { error } = await client.auth.exchangeCodeForSession(code);
    if (error) return authRedirect(request, loginUrl(locale, next, "failed"));
    const { data, error: verificationError } = await client.auth.getClaims();
    if (verificationError || !data?.claims.sub) return authRedirect(request, loginUrl(locale, next, "failed"));
    return authRedirect(request, next);
  } catch {
    return authRedirect(request, loginUrl(locale, next, "failed"));
  }
}

export async function readLoginState(createClient: ClientFactory, hadSessionCookie: boolean) {
  try {
    const client = await createClient();
    if (!client) return privateResponse(Response.json({ status: "unavailable" }));
    const { data, error } = await client.auth.getClaims();
    if (error) {
      const expired = hadSessionCookie && (error.name === "AuthSessionMissingError" || ((error.status ?? 0) >= 400 && (error.status ?? 0) < 500));
      return privateResponse(Response.json({ status: expired ? "expired" : "unavailable" }, { status: expired ? 200 : 503 }));
    }
    if (!data?.claims.sub) return privateResponse(Response.json({ status: hadSessionCookie ? "expired" : "signed_out" }));
    // Identity is validated on the server. Tokens and profile metadata stay there.
    return privateResponse(Response.json({ status: "signed_in" }));
  } catch {
    return privateResponse(Response.json({ status: "unavailable" }, { status: 503 }));
  }
}

export async function endLogin(request: Request, createClient: ClientFactory) {
  if (!isSameOriginPost(request)) return privateResponse(new Response(null, { status: 403 }));
  const form = await request.formData().catch(() => null);
  if (!form) return privateResponse(new Response(null, { status: 400 }));
  const locale = authLocale(form.get("locale"));
  const next = safeReturnTo(form.get("next"), locale);
  try {
    const client = await createClient();
    if (!client) return authRedirect(request, loginUrl(locale, next, "unavailable"));
    const { error } = await client.auth.signOut({ scope: "local" });
    if (error) return authRedirect(request, loginUrl(locale, next, "logout_failed"));
    return authRedirect(request, loginUrl(locale, next, "signed_out"));
  } catch {
    return authRedirect(request, loginUrl(locale, next, "logout_failed"));
  }
}
