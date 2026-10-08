"use client";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import styles from "./AuthSurfaces.module.css";

export default function SavedCount({ id, refreshKey }: { id: string; refreshKey: number }) {
  const t = useTranslations("Saved");
  const [count, setCount] = useState<number | null>(null);
  const [failed, setFailed] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;
    async function load() {
      controller?.abort();
      const request = new AbortController(); controller = request;
      setCount(null); setFailed(false);
      try {
        const response = await fetch(`/api/saved-count?id=${id}`, { cache: "no-store", signal: request.signal });
        const data = await response.json();
        if (!active || request.signal.aborted) return;
        if (!response.ok || data.id !== id.toLowerCase() || !Number.isSafeInteger(data.savedCount) || data.savedCount < 0) { setFailed(true); return; }
        setCount(data.savedCount);
      } catch { if (active && !request.signal.aborted) setFailed(true); }
    }
    const refresh = () => { void load(); };
    const show = (event: PageTransitionEvent) => { if (event.persisted) refresh(); };
    void Promise.resolve().then(() => { if (active) refresh(); });
    window.addEventListener("focus", refresh); window.addEventListener("pageshow", show);
    return () => { active = false; controller?.abort(); window.removeEventListener("focus", refresh); window.removeEventListener("pageshow", show); };
  }, [id, refreshKey, retry]);
  return <div className={styles.saveCount}>
    <span role="status" aria-live="polite">{count !== null ? t("count", { count }) : t(failed ? "countUnavailable" : "countLoading")}</span>
    {failed && <button type="button" className={styles.countRetry} onClick={() => setRetry(value => value + 1)}>{t("countRetry")}</button>}
  </div>;
}
