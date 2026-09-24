import assert from "node:assert/strict";
import {
  isSameOriginPageRequest,
  mayCacheResponse,
  noPageResponseCacheFirstPlugin,
  noPageResponseCachePlugin,
} from "../app/lib/serviceWorkerCachePolicy.ts";

function pageRequest(url, options = {}) {
  return isSameOriginPageRequest(
    {
      mode: options.mode ?? "cors",
      destination: options.destination ?? "",
      headers: new Headers(options.headers ?? {}),
    },
    new URL(url),
    options.sameOrigin ?? true,
  );
}

for (const path of [
  "/ko/info/story",
  "/ko/%69nfo/story",
  "/%6bo/info/story",
  "/info/story",
]) {
  assert.equal(pageRequest(`https://example.test${path}`, { mode: "navigate" }), true);
  assert.equal(pageRequest(`https://example.test${path}?_rsc=123`), true);
  assert.equal(pageRequest(`https://example.test${path}`, { headers: { RSC: "1" } }), true);
}

assert.equal(pageRequest("https://example.test/ko", { headers: { Accept: "text/html" } }), true);
assert.equal(pageRequest("https://example.test/%6bo/info", { headers: { Accept: "TEXT/HTML" } }), true);
assert.equal(pageRequest("https://example.test/info/story", { destination: "document" }), true);
assert.equal(pageRequest("https://example.test/ko/info", { headers: { Accept: "text/x-component" } }), true);
assert.equal(pageRequest("https://example.test/_next/static/app.js"), false);
assert.equal(pageRequest("https://example.test/image.webp"), false);
assert.equal(pageRequest("https://elsewhere.test/ko/info", { mode: "navigate", sameOrigin: false }), false);

const html = new Response("private story", {
  headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
});
const rsc = new Response("rsc story", { headers: { "Content-Type": "text/x-component" } });
const image = new Response("image bytes", { headers: { "Content-Type": "image/webp" } });
assert.equal(mayCacheResponse(html), false);
assert.equal(mayCacheResponse(rsc), false);
assert.equal(mayCacheResponse(image), true);
assert.equal(await noPageResponseCachePlugin.cacheWillUpdate({ response: html }), null);
assert.equal(await noPageResponseCachePlugin.cachedResponseWillBeUsed({ cachedResponse: html }), null);
assert.equal(await noPageResponseCachePlugin.cacheWillUpdate({ response: image }), image);
assert.equal(await noPageResponseCachePlugin.cachedResponseWillBeUsed({ cachedResponse: image }), image);
const unavailable = new Response("temporarily unavailable", {
  status: 503,
  headers: { "Content-Type": "text/plain" },
});
assert.equal(await noPageResponseCacheFirstPlugin.cacheWillUpdate({ response: unavailable }), null);
assert.equal(await noPageResponseCacheFirstPlugin.cachedResponseWillBeUsed({ cachedResponse: unavailable }), null);

// Exercise the real Serwist NetworkFirst strategy with a small Cache API mock.
// A generic fetch() of an encoded URL has no navigation or RSC request hint.
process.env.NODE_ENV = "production";
const { CacheFirst, NetworkFirst } = await import("serwist");
const stored = new Map();
globalThis.ExtendableEvent = class ExtendableEvent {
  waitUntil() {}
};
globalThis.FetchEvent = class FetchEvent extends ExtendableEvent {};
globalThis.self = globalThis;
globalThis.caches = {
  match: async (request, { cacheName }) => stored.get(`${cacheName}|${request.url}`)?.clone(),
  open: async (cacheName) => ({
    put: async (request, response) => stored.set(`${cacheName}|${request.url}`, response.clone()),
  }),
};
const strategy = new NetworkFirst({ cacheName: "page-response-test" });
strategy.plugins.push(noPageResponseCachePlugin);

let networkResponse;
globalThis.fetch = async () => {
  if (!networkResponse) throw new Error("offline");
  return networkResponse.clone();
};
async function fetchThroughCache(request, cacheStrategy = strategy) {
  const [response, done] = cacheStrategy.handleAll({ request, event: new ExtendableEvent() });
  try {
    return await response;
  } finally {
    await done.catch(() => {});
  }
}

for (const path of ["/ko/%69nfo/story", "/%6bo/info/story", "/info/story"]) {
  const request = new Request(`https://example.test${path}`);
  assert.equal(pageRequest(request.url), false);
  networkResponse = html;
  assert.equal(await (await fetchThroughCache(request)).text(), "private story");
  assert.equal(stored.has(`${strategy.cacheName}|${request.url}`), false);

  // Even an HTML response left by an older worker must not be reused.
  stored.set(`${strategy.cacheName}|${request.url}`, html.clone());
  networkResponse = undefined;
  await assert.rejects(() => fetchThroughCache(request));
  stored.delete(`${strategy.cacheName}|${request.url}`);
}

const rscRequest = new Request("https://example.test/ko/info/story?_rsc=123");
networkResponse = rsc;
assert.equal(await (await fetchThroughCache(rscRequest)).text(), "rsc story");
assert.equal(stored.has(`${strategy.cacheName}|${rscRequest.url}`), false);

const noStoreRequest = new Request("https://example.test/ko/info/story?format=text");
networkResponse = new Response("private text", {
  headers: { "Content-Type": "text/plain", "Cache-Control": "private, no-store" },
});
assert.equal(await (await fetchThroughCache(noStoreRequest)).text(), "private text");
assert.equal(stored.has(`${strategy.cacheName}|${noStoreRequest.url}`), false);

const imageRequest = new Request("https://example.test/image.webp");
networkResponse = image;
assert.equal(await (await fetchThroughCache(imageRequest)).text(), "image bytes");
assert.equal(stored.has(`${strategy.cacheName}|${imageRequest.url}`), true);
networkResponse = undefined;
assert.equal(await (await fetchThroughCache(imageRequest)).text(), "image bytes");

// CacheFirst must not retain a transient error once the JS asset recovers.
const assetStrategy = new CacheFirst({ cacheName: "asset-status-test" });
assetStrategy.plugins.push(noPageResponseCacheFirstPlugin);
const jsRequest = new Request("https://example.test/_next/static/app.js");
networkResponse = unavailable;
assert.equal((await fetchThroughCache(jsRequest, assetStrategy)).status, 503);
assert.equal(stored.has(`${assetStrategy.cacheName}|${jsRequest.url}`), false);
networkResponse = new Response("healthy asset", {
  status: 200,
  headers: { "Content-Type": "application/javascript" },
});
assert.equal((await fetchThroughCache(jsRequest, assetStrategy)).status, 200);
assert.equal(stored.has(`${assetStrategy.cacheName}|${jsRequest.url}`), true);
networkResponse = undefined;
assert.equal(await (await fetchThroughCache(jsRequest, assetStrategy)).text(), "healthy asset");

// A 503 written by the previous worker must not block recovery either.
stored.set(`${assetStrategy.cacheName}|${jsRequest.url}`, unavailable.clone());
networkResponse = new Response("recovered asset", {
  status: 200,
  headers: { "Content-Type": "application/javascript" },
});
assert.equal(await (await fetchThroughCache(jsRequest, assetStrategy)).text(), "recovered asset");

console.log("ok");
