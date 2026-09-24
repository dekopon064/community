import { defaultCache } from "@serwist/next/worker";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { CacheFirst, NetworkFirst, NetworkOnly, Serwist, StaleWhileRevalidate } from "serwist";
import {
  isSameOriginPageRequest,
  noPageResponseCacheFirstPlugin,
  noPageResponseCachePlugin,
} from "./lib/serviceWorkerCachePolicy";

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

// Never serve same-origin documents or RSC payloads from an offline cache.
const pagesNetworkOnly = {
  matcher: ({ request, url, sameOrigin }: { request: Request; url: URL; sameOrigin: boolean }) =>
    isSameOriginPageRequest(request, url, sameOrigin),
  handler: new NetworkOnly(),
  method: "GET" as const,
};

// A generic fetch() can receive HTML with Accept: */*. Do not let any
// default runtime strategy store or reuse that response as an asset.
for (const route of defaultCache) {
  if (route.handler instanceof CacheFirst) {
    route.handler.plugins.push(noPageResponseCacheFirstPlugin);
  } else if (
    route.handler instanceof NetworkFirst ||
    route.handler instanceof StaleWhileRevalidate
  ) {
    route.handler.plugins.push(noPageResponseCachePlugin);
  }
}

// 이전 서비스 워커가 저장한 페이지도 새 워커 활성화 시 제거한다.
self.addEventListener("activate", (event: ExtendableEvent) => {
  event.waitUntil(
    Promise.all(
      ["pages", "pages-rsc", "pages-rsc-prefetch", "start-url", "others"].map(
        (name) => caches.delete(name),
      ),
    ),
  );
});

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [feedbackPostOnly, pagesNetworkOnly, ...defaultCache],
});

serwist.addEventListeners();
