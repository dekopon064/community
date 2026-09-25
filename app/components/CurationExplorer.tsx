import { useLocale, useTranslations } from "next-intl";
import CurationCard from "@/app/components/CurationCard";
import InfoStatePanel from "@/app/components/InfoStatePanel";
import SignalRibbon from "@/app/components/SignalRibbon";
import { Link } from "@/i18n/navigation";
import type { LocalizedCuration } from "@/app/lib/types";
import { USER_CATEGORIES, type UserCategory } from "@/app/lib/userCategories";

export default function CurationExplorer({
  curations,
  todayKst,
  selectedCategory,
}: {
  curations: LocalizedCuration[];
  todayKst: string;
  selectedCategory?: UserCategory;
}) {
  const locale = useLocale();
  const t = useTranslations("Info");
  const categoriesT = useTranslations("Categories");

  const filtered =
    selectedCategory === undefined
      ? curations
      : curations.filter((item) => item.userCategory === selectedCategory);

  return (
    <div className="grid min-w-0 gap-10 lg:grid-cols-[minmax(13rem,0.42fr)_minmax(0,1fr)] lg:gap-14">
      <aside className="lg:sticky lg:top-28 lg:self-start">
        <h1 className="max-w-[12ch] text-4xl font-bold leading-[1.08] tracking-[-0.04em] text-ink md:text-5xl">
          {selectedCategory ? categoriesT(selectedCategory) : t("title")}
        </h1>
        <p className="mt-5 max-w-md text-base leading-7 text-ink-sub">
          {t("intro")}
        </p>
        <SignalRibbon className="mt-7 ml-auto block h-8 w-44 text-sky/70 lg:ml-0" />

        <p className="mt-7 border-t border-stone pt-5 text-sm leading-6 text-ink-sub">
          {t("reviewNote")}
        </p>

        {!selectedCategory && (
          <nav
            aria-label={t("filterLabel")}
            className="-mx-5 mt-7 overflow-x-auto px-5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:mx-0 lg:overflow-visible lg:px-0"
          >
            <div className="flex gap-2 lg:flex-wrap">
              {USER_CATEGORIES.map((category) => (
                <Link
                  key={category}
                  href={`/info/category/${category}`}
                  className="inline-flex min-h-11 shrink-0 items-center rounded-full border border-stone bg-transparent px-4 py-2 text-sm font-bold text-ink-sub transition-colors hover:text-ink"
                >
                  {categoriesT(category)}
                </Link>
              ))}
            </div>
          </nav>
        )}
      </aside>

      <section aria-labelledby="curation-results-title" className="min-w-0">
        <p
          id="curation-results-title"
          aria-live="polite"
          className="mb-5 text-sm font-bold text-ink"
        >
          {t("resultCount", { count: filtered.length })}
        </p>

        <div id="curation-results" className="flex min-w-0 flex-col gap-4">
          {filtered.length > 0 ? (
            filtered.map((item) => (
              <CurationCard
                key={item.id}
                slug={item.slug}
                category={item.userCategory}
                categoryLabel={item.userCategory ? categoriesT(item.userCategory) : null}
                title={item.title}
                summary={item.summary}
                summaryLabel={t("atAGlance")}
                locale={locale}
                deadlineKind={item.application_deadline_kind}
                deadlineOn={item.application_deadline_on}
                eventStartOn={item.event_start_on}
                eventEndOn={item.event_end_on}
                todayKst={todayKst}
              />
            ))
          ) : (
            <InfoStatePanel
              title={
                !selectedCategory && curations.length === 0
                  ? t("emptyTitle")
                  : t("filteredEmptyTitle")
              }
              description={
                !selectedCategory && curations.length === 0
                  ? t("emptyDescription")
                  : t("filteredEmptyDescription")
              }
              role="status"
              headingLevel={2}
            >
              {!selectedCategory && curations.length === 0 ? (
                <Link
                  href="/"
                  className="inline-flex min-h-11 items-center rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white transition-colors hover:bg-focus"
                >
                  {t("homeAction")}
                </Link>
              ) : null}
            </InfoStatePanel>
          )}
        </div>
      </section>
    </div>
  );
}
