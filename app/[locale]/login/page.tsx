import { ArrowRight, CircleAlert, Info } from "lucide-react";
import styles from "@/app/components/auth/AuthSurfaces.module.css";
import { fetchLocalizedCurationBySlug } from "@/app/lib/curations";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import { createAuthClient } from "@/app/lib/auth/server";
import { kakaoLoginEnabled, publicAuthConfig } from "@/app/lib/auth/config";
import { authLocale, safeReturnTo, publicBrowseReturnTo } from "@/app/lib/auth/urls";
import { routing } from "@/i18n/routing";
import LoginForm from "@/app/components/auth/LoginForm";
import { readIntent, INTENT_COOKIE, matchesIntent } from "@/app/lib/saved/intent";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };

const notices = ["cancelled", "failed", "expired", "unavailable", "signed_out", "logout_failed"] as const;

export default async function LoginPage({ params, searchParams }: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ next?: string; notice?: string; saveIntent?: string }>;
}) {
  const { locale: requestedLocale } = await params;
  if (!hasLocale(routing.locales, requestedLocale)) notFound();
  const locale = authLocale(requestedLocale);
  const query = await searchParams;
  const next = safeReturnTo(query.next, locale);
  const browseNext = publicBrowseReturnTo(next, locale);
  const t = await getTranslations({ locale, namespace: "Auth" });
  const kakaoEnabled = kakaoLoginEnabled();
  const store = await cookies();
  const pendingIntent = readIntent(store.get(INTENT_COOKIE)?.value);
  const saveIntent = pendingIntent?.phase === "pending" && matchesIntent(pendingIntent, query.saveIntent, next) ? pendingIntent.token : undefined;
  const savedT = await getTranslations({ locale, namespace: "Saved" });
  // Use the existing public-only read; cookie titles never become display authority.
  let saveTitle: string | null = null;
  if (saveIntent && pendingIntent) {
    try {
      const item = await fetchLocalizedCurationBySlug(pendingIntent.slug, locale);
      if (item?.id === pendingIntent.id && (item.userCategory === "policy" || item.userCategory === "program")) saveTitle = item.title;
    } catch { /* Context is optional; login remains available during a public read failure. */ }
  }
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
  const errorNotice = notice && ["failed", "unavailable", "logout_failed"].includes(notice);
  return (
    <section className={styles.login}>
      <h1 className={styles.heading}>{signedIn ? t("signedInTitle") : t("title")}</h1>
      <p className={styles.lead}>{signedIn ? t("signedInDescription") : saveIntent ? t("savePurpose") : t("benefit")}</p>
      {saveTitle && <div className={styles.context}><p className={styles.contextLabel}>{t("saveContext")}</p><p className={styles.contextTitle}>{saveTitle}</p></div>}
      {notice && <div role={errorNotice ? "alert" : "status"} className={`${styles.notice} ${errorNotice ? styles.error : ""}`}>
        {notice !== "signed_out" && (errorNotice ? <CircleAlert size={20} aria-hidden="true" /> : <Info size={20} aria-hidden="true" />)}
        <div><strong>{t(`noticeTitle.${notice}`)}</strong><p>{t(`noticeBody.${notice === "logout_failed" && !signedIn ? "logout_failed_signed_out" : notice}`)}</p>
          {notice === "unavailable" && <a className={styles.link} href={`/${locale}/login?${new URLSearchParams({ next, ...(saveIntent ? { saveIntent } : {}) })}`}>{t("retry")}</a>}
        </div>
      </div>}
      {signedIn ? (
        <div className="mt-8 border-t border-info-rule pt-6">
          {saveIntent ? <form action="/api/saved/continue" method="post"><input type="hidden" name="token" value={saveIntent} /><input type="hidden" name="id" value={pendingIntent!.id} /><button type="submit" className="inline-flex min-h-12 items-center rounded-xl bg-ink px-6 py-3 font-semibold text-canvas-white hover:opacity-85">{savedT("continueSave")}</button></form> : <a href={next} className="inline-flex min-h-12 items-center rounded-xl bg-ink px-6 py-3 font-semibold text-canvas-white hover:opacity-85">{t("continue")}</a>}
          <form action="/api/auth/logout" method="post" className="mt-4">
            <input type="hidden" name="locale" value={locale} />
            <input type="hidden" name="next" value={next} />
            <button type="submit" className="min-h-11 py-2 text-ink underline underline-offset-4">{t("logout")}</button>
          </form>
        </div>
      ) : <LoginForm locale={locale} next={next} ready={!unavailable} kakaoEnabled={kakaoEnabled} saveIntent={saveIntent} />}
      {!signedIn && <form action="/api/saved/cancel" method="post" className={styles.exit}><input type="hidden" name="locale" value={locale} /><input type="hidden" name="next" value={browseNext} /><button type="submit" className={styles.link}>{t("browse")}<ArrowRight size={18} aria-hidden="true" /></button><p className={styles.publicNote}>{t("publicNote")}</p></form>}
    </section>
  );
}
