import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";

export default async function SiteFooter() {
  const t = await getTranslations("Footer");

  return (
    <footer className="border-t border-stone/80 px-5 py-5 lg:px-8">
      <div className="mx-auto max-w-7xl">
        <Link
          href="/feedback"
          className="inline-flex min-h-11 items-center text-sm text-ink-sub underline underline-offset-2 hover:text-ink"
        >
          {t("feedbackLink")}
        </Link>
      </div>
    </footer>
  );
}
