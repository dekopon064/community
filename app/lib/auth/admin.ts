import "server-only";
import { createAuthClient } from "./server";
import { requireVerifiedAdmin, verifyAdminAccess } from "./admin-policy";

export function getAdminAccess(options?: { readOnly?: boolean }) {
  return verifyAdminAccess(() => createAuthClient(options), process.env.MACHIMOA_ADMIN_USER_IDS);
}

// Call at the start of every future admin Route Handler / Server Action,
// before reading protected data or executing a mutation. Throws on all denials.
export function requireAdmin() {
  return requireVerifiedAdmin(createAuthClient, process.env.MACHIMOA_ADMIN_USER_IDS);
}
