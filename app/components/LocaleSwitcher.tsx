"use client";

import { useTransition } from "react";
import { useLocale } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";

const TARGET_LANGUAGE: Record<string, { label: string; ariaLabel: string }> = {
  ko: { label: "日本語", ariaLabel: "일본어로 전환" },
  ja: { label: "한국어", ariaLabel: "韓国語に切り替える" },
};

export default function LocaleSwitcher() {
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const nextLocale = locale === "ko" ? "ja" : "ko";
  const targetLanguage = TARGET_LANGUAGE[locale] ?? {
    label: nextLocale.toUpperCase(),
    ariaLabel: `Switch to ${nextLocale.toUpperCase()}`,
  };

  function toggle() {
    startTransition(() => {
      router.replace(pathname, { locale: nextLocale });
    });
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={isPending}
      aria-label={targetLanguage.ariaLabel}
      className="min-h-11 min-w-11 rounded-full border border-stone bg-canvas-white px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:border-sky hover:bg-mineral disabled:opacity-50"
    >
      {targetLanguage.label}
    </button>
  );
}
