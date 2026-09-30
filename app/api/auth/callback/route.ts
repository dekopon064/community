import { createAuthClient } from "@/app/lib/auth/server";
import { finishGoogleLogin } from "@/app/lib/auth/handlers";

export async function GET(request: Request) {
  return finishGoogleLogin(request, createAuthClient, process.env.AUTH_SITE_URL);
}
