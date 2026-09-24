import type { SerwistPlugin } from "serwist";

type PageRequest = Pick<Request, "mode" | "destination" | "headers">;

// Do not cache documents or Next.js RSC payloads, regardless of URL spelling.
// This includes percent-encoded paths and locale-less aliases.
export function isSameOriginPageRequest(
  request: PageRequest,
  url: URL,
  sameOrigin: boolean,
): boolean {
  if (!sameOrigin) {
    return false;
  }

  const accept = (request.headers.get("Accept") ?? "").toLowerCase();
  return (
    request.mode === "navigate" ||
    request.destination === "document" ||
    request.headers.get("RSC") === "1" ||
    url.searchParams.has("_rsc") ||
    accept.includes("text/html") ||
    accept.includes("text/x-component")
  );
}

export function mayCacheResponse(response: Response): boolean {
  const contentType = (response.headers.get("Content-Type") ?? "")
    .split(";", 1)[0]
    .trim()
    .toLowerCase();
  const cacheControl = (response.headers.get("Cache-Control") ?? "").toLowerCase();

  return (
    contentType !== "text/html" &&
    contentType !== "application/xhtml+xml" &&
    contentType !== "text/x-component" &&
    !cacheControl.split(",").some((directive) => directive.trim() === "no-store")
  );
}

// Guard both new writes and fallback reads from older runtime caches.
export const noPageResponseCachePlugin: SerwistPlugin = {
  cacheWillUpdate: ({ response }) =>
    mayCacheResponse(response) ? response : null,
  cachedResponseWillBeUsed: ({ cachedResponse }) =>
    cachedResponse && mayCacheResponse(cachedResponse) ? cachedResponse : null,
};

// CacheFirst has no default cacheWillUpdate plugin: without one it only
// caches status 200. Keep that rule when adding the page-response guard.
export const noPageResponseCacheFirstPlugin: SerwistPlugin = {
  cacheWillUpdate: ({ response }) =>
    response.status === 200 && mayCacheResponse(response) ? response : null,
  cachedResponseWillBeUsed: ({ cachedResponse }) =>
    cachedResponse?.status === 200 && mayCacheResponse(cachedResponse)
      ? cachedResponse
      : null,
};
