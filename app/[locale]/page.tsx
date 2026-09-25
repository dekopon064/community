import { getTranslations, setRequestLocale } from "next-intl/server";
import HomeAtlasBackdrop from "@/app/components/HomeAtlasBackdrop";
import HomeCurationEntry from "@/app/components/HomeCurationEntry";
import HomeMailbox from "@/app/components/HomeMailbox";
import { todayKst } from "@/app/lib/applicationDeadlineDisplay";
import { fetchLocalizedCurations } from "@/app/lib/curations";

// 공개 상태 변경은 다음 요청부터 바로 반영한다.
export const dynamic = "force-dynamic";

function asStringList(value: unknown): readonly string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export default async function Home({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Home");
  const categoriesT = await getTranslations("Categories");
  const headlineParts = asStringList(t.raw("headlineParts"));

  const curations = await fetchLocalizedCurations(locale);
  const today = todayKst();
  const [primary, secondary] = curations;
  const isJapanese = locale === "ja";

  return (
    <div className="relative isolate min-h-[calc(100dvh-4.25rem)] overflow-hidden bg-canvas lg:min-h-[calc(100dvh-4.5rem)]">
      <HomeAtlasBackdrop />
      <div className="relative mx-auto max-w-xl px-4 pb-24 pt-[49px] sm:px-8 lg:max-w-7xl lg:grid lg:grid-cols-[minmax(13.5rem,0.82fr)_minmax(0,1.18fr)_18.5rem] lg:items-start lg:gap-x-8 lg:px-8 lg:pb-16 lg:pt-[51px]">
        <section className="relative lg:pt-[69px]">
          <h1
            aria-label={headlineParts.length > 1 ? t("headline") : undefined}
            className={isJapanese
              ? "max-w-[20ch] text-[clamp(1.625rem,7.4vw,2rem)] font-bold leading-[1.2] tracking-[-0.045em] text-ink md:text-[clamp(2rem,5vw,2.45rem)] lg:max-w-none lg:text-[2.625rem]"
              : "max-w-[15ch] text-[1.875rem] font-bold leading-[1.25] tracking-[-0.055em] text-ink [text-wrap:balance] md:text-4xl lg:max-w-[13ch] lg:text-[2.625rem] lg:leading-[1.2]"}
          >
            {headlineParts.length > 1 ? (
              <span aria-hidden="true">
                <span className="block whitespace-nowrap">
                  {headlineParts[0]}
                </span>
                {isJapanese ? (
                  headlineParts.slice(1).map((part) => (
                    <span key={part} className="block whitespace-nowrap">
                      {part}
                    </span>
                  ))
                ) : (
                  <span className="flex flex-wrap gap-x-[0.28em]">
                    {headlineParts.slice(1).map((part) => (
                      <span key={part} className="whitespace-nowrap">
                        {part}
                      </span>
                    ))}
                  </span>
                )}
              </span>
            ) : (
              t("headline")
            )}
          </h1>
          <p className="mt-5 max-w-sm text-base leading-7 text-ink-sub md:text-lg">
            {t("intro")}
          </p>
        </section>

        <section aria-label={t("sectionTitle")} className="mt-[33px] space-y-[18px] lg:mt-0 lg:space-y-8">
          {primary ? (
            <HomeCurationEntry
              slug={primary.slug}
              category={primary.userCategory}
              categoryLabel={primary.userCategory ? categoriesT(primary.userCategory) : null}
              title={primary.title}
              summary={primary.summary}
              locale={locale}
              deadlineKind={primary.application_deadline_kind}
              deadlineOn={primary.application_deadline_on}
              eventStartOn={primary.event_start_on}
              eventEndOn={primary.event_end_on}
              todayKst={today}
            />
          ) : (
            <p className="border-b border-stone pb-5 text-sm leading-6 text-ink-sub lg:mt-[72px]">
              {t("empty")}
            </p>
          )}
          {secondary && (
            <HomeCurationEntry
              slug={secondary.slug}
              category={secondary.userCategory}
              categoryLabel={secondary.userCategory ? categoriesT(secondary.userCategory) : null}
              title={secondary.title}
              summary={secondary.summary}
              locale={locale}
              deadlineKind={secondary.application_deadline_kind}
              deadlineOn={secondary.application_deadline_on}
              eventStartOn={secondary.event_start_on}
              eventEndOn={secondary.event_end_on}
              todayKst={today}
            />
          )}
        </section>

        <aside className="relative hidden min-w-0 pl-5 lg:block lg:pt-[82px]">
          <HomeMailbox />
        </aside>
      </div>
    </div>
  );
}
