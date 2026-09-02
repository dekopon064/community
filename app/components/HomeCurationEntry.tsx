import { ArrowUpRight } from "lucide-react";
import { Link } from "@/i18n/navigation";
import SignalGlyph from "@/app/components/SignalGlyph";
import { categoryGlyphKind } from "@/app/lib/categories";
import type { CurationCategoryKey } from "@/app/lib/categories";

interface HomeCurationEntryProps {
  slug: string;
  category: CurationCategoryKey;
  categoryLabel: string;
  title: string;
  summary: string;
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

export default function HomeCurationEntry({
  slug,
  category,
  categoryLabel,
  title,
  summary,
  publishedAt,
  publishedLabel,
  locale,
}: HomeCurationEntryProps) {
  const published = formatPublishedAt(publishedAt, locale);
  const glyph = categoryGlyphKind(category);

  return (
    <Link
      href={`/info/${slug}`}
      className="group block min-h-[11.5rem] rounded-[13px] border border-stone bg-canvas-white p-5 shadow-premium-sm transition-[transform,border-color,box-shadow] hover:-translate-y-0.5 hover:border-sky focus-visible:-translate-y-0.5 lg:min-h-[12.5rem] lg:px-7 lg:py-6"
    >
      <article className="grid min-w-0 grid-cols-[2.875rem_minmax(0,1fr)_1.125rem] items-start gap-3 lg:grid-cols-[3.5rem_minmax(0,1fr)_1.375rem] lg:gap-4">
        <div
          className="grid h-[2.875rem] w-[2.875rem] shrink-0 place-items-center rounded-[14px] bg-mineral text-ink lg:h-14 lg:w-14 lg:rounded-[17px]"
        >
          <SignalGlyph kind={glyph} className="h-[1.375rem] w-[1.375rem] lg:h-7 lg:w-7" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs font-semibold text-ink-sub">
            {categoryLabel}
          </p>
          <h2 className="line-clamp-2 min-h-[2.8em] text-[17px] font-bold leading-[1.4] tracking-[-0.038em] text-ink lg:min-h-[2.76em] lg:text-[19px] lg:leading-[1.38]">
            {title}
          </h2>
          <p className="mt-2 line-clamp-2 min-h-[3.16em] text-[13px] leading-[1.58] tracking-[-0.018em] text-ink-sub lg:min-h-[3.24em] lg:text-sm lg:leading-[1.62]">
            {summary}
          </p>
          {published && (
            <p className="mt-3 text-xs font-semibold tabular-nums text-ink-sub">
              {publishedLabel} · <time dateTime={publishedAt}>{published}</time>
            </p>
          )}
        </div>
        <ArrowUpRight
          className="h-[1.125rem] w-[1.125rem] shrink-0 text-ink-sub transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 lg:h-5 lg:w-5"
          strokeWidth={1.8}
          aria-hidden="true"
        />
      </article>
    </Link>
  );
}
