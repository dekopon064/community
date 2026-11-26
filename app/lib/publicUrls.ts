export const publicOrigin = "https://community-app-drab.vercel.app";

export function publicArticleUrl(locale: string, slug: string): string {
  return `${publicOrigin}/${locale}/info/${encodeURIComponent(slug)}`;
}
