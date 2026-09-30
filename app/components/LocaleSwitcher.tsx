"use client";

import { useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";
import { loginUrl, safeReturnTo } from "@/app/lib/auth/urls";

const LOCALES = ["ko", "ja"] as const;

export default function LocaleSwitcher() {
  const locale = useLocale();
  const t = useTranslations("LocaleSwitcher");
  const pathname = usePathname();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function selectLocale(nextLocale: (typeof LOCALES)[number]) {
    if (nextLocale === locale || isPending) return;

    let destination = pathname;
    if (pathname === "/login") {
      const query = new URLSearchParams(window.location.search);
      const notice = query.get("notice") || undefined;
      const allowedNotice = ["cancelled", "failed", "expired", "unavailable", "signed_out", "logout_failed"].includes(notice || "") ? notice : undefined;
      destination = loginUrl(nextLocale, safeReturnTo(query.get("next"), nextLocale), allowedNotice).slice(3);
    }
    startTransition(() => {
      router.replace(destination, { locale: nextLocale });
    });
  }

  return (
    <div
      role="group"
      aria-label={t("label")}
      className="locale-switcher inline-flex h-11 items-center rounded-full bg-canvas-white"
    >
      {LOCALES.map((option) => {
        const isActive = locale === option;
        const language = t(option);

        return (
          <button
            key={option}
            type="button"
            onClick={() => selectLocale(option)}
            disabled={isPending}
            aria-pressed={isActive}
            aria-label={isActive ? t("current", { language }) : t("switch", { language })}
            className="grid h-11 w-11 min-w-11 place-items-center rounded-full bg-transparent text-xs font-semibold disabled:opacity-50 sm:w-auto sm:px-1"
          >
            <span
              className={`grid h-9 min-w-9 place-items-center rounded-full px-0 transition-colors sm:px-2 ${
                isActive
                  ? "bg-ink text-canvas-white"
                  : "text-ink-sub hover:bg-mineral hover:text-ink"
              }`}
            >
              {language}
            </span>
          </button>
        );
      })}
    </div>
  );
}
