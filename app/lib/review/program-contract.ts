import { ReviewFailure } from "./contracts";

export const programFields = ["schema_version", "content_kind", "application_actor", "delivery_mode", "activity_region", "activity_evidence", "residence_scope", "residence_evidence", "target_raw", "conditions", "application_methods", "fee_kind", "fee_amounts", "source_status", "conflicts", "missing", "editorial_pending", "period_evidence", "periods", "official_url", "description"] as const;
export const patchFields = ["content_kind", "application_actor", "delivery_mode", "activity_region", "activity_evidence", "residence_scope", "residence_evidence", "target_raw", "conditions", "application_methods", "fee_kind", "fee_amounts", "source_status", "period_evidence", "periods", "official_url", "description"] as const;
export type ProgramField = typeof programFields[number];
export type ProgramFacts = Record<ProgramField, string | string[] | Record<string, Period>>;
export type Period = { raw: string | null; value: string | null; status: string; precision: string | null };
export type ProgramCommand = { action: "save_facts" | "exclude"; revision: string; version: string; note: string; patch?: Partial<ProgramFacts>; resolve?: string[] };
export const programReasonText: Record<string, string> = {
  activity_location_unknown: "실제 개최지를 확인하고 서울·경기·인천 여부와 원문 근거를 입력해 주세요.",
  delivery_mode_unknown: "온라인 예약과 온라인 진행을 구분해 실제 진행 방식·개최지를 입력해 주세요.",
  residence_scope_unknown: "온라인 프로그램의 거주 지역 조건을 확인해 전국 또는 수도권 포함 여부를 입력해 주세요.",
  program_purpose_unconfirmed: "문화·생활교육·체험·교류 등 개인이 이용할 프로그램인지 본문 근거를 확인해 주세요.",
  policy_eligibility_unconfirmed: "정책·금융은 일반 프로그램처럼 자격을 추정할 수 없습니다. 실제 프로그램으로 잘못 분류됐는지 확인해 주세요.",
  attachment_dependent: "이미지·첨부에서 필요한 프로그램 설명을 확인하고 사실과 근거를 입력해 주세요.",
  program_description_missing: "공통 이용안내 외의 프로그램 설명·장소·신청 방법을 확인해 입력해 주세요.",
  missing_source_url: "서울 예약의 공식 상세 링크를 확인해 입력해 주세요.",
  source_status_unknown: "현재 접수 상태를 공식 원문에서 확인해 입력해 주세요.",
  source_status_conflict: "API와 본문의 접수 상태가 다릅니다. 현재 상태와 판단 근거를 입력해 주세요.",
  application_actor_conflict: "개인 신청 가능과 기관 전용 안내가 충돌합니다. 실제 신청 주체와 조건을 확인해 주세요.",
  target_conflict: "대상 필드와 본문의 연령·참여 조건이 다릅니다. 확인한 조건을 입력해 주세요.",
  fee_conflict: "무료·유료 안내가 다릅니다. 확인한 비용 구분·금액과 근거를 입력해 주세요.",
  eligibility_document_unconfirmed: "필수 증빙 조건을 확인해 실제 요구사항과 근거를 기록해 주세요. 외국인 참여를 임의 보장하지 마세요.",
};
for (const code of ["period_missing_or_unparsed", "body_period_needs_confirmation", "period_order_conflict", "body_api_period_conflict", "invalid_body_date", "date_weekday_conflict"]) programReasonText[code] = "신청 기간과 운영 기간·요일의 부족 또는 충돌을 확인해 각각의 날짜·시간과 판단 근거를 입력해 주세요.";

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ReviewFailure("invalid_input");
  return value as Record<string, unknown>;
}
function text(value: unknown, max = 60000): string {
  if (typeof value !== "string" || value.length > max) throw new ReviewFailure("invalid_input");
  return value;
}
export function strings(value: unknown, limit = 200): string[] {
  if (!Array.isArray(value) || value.length > limit) throw new ReviewFailure("invalid_input");
  return value.map((x) => text(x, 4000));
}
const enums: Record<string, string[]> = {
  schema_version: ["program-scope-v1-local"], content_kind: ["program", "unknown", "employment", "institutional_business", "policy_finance"],
  application_actor: ["individual", "individual_or_group", "institution", "nationality_excluded"], delivery_mode: ["online", "offline", "hybrid", "unknown"],
  activity_region: ["capital", "noncapital", "mixed", "not_applicable", "unknown"], residence_scope: ["nationwide", "includes_capital", "capital", "noncapital", "not_stated", "unknown"],
  fee_kind: ["free", "paid", "unknown"], source_status: ["open", "reservation_closed", "application_closed", "unknown"],
};
const arrayFields = new Set(["activity_evidence", "residence_evidence", "conditions", "application_methods", "fee_amounts", "conflicts", "missing", "editorial_pending", "period_evidence"]);
function value(field: string, input: unknown) {
  if (arrayFields.has(field)) return strings(input);
  if (field === "periods") {
    const p = object(input); const out: Record<string, Period> = {};
    const names = ["RCPTBGNDT", "RCPTENDDT", "SVCOPNBGNDT", "SVCOPNENDDT"];
    if (Object.keys(p).length !== 4 || Object.keys(p).some((k) => !names.includes(k))) throw new ReviewFailure("invalid_input");
    for (const name of names) {
      const d = object(p[name]); const status = text(d.status, 20);
      if (!["ok", "missing", "unparsed"].includes(status)) throw new ReviewFailure("invalid_input");
      const nullable = (x: unknown) => x === null ? null : text(x, 1000);
      out[name] = { raw: nullable(d.raw), value: nullable(d.value), status, precision: nullable(d.precision) };
      if (status === "ok" && (!out[name].value || !["day", "second"].includes(out[name].precision ?? ""))) throw new ReviewFailure("invalid_input");
    }
    return out;
  }
  const t = text(input);
  if (enums[field] && !enums[field].includes(t)) throw new ReviewFailure("invalid_input");
  if (field === "official_url" && t !== "") {
    let u: URL; try { u = new URL(t); } catch { throw new ReviewFailure("invalid_input"); }
    if (!["http:", "https:"].includes(u.protocol) || u.hostname !== "yeyak.seoul.go.kr" || u.username || u.password || u.port || u.hash || u.pathname !== "/web/reservation/selectReservView.do" || !/^[A-Za-z0-9_-]+$/.test(u.searchParams.get("rsv_svc_id") ?? "") || [...u.searchParams.keys()].length !== 1) throw new ReviewFailure("invalid_input");
  }
  return t;
}
export function programFacts(input: unknown): ProgramFacts {
  const obj = object(input);
  // Explicit field projection; never forward provider fields or raw HTML.
  return Object.fromEntries(programFields.map((k) => [k, value(k, obj[k])])) as ProgramFacts;
}
export function programCommand(input: unknown): ProgramCommand {
  const obj = object(input); const action = obj.action;
  const keys = action === "save_facts" ? ["action", "revision", "version", "note", "patch", "resolve"] : ["action", "revision", "version", "note"];
  if (!["save_facts", "exclude"].includes(String(action)) || Object.keys(obj).some((k) => !keys.includes(k))) throw new ReviewFailure("invalid_input");
  const revision = text(obj.revision, 64), version = text(obj.version, 64), note = text(obj.note, 4000).trim();
  if (!/^[a-f0-9]{64}$/.test(revision) || !/^[a-f0-9]{64}$/.test(version) || !note) throw new ReviewFailure("invalid_input");
  const command: ProgramCommand = { action: action as ProgramCommand["action"], revision, version, note };
  if (action === "save_facts") {
    const patch = object(obj.patch);
    if (!Object.keys(patch).length || Object.keys(patch).some((k) => !(patchFields as readonly string[]).includes(k))) throw new ReviewFailure("invalid_input");
    command.patch = Object.fromEntries(Object.entries(patch).map(([k, v]) => [k, value(k, v)]));
    command.resolve = strings(obj.resolve, 30);
  }
  return command;
}
