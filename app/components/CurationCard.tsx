import { ArrowUpRight } from "lucide-react";
import SignalGlyph from "@/app/components/SignalGlyph";
import { categoryGlyphKind } from "@/app/lib/categories";
import { Link } from "@/i18n/navigation";
import type { CurationCategoryKey } from "@/app/lib/categories";

export interface CurationCardProps {
  slug: string;
  category: CurationCategoryKey;
  categoryLabel: string;
  title: string;
  summary: string;
  summaryLabel: string;
  publishedAt: string;
  publishedLabel: string;
  locale: string;
}

function formatPublishedAt(value: string, locale: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

// 서버/클라이언트 무관하게 재사용 가능한 프레젠테이션 컴포넌트
export default function CurationCard({
  slug,
  category,
  categoryLabel,
  title,
  summary,
  summaryLabel,
  publishedAt,
  publishedLabel,
  locale,
}: CurationCardProps) {
  const published = formatPublishedAt(publishedAt, locale);

  return (
    <Link
      href={`/info/${slug}`}
      className="group block rounded-[1.35rem] border border-stone bg-canvas-white transition-[transform,border-color,box-shadow] hover:-translate-y-0.5 hover:border-sky hover:shadow-premium-sm focus-visible:-translate-y-0.5"
    >
      <article className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-4 p-5 md:gap-5 md:p-6">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-mineral text-ink md:h-14 md:w-14">
          <SignalGlyph
            kind={categoryGlyphKind(category)}
            className="h-8 w-8 md:h-9 md:w-9"
          />
        </div>

        <div className="min-w-0">
          <p className="text-xs font-semibold text-ink-sub">{categoryLabel}</p>
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
          {published && (
            <p className="mt-4 text-xs font-semibold tabular-nums text-coral">
              {publishedLabel} · <time dateTime={publishedAt}>{published}</time>
            </p>
          )}
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
