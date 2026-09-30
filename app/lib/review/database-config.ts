// Server configuration policy; this module is never imported by UI components.
export function databaseReviewConfig(environment: Record<string, string | undefined>) {
  if (environment.MACHIMOA_REVIEW_MODE !== "database") return null;
  const key = environment.SUPABASE_SERVICE_ROLE_KEY?.trim();
  if (!key || key === environment.NEXT_PUBLIC_SUPABASE_ANON_KEY || key === environment.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) return null;
  // Accept Supabase server secret keys or legacy service_role JWTs, never public keys.
  let serviceKey = key.startsWith("sb_secret_") && key.length > 20;
  if (!serviceKey) {
    try { serviceKey = JSON.parse(Buffer.from(key.split(".")[1], "base64url").toString()).role === "service_role" && key.split(".").length === 3; }
    catch { return null; }
  }
  if (!serviceKey) return null;
  try {
    const url = new URL(environment.NEXT_PUBLIC_SUPABASE_URL ?? "");
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.username || url.password || url.search || url.hash || !["", "/"].includes(url.pathname) || (url.protocol !== "https:" && !(url.protocol === "http:" && loopback))) return null;
    return { url: url.origin, key };
  } catch { return null; }
}
