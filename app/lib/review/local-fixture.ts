// Local test double only. This is NOT the operational evaluator or a DB adapter.
import { ReviewFailure } from "./contracts";
import type { Facts, FactsItem, CandidateItem, ReviewItem, ReviewKind, ReviewStore, ReviewCommand } from "./contracts";

export function fixtureFacts(): Facts {
  return { productType: "policy_reference", category: "policy", scope: "unknown", regions: [], evidence: "", foreignEligibility: "unknown", delivery: "unknown", deadlineKind: "", deadlineOn: "", eventStart: "", eventEnd: "" };
}
function sampleItems(): ReviewItem[] {
  const base = { revision: "a".repeat(64), version: "1", history: [], source: { name: "로컬 시험 출처", title: "청년 생활 지원 신청 안내 (가상 자료)", url: "https://example.invalid/local-review", body: "이 자료는 화면 검증용 가상 원문입니다.\n신청 대상: 서울 거주 청년, 외국인 거주자 포함\n접수 마감: 2026년 10월 20일\n\n실제 기관의 공고나 운영 데이터를 사용하지 않습니다." } };
  const facts: FactsItem = { ...base, id: "10000000-0000-4000-8000-000000000001", kind: "facts", facts: fixtureFacts(), reasons: ["region_scope_unknown", "relevance_unconfirmed", "application_deadline_unknown"], status: "open", aiStatus: "blocked" };
  const event: FactsItem = { ...structuredClone(facts), id: "10000000-0000-4000-8000-000000000002", source: { ...base.source, title: "한·일 청년 교류 행사 (가상 자료)", body: "로컬 시험용 원문입니다.\n이용 대상: 전국 청년\n개최 기간: 2026년 10월 24일~25일\n신청 기간과 개최 기간은 별도입니다." }, facts: { ...fixtureFacts(), productType: "event_program", category: "event", scope: "nationwide" }, reasons: ["event_period_unknown"] };
  const candidate: CandidateItem = { ...structuredClone(base), id: "20000000-0000-4000-8000-000000000001", kind: "candidates", status: "pending", category: "policy", period: "신청 마감: 2026.10.20", publishedAt: null, publishedId: null, content: { titleKo: "청년 생활 지원 신청 안내", summaryKo: "서울 거주 청년을 위한 지원 신청 정보를 확인하세요.", contentKo: "## 신청 대상\n서울 거주 청년으로 외국인 거주자도 신청할 수 있습니다.\n\n## 신청 기간\n2026년 10월 20일까지입니다.\n\n이 내용은 로컬 시험용입니다.", titleJa: "若者向け生活支援の申請案内", summaryJa: "ソウル在住の若者向けの申請情報をご確認ください。", contentJa: "## 申請対象\nソウル在住の若者。外国人住民も申請できます。\n\n## 申請期間\n2026年10月20日までです。\n\nローカルテスト用の内容です。" } };
  return [facts, event, candidate];
}
export class LocalReviewStore implements ReviewStore {
  readonly mode = "local-fixture" as const;
  private items: Map<string, ReviewItem>;
  private blockedPublications = new Set<string>();
  constructor() { this.items = new Map(sampleItems().map((item) => [item.id, item])); }
  async list(kind: ReviewKind, offset = 0) {
    return [...this.items.values()].filter((item) => item.kind === kind).slice(offset, offset + 25).map((item) => ({ id: item.id, title: item.kind === "facts" ? item.source.title : item.content.titleKo, sourceName: item.source.name, status: item.status, reasons: item.kind === "facts" ? [...item.reasons] : [] }));
  }
  async get(kind: ReviewKind, id: string) {
    const item = this.items.get(id);
    if (!item || item.kind !== kind) throw new ReviewFailure("not_found");
    return structuredClone(item);
  }
  // Failure injection belongs to tests, never to a UI/request payload.
  blockPublication(id: string) { this.blockedPublications.add(id); }
  advanceRevision(id: string) { const item = this.items.get(id); if (item) item.revision = "b".repeat(64); }
  async execute(kind: ReviewKind, id: string, command: ReviewCommand, actor: string) {
    const existing = this.items.get(id);
    if (!existing || existing.kind !== kind) throw new ReviewFailure("not_found");
    if (existing.revision !== command.revision || existing.version !== command.version) throw new ReviewFailure("conflict");
    if ((existing.kind === "facts" && existing.status !== "open") || (existing.kind === "candidates" && existing.status !== "pending")) throw new ReviewFailure("already_processed");
    const item = structuredClone(existing);
    const now = new Date().toISOString();
    if (item.kind === "facts" && command.action === "save_facts") {
      item.facts = structuredClone(command.facts);
      const f = item.facts;
      const unsupported = item.reasons.filter((r) => !["product_type_unknown", "product_type_unconfirmed", "region_scope_unknown", "relevance_unconfirmed", "user_category_unconfirmed", "application_deadline_unknown", "event_period_unknown"].includes(r));
      item.reasons = [...unsupported];
      if (!f.productType) item.reasons.push("product_type_unknown");
      if (f.productType !== "living_guide" && f.scope === "unknown") item.reasons.push("region_scope_unknown");
      if (f.productType === "policy_reference" && f.foreignEligibility === "unknown") item.reasons.push("relevance_unconfirmed");
      if (!f.category) item.reasons.push("user_category_unconfirmed");
      if (["policy", "program"].includes(f.category) && !f.deadlineKind) item.reasons.push("application_deadline_unknown");
      if (f.category === "event" && (!f.eventStart || !f.eventEnd)) item.reasons.push("event_period_unknown");
      const nonTarget = (f.productType === "policy_reference" && f.foreignEligibility === "ineligible") || (f.productType !== "living_guide" && f.scope === "specific" && !f.regions.some((r) => ["11", "28", "41"].includes(r)));
      if (nonTarget) { item.status = "excluded"; item.aiStatus = "cancelled"; }
      else { item.status = item.reasons.length ? "open" : "resolved"; item.aiStatus = item.reasons.length ? "blocked" : "queued"; }
    } else if (item.kind === "facts" && command.action === "exclude") {
      item.status = "excluded"; item.aiStatus = "cancelled"; item.reasons = ["manual_non_target"];
    } else if (item.kind === "candidates" && command.action === "save_candidate") {
      item.content = structuredClone(command.content);
    } else if (item.kind === "candidates" && command.action === "reject") {
      item.status = "rejected";
    } else if (item.kind === "candidates" && command.action === "publish") {
      if (this.blockedPublications.has(id)) throw new ReviewFailure("publish_failed");
      item.status = "published"; item.publishedAt = now; item.publishedId = "30000000-0000-4000-8000-000000000001";
    } else throw new ReviewFailure("invalid_input");
    item.version = String(Number(item.version) + 1);
    item.history.push({ action: command.action, actor, at: now, note: "note" in command ? command.note : "" });
    this.items.set(id, item); // One synchronous commit, no await between check and commit.
    return structuredClone(item);
  }
}
