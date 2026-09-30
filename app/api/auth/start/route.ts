import { createAuthClient } from "@/app/lib/auth/server";
import { startGoogleLogin } from "@/app/lib/auth/handlers";

export async function POST(request: Request) {
  return startGoogleLogin(request, createAuthClient, process.env.AUTH_SITE_URL);
}
