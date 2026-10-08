import { useLocale, useTranslations } from "next-intl";
import { Suspense } from 'react';
import CategoryIcon from "@/app/components/CategoryIcon";
import PublicCurationList from './PublicCurationList';
import { publicCurationItem, supportsExploration } from '@/app/lib/publicContentFilters';
import Link from "@/app/components/PublicNavigationLink";
import type { LocalizedCuration } from "@/app/lib/types";
import { USER_CATEGORIES, type UserCategory } from "@/app/lib/userCategories";

export default function CurationExplorer({
  curations,
  todayKst,
  selectedCategory,
  nowIso,
}: {
  curations: LocalizedCuration[];
  todayKst: string;
  selectedCategory?: UserCategory;
  nowIso: string;
}) {
  const locale = useLocale();
  const t = useTranslations("Info");
  const categoriesT = useTranslations("Categories");
  const intro = selectedCategory ? t(`categoryIntros.${selectedCategory}`) : t("intro");

  const filtered =
    selectedCategory === undefined
      ? curations
      : curations.filter((item) => item.userCategory === selectedCategory);

  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(13rem,0.42fr)_minmax(0,1fr)] lg:gap-14">
      <aside className="lg:sticky lg:top-28 lg:self-start">
        <div className="flex flex-wrap items-center gap-2.5 md:gap-3">
          {selectedCategory && (
            <CategoryIcon category={selectedCategory} size={48} className="h-10 w-10 shrink-0 md:h-12 md:w-12" />
          )}
          <h1 className={`max-w-[12ch] text-4xl font-bold leading-[1.12] tracking-[-0.035em] text-primary-text md:text-5xl${locale === "ja" && selectedCategory === "youth_space" ? " lg:whitespace-nowrap lg:text-[clamp(2rem,3.3vw,2.625rem)]" : ""}`}>
            {selectedCategory ? categoriesT(selectedCategory) : t("title")}
          </h1>
        </div>
        <p className="public-readable mt-3 text-sm leading-6 text-info-muted lg:hidden">
          {selectedCategory ? intro : t("compactReviewNote")}
        </p>
        <p className="public-readable mt-5 hidden max-w-md text-base leading-7 text-info-body lg:block">
          {intro}
        </p>
        <p className="mt-7 hidden border-t border-info-rule pt-5 text-sm leading-6 text-info-muted lg:block">
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
                  className="inline-flex min-h-11 shrink-0 items-center rounded-full border border-info-rule bg-info-surface px-4 py-2 text-sm font-semibold text-info-muted transition-colors hover:bg-info-hover hover:text-ink"
                >
                  {categoriesT(category)}
                </Link>
              ))}
            </div>
          </nav>
        )}
      </aside>

      <section aria-labelledby="curation-results-title" className="min-w-0">
        <Suspense fallback={<p role="status" className="text-info-muted">{t('loading')}</p>}>
          <PublicCurationList items={filtered.map(publicCurationItem)} category={supportsExploration(selectedCategory)?selectedCategory:undefined} todayKst={todayKst} nowIso={nowIso}/>
        </Suspense>
      </section>
    </div>
  );
}
