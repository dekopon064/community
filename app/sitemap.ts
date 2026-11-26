import type { MetadataRoute } from "next";
import { fetchPublishedSitemapSlugs } from "@/app/lib/curations";
import { publicArticleUrl, publicOrigin } from "@/app/lib/publicUrls";
import { routing } from "@/i18n/routing";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const slugs = await fetchPublishedSitemapSlugs();
  const entries: MetadataRoute.Sitemap = [];
  for (const locale of routing.locales) {
    const home = `${publicOrigin}/${locale}`;
    entries.push({ url: home });
    for (const slug of slugs) {
      entries.push({ url: publicArticleUrl(locale, slug) });
    }
  }
  return entries;
}
