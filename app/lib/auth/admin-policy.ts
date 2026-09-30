import type { SupabaseClient } from "@supabase/supabase-js";
import { privateResponse } from "./http";

type ClientFactory = () => Promise<{ auth: Pick<SupabaseClient["auth"], "getClaims"> } | null>;
export type AdminFailure = "signed_out" | "forbidden" | "auth_unavailable" | "configuration_error";
export type AdminAccess = { status: "admin"; userId: string } | { status: AdminFailure };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function parseAdminIds(value: string | undefined): Set<string> | null {
  if (!value?.trim()) return new Set();
  const ids = value.split(",").map((id) => id.trim().toLowerCase());
  // Reject the whole list on a typo; never partially grant a malformed config.
  return ids.every((id) => uuid.test(id)) ? new Set(ids) : null;
}

// Pure policy for the server adapter and tests. No browser identity is accepted.
export async function verifyAdminAccess(createClient: ClientFactory, configuredIds: string | undefined): Promise<AdminAccess> {
  try {
    const client = await createClient();
    if (!client) return { status: "auth_unavailable" };
    const { data, error } = await client.auth.getClaims();
    if (error) {
      const expired = error.name === "AuthSessionMissingError" ||
        ["bad_jwt", "refresh_token_not_found", "refresh_token_already_used", "session_not_found"].includes(error.code || "");
      return { status: expired ? "signed_out" : "auth_unavailable" };
    }
    if (!data?.claims) return { status: "signed_out" };
    const sub = data.claims.sub;
    if (typeof sub !== "string" || !uuid.test(sub)) return { status: "auth_unavailable" };
    const ids = parseAdminIds(configuredIds);
    if (!ids) return { status: "configuration_error" };
    return ids.has(sub.toLowerCase()) ? { status: "admin", userId: sub.toLowerCase() } : { status: "forbidden" };
  } catch {
    return { status: "auth_unavailable" };
  }
}

export class AdminAccessError extends Error {
  readonly status: AdminFailure;
  constructor(status: AdminFailure) {
    super("Admin access denied");
    this.name = "AdminAccessError";
    this.status = status;
  }
}

export async function requireVerifiedAdmin(createClient: ClientFactory, configuredIds: string | undefined) {
  const access = await verifyAdminAccess(createClient, configuredIds);
  if (access.status !== "admin") throw new AdminAccessError(access.status);
  return { userId: access.userId };
}

export function adminAccessFailure(error: unknown) {
  const status = error instanceof AdminAccessError ? error.status : "auth_unavailable";
  const httpStatus = status === "signed_out" ? 401 : status === "forbidden" ? 403 : 503;
  return privateResponse(Response.json({ status }, { status: httpStatus }));
}
