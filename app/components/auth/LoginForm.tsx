"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { AuthLocale } from "@/app/lib/auth/urls";
import { providerErrorNotice } from "@/app/lib/auth/urls";

export default function LoginForm({ locale, next, ready }: { locale: AuthLocale; next: string; ready: boolean }) {
  const t = useTranslations("Auth");
  const [pending, setPending] = useState(false);
  useEffect(() => {
    const notice = providerErrorNotice(window.location.hash);
    if (notice) {
      const url = new URL(window.location.href);
      url.hash = "";
      url.searchParams.set("notice", notice);
      window.location.replace(url.pathname + url.search);
      return;
    }
    const reset = () => setPending(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);
  return (
    <form action="/api/auth/start" method="post" onSubmit={() => setPending(true)} className="mt-8">
      <input type="hidden" name="locale" value={locale} />
      <input type="hidden" name="next" value={next} />
      <button type="submit" disabled={!ready || pending} className="inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-ink px-6 py-3 font-semibold text-canvas-white transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50">
        {pending ? t("connecting") : t("googleLogin")}
      </button>
      <p className="mt-3 text-sm leading-6 text-info-muted" role="status">{pending ? t("connectingHint") : t("googleHint")}</p>
    </form>
  );
}
