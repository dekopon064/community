"use client";

import PublicPosterLink from "./PublicPosterLink";
import { useState, type ReactNode } from "react";
import CategoryIcon from "@/app/components/CategoryIcon";
import CurationPeriodText from "@/app/components/CurationPeriodText";
import { sourceImageDisplayUrl as sourceImageUrl } from "@/app/lib/sourceImages";
import Link from "@/app/components/PublicNavigationLink";
import type { UserCategory } from "@/app/lib/userCategories";
import styles from "./SourceImageLayout.module.css";
import programStyles from './ProgramListLayout.module.css';
import eventStyles from './EventListLayout.module.css';

export interface CurationCardProps {
  slug: string; category: UserCategory | null; categoryLabel: string | null;
  title: string; summary: string; imageUrl?: string | null; summaryLabel?: string;
  locale: string; deadlineKind: string | null; deadlineOn: string | null;
  eventStartOn: string | null; eventEndOn: string | null; todayKst: string;
  periodOverride?: ReactNode;
  programLayout?: boolean; eventLayout?: boolean; comparisonFacts?: ReactNode;
}

export default function CurationCard({ slug, category, categoryLabel, title, summary, imageUrl,
  summaryLabel, locale, deadlineKind, deadlineOn, eventStartOn, eventEndOn, todayKst, periodOverride, programLayout = false, eventLayout = false, comparisonFacts }: CurationCardProps) {
  const src = sourceImageUrl(imageUrl), [failed, setFailed] = useState<string | null>(null);
  const href = `/info/${slug}`;
  const hasImage = !!src && src !== failed;
  const comparisonLayout = programLayout || eventLayout;
  const comparisonCard = `${programStyles.card}${eventLayout ? ` ${eventStyles.card}` : ''}`;
  const meta = <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm leading-6">
    {categoryLabel && <span className="font-semibold text-primary-text">{categoryLabel}</span>}
    {periodOverride ?? <CurationPeriodText category={category} deadlineKind={deadlineKind} deadlineOn={deadlineOn} eventStartOn={eventStartOn}
      eventEndOn={eventEndOn} todayKst={todayKst} locale={locale} />}
  </div>;
  const text = <><h2 className="public-readable break-words text-xl font-bold leading-[1.35] tracking-[-0.025em] text-primary-text md:text-[1.45rem]">{title}</h2>
    <p className="public-readable mt-2 line-clamp-2 break-words text-sm leading-6 text-info-body md:text-[0.95rem] md:leading-7">
      {summaryLabel && <span className="sr-only">{summaryLabel}: </span>}{summary}
    </p></>;

  const titleParts = comparisonLayout ? title.match(/^(\([^)]*\)|（[^）]*）|\[[^\]]*\]|【[^】]*】)([\s\S]+)$/) : null;
  const programText = <Link feedback="card" href={href} className={programStyles.text}>
    <div className={programStyles.meta}>{meta}</div>
    <h2 className={programStyles.title}>{titleParts ? <><span className={programStyles.context}>{titleParts[1]}</span>{titleParts[2]}</> : title}</h2>
    {comparisonFacts}
    <p className={programStyles.summary} data-list-summary>{summaryLabel && <span className="sr-only">{summaryLabel}: </span>}{summary}</p>
  </Link>;

  if (comparisonLayout && !hasImage) return <article data-source-card className={comparisonCard}><div data-list-grid className={`${programStyles.grid} ${programStyles.noImage}`}>{programText}</div></article>;
  if (!hasImage) return <Link feedback="card" href={href} data-source-card className="group block border-b border-info-rule bg-info-surface px-4 py-5 transition-colors hover:bg-info-hover focus-visible:bg-info-hover md:px-6 md:py-6">
    <article className={`grid min-w-0 gap-x-3 ${category ? "grid-cols-[24px_minmax(0,1fr)]" : "grid-cols-1"}`}>
      <div className={category ? "col-start-2" : "col-start-1"}>{meta}</div>
      {category && <CategoryIcon category={category} size={24} className="col-start-1 row-start-2 mt-3 h-6 w-6 shrink-0" />}
      <div className={`${category ? "col-start-2" : "col-start-1"} row-start-2 min-w-0 pt-2`}>{text}</div>
    </article>
  </Link>;

  return <>
    <article data-source-card className={comparisonLayout ? comparisonCard : styles.card}>
      <div data-list-grid className={comparisonLayout ? programStyles.grid : styles.cardGrid}>
        <PublicPosterLink src={src} href={href} title={title} locale={locale}
          className={comparisonLayout ? programStyles.poster : styles.thumbnail}
          imageClassName={comparisonLayout ? programStyles.image : styles.image} onFailure={() => setFailed(src)} />
        {comparisonLayout ? programText : <Link feedback="card" href={href} className={styles.textLink}>{meta}<div className="pt-2">{text}</div></Link>}
      </div>
    </article>
  </>;
}
