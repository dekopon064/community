import { getTranslations, setRequestLocale } from "next-intl/server";
import CurationCard from "@/app/components/CurationCard";
import { fetchLocalizedCurations } from "@/app/lib/curations";

// 새 글 등록 시 최대 60초 안에 대표 카드를 최신화 (ISR)
export const revalidate = 60;

export default async function Home({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Home");

  const [featured] = await fetchLocalizedCurations(locale);

  return (
    // pt-6: 헤더(sticky) 여유 여백, pb-24: 고정 바텀 네비(h-16) 가림 방지
    <div className="min-h-[60vh] bg-canvas px-5 pt-6 pb-24">
      <h2 className="mb-4 text-lg font-bold tracking-tight text-ink">
        {t("sectionTitle")}
      </h2>

      {featured && (
        <div className="mb-8">
          <CurationCard
            slug={featured.slug}
            category={featured.category}
            title={featured.title}
            summary={featured.summary}
          />
        </div>
      )}

      {/* 화면 내 유일한 액센트 컬러(turquoise)를 담은 메인 CTA */}
      <button
        type="button"
        className="w-full rounded-xl bg-turquoise py-4 text-lg font-extrabold text-canvas-white shadow-md transition-transform active:scale-[0.98]"
      >
        {t("cta")}
      </button>
    </div>
  );
}
