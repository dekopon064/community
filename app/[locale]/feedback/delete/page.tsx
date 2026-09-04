import { getTranslations, setRequestLocale } from "next-intl/server";
import DeleteFeedbackForm from "@/app/components/feedback/DeleteFeedbackForm";
import { getTurnstilePublicConfig } from "@/app/lib/turnstile-public";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("FeedbackDelete");
  return { title: t("pageTitle") };
}

export default async function DeleteFeedbackPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const turnstile = getTurnstilePublicConfig("delete");
  const language = locale === "ja" ? "ja" : "ko";

  return (
    <div className="mx-auto min-h-[60vh] max-w-3xl bg-canvas px-5 pt-8 pb-24 md:px-8 md:pt-12">
      <DeleteFeedbackForm
        turnstileSiteKey={turnstile.siteKey}
        turnstileAction={turnstile.action}
        language={language}
      />
    </div>
  );
}
