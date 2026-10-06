import { CalendarDays, ExternalLink, ShieldCheck } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { getSafeSource } from "@/app/lib/publicSourceUrl";

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
        className="text-lg font-bold tracking-[-0.03em] text-primary-text"
      >
        {t("title")}
      </h2>

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
        {source ? (
          <a
            href={source.href}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-source-border bg-source-surface px-[15px] py-[11px] text-sm font-bold text-source-text transition-colors hover:bg-source-hover"
          >
            <span className="min-w-0">
              <span className="flex items-center gap-2">
                <ShieldCheck
                  className="h-4 w-4 shrink-0 text-source-shield"
                  strokeWidth={1.8}
                  aria-hidden="true"
                />
                <span>{t("reviewedTitle")}</span>
              </span>
              <span className="mt-0.5 block truncate text-xs font-medium text-source-domain">
                {source.hostname}
              </span>
            </span>
            <ExternalLink
              className="h-4 w-4 shrink-0 text-source-icon"
              strokeWidth={1.8}
              aria-hidden="true"
            />
            <span className="sr-only">{t("newWindow")}</span>
          </a>
        ) : (
          <div>
            <p className="text-sm font-bold text-ink">{t("reviewedTitle")}</p>
            <p className="mt-2 text-sm leading-6 text-ink-sub">
              {t("sourceUnavailable")}
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
