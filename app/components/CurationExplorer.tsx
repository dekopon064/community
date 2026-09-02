"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import CurationCard from "@/app/components/CurationCard";
import InfoStatePanel from "@/app/components/InfoStatePanel";
import SignalRibbon from "@/app/components/SignalRibbon";
import { Link } from "@/i18n/navigation";
import type { LocalizedCuration } from "@/app/lib/types";
import type { CurationCategoryKey } from "@/app/lib/categories";

const ALL = "all" as const;

export default function CurationExplorer({
  curations,
}: {
  curations: LocalizedCuration[];
}) {
  const locale = useLocale();
  const t = useTranslations("Info");
  const categoriesT = useTranslations("Categories");

  // 화면 분류 key는 DB 원문 category를 덮지 않고 locale 표시명에만 사용한다.
  const categories = useMemo(
    () => Array.from(new Set(curations.map((item) => item.categoryKey))),
    [curations],
  );

  const [active, setActive] = useState<CurationCategoryKey | typeof ALL>(ALL);
  const effectiveActive =
    active === ALL || categories.includes(active) ? active : ALL;

  const filtered =
    effectiveActive === ALL
      ? curations
      : curations.filter((item) => item.categoryKey === effectiveActive);

  const filterOptions: Array<CurationCategoryKey | typeof ALL> = [
    ALL,
    ...categories,
  ];

  return (
    <div className="grid min-w-0 gap-10 lg:grid-cols-[minmax(13rem,0.42fr)_minmax(0,1fr)] lg:gap-14">
      <aside className="lg:sticky lg:top-28 lg:self-start">
        <h1 className="max-w-[12ch] text-4xl font-bold leading-[1.08] tracking-[-0.04em] text-ink md:text-5xl">
          {t("title")}
        </h1>
        <p className="mt-5 max-w-md text-base leading-7 text-ink-sub">
          {t("intro")}
        </p>
        <SignalRibbon className="mt-7 ml-auto block h-8 w-44 text-sky/70 lg:ml-0" />

        <p className="mt-7 border-t border-stone pt-5 text-sm leading-6 text-ink-sub">
          {t("reviewNote")}
        </p>

        <div
          aria-label={t("filterLabel")}
          className="-mx-5 mt-7 overflow-x-auto px-5 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:mx-0 lg:overflow-visible lg:px-0"
        >
          <div className="flex gap-2 lg:flex-wrap">
            {filterOptions.map((category) => {
              const isActive = effectiveActive === category;
              const label =
                category === ALL ? t("all") : categoriesT(category);
            return (
              <button
                key={category}
                type="button"
                onClick={() => setActive(category)}
                aria-pressed={isActive}
                aria-controls="curation-results"
                className={`min-h-11 shrink-0 rounded-full px-4 py-2 text-sm font-bold transition-colors ${
                  isActive
                    ? "bg-ink text-canvas-white"
                    : "border border-stone bg-transparent text-ink-sub hover:text-ink"
                }`}
              >
                  {label}
              </button>
            );
          })}
          </div>
        </div>
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
                category={item.categoryKey}
                categoryLabel={categoriesT(item.categoryKey)}
                title={item.title}
                summary={item.summary}
                summaryLabel={t("atAGlance")}
                publishedAt={item.created_at}
                publishedLabel={t("publishedAt")}
                locale={locale}
              />
            ))
          ) : (
            <InfoStatePanel
              title={
                curations.length === 0
                  ? t("emptyTitle")
                  : t("filteredEmptyTitle")
              }
              description={
                curations.length === 0
                  ? t("emptyDescription")
                  : t("filteredEmptyDescription")
              }
              role="status"
              headingLevel={2}
            >
              {curations.length === 0 ? (
                <Link
                  href="/"
                  className="inline-flex min-h-11 items-center rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white transition-colors hover:bg-focus"
                >
                  {t("homeAction")}
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => setActive(ALL)}
                  className="min-h-11 rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white transition-colors hover:bg-focus"
                >
                  {t("showAllAction")}
                </button>
              )}
            </InfoStatePanel>
          )}
        </div>
      </section>
    </div>
  );
}
