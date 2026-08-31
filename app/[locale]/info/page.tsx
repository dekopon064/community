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
    // pt-6: 헤더(sticky) 여유 여백, pb-24: 고정 바텀 네비(h-16) 가림 방지
    <div className="min-h-[60vh] bg-canvas px-5 pt-6 pb-24 md:px-8">
      <div className="mx-auto max-w-3xl">
        <CurationExplorer curations={curations} />
      </div>
    </div>
  );
}
