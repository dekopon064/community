import { createAuthClient } from "@/app/lib/auth/server";
import { kakaoLoginEnabled, lineLoginEnabled } from "@/app/lib/auth/config";
import { intentCookies } from "@/app/lib/saved/cookies";
import { startWithSave } from "@/app/lib/saved/auth-flow";
export async function POST(request: Request) { return startWithSave(request, createAuthClient, await intentCookies(), process.env.AUTH_SITE_URL, kakaoLoginEnabled(), lineLoginEnabled()); }
