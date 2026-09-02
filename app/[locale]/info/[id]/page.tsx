import { notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import CurationTrustPanel from "@/app/components/CurationTrustPanel";
import Markdown from "@/app/components/Markdown";
import SignalGlyph from "@/app/components/SignalGlyph";
import { categoryGlyphKind } from "@/app/lib/categories";
import {
  fetchCompleteCurationSlugs,
  fetchLocalizedCurationBySlug,
} from "@/app/lib/curations";

// 콘텐츠 수정 시 최대 60초 안에 상세 페이지를 최신화 (ISR)
export const revalidate = 60;

export async function generateStaticParams() {
  const slugs = await fetchCompleteCurationSlugs();
  return slugs.map((slug) => ({ id: slug }));
}

export default async function InfoDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);

  const item = await fetchLocalizedCurationBySlug(id, locale);

  if (!item) {
    notFound();
  }

  const t = await getTranslations("InfoDetail");
  const categoriesT = await getTranslations("Categories");
  const publishedDate = new Intl.DateTimeFormat(locale, {
    dateStyle: "long",
  }).format(new Date(item.created_at));

  return (
    <div className="mx-auto min-h-[60vh] max-w-6xl bg-canvas px-5 pt-8 pb-24 md:px-8 md:pt-12 lg:px-10 lg:pt-16">
      <Link
        href="/info"
        className="mb-8 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-ink-sub transition-colors hover:text-ink"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        {t("back")}
      </Link>

      <header className="max-w-4xl">
        <div className="flex items-center gap-3 text-sm font-bold text-ink-sub">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-mineral text-ink">
            <SignalGlyph
              kind={categoryGlyphKind(item.categoryKey)}
              className="h-7 w-7"
            />
          </span>
          <span>{categoriesT(item.categoryKey)}</span>
        </div>
        <h1 className="mt-5 break-words text-3xl font-bold leading-[1.16] tracking-[-0.04em] text-ink md:text-5xl">
          {item.title}
        </h1>
        <p className="mt-5 max-w-3xl text-lg leading-8 text-ink-sub md:text-xl md:leading-9">
          {item.summary}
        </p>
        <p className="mt-5 text-sm font-semibold tabular-nums text-coral">
          {t("publishedAt")} · {publishedDate}
        </p>
      </header>

      <div className="mt-10 grid min-w-0 gap-7 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.36fr)] lg:items-start lg:gap-10">
        <article className="order-2 min-w-0 rounded-[1.5rem] border border-stone bg-canvas-white px-5 py-7 md:px-9 md:py-10 lg:order-1">
          <Markdown>{item.content}</Markdown>
        </article>

        <div className="order-1 lg:order-2">
          <CurationTrustPanel
            locale={locale}
            sourceUrl={item.source_url}
            publishedAt={item.created_at}
            updatedAt={item.updated_at}
          />
        </div>
      </div>
    </div>
  );
}
