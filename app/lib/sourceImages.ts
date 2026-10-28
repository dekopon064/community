// Browser URL metadata validation only. Server-side analysis also requires the
// DNS/IP/size/time protections in home-colors/download; this is not an SSRF guard.
const URL_PATTERN = /^https:\/\/(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::443)?(?:[/?][^\s\\#<>"']*)?$/i;

export function sourceImageUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const url = value.replace(/^ +| +$/g, "");
  if (url.length > 2048 || !URL_PATTERN.test(url) || /%0[ad]/i.test(url)) return null;
  const parsed = new URL(url);
  if (/\.(localhost|local|internal|invalid|test)$/i.test(parsed.hostname) || /\.svg(?:$|[/?])/i.test(parsed.pathname)) return null;
  return url;
}

// Rendering only: never use this for submitted URLs or server-side downloads.
export function sourceImageDisplayUrl(value:unknown):string|null {
  if(typeof value==='string'&&/^\/api\/living\/images\/[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value))return value;
  return sourceImageUrl(value);
}
