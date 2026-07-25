"use client";

import { useTransition } from "react";
import { useLocale } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";

const LABELS: Record<string, string> = {
  ko: "KOR",
  ja: "日本語",
};

export default function LocaleSwitcher() {
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const nextLocale = locale === "ko" ? "ja" : "ko";

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
      aria-label="언어 전환"
      className="absolute right-4 rounded-md border border-stone bg-transparent px-2.5 py-1 text-xs font-medium text-ink-sub transition-colors hover:bg-canvas disabled:opacity-50"
    >
      {LABELS[locale] ?? locale.toUpperCase()}
    </button>
  );
}
