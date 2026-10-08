"use client";

import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import CategoryIcon from "./CategoryIcon";
import { isUserCategory } from "@/app/lib/userCategories";
import styles from "./PublicNavigationFeedback.module.css";

function Lines({ large = false }: { large?: boolean }) {
  return <div aria-hidden="true" className="space-y-3">
    <div className={`${styles.skeleton} h-4 w-28`} />
    <div className={`${styles.skeleton} ${large ? "h-10 w-[85%]" : "h-6 w-[85%]"}`} />
    <div className={`${styles.skeleton} h-4 w-full`} />
    <div className={`${styles.skeleton} h-4 w-3/4`} />
  </div>;
}

export function PublicCardsLoading() {
  const locale = useLocale();
  return <div className={styles.loading} aria-busy="true" data-public-loading="cards">
    <p role="status" className={`${styles.label} px-4 pt-4 md:px-6`}>{locale === "ja" ? "情報を読み込んでいます。" : "정보를 불러오는 중입니다."}</p>
    {[0, 1].map(n => <div className={styles.row} key={n}><Lines /></div>)}
  </div>;
}

export function PublicListLoading() {
  const locale = useLocale();
  const params = useParams();
  const category = typeof params.category === "string" && isUserCategory(params.category) ? params.category : null;
  const t = useTranslations("Info");
  const categories = useTranslations("Categories");
  const intro = category ? t(`categoryIntros.${category}`) : t("intro");
  return <div className="min-h-[60vh] bg-canvas px-5 pb-24 pt-8 md:px-8 md:pt-16 lg:px-10 lg:pt-20" data-public-loading="list">
    <div className="mx-auto grid max-w-6xl min-w-0 gap-6 lg:grid-cols-[minmax(13rem,0.42fr)_minmax(0,1fr)] lg:gap-14">
      <aside>
        <div className="flex items-center gap-2.5 md:gap-3">
          {category && <CategoryIcon category={category} size={48} className="h-10 w-10 shrink-0 md:h-12 md:w-12" />}
          <h1 className={`max-w-[12ch] text-4xl font-bold leading-[1.12] tracking-[-0.035em] text-primary-text md:text-5xl${locale === "ja" && category === "youth_space" ? " lg:whitespace-nowrap lg:text-[clamp(2rem,3.3vw,2.625rem)]" : ""}`}>{category ? categories(category) : t("title")}</h1>
        </div>
        <p className="public-readable mt-3 text-sm leading-6 text-info-muted lg:hidden">{category ? intro : t("compactReviewNote")}</p>
        <p className="public-readable mt-5 hidden max-w-md text-base leading-7 text-info-body lg:block">{intro}</p>
        <p className="mt-7 hidden border-t border-info-rule pt-5 text-sm leading-6 text-info-muted lg:block">{t("reviewNote")}</p>
      </aside>
      <div className="min-w-0"><div className="mb-4 hidden h-5 lg:block" aria-hidden="true" /><div className="border-t border-info-rule"><PublicCardsLoading /></div></div>
    </div>
  </div>;
}

export function PublicDetailLoading() {
  const locale = useLocale();
  return <div className={`${styles.loading} mx-auto min-h-[60vh] max-w-6xl bg-canvas px-5 pb-24 pt-8 md:px-8 md:pt-12 lg:px-10 lg:pt-16`} aria-busy="true" data-public-loading="detail">
    <p role="status" className={styles.label}>{locale === "ja" ? "情報を読み込んでいます。" : "정보를 불러오는 중입니다."}</p>
    <div className="mb-8 h-11" aria-hidden="true"><div className={`${styles.skeleton} h-4 w-20`} /></div>
    <Lines large />
    <div className="mt-10 grid min-w-0 gap-7 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.36fr)] lg:gap-10" aria-hidden="true">
      <div className="space-y-12 rounded-[1.5rem] border border-stone bg-canvas-white px-5 py-7 md:px-9 md:py-10"><Lines /><Lines /><Lines /></div>
      <div className="space-y-5 border-t border-info-rule pt-5"><div className={`${styles.skeleton} h-5 w-32`} /><div className={`${styles.skeleton} h-4 w-full`} /><div className={`${styles.skeleton} h-4 w-3/4`} /></div>
    </div>
  </div>;
}
