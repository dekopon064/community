import styles from "@/app/components/auth/AuthSurfaces.module.css";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import SavedList from "@/app/components/auth/SavedList";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };
export default async function SavedPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  if (locale !== "ko" && locale !== "ja") notFound();
  const t = await getTranslations({ locale, namespace: "Saved" });
  return <section className={styles.saved}><h1 className={styles.heading}>{t("title")}</h1><p className={styles.lead}>{t("description")}</p><SavedList locale={locale} /></section>;
}
