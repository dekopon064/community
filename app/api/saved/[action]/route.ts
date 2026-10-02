import { createAuthClient } from "@/app/lib/auth/server";
import { intentCookies } from "@/app/lib/saved/cookies";
import { savedRequest } from "@/app/lib/saved/handlers";
async function handle(request: Request, context: { params: Promise<{ action: string }> }) { return savedRequest(request, (await context.params).action, createAuthClient, await intentCookies()); }
export const GET = handle;
export const POST = handle;
