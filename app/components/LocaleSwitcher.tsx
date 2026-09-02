"use client";

import { useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";

const LOCALES = ["ko", "ja"] as const;

export default function LocaleSwitcher() {
  const locale = useLocale();
  const t = useTranslations("LocaleSwitcher");
  const pathname = usePathname();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function selectLocale(nextLocale: (typeof LOCALES)[number]) {
    if (nextLocale === locale || isPending) return;

    startTransition(() => {
      router.replace(pathname, { locale: nextLocale });
    });
  }

  return (
    <div
      role="group"
      aria-label={t("label")}
      className="inline-flex min-h-11 rounded-full border border-stone bg-canvas-white p-1"
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
            className={`min-h-11 min-w-11 rounded-full px-3 text-xs font-semibold transition-colors disabled:opacity-50 ${
              isActive
                ? "bg-ink text-canvas-white"
                : "text-ink-sub hover:bg-mineral hover:text-ink"
            }`}
          >
            {language}
          </button>
        );
      })}
    </div>
  );
}
