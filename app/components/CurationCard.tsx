import CategoryIcon from "@/app/components/CategoryIcon";
import CurationPeriodText from "@/app/components/CurationPeriodText";
import { Link } from "@/i18n/navigation";
import type { UserCategory } from "@/app/lib/userCategories";

export interface CurationCardProps {
  slug: string;
  category: UserCategory | null;
  categoryLabel: string | null;
  title: string;
  summary: string;
  summaryLabel?: string;
  locale: string;
  deadlineKind: string | null;
  deadlineOn: string | null;
  eventStartOn: string | null;
  eventEndOn: string | null;
  todayKst: string;
}

export default function CurationCard({
  slug,
  category,
  categoryLabel,
  title,
  summary,
  summaryLabel,
  locale,
  deadlineKind,
  deadlineOn,
  eventStartOn,
  eventEndOn,
  todayKst,
}: CurationCardProps) {
  return (
    <Link
      href={`/info/${slug}`}
      className="group block border-b border-info-rule bg-info-surface px-4 py-5 transition-colors hover:bg-info-hover focus-visible:bg-info-hover md:px-6 md:py-6"
    >
      <article className={`grid min-w-0 gap-x-3 ${category ? "grid-cols-[24px_minmax(0,1fr)]" : "grid-cols-1"}`}>
        <div className={`flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm leading-6 ${category ? "col-start-2" : "col-start-1"}`}>
          {categoryLabel && (
            <span className="font-semibold text-primary-text">{categoryLabel}</span>
          )}
          <CurationPeriodText
            category={category}
            deadlineKind={deadlineKind}
            deadlineOn={deadlineOn}
            eventStartOn={eventStartOn}
            eventEndOn={eventEndOn}
            todayKst={todayKst}
            locale={locale}
          />
        </div>
        {category && (
          <CategoryIcon category={category} size={24} className="col-start-1 row-start-2 mt-3 h-6 w-6 shrink-0" />
        )}
        <div className={`${category ? "col-start-2" : "col-start-1"} row-start-2 min-w-0 pt-2`}>
          <h2 className="break-words text-xl font-bold leading-[1.35] tracking-[-0.025em] text-primary-text md:text-[1.45rem]">
            {title}
          </h2>
          <p className="mt-2 line-clamp-2 break-words text-sm leading-6 text-info-body md:text-[0.95rem] md:leading-7">
            {summaryLabel && <span className="sr-only">{summaryLabel}: </span>}
            {summary}
          </p>
        </div>
      </article>
    </Link>
  );
}
