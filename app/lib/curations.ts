import { supabase } from "@/app/lib/supabase";
import type { Curation, LocalizedCuration } from "@/app/lib/types";
import { routing } from "@/i18n/routing";

const BILINGUAL_FIELDS = [
  "title_ko",
  "summary_ko",
  "content_ko",
  "title_ja",
  "summary_ja",
  "content_ja",
] as const;

type AppLocale = (typeof routing.locales)[number];

function isNonEmptyText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isAppLocale(locale: string): locale is AppLocale {
  return (routing.locales as readonly string[]).includes(locale);
}

export function isCompleteBilingualCuration(
  row: Pick<Curation, (typeof BILINGUAL_FIELDS)[number]>,
): boolean {
  return BILINGUAL_FIELDS.every((field) => isNonEmptyText(row[field]));
}

export function localizeCuration(
  row: Curation,
  locale: string,
): LocalizedCuration | null {
  if (!isCompleteBilingualCuration(row) || !isAppLocale(locale)) {
    return null;
  }

  const title = locale === "ja" ? row.title_ja : row.title_ko;
  const summary = locale === "ja" ? row.summary_ja : row.summary_ko;
  const content = locale === "ja" ? row.content_ja : row.content_ko;

  if (
    !isNonEmptyText(title) ||
    !isNonEmptyText(summary) ||
    !isNonEmptyText(content)
  ) {
    return null;
  }

  return {
    id: row.id,
    slug: row.slug,
    category: row.category,
    title,
    summary,
    content,
    source: row.source,
    source_item_id: row.source_item_id,
    source_url: row.source_url,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

async function fetchCurationRows(): Promise<Curation[]> {
  const { data } = await supabase
    .from("curations")
    .select("*")
    .order("created_at", { ascending: false });

  return (data ?? []) as Curation[];
}

export async function fetchLocalizedCurations(
  locale: string,
): Promise<LocalizedCuration[]> {
  const rows = await fetchCurationRows();
  return rows
    .map((row) => localizeCuration(row, locale))
    .filter((item): item is LocalizedCuration => item !== null);
}

export async function fetchLocalizedCurationBySlug(
  slug: string,
  locale: string,
): Promise<LocalizedCuration | null> {
  const { data } = await supabase
    .from("curations")
    .select("*")
    .eq("slug", slug)
    .maybeSingle();

  if (!data) {
    return null;
  }

  return localizeCuration(data as Curation, locale);
}

export async function fetchCompleteCurationSlugs(): Promise<string[]> {
  const { data } = await supabase
    .from("curations")
    .select(
      "slug, title_ko, summary_ko, content_ko, title_ja, summary_ja, content_ja",
    );

  const rows = (data ?? []) as Pick<
    Curation,
    "slug" | (typeof BILINGUAL_FIELDS)[number]
  >[];

  return rows.filter(isCompleteBilingualCuration).map((row) => row.slug);
}
