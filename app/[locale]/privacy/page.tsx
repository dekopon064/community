import { getTranslations, setRequestLocale } from "next-intl/server";
import { getPrivacyDocument } from "@/app/content/privacy";
import PrivacyDocument from "@/app/components/PrivacyDocument";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Privacy");
  return { title: t("documentTitle") };
}

export default async function PrivacyPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Privacy");
  const document = getPrivacyDocument(locale);

  return (
    <div className="mx-auto min-h-[60vh] max-w-6xl bg-canvas px-5 pt-8 pb-24 md:px-8 md:pt-12 lg:px-10 lg:pt-16">
      <PrivacyDocument
        document={document}
        skipLabel={t("skipToContent")}
        contactLabel={t("contactLabel")}
        emailLabel={t("emailLabel")}
        datesNote={t("datesNote")}
        feedbackLabel={t("feedbackLink")}
        deleteLabel={t("deleteLink")}
      />
    </div>
  );
}
