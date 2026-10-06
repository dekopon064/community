// Shared with the existing trust panel: render only HTTP(S) source links.
export function getSafeSource(value: string | null) {
  if (!value) return null;

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return { href: url.href, hostname: url.hostname.replace(/^www\./, "") };
  } catch {
    return null;
  }
}
