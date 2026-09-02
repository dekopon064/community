import { getTranslations } from "next-intl/server";
import InfoStatePanel from "@/app/components/InfoStatePanel";
import { Link } from "@/i18n/navigation";

export default async function CurationNotFound() {
  const t = await getTranslations("InfoStates");

  return (
    <div className="mx-auto min-h-[60vh] max-w-4xl bg-canvas px-5 pt-12 pb-24 md:px-8 md:pt-20">
      <InfoStatePanel
        title={t("notFoundTitle")}
        description={t("notFoundDescription")}
      >
        <Link
          href="/info"
          className="inline-flex min-h-11 items-center rounded-full bg-ink px-5 py-2.5 text-sm font-bold text-canvas-white transition-colors hover:bg-focus"
        >
          {t("goToList")}
        </Link>
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
