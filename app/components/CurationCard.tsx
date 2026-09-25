import { ArrowUpRight } from "lucide-react";
import CurationPeriodText from "@/app/components/CurationPeriodText";
import SignalGlyph from "@/app/components/SignalGlyph";
import { userCategoryGlyphKind } from "@/app/lib/userCategories";
import { Link } from "@/i18n/navigation";
import type { UserCategory } from "@/app/lib/userCategories";

export interface CurationCardProps {
  slug: string;
  category: UserCategory | null;
  categoryLabel: string | null;
  title: string;
  summary: string;
  summaryLabel: string;
  locale: string;
  deadlineKind: string | null;
  deadlineOn: string | null;
  eventStartOn: string | null;
  eventEndOn: string | null;
  todayKst: string;
}

// 서버/클라이언트 무관하게 재사용 가능한 프레젠테이션 컴포넌트
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
      className="group block rounded-[1.35rem] border border-stone bg-canvas-white transition-[transform,border-color,box-shadow] hover:-translate-y-0.5 hover:border-sky hover:shadow-premium-sm focus-visible:-translate-y-0.5"
    >
      <article className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-4 p-5 md:gap-5 md:p-6">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-mineral text-ink md:h-14 md:w-14">
          <SignalGlyph
            kind={category ? userCategoryGlyphKind(category) : "document"}
            className="h-8 w-8 md:h-9 md:w-9"
          />
        </div>

        <div className="min-w-0">
          {categoryLabel && (
            <p className="text-xs font-semibold text-ink-sub">{categoryLabel}</p>
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
          <h2 className="mt-1 break-words text-xl font-bold leading-snug tracking-[-0.035em] text-ink md:text-2xl">
            {title}
          </h2>
          <div className="mt-4 rounded-xl bg-mineral/70 px-3.5 py-3 md:px-4">
            <p className="text-xs font-bold tracking-[-0.01em] text-ink">
              {summaryLabel}
            </p>
            <p className="mt-1.5 line-clamp-3 break-words text-sm leading-6 text-ink-sub md:text-base md:leading-7">
              {summary}
            </p>
          </div>
        </div>

        <ArrowUpRight
          className="mt-1 h-5 w-5 shrink-0 text-ink-sub transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
          strokeWidth={1.8}
          aria-hidden="true"
        />
      </article>
    </Link>
  );
}
