import { notFound } from "next/navigation";
import { setRequestLocale } from "next-intl/server";
import CurationExplorer from "@/app/components/CurationExplorer";
import { todayKst } from "@/app/lib/applicationDeadlineDisplay";
import { fetchLocalizedCurations } from "@/app/lib/curations";
import { isUserCategory } from "@/app/lib/userCategories";

export const dynamic = "force-dynamic";

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ locale: string; category: string }>;
}) {
  const { locale, category } = await params;
  if (!isUserCategory(category)) notFound();
  setRequestLocale(locale);

  const curations = await fetchLocalizedCurations(locale);

  return (
    <div className="min-h-[60vh] bg-canvas px-5 pb-24 pt-10 md:px-8 md:pt-16 lg:px-10 lg:pt-20">
      <div className="mx-auto max-w-6xl">
        <CurationExplorer
          curations={curations}
          todayKst={todayKst()}
          selectedCategory={category}
        />
      </div>
    </div>
  );
}
