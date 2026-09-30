import { createAuthClient } from "@/app/lib/auth/server";
import { startSocialLogin } from "@/app/lib/auth/handlers";
import { kakaoLoginEnabled } from "@/app/lib/auth/config";

export async function POST(request: Request) {
  return startSocialLogin(request, createAuthClient, process.env.AUTH_SITE_URL, kakaoLoginEnabled());
}
