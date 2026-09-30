import { createAuthClient } from "@/app/lib/auth/server";
import { finishSocialLogin } from "@/app/lib/auth/handlers";

export async function GET(request: Request) {
  return finishSocialLogin(request, createAuthClient, process.env.AUTH_SITE_URL);
}
