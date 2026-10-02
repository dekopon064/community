"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { loginUrl } from "@/app/lib/auth/urls";
import { ArrowRight, CircleAlert } from "lucide-react";
import { formatApplicationDeadline, todayKst } from "@/app/lib/applicationDeadlineDisplay";
import styles from "./AuthSurfaces.module.css";
type Item = { id: string; availability: string; information: { slug: string; title: string; category: string; applicationDeadlineKind: string | null; applicationDeadlineOn: string | null } | null };
export default function SavedList({ locale }: { locale: "ko" | "ja" }) {
  const t = useTranslations("Saved"), generation = useRef(0);
  const [items, setItems] = useState<Item[]>([]), [error, setError] = useState<string | null>(null), [busy, setBusy] = useState(true), [more, setMore] = useState(false), [message, setMessage] = useState<string | null>(null);
  const [failedRemoval, setFailedRemoval] = useState<string | null>(null);
  const nav = useTranslations("Nav");
  async function load(append = false) {
    const version = ++generation.current; setBusy(true); setError(null); setFailedRemoval(null);
    try {
      const response = await fetch(`/api/saved/list?locale=${locale}&offset=${append ? items.length : 0}`, { cache: "no-store" }); const data = await response.json();
      if (version !== generation.current) return;
      if (!response.ok) { setError(response.status === 401 ? "authentication_required" : "list_failed"); setItems([]); return; }
      if (!Array.isArray(data.items)) { setError("list_failed"); setItems([]); return; }
      setItems(p => append ? [...p, ...data.items] : data.items); setMore(data.hasMore === true);
    } catch { if (version === generation.current) { setError("list_failed"); setItems([]); } } finally { if (version === generation.current) setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => { if (active) void load(); });
    const reset = () => { generation.current++; setItems([]); setMessage(null); void load(); };
    window.addEventListener("pageshow", reset); window.addEventListener("focus", reset); window.addEventListener("machimoa-account-change", reset);
    const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("machimoa-account") : null;
    if (channel) channel.onmessage = reset;
    return () => {
      active = false;
      // This is an async request version counter, not a DOM ref.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      generation.current++;
      channel?.close(); window.removeEventListener("pageshow", reset); window.removeEventListener("focus", reset); window.removeEventListener("machimoa-account-change", reset);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);
  useEffect(() => { if (!message) return; const timer = setTimeout(() => setMessage(null), 3000); return () => clearTimeout(timer); }, [message]);
  async function remove(id: string) {
    const version = ++generation.current; setBusy(true); setError(null); setMessage(null);
    try {
      const response = await fetch("/api/saved/remove", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) }); const data = await response.json();
      if (version !== generation.current) return;
      if (!response.ok || data.saved !== false || data.id !== id) { if (response.status === 401) { setItems([]); setMore(false); } setFailedRemoval(id); setError(response.status === 401 ? "authentication_required" : "request_failed"); return; }
      setFailedRemoval(null);
      setItems(p => p.filter(item => item.id !== id)); setMessage("removed");
    } catch { if (version === generation.current) { setFailedRemoval(id); setError("request_failed"); } } finally { if (version === generation.current) setBusy(false); }
  }
  return <div aria-busy={busy}>
    {message && <p role="status" aria-live="polite" aria-atomic="true" className={`${styles.result} mt-3`}>{t(message)}</p>}
    {error && <div role="alert" className={`${styles.notice} ${styles.error}`}><CircleAlert size={20} aria-hidden="true" /><div><strong>{t(`errors.${error}`)}</strong>{error === "authentication_required" ? <a href={loginUrl(locale, `/${locale}/saved`)} className={styles.link}>{t("login")}</a> : <button disabled={busy} onClick={() => failedRemoval ? void remove(failedRemoval) : void load()} className={styles.link}>{t("retry")}</button>}</div></div>}
    {!error && !items.length && (busy ? <p role="status" className="mt-7 leading-7 text-info-body">{t("processing")}</p> : <div className={styles.empty}><p>{t("empty")}</p><p>{t("emptyMore")}</p><a href={`/${locale}`} className={styles.link}>{t("explore")}<ArrowRight size={18} aria-hidden="true" /></a></div>)}
    <ul className={styles.savedList}>{items.map(item => {
      const information = item.availability === "available" ? item.information : null;
      const deadline = information && formatApplicationDeadline({ kind: information.applicationDeadlineKind, on: information.applicationDeadlineOn, todayKst: todayKst(), locale });
      return <li key={item.id} className={styles.savedRow}><div className="min-w-0">{information ? <><a href={`/${locale}/info/${encodeURIComponent(information.slug)}`} className={styles.savedOpen}>{["policy", "program"].includes(information.category) && <span className={styles.category}>{nav(information.category)}</span>}<span className={styles.savedTitle}>{information.title}</span></a>{deadline && <p className={styles.meta}>{deadline}</p>}</> : <p className={styles.unavailable}>{t("unavailable")}</p>}</div><button disabled={busy} onClick={() => void remove(item.id)} className={styles.remove} aria-label={`${t("remove")}: ${information?.title ?? t("unavailable")}`}>{t("remove")}</button></li>;
    })}</ul>
    {!error && more && <button disabled={busy} onClick={() => void load(true)} className={`${styles.link} mt-4`}>{t("more")}</button>}
  </div>;
}
