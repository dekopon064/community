"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { dismissPreview, trashList } from "@/app/lib/review/trash";
import type { TrashItem } from "@/app/lib/review/trash";
import { failureText } from "@/app/lib/review/presentation";
import { secondaryButton } from "./ReviewEditors";

const blocked: Record<string, string> = {
  source_missing: "원본이 없어 복구할 수 없습니다.", source_changed: "원문이 변경되어 이전 항목을 복구할 수 없습니다. 최신 review 항목을 확인해 주세요.",
  processing_active: "작업이 처리 중입니다. 완료 후 새로고침해 주세요.", already_published: "이미 게시된 항목이라 복구할 수 없습니다.", state_changed: "항목 상태가 변경되었습니다. 최신 상태를 확인해 주세요.",
};
const sourceName = (name: string) => ({ youthcenter_policy: "청년정책", youthcenter_content: "청년센터 콘텐츠", seoul_reservation: "서울 공공서비스예약" }[name] ?? name);
const time = (stamp: string) => new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(stamp));
type Confirmation = { action: "dismiss" | "empty"; episodeId: string | null; version: string; count: number; title?: string };
function DeleteConfirmation({ selection, busy, error, returnFocus, cancel, submit }: { selection: Confirmation; busy: boolean; error: string; returnFocus: RefObject<HTMLElement | null>; cancel: () => void; submit: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null), cancelButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = returnFocus.current ?? document.activeElement as HTMLElement | null, element = dialog.current;
    element?.showModal(); cancelButton.current?.focus();
    return () => { element?.close(); queueMicrotask(() => { if (previous?.isConnected) previous.focus({ preventScroll: true }); }); };
  }, [returnFocus]);
  return <dialog ref={dialog} aria-labelledby="trash-delete-title" aria-describedby="trash-delete-description" onCancel={e => { e.preventDefault(); if (!busy) cancel(); }} className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-xl border border-info-rule bg-info-surface p-6 text-info-title backdrop:bg-black/40">
    <h2 id="trash-delete-title" className="text-xl font-bold">{selection.action === "empty" ? "휴지통 비우기" : "휴지통 항목 삭제"}</h2>
    {selection.title && <p className="mt-4 break-words font-semibold leading-7">{selection.title}</p>}
    <p id="trash-delete-description" className="mt-3 leading-7 text-info-body">{selection.action === "empty" ? `휴지통의 항목 ${selection.count.toLocaleString("ko-KR")}개를 삭제합니다. 삭제하면 복구할 수 없습니다.` : "휴지통에서 삭제하면 복구할 수 없습니다."}</p>
    {error && <p role="alert" className="mt-4 leading-7 text-info-status">{failureText[error] ?? failureText.unavailable}</p>}
    <div className="mt-6 flex flex-wrap gap-3"><button ref={cancelButton} type="button" className={secondaryButton} disabled={busy} onClick={cancel}>취소</button><button type="button" className={`${secondaryButton} text-info-status`} disabled={busy} onClick={submit}>{busy ? "삭제 중…" : selection.action === "empty" ? `${selection.count.toLocaleString("ko-KR")}개 삭제` : "삭제"}</button></div>
  </dialog>;
}
export default function TrashPanel({ active, onBusy, onRestored }: { active: boolean; onBusy: (busy: boolean) => void; onRestored: () => void }) {
  const [items, setItems] = useState<TrashItem[]>([]), [loading, setLoading] = useState(true), [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [offset, setOffset] = useState(0), [hasMore, setHasMore] = useState(false);
  const [clock, setClock] = useState<{ server: number; mono: number } | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null), [deleteError, setDeleteError] = useState(""), [queryFailed, setQueryFailed] = useState(false);
  const sending = useRef(false), generation = useRef(0), message = useRef<HTMLDivElement>(null), requests = useRef(new Map<string, string>());
  const confirmationOrigin = useRef<HTMLElement | null>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    const seq = ++generation.current; const started = performance.now(); setLoading(true);
    try {
      const r = await fetch(`/api/admin/review-trash?offset=${offset}`, { credentials: "same-origin", cache: "no-store", signal });
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new Error(data?.code ?? "unavailable");
      if (data?.mode !== "database" || typeof data.hasMore !== "boolean") throw new Error("unavailable");
      const list = trashList(data);
      if (signal?.aborted || seq !== generation.current) return;
      const received = performance.now();
      // Conservative transit allowance; browser wall-clock changes cannot extend recovery time.
      const server = Date.parse(list.serverNow) + (received - started);
      const visible = list.items.filter(e => Date.parse(e.expiresAt) > server);
      setClock({ server, mono: received }); setItems(visible); setHasMore(data.hasMore); setError(""); setQueryFailed(false);
      if (!visible.length && offset > 0) setOffset(n => Math.max(0, n - 25));
    } catch (e) { if (!signal?.aborted && seq === generation.current) { setError(e instanceof Error ? e.message : "unavailable"); setQueryFailed(true); } }
    finally { if (!signal?.aborted && seq === generation.current) setLoading(false); }
  }, [offset]);
  useEffect(() => { if (!active) return; const c = new AbortController(); const current = generation; queueMicrotask(() => { if (!c.signal.aborted) void load(c.signal); }); return () => { c.abort(); current.current++; }; }, [active, load]);
  useEffect(() => { onBusy(Boolean(busy) || Boolean(confirmation)); return () => onBusy(false); }, [busy, confirmation, onBusy]);
  useEffect(() => { if (active && !confirmation && (error || notice)) { message.current?.focus({ preventScroll: true }); message.current?.scrollIntoView({ block: "nearest" }); } }, [active, error, notice, confirmation]);
  useEffect(() => {
    if (!active || !clock || !items.length) return;
    const now = () => clock.server + performance.now() - clock.mono;
    const expire = () => { const stamp = now(); setItems(old => old.filter(e => Date.parse(e.expiresAt) > stamp)); };
    const timer = window.setTimeout(expire, Math.max(0, Math.min(...items.map(e => Date.parse(e.expiresAt))) - now()) + 1);
    const resume = () => { if (document.visibilityState === "visible") expire(); };
    document.addEventListener("visibilitychange", resume);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", resume); };
  }, [active, clock, items]);
  const restore = useCallback(async (e: TrashItem) => {
    if (sending.current || loading || !e.canRestore) return;
    if (clock && Date.parse(e.expiresAt) <= clock.server + performance.now() - clock.mono) { setItems(old => old.filter(x => x.id !== e.id)); setError("trash_expired"); return; }
    sending.current = true; setBusy(e.id); setError(""); setNotice("");
    const key = e.id + e.version; let requestId = requests.current.get(key); if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    try {
      const r = await fetch("/api/admin/review-trash", { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "restore", episodeId: e.id, revision: e.revision, version: e.version, requestId }) });
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new Error(data?.code ?? "unavailable");
      if (data?.mode !== "database" || data.episodeId !== e.id || data.sourceItemId !== e.sourceItemId || data.item?.status !== "open") throw new Error("unavailable");
      setItems(old => old.filter(x => x.id !== e.id)); setNotice("사람 사실 review로 복구했습니다. 돌아가서 기존 사실과 근거를 다시 확인해 주세요."); onRestored();
    } catch (err) { setError(err instanceof Error ? err.message : "unavailable"); }
    finally { sending.current = false; setBusy(null); }
  }, [clock, loading, onRestored]);
  const prepareEmpty = async () => {
    if (sending.current || loading || queryFailed) return;
    confirmationOrigin.current = document.activeElement as HTMLElement | null;
    sending.current = true; setBusy("preview"); setError(""); setNotice("");
    try {
      const r = await fetch("/api/admin/review-trash?preview=dismiss", { credentials: "same-origin", cache: "no-store" });
      const data = await r.json().catch(() => null);
      if (!r.ok || data?.mode !== "database") throw new Error(data?.code ?? "unavailable");
      const preview = dismissPreview(data);
      if (!preview.count) { setNotice("휴지통에 삭제할 항목이 없습니다."); await load(); }
      else if (preview.count > 5000) setError("too_many_trash_items");
      else { setDeleteError(""); setConfirmation({ action: "empty", episodeId: null, ...preview }); }
    } catch (err) { setError(err instanceof Error ? err.message : "unavailable"); }
    finally { sending.current = false; setBusy(null); }
  };
  const dismiss = async () => {
    if (!confirmation || sending.current) return;
    const selected = confirmation; sending.current = true; setBusy("delete"); setDeleteError("");
    const key = `delete:${selected.action}:${selected.episodeId}:${selected.version}`;
    let requestId = requests.current.get(key); if (!requestId) { requestId = crypto.randomUUID(); requests.current.set(key, requestId); }
    try {
      const r = await fetch("/api/admin/review-trash", { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: selected.action, episodeId: selected.episodeId, version: selected.version, requestId }) });
      const data = await r.json().catch(() => null);
      if (!r.ok) throw new Error(data?.code ?? "unavailable");
      if (data?.mode !== "database" || data.action !== selected.action || data.episodeId !== selected.episodeId || data.count !== selected.count) throw new Error("unavailable");
      setConfirmation(null); setItems(old => selected.action === "empty" ? [] : old.filter(e => e.id !== selected.episodeId));
      setNotice(`${data.count.toLocaleString("ko-KR")}개 항목을 휴지통에서 삭제했습니다.`);
      if (offset) setOffset(0); else await load();
    } catch (err) {
      const code = err instanceof Error ? err.message : "unavailable";
      if (["conflict", "already_processed", "trash_expired", "not_found"].includes(code)) { setConfirmation(null); setError("trash_targets_changed"); }
      else setDeleteError(code);
    } finally { sending.current = false; setBusy(null); }
  };
  return <section hidden={!active} aria-label="휴지통" aria-busy={loading || Boolean(busy)} className="py-6">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-xl font-bold">휴지통</h2><p className="mt-2 max-w-3xl leading-7 text-info-body">제외한 항목은 72시간 이내에 복구할 수 있습니다. 기한이 지나거나 삭제하면 이 목록에서 사라지며 복구할 수 없습니다. 원본과 처리 기록은 유지됩니다.</p></div><div className="flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={loading || Boolean(busy) || Boolean(confirmation)} onClick={() => { setNotice(""); void load(); }}>새로고침</button><button type="button" className={secondaryButton} disabled={loading || Boolean(busy) || Boolean(confirmation) || queryFailed} onClick={() => void prepareEmpty()}>{busy === "preview" ? "대상 확인 중…" : "휴지통 비우기"}</button></div></div>
    {clock && <p className="mt-3 text-sm text-info-muted">조회 기준: {time(new Date(clock.server).toISOString())} (한국 시간)</p>}
    {(error || notice) && <div ref={message} tabIndex={-1} role={error ? "alert" : "status"} className="my-5 border-y border-info-rule py-4 leading-7"><p className={error ? "text-info-status" : "text-info-body"}>{error ? failureText[error] ?? failureText.unavailable : notice}</p>{error && <p className="mt-2 text-sm text-info-muted">새로고침으로 최신 상태를 확인해 주세요. 조회 실패 시 이전 목록을 유지합니다.</p>}</div>}
    {loading && <p role="status" className="py-6 text-info-muted">휴지통을 불러오는 중입니다.</p>}
    {!loading && !error && !items.length && <p className="my-6 border-y border-info-rule py-6 text-info-body">{offset ? "이 페이지에 복구 가능한 항목이 없습니다. 이전 페이지를 확인해 주세요." : "휴지통에 표시할 항목이 없습니다. 사람 사실 review에서 제외한 항목이 기한 내에 여기에 표시됩니다."}</p>}
    <ul className="mt-5 divide-y divide-info-rule">{items.map(e => <li key={e.id} className="grid gap-4 py-5 sm:grid-cols-[minmax(0,1fr)_auto]"><div className="min-w-0"><h3 className="break-words text-lg font-semibold leading-7">{e.title}</h3><p className="mt-1 text-sm text-info-muted">{sourceName(e.sourceName)}</p><p className="mt-3 whitespace-pre-wrap break-words leading-7 text-info-body">제외 사유: {e.note}</p><dl className="mt-3 grid gap-2 text-sm leading-6 sm:grid-cols-2"><div><dt className="text-info-muted">제외 시각</dt><dd>{time(e.excludedAt)} (한국 시간)</dd></div><div><dt className="text-info-muted">복구 기한</dt><dd>{time(e.expiresAt)} (한국 시간)</dd></div></dl>{e.blockReason && <p className="mt-3 leading-7 text-info-status">{blocked[e.blockReason]}</p>}</div><div className="flex flex-wrap items-start gap-3"><button type="button" aria-label={`${e.title} 복구`} className={secondaryButton} disabled={loading || Boolean(busy) || queryFailed || Boolean(confirmation) || !e.canRestore} onClick={() => void restore(e)}>{busy === e.id ? "복구 중…" : "복구"}</button><button type="button" aria-label={`${e.title} 삭제`} className={secondaryButton} disabled={loading || Boolean(busy) || queryFailed || Boolean(confirmation) || !e.dismissVersion} onClick={event => { confirmationOrigin.current = event.currentTarget; setDeleteError(""); setError(""); setNotice(""); setConfirmation({ action: "dismiss", episodeId: e.id, version: e.dismissVersion!, title: e.title, count: 1 }); }}>삭제</button></div></li>)}</ul>
    <div className="mt-6 flex flex-wrap gap-3"><button type="button" className={secondaryButton} disabled={loading || Boolean(busy) || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 25))}>이전 페이지</button><button type="button" className={secondaryButton} disabled={loading || Boolean(busy) || !hasMore} onClick={() => setOffset(n => n + 25)}>다음 페이지</button></div>
    {confirmation && <DeleteConfirmation selection={confirmation} busy={busy === "delete"} error={deleteError} returnFocus={confirmationOrigin} cancel={() => setConfirmation(null)} submit={() => void dismiss()} />}
  </section>;
}
