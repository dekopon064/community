import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import { createAuthClient } from "@/app/lib/auth/server";
import { publicAuthConfig } from "@/app/lib/auth/config";
import { authLocale, safeReturnTo } from "@/app/lib/auth/urls";
import { routing } from "@/i18n/routing";
import LoginForm from "@/app/components/auth/LoginForm";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };

const notices = ["cancelled", "failed", "expired", "unavailable", "signed_out", "logout_failed"] as const;

export default async function LoginPage({ params, searchParams }: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ next?: string; notice?: string }>;
}) {
  const { locale: requestedLocale } = await params;
  if (!hasLocale(routing.locales, requestedLocale)) notFound();
  const locale = authLocale(requestedLocale);
  const query = await searchParams;
  const next = safeReturnTo(query.next, locale);
  const browseNext = /^\/(ko|ja)\/admin(?:[/?#]|$)/.test(next) ? `/${locale}` : next;
  const t = await getTranslations({ locale, namespace: "Auth" });
  const store = await cookies();
  const hadSession = store.getAll().some(({ name }) => /^sb-.+-auth-token(?:\.\d+)?$/.test(name)) || store.has("machimoa-auth-expired");
  // No refresh here: Proxy owns cookie writes on page requests.
  let signedIn = false;
  let unavailable = !publicAuthConfig();
  if (hadSession && !unavailable) {
    try {
      const client = await createAuthClient({ readOnly: true });
      const result = await client!.auth.getClaims();
      signedIn = !!result.data?.claims.sub && !result.error;
      unavailable = !!result.error && (result.error.status ?? 0) >= 500;
    } catch { unavailable = true; }
  }
  const suppliedNotice = notices.find((value) => value === query.notice);
  const notice = signedIn ? (suppliedNotice === "logout_failed" ? suppliedNotice : undefined) :
    unavailable ? "unavailable" : suppliedNotice || (hadSession ? "expired" : undefined);
  return (
    <section className="mx-auto max-w-xl px-5 py-12 sm:py-20">
      <h1 className="text-3xl font-bold tracking-tight text-primary-text">{signedIn ? t("signedInTitle") : t("title")}</h1>
      <p className="mt-4 max-w-prose leading-7 text-info-body">{signedIn ? t("signedInDescription") : t("description")}</p>
      {notice && <p role={notice === "signed_out" ? "status" : "alert"} className="mt-6 border-y border-info-rule py-4 leading-7 text-info-status">{t(`notices.${notice}`)}</p>}
      {signedIn ? (
        <div className="mt-8 border-t border-info-rule pt-6">
          <a href={next} className="inline-flex min-h-12 items-center rounded-xl bg-ink px-6 py-3 font-semibold text-canvas-white hover:opacity-85">{t("continue")}</a>
          <form action="/api/auth/logout" method="post" className="mt-4">
            <input type="hidden" name="locale" value={locale} />
            <input type="hidden" name="next" value={next} />
            <button type="submit" className="min-h-11 py-2 text-ink underline underline-offset-4">{t("logout")}</button>
          </form>
        </div>
      ) : <LoginForm locale={locale} next={next} ready={!unavailable} />}
      {!signedIn && <a href={browseNext} className="mt-6 inline-flex min-h-11 items-center text-ink underline underline-offset-4">{t("browse")}</a>}
    </section>
  );
}
