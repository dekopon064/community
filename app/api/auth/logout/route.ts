import { createAuthClient } from "@/app/lib/auth/server";
import { intentCookies } from "@/app/lib/saved/cookies";
import { logoutWithSave } from "@/app/lib/saved/auth-flow";
export async function POST(request: Request) { return logoutWithSave(request, createAuthClient, await intentCookies()); }
