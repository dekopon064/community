import { createAuthClient } from "@/app/lib/auth/server";
import { intentCookies } from "@/app/lib/saved/cookies";
import { finishWithSave } from "@/app/lib/saved/auth-flow";
export async function GET(request: Request) { return finishWithSave(request, createAuthClient, await intentCookies(), process.env.AUTH_SITE_URL); }
