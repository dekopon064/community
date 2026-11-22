import type { MetadataRoute } from "next";
import { fetchPublishedSitemapSlugs } from "@/app/lib/curations";
import { routing } from "@/i18n/routing";

export const dynamic = "force-dynamic";

const origin = "https://community-app-drab.vercel.app";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const slugs = await fetchPublishedSitemapSlugs();
  const entries: MetadataRoute.Sitemap = [];
  for (const locale of routing.locales) {
    const home = `${origin}/${locale}`;
    entries.push({ url: home });
    for (const slug of slugs) {
      entries.push({ url: `${home}/info/${encodeURIComponent(slug)}` });
    }
  }
  return entries;
}
