// No proxy or server fetch: only validated URL metadata reaches the browser.
const URL_PATTERN = /^https:\/\/(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::443)?(?:[/?][^\s\\#<>"']*)?$/i;

export function sourceImageUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const url = value.replace(/^ +| +$/g, "");
  if (url.length > 2048 || !URL_PATTERN.test(url) || /%0[ad]/i.test(url)) return null;
  const parsed = new URL(url);
  if (/\.(localhost|local|internal|invalid|test)$/i.test(parsed.hostname) || /\.svg(?:$|[/?])/i.test(parsed.pathname)) return null;
  return url;
}
