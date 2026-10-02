"use client";
import { useEffect, useRef, useState } from "react";
import styles from "./AuthSurfaces.module.css";
import { Bookmark } from "lucide-react";
import { useTranslations } from "next-intl";
import { isUuid } from "@/app/lib/saved/intent";
export default function SaveControl({ id, slug, locale }: { id: string; slug: string; locale: string }) {
  const t = useTranslations("Saved");
  const [saved, setSaved] = useState(false), [busy, setBusy] = useState(true), [error, setError] = useState<string | null>(null), [message, setMessage] = useState<string | null>(null);
  const generation = useRef(0), working = useRef(false), revision = useRef<string | null>(null), retryAction = useRef("request");
  useEffect(() => { if (!message) return; const timer = setTimeout(() => setMessage(null), 3000); return () => clearTimeout(timer); }, [message]);
  async function refresh() {
    if (working.current) return;
    const version = ++generation.current;
    setSaved(false); revision.current = null; setMessage(null); setBusy(true);
    try {
      const response = await fetch(`/api/saved/state?id=${id}`, { cache: "no-store" }); const data = await response.json();
      if (version !== generation.current) return;
      if (response.status === 401) { setSaved(false); setError(null); return; }
      if (!response.ok || (typeof data.saved !== "boolean" || typeof data.version !== "string")) { setError("state_failed"); return; }
      setSaved(data.saved); revision.current = data.version; setError(null);
    } catch { if (version === generation.current) setError("state_failed"); }
    finally { if (version === generation.current) setBusy(false); }
  }
  async function mutate(action: string, token?: string) {
    if (working.current) return;
    working.current = true; retryAction.current = action === "remove" ? "remove" : "request"; const version = ++generation.current;
    setBusy(true); setError(null); setMessage(null);
    try {
      // Only obtain an initial version for a new deliberate action, never retry
      // a stale in-flight request automatically after its version was rejected.
      if ((action === "request" || action === "save") && revision.current === null) {
        const state = await fetch(`/api/saved/state?id=${id}`, { cache: "no-store" });
        const current = await state.json();
        if (version !== generation.current) return;
        if (state.ok && typeof current.version === "string") revision.current = current.version;
        else if (state.status !== 401) { setError("state_failed"); return; }
      }
      const response = await fetch(`/api/saved/${action}`, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, slug, locale, ...(token ? { token } : {}), ...(revision.current !== null ? { version: revision.current } : {}) }) }); const data = await response.json();
      if (version !== generation.current) return;
      if (data.loginUrl) { window.location.assign(data.loginUrl); return; }
      if (!response.ok) {
        if (data.error === "state_changed") {
          revision.current = typeof data.version === "string" ? data.version : null;
          if (typeof data.saved === "boolean") setSaved(data.saved);
        }
        setError(action === "resume" && response.status >= 500 ? "save_after_login_failed" : data.error ?? "request_failed"); return; }
      if (typeof data.saved !== "boolean" || data.id !== id) { setError("request_failed"); return; }
      revision.current = typeof data.version === "string" ? data.version : null; setSaved(data.saved); setMessage(data.saved ? "saved" : "removed");
    } catch { if (version === generation.current) setError(action === "resume" ? "save_after_login_failed" : "request_failed"); }
    finally { if (version === generation.current) { working.current = false; setBusy(false); } }
  }
  useEffect(() => {
    let active = true;
    // Start after subscribing, and cancel the first Strict Mode setup cleanly.
    void Promise.resolve().then(async () => {
      if (!active) return;
      const url = new URL(window.location.href), token = url.searchParams.get("saveIntent"), result = url.searchParams.get("saveResult");
      if (result || token) { url.searchParams.delete("saveResult"); url.searchParams.delete("saveIntent"); window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash); }
      if (token && isUuid(token)) await mutate("resume", token);
      else { await refresh(); if (active && (result === "intent_expired" || result === "save_after_login_failed")) setError(result); }
    });
    const reset = () => { working.current = false; generation.current++; setError(null); void refresh(); };
    const show = (event: PageTransitionEvent) => { if (event.persisted) reset(); };
    window.addEventListener("focus", refresh); window.addEventListener("pageshow", show); window.addEventListener("machimoa-account-change", reset);
    const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("machimoa-account") : null;
    if (channel) channel.onmessage = reset;
    return () => { active = false; channel?.close(); window.removeEventListener("focus", refresh); window.removeEventListener("pageshow", show); window.removeEventListener("machimoa-account-change", reset); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  const errorKey = error && ["authentication_required", "information_unavailable", "intent_expired", "save_after_login_failed", "state_failed", "unavailable", "state_changed"].includes(error) ? error : "request_failed";
  return <div className={styles.save} aria-busy={busy}>
    <button type="button" disabled={busy || error === "state_failed"} aria-pressed={saved} aria-label={busy ? t("processing") : t(saved ? "remove" : "save")} onClick={() => void mutate(saved ? "remove" : "request")} className={styles.saveButton}><Bookmark size={18} fill={saved ? "currentColor" : "none"} aria-hidden="true" />{busy ? t("processing") : t(saved ? "isSaved" : "save")}</button>
    {message && <p role="status" aria-live="polite" aria-atomic="true" className={styles.result}>{t(message)}</p>}
    {error && <div role="alert" className={styles.saveError}><p>{t(`errors.${errorKey}`)}</p><button type="button" disabled={busy} onClick={() => error === "state_failed" ? void refresh() : void mutate(retryAction.current)} className="min-h-11 font-semibold text-ink underline underline-offset-4">{t("retry")}</button></div>}
  </div>;
}
