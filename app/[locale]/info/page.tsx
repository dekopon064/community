import { setRequestLocale } from "next-intl/server";
import CurationExplorer from "@/app/components/CurationExplorer";
import { fetchLocalizedCurations } from "@/app/lib/curations";

// 새 글 등록 시 최대 60초 안에 목록을 최신화 (ISR)
export const revalidate = 60;

export default async function InfoPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const curations = await fetchLocalizedCurations(locale);

  return (
    <div className="min-h-[60vh] bg-canvas px-5 pt-10 pb-24 md:px-8 md:pt-16 lg:px-10 lg:pt-20">
      <div className="mx-auto max-w-6xl">
        <CurationExplorer curations={curations} />
      </div>
    </div>
  );
}
