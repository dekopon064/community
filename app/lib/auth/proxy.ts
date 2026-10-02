import { createServerClient, type CookieOptions } from "@supabase/ssr";
import type { NextRequest, NextResponse } from "next/server";
import { publicAuthConfig } from "./config";
import { preventAuthCaching } from "./http";

export function hasAuthCookie(values: { name: string }[]) {
  return values.some(({ name }) => /^sb-.+-auth-token(?:\.\d+)?$/.test(name));
}

export async function refreshLogin(request: NextRequest) {
  const changes = new Map<string, { name: string; value: string; options: CookieOptions }>();
  const hadSession = hasAuthCookie(request.cookies.getAll());
  const config = publicAuthConfig();
  if (config && hadSession) {
    const client = createServerClient(config.url, config.key, {
      cookieOptions: { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production" },
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (values) => values.forEach((cookie) => {
          request.cookies.set(cookie.name, cookie.value);
          changes.set(cookie.name, cookie);
        }),
      },
    });
    try {
      // Refresh before next-intl constructs the rewrite's request headers.
      const { data, error } = await client.auth.getClaims();
      if ((!data?.claims && !error) || (error && error.status && error.status < 500)) {
        const cookie = { name: "machimoa-auth-expired", value: "1", options: { path: "/", httpOnly: true, sameSite: "lax" as const, maxAge: 120, secure: process.env.NODE_ENV === "production" } };
        request.cookies.set(cookie.name, cookie.value);
        changes.set(cookie.name, cookie);
      }
    } catch {
      // A transient Auth outage must not block anonymous public information.
    }
  }
  return (response: NextResponse) => {
    changes.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
    if (hadSession || changes.size || request.cookies.has("machimoa-save-intent") || /^\/(ko|ja)\/(login|admin|saved)(?:\/|$)/.test(request.nextUrl.pathname)) {
      preventAuthCaching(response.headers);
    }
    return response;
  };
}
