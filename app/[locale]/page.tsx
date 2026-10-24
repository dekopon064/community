import { Suspense } from "react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { PublicCardsLoading } from "@/app/components/PublicPageLoading";
import HomeExperience from "@/app/components/HomeExperience";
import { homeItems, type HomeSections } from "@/app/lib/homePresentation";
import { selectHomeContent } from "@/app/lib/homeSelection";
import { todayKst } from "@/app/lib/applicationDeadlineDisplay";
import { fetchLocalizedCurations } from "@/app/lib/curations";
import { supabase } from '@/app/lib/supabase';
import { attachHomeCardColors } from '@/app/lib/home-colors/public-read';

// Keep publication visibility; compute all home selections at one request time.
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
  const requestTime = new Date(), now = requestTime.getTime(), today = todayKst(requestTime);
  const selection = selectHomeContent(rows, now);
  const display = (values: typeof rows) => homeItems(values, locale, today, key => categories(key), now);
  // Colors are read only for the at-most-six representative cards. Lower sections
  // use the existing list cards and never trigger analysis or additional color reads.
  const items = await attachHomeCardColors(display(selection.featured), supabase);
  const sections: HomeSections = {
    deadline: display(selection.sections.deadline), experiences: display(selection.sections.experiences),
    learning: display(selection.sections.learning), events: display(selection.sections.events),
  };
  return <HomeExperience locale={locale} headline={headline} intro={t("intro")}
    items={items} sections={sections}
    topicLabels={Object.fromEntries(["culture_experience", "language_learning", "employment_career"].map(key => [key, filters(`programTopics.${key}`)]))} />;
}
