export function localFixtureEnabled(environment: Record<string, string | undefined>): boolean {
  if (environment.NODE_ENV !== "development" || environment.MACHIMOA_REVIEW_MODE !== "local-fixture") return false;
  try {
    const url = new URL(environment.NEXT_PUBLIC_SUPABASE_URL ?? "");
    return url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) && !url.username && !url.password;
  } catch { return false; }
}
