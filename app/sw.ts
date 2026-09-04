import { defaultCache } from "@serwist/next/worker";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { NetworkOnly, Serwist } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    // Serwist가 빌드 시 주입하는 프리캐시 매니페스트(앱 쉘: HTML/CSS/JS)
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: WorkerGlobalScope;

function readSupabaseOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (typeof raw !== "string" || raw.length === 0) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not configured");
  }
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not a valid URL");
  }
}

const supabaseOrigin = readSupabaseOrigin();

const feedbackPostOnly = {
  matcher: ({ url }: { url: URL }) =>
    url.origin === supabaseOrigin &&
    (url.pathname === "/functions/v1/submit-feedback" ||
      url.pathname === "/functions/v1/delete-feedback"),
  handler: new NetworkOnly(),
  method: "POST" as const,
};

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [feedbackPostOnly, ...defaultCache],
});

serwist.addEventListeners();
