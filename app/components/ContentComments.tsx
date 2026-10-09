"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { MessageSquare } from "lucide-react";
import Link from "./PublicNavigationLink";
import { loginUrl } from "../lib/auth/urls";
import { COMMENT_LIMIT, type CommentPage, type CommentCursor, normalizeComment, validComment } from "../lib/comments/contracts";
import styles from "./ContentComments.module.css";

type Submission = { requestId: string; body: string; expectedCode: string };
type Notice = "read_failed" | "unavailable" | "authentication_required" | "forbidden" | "request_conflict" | "rate_limited" | "identity_changed" | "invalid_request" | "uncertain" | "accepted" | "deleted" | "hidden" | "absent" | null;
type Mutation = { outcome?: string; code?: string; state?: string; error?: Notice };
const knownErrors = new Set(["authentication_required", "forbidden", "request_conflict", "rate_limited", "identity_changed", "invalid_request", "information_unavailable"]);

export default function ContentComments({ id, slug, locale }: { id: string; slug: string; locale: string }) {
  const t = useTranslations("Comments"), inputId = useId();
  const authLocale = locale === "ja" ? "ja" : "ko";
  // PublicNavigationLink applies the locale itself; next stays fully qualified.
  const loginHref = loginUrl(authLocale, `/${authLocale}/info/${encodeURIComponent(slug)}#comments`).slice(3);
  const [page, setPage] = useState<CommentPage | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false), [reading, setReading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null), [unavailable, setUnavailable] = useState(false);
  const [pending, setPending] = useState<Submission | null>(null), [mayRetry, setMayRetry] = useState(false);
  const requestSequence = useRef(0), mounted = useRef(true), writing = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null), focusComposer = useRef(false);
  const [removal, setRemoval] = useState<{ id: string; action: "remove" | "hide" } | null>(null);
  const cancelRemoval = useRef<HTMLButtonElement>(null), removalTrigger = useRef<HTMLButtonElement | null>(null);
  const listTitle = useRef<HTMLHeadingElement>(null);
  const code = page?.viewer.code;
  const publicName = code ? t("resident", { code }) : null;
  const count = [...normalizeComment(draft)].length;

  useEffect(() => {
    if (code && !busy && focusComposer.current) {
      focusComposer.current = false;
      input.current?.focus({ preventScroll: true });
    }
  }, [code, busy]);

  useEffect(() => {
    if (removal) cancelRemoval.current?.focus({ preventScroll: true });
  }, [removal]);
  function dismissRemoval() {
    setRemoval(null);
    removalTrigger.current?.focus({ preventScroll: true });
  }

  const load = useCallback(async (cursor?: CommentCursor) => {
    const sequence = ++requestSequence.current;
    setReading(true);
    try {
      const query = new URLSearchParams({ id });
      if (cursor) { query.set("at", cursor.at); query.set("beforeId", cursor.id); }
      const response = await fetch(`/api/comments?${query}`, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) {
        if (response.status === 404 && mounted.current && sequence === requestSequence.current) { setUnavailable(true); setPage(null); }
        throw new Error("read_failed");
      }
      const data = await response.json() as CommentPage;
      if (!mounted.current || sequence !== requestSequence.current) return;
      setUnavailable(false);
      setPage(previous => ({ ...data, items: cursor && previous && previous.viewer.code === data.viewer.code && previous.viewer.signedIn === data.viewer.signedIn ? [...new Map([...previous.items, ...data.items].map(item => [item.id, item])).values()] : data.items }));
      setNotice(previous => previous === "read_failed" ? null : previous);
    } catch { if (mounted.current && sequence === requestSequence.current) setNotice("read_failed"); }
    finally { if (mounted.current && sequence === requestSequence.current) setReading(false); }
  }, [id]);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    const sequence = requestSequence;
    queueMicrotask(() => { if (active) void load(); });
    const refresh = () => { if (!writing.current) void load(); };
    window.addEventListener("focus", refresh);
    return () => { active = false; mounted.current = false; sequence.current++; window.removeEventListener("focus", refresh); };
  }, [load]);

  async function mutate(action: string, fields: Record<string, string>): Promise<Mutation> {
    const response = await fetch("/api/comments", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, action, ...fields }),
    });
    const data = await response.json() as Mutation;
    if (!response.ok && (response.status >= 500 || !knownErrors.has(data.error ?? ""))) throw new Error("uncertain");
    if (response.status === 404) { setUnavailable(true); setPage(null); return { error: "unavailable" }; }
    return data;
  }
  async function prepare() {
    if (writing.current) return;
    writing.current = true; setBusy(true); setNotice(null);
    try {
      const data = await mutate("prepare", {});
      if (data.code) setPage(previous => previous ? { ...previous, viewer: { ...previous.viewer, code: data.code! } } : previous);
      else setNotice(data.error ?? "unavailable");
    } catch { setNotice("unavailable"); }
    finally { writing.current = false; setBusy(false); }
  }
  async function submit(submission?: Submission) {
    if (writing.current || !code || (!submission && !validComment(draft))) return;
    const value = submission ?? { requestId: crypto.randomUUID(), body: normalizeComment(draft), expectedCode: code };
    if (value.expectedCode !== code) { setNotice("identity_changed"); return; }
    writing.current = true; setBusy(true); setNotice(null); setPending(value); setMayRetry(false);
    try {
      const result = await mutate("create", value);
      if (result.outcome === "accepted") { setDraft(""); setPending(null); setNotice("accepted"); await load(); }
      else { setPending(null); setNotice(result.error ?? "uncertain"); if (result.error === "identity_changed" || result.error === "authentication_required") await load(); }
    } catch { setNotice("uncertain"); }
    finally { writing.current = false; setBusy(false); }
  }
  async function resolveSubmission() {
    if (writing.current || !pending) return;
    writing.current = true; setBusy(true); setMayRetry(false);
    try {
      const query = new URLSearchParams({ id, requestId: pending.requestId });
      const response = await fetch(`/api/comments?${query}`, { cache: "no-store", credentials: "same-origin" });
      const result = await response.json() as Mutation;
      if (!response.ok) { setNotice(result.error ?? "uncertain"); return; }
      if (result.outcome === "accepted") { setPending(null); setDraft(""); setNotice("accepted"); await load(); }
      else if (result.outcome === "absent") { setMayRetry(true); setNotice("absent"); await load(); }
      else setNotice("uncertain");
    } catch { setNotice("uncertain"); }
    finally { writing.current = false; setBusy(false); }
  }
  async function remove(commentId: string, action: "remove" | "hide") {
    if (writing.current) return;
    writing.current = true; setBusy(true); setNotice(null);
    try {
      const result = await mutate(action, { commentId });
      setNotice(result.outcome === "deleted" ? "deleted" : result.outcome === "hidden" ? "hidden" : result.error ?? "uncertain");
      await load();
    } catch { setNotice("uncertain"); }
    finally { writing.current = false; setBusy(false); }
  }
  const error = notice && !["accepted", "deleted", "hidden", "absent"].includes(notice);
  const preservedDraft = draft ? <div className={styles.preservedDraft}>
    <label htmlFor={inputId} className={styles.srOnly}>{t("bodyLabel")}</label>
    <textarea id={inputId} value={draft} readOnly rows={2} aria-describedby={`${inputId}-preserved`} />
    <p id={`${inputId}-preserved`} className={styles.subtle}>{t("preservedDraft")}</p>
  </div> : null;
  return (
    <section id="comments" aria-labelledby={`${inputId}-title`} className={styles.section}>
      <h2 ref={listTitle} tabIndex={-1} id={`${inputId}-title`} className={styles.title}>
        <MessageSquare size={18} strokeWidth={1.8} aria-hidden="true" />{t("title")}
      </h2>
      {unavailable ? <>
        <p role="status" className={styles.notice}>{t("unavailable")}</p>
        {draft && <div className={styles.composer}>{preservedDraft}</div>}
      </> : <>
        {notice === "read_failed" && <p role="alert" className={`${styles.notice} ${styles.error}`}>{t("read_failed")}</p>}
        {reading && <p role="status" className={styles.loading}>{t("loading")}</p>}
        {page && page.items.length === 0 && !reading && notice !== "read_failed" && <p className={styles.empty}>{t("empty")}</p>}
        <ul className={styles.list} aria-label={t("listTitle")}>
          {page?.items.map(item => <li key={item.id} className={styles.comment}>
            <div className={styles.metadata}>
              <strong>{t("resident", { code: item.residentCode })}</strong>
              <time dateTime={item.createdAt}>{new Intl.DateTimeFormat(locale === "ja" ? "ja-JP" : "ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(item.createdAt))}</time>
              {(item.canDelete || page.viewer.moderator) && <div className={styles.actions}>
                {item.canDelete && <button type="button" disabled={busy} onClick={event => { removalTrigger.current = event.currentTarget; setRemoval({ id: item.id, action: "remove" }); }}>{t("delete")}</button>}
                {page.viewer.moderator && <button type="button" disabled={busy} onClick={event => { removalTrigger.current = event.currentTarget; setRemoval({ id: item.id, action: "hide" }); }}>{t("hide")}</button>}
              </div>}
            </div>
            <p className={styles.body}>{item.body}</p>
            {removal?.id === item.id && (removal.action === "remove" ? item.canDelete : page.viewer.moderator) && <div className={styles.confirmation} role="group" aria-labelledby={`${inputId}-${item.id}-confirm`} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); dismissRemoval(); } }}>
              <p id={`${inputId}-${item.id}-confirm`}>{t(removal.action === "remove" ? "confirmDelete" : "confirmHide")}</p>
              <div className={styles.confirmActions}>
                <button ref={cancelRemoval} type="button" className={styles.secondary} onClick={dismissRemoval}>{t("cancel")}</button>
                <button type="button" className={styles.secondary} disabled={busy} onClick={async () => { const choice = removal; setRemoval(null); await remove(choice.id, choice.action); listTitle.current?.focus({ preventScroll: true }); }}>{t(removal.action === "remove" ? "confirmDeleteAction" : "confirmHideAction")}</button>
              </div>
            </div>}
          </li>)}
        </ul>
        <div className={styles.listFooter}>
          {page?.next && <button type="button" className={styles.secondary} disabled={reading || busy} onClick={() => void load(page.next!)}>{reading ? t("loading") : t("more")}</button>}
          {notice === "read_failed" && <button type="button" className={styles.secondary} disabled={reading || busy} onClick={() => void load()}>{t("reload")}</button>}
        </div>
        {page?.viewer.signedIn ? <div className={styles.composer}>
          {publicName ? <>
            <p className={styles.identity}><span className={styles.srOnly}>{t("authorLabel")}: </span><strong>{publicName}</strong></p>
            <label htmlFor={inputId} className={styles.srOnly}>{t("bodyLabel")}</label>
            <textarea ref={input} id={inputId} placeholder={t("bodyLabel")} value={draft} onChange={event => setDraft(event.target.value)} readOnly={busy || !!pending} rows={2} aria-invalid={count > COMMENT_LIMIT || undefined} aria-describedby={`${inputId}-limit${pending ? ` ${inputId}-preserved` : ""}`} />
            {pending && <p id={`${inputId}-preserved`} className={styles.draftHelp}>{t("preservedDraft")}</p>}
            <div className={styles.composerFooter}>
              <p id={`${inputId}-limit`} className={count > COMMENT_LIMIT ? styles.error : styles.subtle}>{t("length", { count, limit: COMMENT_LIMIT })}</p>
              <button type="button" className={styles.primary} disabled={busy || !!pending || !validComment(draft)} onClick={() => void submit()}>{busy ? t("processing") : t("post")}</button>
            </div>
          </> : <>
            <div className={styles.prepareRow}>
              <p className={styles.prepareHelp}>{t("prepareHelp")}</p>
              <button type="button" className={styles.secondary} disabled={busy} onClick={() => { focusComposer.current = true; void prepare(); }}>{busy ? t("processing") : t("prepare")}</button>
            </div>
            {preservedDraft}
          </>}
        </div> : page ? <div className={styles.composer}>
          <div className={styles.loginPrompt}><p>{t("loginHelp")}</p><Link className={styles.secondary} href={loginHref}>{t("login")}</Link></div>
          {preservedDraft}
        </div> : null}
        {notice && notice !== "read_failed" && <p role={error ? "alert" : "status"} className={`${styles.notice} ${error ? styles.error : ""}`}>{t(notice)}</p>}
        {pending && <div className={styles.recovery}>
          <button type="button" className={styles.secondary} disabled={busy} onClick={() => void resolveSubmission()}>{t("checkSubmission")}</button>
          {mayRetry && code === pending.expectedCode && <button type="button" className={styles.secondary} disabled={busy} onClick={() => void submit(pending)}>{t("retrySame")}</button>}
          {mayRetry && code !== pending.expectedCode && <p role="status">{t("identity_changed")}</p>}
          {mayRetry && code && code !== pending.expectedCode && <button type="button" className={styles.secondary} disabled={busy} onClick={() => { setPending(null); setMayRetry(false); setNotice(null); }}>{t("newAccountDraft")}</button>}
        </div>}
        {(notice === "uncertain" || notice === "unavailable") && <div className={styles.recovery}><button type="button" className={styles.secondary} disabled={reading || busy} onClick={() => void load()}>{t("reload")}</button></div>}
      </>}
    </section>
  );
}
