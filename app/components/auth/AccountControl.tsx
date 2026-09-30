"use client";

import { useEffect, useState } from "react";
import { UserRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname } from "@/i18n/navigation";
import { authLocale, loginUrl, safeReturnTo } from "@/app/lib/auth/urls";

type LoginState = "signed_in" | "signed_out" | "expired" | "unavailable";

export default function AccountControl() {
  const locale = authLocale(useLocale());
  const pathname = usePathname();
  const t = useTranslations("Auth");
  const [status, setStatus] = useState<LoginState | null>(null);

  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    async function check() {
      try {
        const response = await fetch("/api/auth/session", { cache: "no-store", signal: controller.signal });
        const data = await response.json();
        if (current) setStatus((previous) => previous === "expired" && data.status === "signed_out" ? previous :
          ["signed_in", "signed_out", "expired", "unavailable"].includes(data.status) ? data.status : "unavailable");
      } catch {
        if (current) setStatus("unavailable");
      }
    }
    void check();
    window.addEventListener("focus", check);
    return () => { current = false; controller.abort(); window.removeEventListener("focus", check); };
  }, [pathname]);

  const next = safeReturnTo(`/${locale}${pathname === "/" ? "" : pathname}`, locale);
  const href = loginUrl(locale, next, status === "expired" ? "expired" : undefined);
  return (
    <a href={href} onClick={(event) => {
      const location = window.location;
      event.currentTarget.href = loginUrl(locale, safeReturnTo(location.pathname + location.search + location.hash, locale), status === "expired" ? "expired" : undefined);
    }} title={status === "expired" ? t("notices.expired") : undefined} aria-label={status === "signed_in" ? t("account") : status === "expired" ? t("notices.expired") : t("login")} className="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-full px-2 text-ink hover:bg-mineral">
      <UserRound size={20} aria-hidden="true" />
      <span className="hidden text-sm font-semibold xl:inline">{status === "signed_in" ? t("account") : t("login")}</span>
    </a>
  );
}
