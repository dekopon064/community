import "server-only";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { publicAuthConfig } from "./config";

// A new SDK client for each request. No service role or provider secret is used.
export async function createAuthClient(options?: { readOnly?: boolean }) {
  const config = publicAuthConfig();
  if (!config) return null;
  const cookieStore = await cookies();
  return createServerClient(config.url, config.key, {
    cookieOptions: { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production" },
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (values) => {
        // Page rendering cannot write cookies; Proxy performs its refresh first.
        if (options?.readOnly) return;
        // Route Handlers always return no-store, including error redirects.
        values.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
      },
    },
  });
}
