import { ArrowUpRight } from "lucide-react";
import { Link } from "@/i18n/navigation";
import SignalGlyph from "@/app/components/SignalGlyph";

interface HomeCurationEntryProps {
  slug: string;
  category: string;
  title: string;
  summary: string;
  publishedAt: string;
  publishedLabel: string;
  locale: string;
  primary?: boolean;
}

function glyphForCategory(category: string) {
  const normalized = category.toLocaleLowerCase();
  if (/(주거|집|housing|home|임대)/.test(normalized)) return "housing" as const;
  if (/(외국인|등록|비자|visa|identity|행정)/.test(normalized)) return "identity" as const;
  return "document" as const;
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
  title,
  summary,
  publishedAt,
  publishedLabel,
  locale,
  primary = false,
}: HomeCurationEntryProps) {
  const published = formatPublishedAt(publishedAt, locale);
  const glyph = glyphForCategory(category);

  return (
    <Link
      href={`/info/${slug}`}
      className={`group block rounded-[1.35rem] border border-stone bg-canvas-white transition-[transform,border-color,box-shadow] hover:-translate-y-0.5 hover:border-sky hover:shadow-premium-sm focus-visible:-translate-y-0.5 ${
        primary ? "p-5 md:p-6" : "p-4 md:p-5"
      }`}
    >
      <article className="flex items-center gap-4">
        <div
          className={`grid shrink-0 place-items-center rounded-2xl ${
            primary ? "h-14 w-14 bg-mineral text-ink" : "h-12 w-12 bg-canvas text-ink-sub"
          }`}
        >
          <SignalGlyph kind={glyph} accent={primary} className={primary ? "h-9 w-9" : "h-8 w-8"} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="mb-1 truncate text-xs font-semibold text-ink-sub">{category}</p>
          <h2 className={`truncate font-bold tracking-[-0.035em] text-ink ${primary ? "text-xl md:text-2xl" : "text-lg"}`}>
            {title}
          </h2>
          <p className="mt-1 line-clamp-2 text-sm leading-6 text-ink-sub">{summary}</p>
          {primary && published && (
            <p className="mt-3 text-xs font-semibold tabular-nums text-coral">
              {publishedLabel} · <time dateTime={publishedAt}>{published}</time>
            </p>
          )}
        </div>
        <ArrowUpRight
          className="h-5 w-5 shrink-0 text-ink-sub transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
          strokeWidth={1.8}
          aria-hidden="true"
        />
      </article>
    </Link>
  );
}
