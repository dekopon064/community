"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { CandidateImageSelection, CandidateContent, Facts, ReviewItem, ReviewKind, ListItem, ReviewCommand } from "@/app/lib/review/contracts";
import { actionText, aiStatusText, categories, failureText, reasonText, sourceLink, statusText } from "@/app/lib/review/presentation";
import { CandidateEditor, FactsEditor, fieldClass, primaryButton, secondaryButton } from "./ReviewEditors";
import { CandidateContentNotices } from "./CandidateContentNotices";
import CandidateImageEditor, { candidateImageError } from "./CandidateImageEditor";
import ProgramReviewPanel from "./ProgramReviewPanel";
import MySeoulReviewPanel from "./MySeoulReviewPanel";
import { myseoulGuidance } from "@/app/lib/review/myseoul-contract";
import AiQueuePanel from "./AiQueuePanel";
import TrashPanel from "./TrashPanel";
import { quickReasons } from "@/app/lib/review/trash";
import type { QuickReason } from "@/app/lib/review/trash";
import FactsGuidance from "./FactsGuidance";
import { programReasonText } from "@/app/lib/review/program-contract";
import { reviewDetailPath } from "@/app/lib/review/program-ui";

class RequestFailure extends Error {
  code: string; fields: Record<string, string>;
  constructor(code: string, fields: Record<string, string> = {}) { super(code); this.code = code; this.fields = fields; }
}
async function call(path: string, body?: unknown, signal?: AbortSignal) {
  const response = await fetch(path, { cache: "no-store", credentials: "same-origin", signal, ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new RequestFailure(data?.code ?? "unavailable", data?.fields);
  if (!["local-fixture", "database"].includes(data?.mode)) throw new RequestFailure("unavailable");
  return data;
}
function time(value: string) { return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function focusTask(element: HTMLElement | null) {
  element?.focus({ preventScroll: true });
  element?.scrollIntoView({ block: "start" });
}

export default function ReviewWorkspace() {
  const [kind, setKind] = useState<ReviewKind | "ai" | "trash">("facts");
  const [list, setList] = useState<ListItem[]>([]);
  const [item, setItem] = useState<ReviewItem | null>(null);
  const [programId, setProgramId] = useState<string | null>(null);
  const [myseoulId, setMyseoulId] = useState<string | null>(null);
  const [programBlocked, setProgramBlocked] = useState(false);
  const [facts, setFacts] = useState<Facts | null>(null);
  const [imageSelection, setImageSelection] = useState<CandidateImageSelection | null>(null);
  const [content, setContent] = useState<CandidateContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState("");
  const programResult = useCallback((next: { id: string; status: string; source: { title: string; name?: string }; result: { reasons: string[] } }) => {
    setList(old => old.flatMap(entry => entry.id === next.id && ["resolved", "excluded"].includes(next.status) ? [] : [entry.id === next.id ? { ...entry, title: next.source.title, status: next.status, reasons: next.status === "open" ? next.result.reasons : [] } : entry]));
    if (next.status === "excluded") { setProgramId(null); setMyseoulId(null); setNotice("제외했습니다. 제외 시각부터 72시간 이내에 휴지통에서 복구할 수 있습니다."); }
  }, []);
  const [note, setNote] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [confirmation, setConfirmation] = useState<"publish" | "reject" | "exclude" | null>(null);
  const [reload, setReload] = useState(0);
  const [mode, setMode] = useState<"database" | "local-fixture" | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const pendingRequest = useRef<{ key: string; id: string } | null>(null);
  const sending = useRef(false);
  const trashBusy = useCallback((value: boolean) => setBusy(value), []);
  const restored = useCallback(() => setReload(n => n + 1), []);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const resultMessage = useRef<HTMLParagraphElement>(null);
  const errorMessageBox = useRef<HTMLDivElement>(null);
  const confirmationBox = useRef<HTMLElement>(null);
  const imageEditable = item?.kind === "candidates" && item.source.name === "myseoul_program" && item.status === "pending" && !item.publishedId && Boolean(item.image);
  const imageDirty = Boolean(imageEditable && imageSelection && item?.kind === "candidates" && (item.image?.mode !== imageSelection.mode || item.image?.url !== imageSelection.url));
  const invalidImage = imageEditable && imageSelection ? candidateImageError(imageSelection) : "";
  const contentDirty = Boolean(item && (item.kind === "facts" ? JSON.stringify(item.facts) !== JSON.stringify(facts) : JSON.stringify(item.content) !== JSON.stringify(content)));
  const fieldsDirty = contentDirty || imageDirty;
  const dirty = programBlocked || fieldsDirty || Boolean(note) || Boolean(changeNote);
  const publicChange = Boolean(item?.kind === "candidates" && item.source.name === "myseoul_program" && item.status === "published" && item.programInfo?.inputChanged);
  const processed = item && (item.kind === "facts" ? item.status !== "open" : item.status !== "pending" && !publicChange);
  const locked = busy || Boolean(processed) || Boolean(confirmation);

  useEffect(() => {
    if (kind === "ai" || kind === "trash") return;
    const controller = new AbortController();
    call(`/api/admin/review?kind=${kind}&offset=${offset}`, undefined, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setList(data.items); setMode(data.mode); setHasMore(data.hasMore); setError(""); setLoading(false);
    }).catch((e) => { if (!controller.signal.aborted) { setError(e instanceof RequestFailure ? e.code : "unavailable"); setLoading(false); } });
    return () => controller.abort();
  }, [kind, reload, offset]);

  // Move focus with the task, especially when the mobile detail is below the list.
  useEffect(() => { if (item) focusTask(detailHeading.current); }, [item]);
  useEffect(() => { if (error) focusTask(errorMessageBox.current); else if (notice) focusTask(resultMessage.current); }, [error, notice]);
  useEffect(() => { if (confirmation) focusTask(confirmationBox.current); }, [confirmation]);

  function accept(next: ReviewItem) {
    setItem(next); setFacts(next.kind === "facts" ? next.facts : null); setContent(next.kind === "candidates" ? next.content : null);
    setImageSelection(next.kind === "candidates" && next.image ? { mode: next.image.mode, url: next.image.url } : null);
    setNote(""); setChangeNote(""); setConfirmation(null); setErrors({});
  }
  async function select(id: string) {
    if (busy || dirty || confirmation || kind === "ai" || kind === "trash") return;
    const entry = list.find(row => row.id === id);
    setError(""); setNotice(""); setItem(null);
    if (kind === "facts" && entry?.sourceName === "myseoul_program") { setProgramId(null); setMyseoulId(id); return; }
    setMyseoulId(null);
    if (kind === "facts" && entry?.sourceName === "seoul_reservation") { setProgramId(id); return; }
    setProgramId(null); setBusy(true);
    try { const data = await call(reviewDetailPath(kind, id, entry?.sourceName ?? "")); accept(data.item); }
    catch (e) { setError(e instanceof RequestFailure ? e.code : "unavailable"); }
    finally { setBusy(false); }
  }
  function switchKind(next: ReviewKind | "ai" | "trash") {
    if (busy || dirty || confirmation || next === kind) return;
    setKind(next); setOffset(0); setList([]); setItem(null); setProgramId(null); setMyseoulId(null); setFacts(null); setContent(null); setNotice(""); setError(""); setErrors({}); setLoading(next !== "ai" && next !== "trash");
  }
  async function submit(command: ReviewCommand & { reasonCode?: QuickReason }) {
    if (!item || busy || sending.current) return;
    sending.current = true;
    setBusy(true); setError(""); setErrors({}); setNotice("");
    try {
      const payload = command.action === "exclude" ? { action: "exclude", id: item.id, revision: command.revision, version: command.version, reasonCode: command.reasonCode ?? "custom", note: command.note } : null;
      const key = JSON.stringify(payload);
      if (payload && pendingRequest.current?.key !== key) pendingRequest.current = { key, id: crypto.randomUUID() };
      const data = await call(payload ? "/api/admin/review-trash" : `/api/admin/review/${kind}/${item.id}`, payload ? { ...payload, requestId: pendingRequest.current!.id } : command);
      const next: ReviewItem = data.item; accept(next); setChangeNote("");
      setList((old) => old.flatMap((entry) => next.kind === "facts" && entry.id === next.id && ["resolved", "excluded"].includes(next.status) ? [] : [entry.id === next.id ? { ...entry, status: next.status, title: next.kind === "candidates" ? next.content.titleKo : next.source.title, reasons: next.kind === "facts" ? next.reasons : [] } : entry]));
      const result = command.action === "save_facts" && next.kind === "facts" ?
        next.status === "excluded" ? "사실 저장 후 대상 부적격으로 판정되었습니다. AI는 진행하지 않습니다." : `사실을 저장했습니다. 남은 확인 사유 ${next.reasons.length}개. ${aiStatusText[next.aiStatus]} 저장 요청에서 AI를 실행하지 않았습니다.` :
        command.action === "review_change" ? `${publicChange && command.disposition === "edited" ? "공개 내용을 수정하고 " : ""}최신 원문 대조와 처리 근거를 저장했습니다. AI 실행·재번역은 하지 않았습니다.` :
        command.action === "save_candidate" ? "수정 내용을 비공개로 저장했습니다. AI 실행·재번역은 하지 않았습니다." :
        command.action === "publish" ? "저장된 내용의 승인·게시와 이력을 기록했습니다." : command.action === "exclude" ? `제외했습니다. ${time(data.expiresAt)} (한국 시간)까지 휴지통에서 복구할 수 있습니다.` : "사유를 기록하고 후보를 반려했습니다.";
      if (command.action === "exclude") { setItem(null); setFacts(null); pendingRequest.current = null; }
      setNotice(data.mode === "local-fixture" ? `${result} 실제 DB 저장·게시는 아닌 로컬 시험 결과입니다.` : result);
    } catch (e) {
      setError(e instanceof RequestFailure ? e.code : "unavailable"); setErrors(e instanceof RequestFailure ? e.fields : {}); setConfirmation(null);
    } finally { sending.current = false; setBusy(false); }
  }
  function preconditions() { return { revision: item!.revision, version: item!.version }; }
  const errorMessage = error ? failureText[error] ?? failureText.unavailable : "";
  const source = item ? sourceLink(item.source.url) : null;

  return <div className="mt-8">
    <nav aria-label="검토 단계" className="flex flex-wrap gap-2 border-b border-info-rule pb-4">
      <button type="button" aria-current={kind === "facts" ? "page" : undefined} disabled={busy || dirty || Boolean(confirmation)} onClick={() => switchKind("facts")} className={kind === "facts" ? primaryButton : secondaryButton}>사람 사실 review</button>
      <button type="button" aria-current={kind === "ai" ? "page" : undefined} disabled={busy || dirty || Boolean(confirmation)} onClick={() => switchKind("ai")} className={kind === "ai" ? primaryButton : secondaryButton}>AI 작업 대기</button>
      <button type="button" aria-current={kind === "candidates" ? "page" : undefined} disabled={busy || dirty || Boolean(confirmation)} onClick={() => switchKind("candidates")} className={kind === "candidates" ? primaryButton : secondaryButton}>AI 결과 후보 검토</button>
      <button type="button" aria-current={kind === "trash" ? "page" : undefined} disabled={busy || dirty || Boolean(confirmation)} onClick={() => switchKind("trash")} className={kind === "trash" ? primaryButton : secondaryButton}>휴지통</button>
    </nav>
    <TrashPanel active={kind === "trash"} onBusy={trashBusy} onRestored={restored} />
    <AiQueuePanel active={kind === "ai"} />
    <div hidden={kind === "ai" || kind === "trash"}>
    <p className="my-5 max-w-3xl leading-7 text-info-body">{kind === "facts" ? "원문에서 사실을 확인하고 부족한 판단을 입력하세요. 사실 검토를 통과하면 AI 대기 여부를 확인할 수 있습니다." : publicChange ? "공개된 콘텐츠의 원문 변경을 확인합니다. ‘공개 내용 수정·변경 확인’은 현재 공개 글에 직접 반영됩니다." : "AI가 작성한 두 언어의 내용을 확인하세요. 수정 저장은 비공개이며, 최종 공개는 ‘승인하고 게시’로 처리합니다."}</p>
    {loading ? <p className="border-y border-info-rule py-8 text-info-muted" role="status">검토 목록을 불러오는 중입니다.</p> : mode === "local-fixture" && (!error || list.length > 0) ? <p className="mb-6 border-y border-info-rule py-3 text-sm leading-6 text-info-status">로컬 시험 데이터 · 실제 저장·게시 아님 · 서버 재시작 시 시험 내용이 초기화됩니다.</p> : null}
    {error && <div ref={errorMessageBox} tabIndex={-1} role="alert" className="my-5 scroll-mt-36 border-y border-info-rule py-5">
      <p className="max-w-3xl leading-7 text-info-status">{errorMessage}</p>
      {error === "not_connected" && <p className="mt-3 max-w-3xl text-info-body">권한 확인은 완료됐습니다. 연결 전에는 아래 두 검토 단계의 실제 데이터가 표시되지 않습니다.</p>}
      <div className="mt-4 flex flex-wrap gap-4">
        {["signed_out", "forbidden"].includes(error) && <Link prefetch={false} className={secondaryButton} href="/ko/login?next=%2Fko%2Fadmin">로그인 상태 확인</Link>}
        {!item && <button className={secondaryButton} disabled={busy || loading || dirty} onClick={() => { setLoading(true); setError(""); setReload((n) => n + 1); }}>목록 다시 확인</button>}
        {item && <button className={secondaryButton} disabled={busy} onClick={async () => { setBusy(true); try { const data = await call(`/api/admin/review/${kind}/${item.id}`); accept(data.item); setError(""); setNotice(""); } catch (e) { setError(e instanceof RequestFailure ? e.code : "unavailable"); } finally { setBusy(false); } }}>입력을 버리고 최신 내용 불러오기</button>}
      </div>
    </div>}
    {notice && <p ref={resultMessage} tabIndex={-1} role="status" className="my-5 scroll-mt-36 border-y border-info-rule py-4 leading-7 text-info-body">{notice}</p>}
    {!loading && <div className="grid gap-8 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <aside aria-label="검토 목록" className="min-w-0">
        <h2 className="mb-3 text-lg font-bold">{kind === "facts" ? "사실 확인 항목" : "결과 후보"}</h2>
        {!list.length && !error && <p className="py-6 leading-7 text-info-muted">현재 검토할 항목이 없습니다. 새 항목이 준비되면 이 목록에서 확인할 수 있습니다.</p>}
        <ul className="divide-y divide-info-rule border-y border-info-rule">
          {list.map((entry) => <li key={entry.id}><button disabled={busy || dirty || Boolean(confirmation)} aria-current={(item?.id ?? myseoulId ?? programId) === entry.id ? "true" : undefined} className={`w-full px-3 py-5 text-left hover:bg-info-surface disabled:cursor-not-allowed disabled:opacity-60 ${(item?.id ?? myseoulId ?? programId) === entry.id ? "bg-info-surface" : ""}`} onClick={() => select(entry.id)}>
            <span className="block text-sm text-info-status">{statusText[entry.status] ?? "상태 확인 필요"}</span>
            <span className="mt-2 block break-keep font-semibold leading-6">{entry.title}</span>
            <span className="mt-2 block text-sm text-info-muted">{entry.sourceName === "myseoul_program" ? "마이서울플러스" : entry.sourceName === "seoul_reservation" ? "서울 공공서비스예약" : entry.sourceName}</span>
            {entry.reasons.length > 0 && <span className="mt-2 block text-sm leading-6 text-info-body">{entry.sourceName === "myseoul_program" ? myseoulGuidance(entry.reasons[0]) : entry.sourceName === "seoul_reservation" ? programReasonText[entry.reasons[0]] ?? "원문에서 추가 사실을 확인해 주세요." : reasonText(entry.reasons[0]).title}{entry.reasons.length > 1 ? ` 외 ${entry.reasons.length - 1}개` : ""}</span>}
          </button></li>)}
        </ul>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className={secondaryButton} disabled={busy || dirty || Boolean(confirmation) || offset === 0} onClick={() => { setOffset((n) => Math.max(0, n - 25)); setItem(null); setProgramId(null); setMyseoulId(null); setLoading(true); }}>이전 목록</button>
          <button className={secondaryButton} disabled={busy || dirty || Boolean(confirmation) || !hasMore} onClick={() => { setOffset((n) => n + 25); setItem(null); setProgramId(null); setMyseoulId(null); setLoading(true); }}>다음 목록</button>
        </div>
      </aside>
      <section aria-label="선택한 항목 검토" aria-busy={busy} className="min-w-0">
        {myseoulId ? <MySeoulReviewPanel key={myseoulId} id={myseoulId} onBlocked={setProgramBlocked} onResult={programResult}/> : programId ? <ProgramReviewPanel key={programId} id={programId} onBlocked={setProgramBlocked} onResult={programResult}/> : !item ? <p className="py-6 leading-7 text-info-muted">{busy ? "항목을 불러오는 중입니다." : "목록에서 항목을 선택하면 원문과 검토할 내용을 확인할 수 있습니다."}</p> : <>
          <header className="border-b border-info-rule pb-5">
            <p className="text-sm text-info-status">{statusText[item.status]}</p>
            <h2 ref={detailHeading} tabIndex={-1} className="mt-2 scroll-mt-36 break-keep text-2xl font-bold leading-snug">{item.kind === "facts" ? item.source.title : item.content.titleKo}</h2>
            <p className="mt-3 text-sm leading-6 text-info-muted">{item.source.name}{item.kind === "candidates" ? ` · ${item.category ? categories[item.category] : "분류 확인 필요"} · ${item.period}` : ""}</p>
          </header>
          {item.kind === "facts" && <FactsGuidance item={item} />}
          <details className="my-6 border-b border-info-rule pb-6">
            <summary className="min-h-11 cursor-pointer py-2 font-semibold">원문 확인</summary>
            {source ? <a href={source} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center underline underline-offset-4">공식 원문 열기 (새 창)</a> : <p className="mt-3 text-info-muted">원문 링크를 제공할 수 없습니다.</p>}
            <p className="mt-3 whitespace-pre-wrap break-words leading-7 text-info-body">{item.source.body || "저장된 원문 본문이 없습니다. 원문 링크에서 확인해 주세요."}</p>
          </details>
          {item.kind === "candidates" && item.contentNotices && <CandidateContentNotices notices={item.contentNotices} />}
          {item.kind === "candidates" && item.programInfo && <div className="my-5 border-y border-info-rule py-4 text-sm leading-6 text-info-body">
            <p>후보 입력 사실 버전 {item.programInfo.inputFactsVersion} · 현재 사실 버전 {item.programInfo.currentFactsVersion}</p>
            <p>신청 기간: {item.programInfo.applicationPeriod}</p><p>운영 기간: {item.programInfo.operatingPeriod} (한국 시간)</p>
            {item.programInfo.inputChanged && item.source.name !== "myseoul_program" ? <p role="status" className="mt-2 text-info-status">후보 생성 후 사실이 변경되었습니다. 수정 저장·반려는 가능하지만 게시는 차단됩니다. 자동 요약·재번역은 하지 않았으며 사실과 후보의 재대조 기능은 아직 없습니다.</p> : !publicChange && !item.programInfo.canPublish && <p role="status" className="mt-2 text-info-status">현재 접수 상태·판정 또는 수집원 권한으로 게시할 수 없습니다. 수정 저장·반려는 계속할 수 있습니다.</p>}
          </div>}
          {item.kind === "candidates" && item.source.name === "myseoul_program" && item.programInfo?.inputChanged && <section className="my-6 border-y border-info-rule py-5" aria-label="원문 변경 확인">
            <h3 className="font-semibold">생성 이후 원문이 변경됨</h3>
            <p className="mt-2 leading-7 text-info-body">{item.programInfo.changeReviewed ? "현재 원문과의 대조를 완료했습니다. 다른 게시 조건은 계속 검사합니다." : publicChange ? "공개 글을 자동 수정하거나 숨기지 않았습니다. 최신 원문과 두 언어의 내용을 대조해 주세요." : "후보를 자동 수정하지 않았습니다. 최신 원문을 확인하고 필요한 내용을 수정하거나 영향 없음을 기록해 주세요."}</p>
            <p className="mt-2 text-sm text-info-body">확인할 항목: {item.programInfo.changedFields?.join(" · ") || "본문 또는 입력 사실 변경"}</p>
            {publicChange && item.publishedSlug && <Link prefetch={false} className="mt-3 inline-flex min-h-11 items-center underline underline-offset-4" href={`/ko/info/${encodeURIComponent(item.publishedSlug)}`} target="_blank" rel="noopener noreferrer">관련 공개 콘텐츠 열기 (새 창)</Link>}
            {!item.programInfo.comparisonAvailable && <p className="mt-2 text-sm text-info-muted">생성 당시 비교 자료가 없어 정확한 변경 비교가 불가능합니다. 공식 원문을 확인해 주세요.</p>}
            <label htmlFor="change-review-note" className="mt-4 block font-semibold">최신 원문 대조·처리 근거</label>
            <textarea id="change-review-note" className={fieldClass} rows={3} maxLength={4000} disabled={busy || Boolean(confirmation)} value={changeNote} onChange={e => setChangeNote(e.target.value)} />
            <p className="mt-2 text-sm leading-6 text-info-muted">수정한 경우 아래 한국어·일본어 편집값을 함께 저장합니다.{publicChange && " 현재 공개 글에 직접 반영됩니다."}</p>
            <button type="button" className={`${secondaryButton} mt-4`} disabled={busy || imageDirty || Boolean(confirmation) || !changeNote.trim()} onClick={() => void submit({ ...preconditions(), action: "review_change", disposition: contentDirty ? "edited" : "no_impact", note: changeNote, ...(contentDirty && content ? { content } : {}) })}>{busy ? "처리 중…" : fieldsDirty ? publicChange ? "공개 내용 수정·변경 확인" : "수정 저장·변경 확인" : "내용 영향 없음·변경 확인"}</button>
          </section>}
          <form onSubmit={(event) => { event.preventDefault(); if (!item || busy || processed || confirmation || publicChange) return; if (item.kind === "facts" && facts) void submit({ ...preconditions(), action: "save_facts", facts, ...(item.restoredReviewPending ? { confirmRestored: true } : {}) }); else if (content && !invalidImage) void submit({ ...preconditions(), action: "save_candidate", content, ...(imageEditable && imageSelection ? { imageSelection } : {}) }); }}>
            {imageEditable && item.kind === "candidates" && item.image && imageSelection && <CandidateImageEditor key={item.id + item.version} saved={item.image} value={imageSelection} onChange={setImageSelection} disabled={locked} error={errors.imageUrl} title={content?.titleKo ?? item.content.titleKo} />}
            {item.kind === "facts" && facts ? <FactsEditor value={facts} onChange={setFacts} errors={errors} disabled={locked} editableFields={item.editableFields} reasons={item.reasons} sourceUrl={item.source.url} /> : content && <CandidateEditor value={content} onChange={setContent} errors={errors} disabled={locked} />}
            {fieldsDirty && <p className="mt-6 leading-7 text-info-status">아직 저장하지 않은 변경이 있습니다. 다른 항목으로 이동하거나 게시하려면 저장하거나 수정을 취소해 주세요.</p>}
            {!processed && <div className="my-7 flex flex-wrap gap-3">
              <button type="submit" disabled={publicChange || busy || Boolean(invalidImage) || Boolean(confirmation) || (!fieldsDirty && !(item.kind === "facts" && item.restoredReviewPending))} className={primaryButton}>{busy ? "처리 중…" : item.kind === "facts" ? "사실 저장·재평가" : "수정 저장"}</button>
              {dirty && <button type="button" className={secondaryButton} disabled={busy} onClick={() => { accept(item); setError(""); setNotice(""); }}>수정 취소</button>}
              {item.kind === "candidates" && item.status === "pending" && <button type="button" className={secondaryButton} disabled={busy || dirty || Boolean(confirmation) || (item.kind === "candidates" && Boolean(item.programInfo && !item.programInfo.canPublish))} onClick={() => setConfirmation("publish")}>승인하고 게시</button>}
            </div>}
          </form>
          {!processed && !publicChange && (item.kind === "candidates" || item.excludeAllowed !== false) && <section className="border-t border-info-rule pt-6">
              {item.kind === "facts" && <><h3 className="font-bold">빠른 제외</h3><p className="mt-2 text-sm leading-6 text-info-muted">사유를 자동 기록하고 휴지통으로 이동합니다. 72시간 이내에 복구할 수 있습니다.</p>
              <div className="my-4 flex flex-wrap gap-3">{Object.entries(quickReasons).map(([code, label]) => <button key={code} type="button" className={secondaryButton} disabled={locked || fieldsDirty || Boolean(note)} onClick={() => void submit({ ...preconditions(), action: "exclude", reasonCode: code as QuickReason, note: "" })}>{label} · 제외</button>)}</div></>}
            <h3 className="text-lg font-bold">{item.kind === "facts" ? "부적격으로 제외" : "후보 반려"}</h3>
            <p className="mt-2 leading-7 text-info-muted">{item.kind === "facts" ? "대상이 아니거나 사실을 끝내 확인할 수 없다면 제외 사유를 남겨 주세요." : "공개하기 어려운 후보라면 반려 사유를 남겨 주세요."}</p>
            <label htmlFor="review-note" className="mt-4 block font-semibold">{item.kind === "facts" ? "제외 사유" : "반려 사유"}</label>
            <textarea id="review-note" className={fieldClass} rows={3} value={note} maxLength={item.kind === "facts" ? 500 : 4000} disabled={busy || Boolean(confirmation)} aria-invalid={Boolean(errors.note)} aria-describedby={errors.note ? "note-error" : undefined} onChange={(e) => setNote(e.target.value)} />
            {errors.note && <p id="note-error" className="mt-2 text-sm text-info-status">{errors.note}</p>}
            <button type="button" className={`${secondaryButton} mt-4`} disabled={busy || fieldsDirty || !note.trim() || Boolean(confirmation)} onClick={() => setConfirmation(item.kind === "facts" ? "exclude" : "reject")}>{item.kind === "facts" ? "사유를 남기고 제외" : "사유를 남기고 반려"}</button>
          </section>}
          {confirmation && <section ref={confirmationBox} tabIndex={-1} aria-label="최종 처리 확인" className="mt-8 scroll-mt-36 border-y border-info-rule bg-info-surface px-5 py-6">
            <h3 className="text-xl font-bold">{confirmation === "publish" ? "저장된 최종 내용으로 게시할까요?" : confirmation === "exclude" ? "이 항목을 제외할까요?" : "이 후보를 반려할까요?"}</h3>
            <p className="mt-3 leading-7 text-info-body">{confirmation === "publish" ? `위에 표시된 한국어·일본어 저장본을 승인하고 게시합니다. 승인자·시각과 게시 이력을 함께 기록합니다.${mode === "local-fixture" ? " 현재는 실제 공개 없이 로컬 시험으로 처리됩니다." : ""}` : `기록할 사유: ${note}`}</p>
            <div className="mt-5 flex flex-wrap gap-3"><button className={primaryButton} disabled={busy} onClick={() => void submit(confirmation === "publish" ? { ...preconditions(), action: "publish" } : { ...preconditions(), action: confirmation, note })}>{busy ? "처리 중…" : confirmation === "publish" ? "확인하고 게시" : "확인하고 처리"}</button><button className={secondaryButton} disabled={busy} onClick={() => setConfirmation(null)}>돌아가기</button></div>
          </section>}
          {item.kind === "candidates" && item.publishedAt && <p className="mt-7 text-info-body">{mode === "local-fixture" ? "시험 게시" : "게시"} 시각: {time(item.publishedAt)} (한국 시간)</p>}
          {item.kind === "candidates" && <details className="mt-10 border-t border-info-rule pt-4" open={item.history.length > 0}>
            <summary className="min-h-11 cursor-pointer py-2 font-semibold">저장·처리 이력 ({item.history.length})</summary>
            {item.history.length ? <ol className="divide-y divide-info-rule">{item.history.map((entry, index) => <li key={index} className="py-4 text-sm leading-6"><p className="font-semibold">{entry.changeLabel ?? actionText[entry.action] ?? "처리 기록"} · {time(entry.at)} (한국 시간)</p><p className="break-all text-info-muted">작업 계정: {entry.actor}</p>{entry.note && <p className="mt-1 whitespace-pre-wrap break-words text-info-body">{entry.note}</p>}</li>)}</ol> : <p className="py-3 text-info-muted">아직 저장·처리 이력이 없습니다.</p>}
          </details>}
        </>}
      </section>
    </div>}
    </div>
  </div>;
}
