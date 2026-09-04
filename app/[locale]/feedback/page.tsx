import { getTranslations, setRequestLocale } from "next-intl/server";
import FeedbackForm from "@/app/components/feedback/FeedbackForm";
import { getTurnstilePublicConfig } from "@/app/lib/turnstile-public";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Feedback");
  return { title: t("pageTitle") };
}

export default async function FeedbackPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const turnstile = getTurnstilePublicConfig("submit");

  return (
    <div className="mx-auto min-h-[60vh] max-w-3xl bg-canvas px-5 pt-8 pb-24 md:px-8 md:pt-12">
      <FeedbackForm
        turnstileSiteKey={turnstile.siteKey}
        turnstileAction={turnstile.action}
      />
    </div>
  );
}
