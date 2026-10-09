"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { MessageSquare } from "lucide-react";
import Link from "./PublicNavigationLink";
import { loginUrl } from "../lib/auth/urls";
import { COMMENT_LIMIT, type ThreadPage, type CommentThread, type CommentCursor, normalizeComment, validComment } from "../lib/comments/contracts";
import styles from "./ContentComments.module.css";

type Submission = { requestId: string; body: string; expectedCode: string; parentId?: string };
type Notice = "parent_unavailable" | "read_failed" | "unavailable" | "authentication_required" | "forbidden" | "request_conflict" | "rate_limited" | "identity_changed" | "invalid_request" | "uncertain" | "accepted" | "deleted" | "hidden" | "absent" | null;
type Mutation = { outcome?: string; code?: string; state?: string; commentId?: string; error?: Notice };
const knownErrors = new Set(["authentication_required", "forbidden", "request_conflict", "rate_limited", "identity_changed", "invalid_request", "information_unavailable", "parent_unavailable"]);

export default function ContentComments({ id, slug, locale }: { id: string; slug: string; locale: string }) {
  const t = useTranslations("Comments"), inputId = useId();
  const authLocale = locale === "ja" ? "ja" : "ko";
  // PublicNavigationLink applies the locale itself; next stays fully qualified.
  const loginHref = loginUrl(authLocale, `/${authLocale}/info/${encodeURIComponent(slug)}#comments`).slice(3);
  const [page, setPage] = useState<ThreadPage | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCursors, setPageCursors] = useState<Array<CommentCursor | null>>([null]);
  const currentPage = useRef(1), pageStarts = useRef<Array<CommentCursor | null>>([null]);
  const [total, setTotal] = useState<number | null>(null), [countFailed, setCountFailed] = useState(false);
  const countSequence = useRef(0);
  const [replyTarget, setReplyTarget] = useState<string | null>(null);
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({});
  const [replyPages, setReplyPages] = useState<Record<string, ThreadPage>>({});
  const [replyLoading, setReplyLoading] = useState<Record<string, boolean>>({});
  const [replyUnavailable, setReplyUnavailable] = useState<Record<string, boolean>>({});
  const [replyFailed, setReplyFailed] = useState<Record<string, boolean>>({});
  const [collapsedReplies, setCollapsedReplies] = useState<Record<string, boolean>>({});
  const [replyRecipients, setReplyRecipients] = useState<Record<string, string>>({});
  const [replyAnnouncements, setReplyAnnouncements] = useState<Record<string, { count: number; sequence: number }>>({});
  const [noticeParent, setNoticeParent] = useState<string | null>(null);
  const replyTriggers = useRef<Record<string, HTMLButtonElement | null>>({});
  const replyComposers = useRef<Record<string, HTMLDivElement | null>>({});
  const replyInputs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const replyRows = useRef<Record<string, HTMLLIElement | null>>({});
  const replyFeedback = useRef<Record<string, HTMLDivElement | null>>({});
  const replyToggles = useRef<Record<string, HTMLButtonElement | null>>({});
  const focusReply = useRef<string | null>(null);
  const focusAcceptedReply = useRef<{ parentId: string; commentId?: string } | null>(null);
  const focusAddedReply = useRef<{ parentId: string; commentId?: string; keyboard: boolean; final: boolean } | null>(null);
  const openReply = useRef<string | null>(null);
  useEffect(() => { openReply.current = replyTarget; }, [replyTarget]);
  const replySequence = useRef<Record<string, number>>({});
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false), [reading, setReading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null), [unavailable, setUnavailable] = useState(false);
  const [pending, setPending] = useState<Submission | null>(null), [mayRetry, setMayRetry] = useState(false);
  const requestSequence = useRef(0), mounted = useRef(true), writing = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null), focusComposer = useRef(false);
  const [removal, setRemoval] = useState<{ id: string; action: "remove" | "hide"; parentId?: string } | null>(null);
  const cancelRemoval = useRef<HTMLButtonElement>(null), removalTrigger = useRef<HTMLButtonElement | null>(null);
  const listTitle = useRef<HTMLHeadingElement>(null), scrollAfterPage = useRef(false);
  useEffect(() => {
    if (!reading && page && scrollAfterPage.current) {
      scrollAfterPage.current = false;
      listTitle.current?.scrollIntoView({ block: "start" });
      listTitle.current?.focus({ preventScroll: true });
    }
  }, [page, reading]);
  const code = page?.viewer.code;
  const publicName = code ? t("resident", { code }) : null;
  const count = [...normalizeComment(draft)].length;

  function reveal(element: HTMLElement | null | undefined) {
    if (!element) return;
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  useEffect(() => {
    if (focusReply.current !== replyTarget || !replyTarget || busy || reading) return;
    const composer = replyComposers.current[replyTarget];
    const element = code ? replyInputs.current[replyTarget] : composer?.querySelector<HTMLElement>("a, button");
    if (element) { focusReply.current = null; reveal(element); }
  }, [replyTarget, code, busy, reading]);
  useEffect(() => {
    const target = focusAcceptedReply.current;
    if (!target || busy || reading || replyLoading[target.parentId]) return;
    focusAcceptedReply.current = null;
    reveal((target.commentId ? replyRows.current[target.commentId] : null) ?? replyFeedback.current[target.parentId] ?? replyTriggers.current[target.parentId] ?? listTitle.current);
  }, [busy, reading, replyLoading, replyPages, page]);
  useEffect(() => {
    const target = focusAddedReply.current;
    if (!target || replyLoading[target.parentId]) return;
    focusAddedReply.current = null;
    if (collapsedReplies[target.parentId]) replyToggles.current[target.parentId]?.focus({ preventScroll: true });
    else if (target.keyboard) reveal((target.commentId ? replyRows.current[target.commentId] : null) ?? replyToggles.current[target.parentId]);
    else if (target.final) replyToggles.current[target.parentId]?.focus({ preventScroll: true });
  }, [replyAnnouncements, replyLoading, collapsedReplies]);

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

  const loadCount = useCallback(async () => {
    const sequence = ++countSequence.current;
    try {
      const response = await fetch(`/api/comments?${new URLSearchParams({ id, view: "count" })}`, { cache: "no-store", credentials: "same-origin" });
      const result = await response.json();
      if (!response.ok || !Number.isSafeInteger(result.count) || result.count < 0) throw new Error("count_failed");
      if (mounted.current && sequence === countSequence.current) { setTotal(result.count); setCountFailed(false); }
    } catch { if (mounted.current && sequence === countSequence.current) { setTotal(null); setCountFailed(true); } }
  }, [id]);
  const loadReplies = useCallback(async (parentId: string, cursor?: CommentCursor) => {
    const epoch = requestSequence.current;
    let missing = false;
    const sequence = (replySequence.current[parentId] ?? 0) + 1; replySequence.current[parentId] = sequence;
    setReplyLoading(previous => ({ ...previous, [parentId]: true }));
    try {
      const query = new URLSearchParams({ id, parentId });
      if (cursor) { query.set("at", cursor.at); query.set("beforeId", cursor.id); }
      const response = await fetch(`/api/comments?${query}`, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) { missing = response.status === 404; throw new Error("read_failed"); }
      const data = await response.json() as ThreadPage;
      if (!mounted.current || epoch !== requestSequence.current || sequence !== replySequence.current[parentId]) return;
      setReplyPages(previous => ({ ...previous, [parentId]: { ...data, items: cursor && previous[parentId] && previous[parentId].viewer.code === data.viewer.code && previous[parentId].viewer.signedIn === data.viewer.signedIn ? [...new Map([...previous[parentId].items, ...data.items].map(item => [item.id, item])).values()] : data.items } }));
      setReplyFailed(previous => ({ ...previous, [parentId]: false }));
      setReplyUnavailable(previous => ({ ...previous, [parentId]: false }));
      return data;
    } catch { if (mounted.current && epoch === requestSequence.current && sequence === replySequence.current[parentId]) { setReplyFailed(previous => ({ ...previous, [parentId]: !missing })); setReplyUnavailable(previous => ({ ...previous, [parentId]: missing })); } }
    finally { if (mounted.current && sequence === replySequence.current[parentId]) setReplyLoading(previous => ({ ...previous, [parentId]: false })); }
  }, [id]);
  const load = useCallback(async (cursor?: CommentCursor, number = 1, scroll = false) => {
    const sequence = ++requestSequence.current;
    setReading(true);
    void loadCount();
    try {
      const query = new URLSearchParams({ id });
      if (cursor) { query.set("at", cursor.at); query.set("beforeId", cursor.id); }
      const response = await fetch(`/api/comments?${query}`, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) {
        if (response.status === 404 && mounted.current && sequence === requestSequence.current) { setUnavailable(true); setPage(null); }
        throw new Error("read_failed");
      }
      const data = await response.json() as ThreadPage;
      if (!mounted.current || sequence !== requestSequence.current) return;
      setUnavailable(false);
      setReplyPages({}); setReplyFailed({}); setReplyUnavailable({});
      setPage(data);
      pageStarts.current = [...pageStarts.current.slice(0, number), ...(data.next ? [data.next] : [])];
      setPageCursors(pageStarts.current);
      currentPage.current = number; setPageNumber(number);
      if (scroll) { setReplyTarget(null); scrollAfterPage.current = true; }
      for (const item of data.items) if (item.replyCount > 0) void loadReplies(item.id);
      setNotice(previous => previous === "read_failed" ? null : previous);
      if (!scroll && openReply.current && !data.items.some(item => item.id === openReply.current)) void loadReplies(openReply.current);
    } catch { if (mounted.current && sequence === requestSequence.current) setNotice("read_failed"); }
    finally { if (mounted.current && sequence === requestSequence.current) setReading(false); }
  }, [id, loadCount, loadReplies]);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    const sequence = requestSequence, countEpoch = countSequence;
    queueMicrotask(() => { if (active) void load(); });
    const refresh = () => { if (!writing.current) void load(pageStarts.current[currentPage.current - 1] ?? undefined, currentPage.current); };
    window.addEventListener("focus", refresh);
    return () => { active = false; mounted.current = false; sequence.current++; countEpoch.current++; window.removeEventListener("focus", refresh); };
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
  async function prepare(parentId?: string) {
    if (writing.current) return;
    writing.current = true; setBusy(true); setNotice(null); setNoticeParent(parentId ?? null);
    try {
      const data = await mutate("prepare", {});
      if (data.code) setPage(previous => previous ? { ...previous, viewer: { ...previous.viewer, code: data.code! } } : previous);
      else setNotice(data.error ?? "unavailable");
    } catch { setNotice("unavailable"); }
    finally { writing.current = false; setBusy(false); }
  }
  async function submit(submission?: Submission, parentId?: string) {
    const body = parentId ? replyDrafts[parentId] ?? "" : draft;
    if (writing.current || !code || (!submission && !validComment(body))) return;
    const value = submission ?? { requestId: crypto.randomUUID(), body: normalizeComment(body), expectedCode: code, ...(parentId ? { parentId } : {}) };
    setNoticeParent(value.parentId ?? null);
    if (value.expectedCode !== code) { setNotice("identity_changed"); return; }
    writing.current = true; setBusy(true); setNotice(null); setPending(value); setMayRetry(false);
    try {
      const result = await mutate("create", value);
      if (result.outcome === "accepted") { clearAccepted(value); if (value.parentId) { setReplyTarget(null); setCollapsedReplies(previous => ({ ...previous, [value.parentId!]: false })); focusAcceptedReply.current = { parentId: value.parentId, commentId: result.commentId }; } setPending(null); setNotice("accepted"); await load(value.parentId ? pageStarts.current[currentPage.current - 1] ?? undefined : undefined, value.parentId ? currentPage.current : 1); if (value.parentId) await loadReplies(value.parentId); }
      else { setPending(null); setNotice(result.error ?? "uncertain"); if (result.error === "identity_changed" || result.error === "authentication_required" || result.error === "parent_unavailable") await load(pageStarts.current[currentPage.current - 1] ?? undefined, currentPage.current); }
    } catch { setNotice("uncertain"); }
    finally { writing.current = false; setBusy(false); }
  }
  function clearAccepted(value: Submission) {
    if (value.parentId) setReplyDrafts(previous => ({ ...previous, [value.parentId!]: "" }));
    else setDraft("");
  }
  async function resolveSubmission() {
    if (writing.current || !pending) return;
    setNoticeParent(pending.parentId ?? null);
    writing.current = true; setBusy(true); setMayRetry(false);
    try {
      const query = new URLSearchParams({ id, requestId: pending.requestId });
      const response = await fetch(`/api/comments?${query}`, { cache: "no-store", credentials: "same-origin" });
      const result = await response.json() as Mutation;
      if (!response.ok) { setNotice(result.error ?? "uncertain"); return; }
      if (result.outcome === "accepted") { clearAccepted(pending); if (pending.parentId) { setReplyTarget(null); setCollapsedReplies(previous => ({ ...previous, [pending.parentId!]: false })); focusAcceptedReply.current = { parentId: pending.parentId, commentId: result.commentId }; } setPending(null); setNotice("accepted"); await load(pending.parentId ? pageStarts.current[currentPage.current - 1] ?? undefined : undefined, pending.parentId ? currentPage.current : 1); if (pending.parentId) await loadReplies(pending.parentId); }
      else if (result.outcome === "absent") { setMayRetry(true); setNotice("absent"); await load(pageStarts.current[currentPage.current - 1] ?? undefined, currentPage.current); }
      else setNotice("uncertain");
    } catch { setNotice("uncertain"); }
    finally { writing.current = false; setBusy(false); }
  }
  async function remove(commentId: string, action: "remove" | "hide", parentId?: string) {
    if (writing.current) return;
    setNoticeParent(null);
    writing.current = true; setBusy(true); setNotice(null);
    try {
      const result = await mutate(action, { commentId });
      setNotice(result.outcome === "deleted" ? "deleted" : result.outcome === "hidden" ? "hidden" : result.error ?? "uncertain");
      await load(pageStarts.current[currentPage.current - 1] ?? undefined, currentPage.current);
      if (parentId) await loadReplies(parentId);
    } catch { setNotice("uncertain"); }
    finally { writing.current = false; setBusy(false); }
  }
  const error = notice && !["accepted", "deleted", "hidden", "absent"].includes(notice);
  const feedbackParent = pending?.parentId ?? noticeParent;
  function reloadCurrentPage() { void load(pageStarts.current[currentPage.current - 1] ?? undefined, currentPage.current); }
  function retryPending() { if (pending) void submit(pending); }
  function reloadReply(parentId: string) { return () => { void loadReplies(parentId); }; }
  function prepareReply(parentId: string) { return () => { focusReply.current = parentId; void prepare(parentId); }; }
  function submissionFeedback(parentId: string | null = null) {
    if (feedbackParent !== parentId) return null;
    return <div ref={parentId ? element => { replyFeedback.current[parentId] = element; } : undefined} tabIndex={parentId ? -1 : undefined} className={styles.feedback}>
      {notice && notice !== "read_failed" && <p role={error ? "alert" : "status"} className={`${styles.notice} ${error ? styles.error : ""}`}>{parentId && notice === "accepted" ? t("replyAccepted") : t(notice)}</p>}
      {pending && <>
        <p className={styles.draftHelp}>{t("preservedDraft")}</p>
        <div className={styles.recovery}>
          <button type="button" className={styles.secondary} disabled={busy} onClick={() => void resolveSubmission()}>{t("checkSubmission")}</button>
          {mayRetry && code === pending.expectedCode && <button type="button" className={styles.secondary} disabled={busy} onClick={retryPending}>{t("retrySame")}</button>}
          {mayRetry && code !== pending.expectedCode && <p role="status">{t("identity_changed")}</p>}
          {mayRetry && code && code !== pending.expectedCode && <button type="button" className={styles.secondary} disabled={busy} onClick={() => { setPending(null); setMayRetry(false); setNotice(null); }}>{t("newAccountDraft")}</button>}
        </div>
      </>}
      {(notice === "uncertain" || notice === "unavailable") && <div className={styles.recovery}><button type="button" className={styles.secondary} disabled={reading || busy} onClick={reloadCurrentPage}>{t("reload")}</button></div>}
    </div>;
  }
  function dismissReply(parentId: string) {
    setReplyTarget(null);
    focusReply.current = null;
    reveal(replyTriggers.current[parentId] ?? listTitle.current);
  }
  async function showMoreReplies(parentId: string, cursor: CommentCursor | null | undefined, keyboard: boolean) {
    const known = new Set(replyPages[parentId]?.items.map(item => item.id) ?? []);
    const data = await loadReplies(parentId, cursor ?? undefined);
    if (!data) return;
    const added = data.items.filter(item => !known.has(item.id));
    focusAddedReply.current = { parentId, commentId: added[0]?.id, keyboard, final: !data.next };
    setReplyAnnouncements(previous => ({ ...previous, [parentId]: { count: added.length, sequence: (previous[parentId]?.sequence ?? 0) + 1 } }));
  }
  function replyGroup(item: CommentThread) {
    if (!item.replyCount && !replyPages[item.id] && !replyFailed[item.id] && !replyLoading[item.id]) return null;
    const name = item.state === "live" ? t("resident", { code: item.residentCode! }) : t(item.state === "deleted" ? "deletedReplyContext" : "hiddenReplyContext");
    const collapsed = collapsedReplies[item.id] === true;
    return <div className={styles.replyGroup}>
      <div className={styles.replyHeader}>
        {!collapsed && <span>{t("replyCount", { count: item.replyCount })}</span>}
        <button ref={element => { replyToggles.current[item.id] = element; }} type="button" className={styles.replyToggle} aria-label={t(collapsed ? "expandRepliesFor" : "collapseRepliesFor", { name, count: item.replyCount })} aria-expanded={!collapsed} aria-controls={`${inputId}-${item.id}-replies`} onClick={() => setCollapsedReplies(previous => ({ ...previous, [item.id]: !previous[item.id] }))}>{collapsed ? t("expandReplies", { count: item.replyCount }) : t("collapseReplies")}</button>
      </div>
      <div id={`${inputId}-${item.id}-replies`} hidden={collapsed}>
        {replyPages[item.id] && <ul className={styles.replies} aria-label={t("repliesFor", { name })}>
          {replyPages[item.id].items.map(child => <li key={child.id} ref={element => { replyRows.current[child.id] = element; }} tabIndex={-1} className={styles.comment}>{commentRow(child, item.id)}</li>)}
        </ul>}
        {replyFailed[item.id] && <p role="alert" className={styles.error}>{t("read_failed")}</p>}
        {(replyPages[item.id]?.next || replyFailed[item.id]) && <button type="button" className={styles.replyMore} disabled={!!replyLoading[item.id] || busy} onClick={event => void showMoreReplies(item.id, replyFailed[item.id] ? undefined : replyPages[item.id]?.next, event.detail === 0)}>{t("moreReplies")}</button>}
        {replyLoading[item.id] && <p role="status" className={styles.subtle}>{t("loading")}</p>}
      </div>
      <p role="status" aria-live="polite" aria-atomic="true" className={styles.srOnly}>{replyAnnouncements[item.id] && <span key={replyAnnouncements[item.id].sequence}>{t("repliesLoaded", { count: replyAnnouncements[item.id].count })}</span>}</p>
    </div>;
  }
  const preservedDraft = draft ? <div className={styles.preservedDraft}>
    <label htmlFor={inputId} className={styles.srOnly}>{t("bodyLabel")}</label>
    <textarea id={inputId} value={draft} readOnly rows={2} aria-describedby={`${inputId}-preserved`} />
    <p id={`${inputId}-preserved`} className={styles.subtle}>{t("preservedDraft")}</p>
  </div> : null;
  function commentRow(item: CommentThread, parentId?: string) {
    return item.state !== "live" ? <p className={styles.subtle}>{t(item.state === "deleted" ? "deletedParent" : "hiddenParent")}</p> : <>
            <div className={styles.metadata}>
              <strong>{t("resident", { code: item.residentCode! })}</strong>
              <div className={styles.metaEnd}><time dateTime={item.createdAt}>{new Intl.DateTimeFormat(locale === "ja" ? "ja-JP" : "ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(item.createdAt))}</time>
              {!parentId && <><span aria-hidden="true" className={styles.dateDivider}>·</span><button ref={element => { replyTriggers.current[item.id] = element; }} className={styles.replyButton} type="button" disabled={busy || !!pending} aria-label={t("replyTo", { name: t("resident", { code: item.residentCode! }) })} aria-expanded={replyTarget === item.id} aria-controls={`${inputId}-${item.id}-composer`} onClick={() => { setReplyRecipients(previous => ({ ...previous, [item.id]: t("resident", { code: item.residentCode! }) })); focusReply.current = item.id; setReplyTarget(item.id); }}>{t("reply")}</button></>}
              {(item.canDelete || page?.viewer.moderator) && <div className={styles.actions}>
                {item.canDelete && <button type="button" disabled={busy} onClick={event => { removalTrigger.current = event.currentTarget; setRemoval({ id: item.id, action: "remove", parentId }); }}>{t("delete")}</button>}
                {page?.viewer.moderator && <button type="button" disabled={busy} onClick={event => { removalTrigger.current = event.currentTarget; setRemoval({ id: item.id, action: "hide", parentId }); }}>{t("hide")}</button>}
              </div>}
            </div></div>
            <p className={styles.body}>{item.body}</p>
            {removal?.id === item.id && (removal.action === "remove" ? item.canDelete : page?.viewer.moderator) && <div className={styles.confirmation} role="group" aria-labelledby={`${inputId}-${item.id}-confirm`} onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); dismissRemoval(); } }}>
              <p id={`${inputId}-${item.id}-confirm`}>{t(removal.action === "remove" ? "confirmDelete" : "confirmHide")}</p>
              <div className={styles.confirmActions}>
                <button ref={cancelRemoval} type="button" className={styles.secondary} onClick={dismissRemoval}>{t("cancel")}</button>
                <button type="button" className={styles.secondary} disabled={busy} onClick={async () => { const choice = removal; setRemoval(null); await remove(choice.id, choice.action, choice.parentId); listTitle.current?.focus({ preventScroll: true }); }}>{t(removal.action === "remove" ? "confirmDeleteAction" : "confirmHideAction")}</button>
              </div>
            </div>}
    </>;
  }
  function replyComposer(parentId: string, live: boolean | null) {
    const value = replyDrafts[parentId] ?? "", length = [...normalizeComment(value)].length;
    const recipient = replyRecipients[parentId];
    return <div ref={element => { replyComposers.current[parentId] = element; }} className={styles.composer}>
      <p id={`${inputId}-${parentId}-target`} className={styles.srOnly}>{recipient ? t("replyTo", { name: recipient }) : t("replyComposer")}</p>
      {publicName && <p className={styles.identity}><span className={styles.srOnly}>{t("authorLabel")}: </span><strong>{publicName}</strong></p>}
      {live === false && !replyLoading[parentId] && <p role="status" className={styles.notice}>{t("parent_unavailable")}</p>}
      {replyFailed[parentId] && <div className={styles.recovery}><p role="alert" className={styles.error}>{t("read_failed")}</p><button className={styles.secondary} type="button" disabled={busy || !!replyLoading[parentId]} onClick={reloadReply(parentId)}>{t("reload")}</button></div>}
      {replyLoading[parentId] && <p role="status" className={styles.subtle}>{t("loading")}</p>}
      {!page?.viewer.signedIn ? <div className={styles.loginPrompt}><p>{t("loginHelp")}</p><Link className={styles.secondary} href={loginHref}>{t("login")}</Link></div> : !code ? <button className={styles.secondary} type="button" disabled={busy} onClick={prepareReply(parentId)}>{busy ? t("processing") : t("prepare")}</button> : null}
      <label className={styles.srOnly} htmlFor={`${inputId}-${parentId}`}>{t("replyBodyLabel")}</label>
      <textarea ref={element => { replyInputs.current[parentId] = element; }} id={`${inputId}-${parentId}`} rows={2} value={value} placeholder={t("replyBodyLabel")} readOnly={busy || !!pending || live === false || !code} onChange={event => setReplyDrafts(previous => ({ ...previous, [parentId]: event.target.value }))} aria-invalid={length > COMMENT_LIMIT || undefined} aria-describedby={`${inputId}-${parentId}-target ${inputId}-${parentId}-limit`} />
      <div className={styles.composerFooter}><p id={`${inputId}-${parentId}-limit`} className={length > COMMENT_LIMIT ? styles.error : styles.subtle}>{t("length", { count: length, limit: COMMENT_LIMIT })}</p><div className={styles.confirmActions}>
        <button className={styles.secondary} type="button" disabled={busy || !!pending} onClick={() => dismissReply(parentId)}>{t("cancel")}</button>
        <button className={styles.primary} type="button" disabled={busy || !!pending || !live || !code || !validComment(value)} onClick={() => void submit(undefined, parentId)}>{busy && feedbackParent === parentId ? t("processing") : t("postReply")}</button>
      </div></div>
      {submissionFeedback(parentId)}
    </div>;
  }
  return (
    <section id="comments" aria-labelledby={`${inputId}-title`} className={styles.section}>
      <h2 ref={listTitle} tabIndex={-1} id={`${inputId}-title`} className={styles.title}>
        <MessageSquare size={18} strokeWidth={1.8} aria-hidden="true" />{total === null ? t("title") : t("titleCount", { count: total })}
      </h2>
      {countFailed && <div className={styles.recovery}><p role="status" className={styles.subtle}>{t("count_failed")}</p><button className={styles.secondary} type="button" disabled={busy} onClick={() => void loadCount()}>{t("reloadCount")}</button></div>}
      {unavailable ? <>
        <p role="status" className={styles.notice}>{t("unavailable")}</p>
        {draft && <div className={styles.composer}>{preservedDraft}</div>}
        {replyTarget && replyComposer(replyTarget, false)}
      </> : <>
        {notice === "read_failed" && <p role="alert" className={`${styles.notice} ${styles.error}`}>{t("read_failed")}</p>}
        {reading && <p role="status" className={styles.loading}>{t("loading")}</p>}
        {page && page.items.length === 0 && !reading && notice !== "read_failed" && <p className={styles.empty}>{t("empty")}</p>}
        <ul className={styles.list} aria-label={t("listTitle")}>
          {page?.items.map(item => <li key={item.id} className={styles.comment}>
            {commentRow(item)}
            {replyTarget === item.id && <div id={`${inputId}-${item.id}-composer`} className={styles.replyComposer}>{replyComposer(item.id, item.state === "live")}</div>}
            {replyTarget !== item.id && submissionFeedback(item.id)}
            {replyGroup(item)}
          </li>)}
        </ul>
        <div className={styles.listFooter}>
          {page && pageCursors.length > 1 && <nav className={styles.pagination} aria-label={t("pagination")}>
            <button type="button" className={styles.secondary} disabled={reading || busy || !!pending || pageNumber === 1} onClick={() => void load(pageStarts.current[pageNumber - 2] ?? undefined, pageNumber - 1, true)}>{t("previousPage")}</button>
            {pageCursors.map((cursor, index) => index === 0 || Math.abs(index + 1 - pageNumber) <= 1 ? <button key={index} type="button" className={styles.pageButton} aria-label={t("pageLabel", { page: index + 1 })} aria-current={index + 1 === pageNumber ? "page" : undefined} disabled={reading || busy || !!pending} onClick={() => void load(cursor ?? undefined, index + 1, true)}>{index + 1}</button> : null)}
            <button type="button" className={styles.secondary} disabled={reading || busy || !!pending || !page.next} onClick={() => void load(page.next!, pageNumber + 1, true)}>{t("nextPage")}</button>
          </nav>}
          {notice === "read_failed" && <button type="button" className={styles.secondary} disabled={reading || busy} onClick={() => void load(pageStarts.current[currentPage.current - 1] ?? undefined, currentPage.current)}>{t("reload")}</button>}
        </div>
        {replyTarget && !page?.items.some(item => item.id === replyTarget) && replyComposer(replyTarget, replyUnavailable[replyTarget] ? false : replyPages[replyTarget]?.parentState ? replyPages[replyTarget].parentState === "live" : null)}
        {page?.viewer.signedIn ? <div className={styles.composer}>
          {publicName ? <>
            <p className={styles.identity}><span className={styles.srOnly}>{t("authorLabel")}: </span><strong>{publicName}</strong></p>
            <label htmlFor={inputId} className={styles.srOnly}>{t("bodyLabel")}</label>
            <textarea ref={input} id={inputId} placeholder={t("bodyLabel")} value={draft} onChange={event => setDraft(event.target.value)} readOnly={busy || !!pending} rows={2} aria-invalid={count > COMMENT_LIMIT || undefined} aria-describedby={`${inputId}-limit${pending ? ` ${inputId}-preserved` : ""}`} />
            {pending && <p id={`${inputId}-preserved`} className={styles.draftHelp}>{t("preservedDraft")}</p>}
            <div className={styles.composerFooter}>
              <p id={`${inputId}-limit`} className={count > COMMENT_LIMIT ? styles.error : styles.subtle}>{t("length", { count, limit: COMMENT_LIMIT })}</p>
              <button type="button" className={styles.primary} disabled={busy || !!pending || !validComment(draft)} onClick={() => void submit()}>{busy && !feedbackParent ? t("processing") : t("post")}</button>
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
        {submissionFeedback()}
        {feedbackParent && replyTarget !== feedbackParent && !page?.items.some(item => item.id === feedbackParent) && submissionFeedback(feedbackParent)}
      </>}
    </section>
  );
}
