"use client";
import { useEffect, useState, useRef } from "react";
import styles from "./AuthSurfaces.module.css";
import { UserRound, Bookmark, LogOut, ChevronDown } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname } from "@/i18n/navigation";
import { authLocale, loginUrl, safeReturnTo } from "@/app/lib/auth/urls";
export default function AccountControl() {
  const locale = authLocale(useLocale()), pathname = usePathname(), t = useTranslations("Auth"), savedT = useTranslations("Saved");
  const [status, setStatus] = useState<string | null>(null), [name, setName] = useState<string | null>(null), [open, setOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false), [logoutError, setLogoutError] = useState(false);
  const container = useRef<HTMLDivElement>(null), identity = useRef<string | null>(null);
  useEffect(() => {
    let active = true, version = 0;
    const controller = new AbortController();
    async function check() {
      const current = ++version;
      try {
        const response = await fetch("/api/auth/session", { cache: "no-store", signal: controller.signal }); const data = await response.json();
        if (!active || current !== version) return;
        setStatus(previous => previous === "expired" && data.status === "signed_out" ? previous : ["signed_in", "signed_out", "expired", "unavailable"].includes(data.status) ? data.status : "unavailable");
        setName(data.status === "signed_in" && typeof data.displayName === "string" ? data.displayName : null);
        const key = data.status === "signed_in" ? data.accountId : data.status;
        if (identity.current !== null && identity.current !== key) window.dispatchEvent(new Event("machimoa-account-change"));
        identity.current = key;
      } catch { if (active) { setStatus("unavailable"); setName(null); } }
    }
    void check();
    const show = () => { setOpen(false); void check(); };
    window.addEventListener("focus", show); window.addEventListener("pageshow", show);
    const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("machimoa-account") : null;
    if (channel) channel.onmessage = show;
    return () => { active = false; controller.abort(); channel?.close(); window.removeEventListener("focus", show); window.removeEventListener("pageshow", show); };
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => { if (!container.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); container.current?.querySelector("button")?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  const next = safeReturnTo(`/${locale}${pathname === "/" ? "" : pathname}`, locale);
  const classes = styles.account;
  if (status !== "signed_in") return <a className={classes} href={loginUrl(locale, next, status === "expired" ? "expired" : undefined)} title={status === "unavailable" ? t("notices.unavailable") : undefined} onClick={e => { e.currentTarget.href = loginUrl(locale, safeReturnTo(window.location.pathname + window.location.search, locale), status === "expired" ? "expired" : status === "unavailable" ? "unavailable" : undefined); }}><UserRound size={20} aria-hidden="true" className="hidden sm:block" /><span>{t("login")}</span></a>;
  return <div className="relative" ref={container} onBlur={event => { if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false); }}>
    <button type="button" className={classes} aria-expanded={open} aria-controls="account-actions" onClick={() => setOpen(!open)} title={name ?? t("account")}><UserRound size={20} aria-hidden="true" className="hidden sm:block" /><span className={styles.accountName}>{name ?? t("account")}</span><ChevronDown size={14} aria-hidden="true" /></button>
    {open && <div id="account-actions" className={styles.menu}>
      <a href={`/${locale}/saved`} className={styles.menuAction}><Bookmark size={20} aria-hidden="true" />{savedT("title")}</a>
      <form action="/api/auth/logout" method="post" onSubmit={async event => {
        event.preventDefault(); if (logoutBusy) return;
        const body = new URLSearchParams({ locale, next }); setLogoutBusy(true); setLogoutError(false);
        try {
          const response = await fetch("/api/auth/logout", { method: "POST", body, cache: "no-store" });
          const target = new URL(response.url);
          if (target.origin !== window.location.origin || !response.ok) { setLogoutError(true); return; }
          if (target.searchParams.get("notice") === "signed_out") {
            setName(null); setStatus("signed_out"); window.dispatchEvent(new Event("machimoa-account-change"));
            if (typeof BroadcastChannel !== "undefined") { const channel = new BroadcastChannel("machimoa-account"); channel.postMessage("logout-confirmed"); channel.close(); }
          }
          window.location.assign(target.href);
        } catch { setLogoutError(true); } finally { setLogoutBusy(false); }
      }}><input type="hidden" name="locale" value={locale} /><input type="hidden" name="next" value={next} /><button type="submit" disabled={logoutBusy} className={styles.menuAction}><LogOut size={20} aria-hidden="true" />{t(logoutBusy ? "loggingOut" : "logoutShort")}</button>{logoutError && <p role="alert" className="px-3 text-info-status">{t("notices.logout_failed")}</p>}</form>
    </div>}
  </div>;
}
