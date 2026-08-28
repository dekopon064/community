import { notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import Markdown from "@/app/components/Markdown";
import {
  fetchCompleteCurationSlugs,
  fetchLocalizedCurationBySlug,
} from "@/app/lib/curations";

// 콘텐츠 수정 시 최대 60초 안에 상세 페이지를 최신화 (ISR)
export const revalidate = 60;

export async function generateStaticParams() {
  const slugs = await fetchCompleteCurationSlugs();
  return slugs.map((slug) => ({ id: slug }));
}

export default async function InfoDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);

  const item = await fetchLocalizedCurationBySlug(id, locale);

  if (!item) {
    notFound();
  }

  const t = await getTranslations("InfoDetail");
  const publishedDate = new Intl.DateTimeFormat(locale, {
    dateStyle: "long",
  }).format(new Date(item.created_at));

  return (
    <div className="min-h-[60vh] bg-canvas px-5 pt-6 pb-24">
      {/* 뒤로 가기 */}
      <Link
        href="/info"
        className="mb-6 inline-flex items-center gap-1 text-sm text-ink-sub transition-colors hover:text-ink"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        {t("back")}
      </Link>

      {/* 헤더 */}
      <header className="mb-6">
        <span className="mb-3 inline-block rounded-md border border-stone px-2 py-1 text-xs font-extrabold text-ink">
          {item.category}
        </span>
        <h1 className="mb-3 text-2xl font-black leading-snug tracking-tight text-ink">
          {item.title}
        </h1>
        <p className="text-sm text-ink-sub">
          {t("publishedAt")} · {publishedDate}
        </p>
      </header>

      {/* 본문: 흰색 플랫 카드 + 마크다운 렌더링 */}
      <article className="rounded-2xl border border-stone bg-canvas-white p-6">
        <Markdown>{item.content}</Markdown>
      </article>
    </div>
  );
}
