import { createAuthClient } from "@/app/lib/auth/server";
import { endLogin } from "@/app/lib/auth/handlers";

export async function POST(request: Request) {
  return endLogin(request, createAuthClient);
}
