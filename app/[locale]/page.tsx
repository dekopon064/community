import { getTranslations, setRequestLocale } from "next-intl/server";
import HomeCurationEntry from "@/app/components/HomeCurationEntry";
import SignalRibbon from "@/app/components/SignalRibbon";
import { fetchLocalizedCurations } from "@/app/lib/curations";

// 새 글 등록 시 최대 60초 안에 대표 카드를 최신화 (ISR)
export const revalidate = 60;

function formatPublishedDate(value: string, locale: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export default async function Home({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Home");

  const curations = await fetchLocalizedCurations(locale);
  const [primary, secondary] = curations;
  const primaryPublishedAt = primary
    ? formatPublishedDate(primary.created_at, locale)
    : null;
  const publicationCopy = locale === "ja"
    ? { label: "公開日", rail: "最近公開" }
    : { label: "공개일", rail: "최근 공개" };
  const isJapanese = locale === "ja";

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-canvas">
      <div className="mx-auto grid max-w-7xl gap-10 px-5 py-10 md:gap-12 md:px-8 md:pt-16 lg:min-h-[calc(100vh-4.5rem)] lg:grid-cols-[minmax(16rem,0.9fr)_minmax(24rem,1.25fr)_minmax(10rem,0.48fr)] lg:items-start lg:pt-36 lg:px-10">
        <section className="relative overflow-hidden py-2 md:py-12">
          <h1
            className={isJapanese
              ? "max-w-full text-[clamp(1.75rem,8.2vw,2rem)] font-bold leading-[1.2] tracking-[-0.045em] text-ink sm:max-w-[18ch] md:text-[2.65rem] lg:text-[3.45rem]"
              : "max-w-[15ch] text-4xl font-bold leading-[1.12] tracking-[-0.055em] text-ink md:text-5xl lg:text-[3.45rem]"}
          >
            {t("headline")}
          </h1>
          <p className="mt-5 max-w-sm text-base leading-7 text-ink-sub md:text-lg">
            {t("intro")}
          </p>
          <SignalRibbon className="mt-8 ml-auto block h-9 w-48 text-sky/70 md:mt-10 md:w-52" />
        </section>

        <section aria-label={t("sectionTitle")} className="space-y-3 md:space-y-4">
          {primary ? (
            <HomeCurationEntry
              slug={primary.slug}
              category={primary.category}
              title={primary.title}
              summary={primary.summary}
              publishedAt={primary.created_at}
              publishedLabel={publicationCopy.label}
              locale={locale}
              primary
            />
          ) : (
            <p className="border-b border-stone pb-5 text-sm leading-6 text-ink-sub">
              {t("empty")}
            </p>
          )}
          {secondary && (
            <HomeCurationEntry
              slug={secondary.slug}
              category={secondary.category}
              title={secondary.title}
              summary={secondary.summary}
              publishedAt={secondary.created_at}
              publishedLabel={publicationCopy.label}
              locale={locale}
            />
          )}
        </section>

        {primary && primaryPublishedAt && (
          <aside className="hidden border-l border-stone pl-5 lg:block lg:py-8">
            <p className="text-sm font-bold tracking-[-0.02em] text-ink">{publicationCopy.rail}</p>
            <p className="mt-5 text-base font-bold text-ink">{primary.title}</p>
            <p className="mt-2 text-sm tabular-nums text-ink-sub">
              {publicationCopy.label} · {primaryPublishedAt}
            </p>
          </aside>
        )}
      </div>
    </div>
  );
}
