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
            className="grid h-11 min-w-11 place-items-center rounded-full bg-transparent px-1 text-xs font-semibold disabled:opacity-50"
          >
            <span
              className={`grid h-9 min-w-9 place-items-center rounded-full px-2 transition-colors ${
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
