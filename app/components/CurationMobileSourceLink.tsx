import { ExternalLink } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { getSafeSource } from "@/app/lib/publicSourceUrl";

export default async function CurationMobileSourceLink({
  sourceUrl,
}: {
  sourceUrl: string | null;
}) {
  const source = getSafeSource(sourceUrl);
  if (!source) return null;

  const t = await getTranslations("InfoTrust");
  return (
    <div className="mt-5 flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 border-t border-info-rule pt-3.5 text-sm leading-6 lg:hidden" data-mobile-source>
      <a
        href={source.href}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-primary-text underline underline-offset-4 transition-colors hover:text-focus"
      >
        {t("earlySource")}
        <ExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="sr-only">{t("newWindow")}</span>
      </a>
      <span className="min-w-0 break-all text-xs text-info-muted">{source.hostname}</span>
    </div>
  );
}
