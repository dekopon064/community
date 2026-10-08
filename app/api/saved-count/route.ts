import { createClient } from "@supabase/supabase-js";
import { publicAuthConfig } from "@/app/lib/auth/config";
import { savedCountRequest } from "@/app/lib/saved/count";

export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  return savedCountRequest(request, () => {
    const config = publicAuthConfig();
    return config ? createClient(config.url, config.key, {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
      global: { fetch: (input, init) => fetch(input, { ...init, cache: "no-store" }) },
    }) : null;
  });
}
