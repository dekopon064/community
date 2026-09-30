export function publicAuthConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  return url && key ? { url, key } : null;
}

// Roll out only after the Supabase provider has been configured. Not a secret.
export function kakaoLoginEnabled() {
  return process.env.MACHIMOA_KAKAO_LOGIN_ENABLED === "true";
}
