export type AuthLocale = "ko" | "ja";

export function authLocale(value: unknown): AuthLocale {
  return value === "ja" ? "ja" : "ko";
}

// Only return to locale-prefixed application pages, never another auth endpoint.
export function safeReturnTo(value: unknown, locale: AuthLocale): string {
  const fallback = `/${locale}`;
  if (typeof value !== "string" || value.length > 2048 ||
      !value.startsWith("/") || /[\\\u0000-\u0020\u007f]/.test(value)) return fallback;
  try {
    const url = new URL(value, "https://machimoa.invalid");
    if (url.origin !== "https://machimoa.invalid") return fallback;
    let path = url.pathname;
    for (let i = 0; i < 3; i++) {
      const decoded = decodeURIComponent(path);
      if (decoded === path) break;
      path = decoded;
    }
    if (/[\\\u0000-\u0020\u007f]/.test(path) || /%[0-9a-f]{2}/i.test(path) ||
        path.split("/").some((part) => part === "." || part === "..") ||
        !/^\/(ko|ja)(?:\/|$)/.test(path) || /^\/(ko|ja)\/(login|api|auth)(?:\/|$)/.test(path)) return fallback;
    const canonical = new URL(path, "https://machimoa.invalid");
    if (canonical.origin !== url.origin) return fallback;
    return canonical.pathname + url.search + url.hash;
  } catch {
    return fallback;
  }
}

export function loginUrl(locale: AuthLocale, next: string, notice?: string): string {
  const query = new URLSearchParams({ next: safeReturnTo(next, locale) });
  if (notice) query.set("notice", notice);
  return `/${locale}/login?${query}`;
}

export function siteOrigin(requestUrl: string, configured?: string): string | null {
  try {
    const request = new URL(requestUrl);
    const site = configured ? new URL(configured) : request;
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(site.hostname);
    if (!configured && !local) return null;
    if (site.username || site.password || (site.protocol !== "https:" && !(local && site.protocol === "http:"))) return null;
    if (configured && (site.pathname !== "/" || site.search || site.hash)) return null;
    return site.origin === request.origin ? site.origin : null;
  } catch {
    return null;
  }
}

export function isSameOriginPost(request: Request): boolean {
  return request.headers.get("origin") === new URL(request.url).origin;
}
// Supabase can return provider errors in a URL fragment, which the server never receives.
export function providerErrorNotice(fragment: string) {
  const params = new URLSearchParams(fragment.replace(/^#/, ""));
  if (!params.has("error")) return null;
  return params.get("error") === "access_denied" ? "cancelled" : "failed";
}
