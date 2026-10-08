import { setRequestLocale } from "next-intl/server";
import CurationExplorer from "@/app/components/CurationExplorer";
import { todayKst } from "@/app/lib/applicationDeadlineDisplay";
import { fetchLocalizedCurations } from "@/app/lib/curations";

export const dynamic = "force-dynamic";

export default async function InfoPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const curations = await fetchLocalizedCurations(locale);
  const now = new Date();

  return (
    <div className="min-h-[60vh] bg-canvas px-5 pt-8 pb-24 md:px-8 md:pt-16 lg:px-10 lg:pt-20">
      <div className="mx-auto max-w-6xl">
        <CurationExplorer curations={curations} todayKst={todayKst(now)} nowIso={now.toISOString()} />
      </div>
    </div>
  );
}
