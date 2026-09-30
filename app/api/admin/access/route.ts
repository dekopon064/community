import { requireAdmin } from "@/app/lib/auth/admin";
import { adminAccessFailure } from "@/app/lib/auth/admin-policy";
import { privateResponse } from "@/app/lib/auth/http";

export async function GET() {
  try {
    await requireAdmin();
    // The allowlist, user UUID and tokens never leave the server.
    return privateResponse(Response.json({ status: "admin" }));
  } catch (error) {
    return adminAccessFailure(error);
  }
}
