import { cookies } from "next/headers";
import { createAuthClient } from "@/app/lib/auth/server";
import { readLoginState } from "@/app/lib/auth/handlers";

export async function GET() {
  const store = await cookies();
  const hadSessionCookie = store.get("machimoa-auth-expired")?.value === "1" || store.getAll().some(({ name }) => /^sb-.+-auth-token(?:\.\d+)?$/.test(name));
  if (store.has("machimoa-auth-expired")) store.delete("machimoa-auth-expired");
  return readLoginState(createAuthClient, hadSessionCookie);
}
