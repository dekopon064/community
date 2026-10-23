import { Suspense } from "react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { PublicCardsLoading } from "@/app/components/PublicPageLoading";
import HomeExperience from "@/app/components/HomeExperience";
import { currentHomeItems } from "@/app/lib/homePresentation";
import { todayKst } from "@/app/lib/applicationDeadlineDisplay";
import { fetchLocalizedCurations } from "@/app/lib/curations";
import { supabase } from '@/app/lib/supabase';
import { attachHomeCardColors } from '@/app/lib/home-colors/public-read';

// Keep publication visibility and the existing created_at ordering on every request.
export const dynamic = "force-dynamic";

export default async function Home({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <Suspense fallback={<PublicCardsLoading />}><HomeContents locale={locale} /></Suspense>;
}

async function HomeContents({ locale }: { locale: string }) {
  const [rows, t, categories, filters] = await Promise.all([
    fetchLocalizedCurations(locale), getTranslations("Home"), getTranslations("Categories"), getTranslations("PublicFilters"),
  ]);
  const raw = t.raw("headlineParts");
  const parts = Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : [];
  const headline = parts.length > 1
    ? locale === "ja" ? [parts.slice(0, 2).join(""), parts.slice(2).join("")] : [parts[0], parts.slice(1).join(" ")]
    : [t("headline")];
  const items = await attachHomeCardColors(currentHomeItems(rows, locale, todayKst(), key => categories(key)), supabase);
  // Editorial section assignment remains separate from stored poster colors.
  return <HomeExperience locale={locale} headline={headline} intro={t("intro")}
    items={items}
    topicLabels={Object.fromEntries(["culture_experience", "language_learning", "employment_career"].map(key => [key, filters(`programTopics.${key}`)]))} />;
}
