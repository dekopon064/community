import { notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import CategoryIcon from "@/app/components/CategoryIcon";
import CurationPeriodText from "@/app/components/CurationPeriodText";
import CurationTrustPanel from "@/app/components/CurationTrustPanel";
import Markdown from "@/app/components/Markdown";
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
          <div className="flex items-center gap-2.5 text-sm font-semibold text-ink">
            <CategoryIcon category={item.userCategory} size={20} className="h-5 w-5 shrink-0" />
            <span>{categoriesT(item.userCategory)}</span>
          </div>
        )}
        <h1 className="mt-4 break-words text-[clamp(2rem,5vw,3.25rem)] font-bold leading-[1.17] tracking-[-0.025em] text-ink [overflow-wrap:anywhere]">
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
        <p className="mt-6 max-w-3xl text-lg leading-8 text-info-body md:mt-7 md:text-xl md:leading-9">
          {item.summary}
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
