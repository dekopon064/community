"use client";

import { useTranslations } from "next-intl";
import InfoStatePanel from "@/app/components/InfoStatePanel";
import { Link } from "@/i18n/navigation";

export default function InfoError({
  unstable_retry,
}: {
  unstable_retry: () => void;
}) {
  const t = useTranslations("InfoStates");

  return (
    <div className="mx-auto min-h-[60vh] max-w-4xl bg-canvas px-5 pt-12 pb-24 md:px-8 md:pt-20">
      <InfoStatePanel
        title={t("errorTitle")}
        description={t("errorDescription")}
        role="alert"
      >
        <button
          type="button"
          onClick={() => unstable_retry()}
          className="min-h-11 rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white transition-colors hover:bg-focus"
        >
          {t("retry")}
        </button>
        <Link
          href="/"
          className="inline-flex min-h-11 items-center rounded-full border border-stone bg-canvas-white px-5 py-2.5 text-sm font-bold text-ink transition-colors hover:border-sky"
        >
          {t("goHome")}
        </Link>
      </InfoStatePanel>
    </div>
  );
}
