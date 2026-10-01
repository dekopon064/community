import { notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import CategoryIcon from "@/app/components/CategoryIcon";
import CurationPeriodText from "@/app/components/CurationPeriodText";
import CurationTrustPanel from "@/app/components/CurationTrustPanel";
import CurationBody from "@/app/components/CurationBody";
import { todayKst } from "@/app/lib/applicationDeadlineDisplay";
import { fetchLocalizedCurationBySlug } from "@/app/lib/curations";

export const dynamic = "force-dynamic";

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
  return (
    <div className="mx-auto min-h-[60vh] max-w-6xl bg-canvas px-5 pt-8 pb-24 md:px-8 md:pt-12 lg:px-10 lg:pt-16">
      <Link
        href={item.userCategory ? `/info/category/${item.userCategory}` : "/info"}
        className="mb-8 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-ink-sub transition-colors hover:text-ink"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        {t("back")}
      </Link>

      <header className="max-w-4xl">
        {item.userCategory && (
          <div className="flex items-center gap-2.5 text-sm font-semibold text-primary-text">
            <CategoryIcon category={item.userCategory} size={20} className="h-5 w-5 shrink-0" />
            <span>{categoriesT(item.userCategory)}</span>
          </div>
        )}
        <h1 className="mt-4 break-words text-[clamp(2rem,5vw,3.25rem)] font-bold leading-[1.17] tracking-[-0.025em] text-primary-text [overflow-wrap:anywhere]">
          {item.title}
        </h1>
        <CurationPeriodText
          category={item.userCategory}
          deadlineKind={item.application_deadline_kind}
          deadlineOn={item.application_deadline_on}
          eventStartOn={item.event_start_on}
          eventEndOn={item.event_end_on}
          todayKst={todayKst()}
          locale={locale}
          detail
        />
      </header>

      <div className="mt-10 grid min-w-0 gap-7 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.36fr)] lg:items-start lg:gap-10">
        <article className="min-w-0 rounded-[1.5rem] border border-stone bg-canvas-white px-5 py-7 md:px-9 md:py-10">
          <CurationBody content={item.content} locale={locale} />
        </article>

        <div>
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
