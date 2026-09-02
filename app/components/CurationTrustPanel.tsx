import { CalendarDays, ExternalLink, ShieldCheck } from "lucide-react";
import { getTranslations } from "next-intl/server";

interface CurationTrustPanelProps {
  locale: string;
  sourceUrl: string | null;
  publishedAt: string;
  updatedAt: string;
}

function formatDate(value: string, locale: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(date);
}

function getSafeSource(value: string | null) {
  if (!value) return null;

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return { href: url.href, hostname: url.hostname.replace(/^www\./, "") };
  } catch {
    return null;
  }
}

export default async function CurationTrustPanel({
  locale,
  sourceUrl,
  publishedAt,
  updatedAt,
}: CurationTrustPanelProps) {
  const t = await getTranslations("InfoTrust");
  const source = getSafeSource(sourceUrl);
  const published = formatDate(publishedAt, locale);
  const updated = formatDate(updatedAt, locale);
  const showUpdated = updated && updated !== published;

  return (
    <aside
      aria-labelledby="curation-trust-title"
      className="rounded-[1.4rem] border border-stone bg-canvas-white p-5 md:p-6 lg:sticky lg:top-28"
    >
      <h2
        id="curation-trust-title"
        className="text-lg font-bold tracking-[-0.03em] text-ink"
      >
        {t("title")}
      </h2>

      <div className="mt-5 flex gap-3 border-b border-stone pb-5">
        <ShieldCheck
          className="mt-0.5 h-5 w-5 shrink-0 text-coral"
          strokeWidth={1.8}
          aria-hidden="true"
        />
        <div>
          <p className="text-sm font-bold text-ink">{t("reviewedTitle")}</p>
          <p className="mt-1 text-sm leading-6 text-ink-sub">
            {t("reviewedBody")}
          </p>
        </div>
      </div>

      <div className="flex gap-3 border-b border-stone py-5">
        <CalendarDays
          className="mt-0.5 h-5 w-5 shrink-0 text-ink-sub"
          strokeWidth={1.8}
          aria-hidden="true"
        />
        <dl className="min-w-0 space-y-3 text-sm">
          {published && (
            <div>
              <dt className="font-semibold text-ink-sub">{t("publishedAt")}</dt>
              <dd className="mt-0.5 font-bold tabular-nums text-ink">
                <time dateTime={publishedAt}>{published}</time>
              </dd>
            </div>
          )}
          {showUpdated && (
            <div>
              <dt className="font-semibold text-ink-sub">{t("updatedAt")}</dt>
              <dd className="mt-0.5 font-bold tabular-nums text-ink">
                <time dateTime={updatedAt}>{updated}</time>
              </dd>
            </div>
          )}
        </dl>
      </div>

      <div className="pt-5">
        <p className="text-sm font-bold text-ink">{t("sourceTitle")}</p>
        {source ? (
          <a
            href={source.href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 flex min-h-11 items-center justify-between gap-3 rounded-xl bg-ink px-4 py-3 text-sm font-bold text-canvas-white transition-colors hover:bg-focus"
          >
            <span className="min-w-0">
              <span className="block">{t("openSource")}</span>
              <span className="mt-0.5 block truncate text-xs font-medium text-mineral">
                {source.hostname}
              </span>
            </span>
            <ExternalLink
              className="h-4 w-4 shrink-0"
              strokeWidth={1.8}
              aria-hidden="true"
            />
            <span className="sr-only">{t("newWindow")}</span>
          </a>
        ) : (
          <p className="mt-2 text-sm leading-6 text-ink-sub">
            {t("sourceUnavailable")}
          </p>
        )}
      </div>
    </aside>
  );
}
