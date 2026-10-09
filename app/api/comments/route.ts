import { commentRequest } from "@/app/lib/comments/handler";
import { createAuthClient } from "@/app/lib/auth/server";
import { getAdminAccess, requireAdmin } from "@/app/lib/auth/admin";
import { getReviewRpcClient } from "@/app/lib/review/server";
export const dynamic = "force-dynamic";
const handle = (request: Request) => commentRequest(request, { client: createAuthClient, admin: getAdminAccess, authorize: requireAdmin, service: getReviewRpcClient });
export const GET = handle;
export const POST = handle;
