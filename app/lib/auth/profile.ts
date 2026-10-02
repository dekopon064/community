import type { SupabaseClient, User } from "@supabase/supabase-js";
import { privateResponse } from "./http";

export function displayName(user: Pick<User, "user_metadata" | "email">): string | null {
  for (const key of ["full_name", "name", "nickname", "preferred_username"]) {
    const raw = user.user_metadata?.[key];
    if (typeof raw !== "string") continue;
    const name = raw.replace(/[\u0000-\u001f\u007f]/g, "").trim();
    if (name && !name.includes("@") && name !== user.email) return [...name].slice(0, 128).join("");
  }
  return null;
}

// getUser verifies with Auth, rather than trusting browser-provided metadata.
export async function verifiedAccount(client: Pick<SupabaseClient, "auth"> | null) {
  if (!client) return { status: "unavailable" as const, user: null };
  try {
    const { data, error } = await client.auth.getUser();
    if (error) {
      const missing = error.name === "AuthSessionMissingError" || (error.status && error.status >= 400 && error.status < 500);
      return { status: missing ? "signed_out" as const : "unavailable" as const, user: null };
    }
    return data.user?.id ? { status: "signed_in" as const, user: data.user } : { status: "signed_out" as const, user: null };
  } catch { return { status: "unavailable" as const, user: null }; }
}

export async function profileResponse(client: SupabaseClient | null, hadCookie: boolean) {
  const account = await verifiedAccount(client);
  return privateResponse(Response.json({
    status: account.status === "signed_out" && hadCookie ? "expired" : account.status,
    displayName: account.user ? displayName(account.user) : null,
    accountId: account.user?.id ?? null,
  }, { status: account.status === "unavailable" ? 503 : 200 }));
}
