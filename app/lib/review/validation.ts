import { sourceImageUrl } from "../sourceImages";
import { ReviewFailure } from "./contracts";
import type { CandidateContent, Facts, ReviewCommand, ReviewKind } from "./contracts";

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ReviewFailure("invalid_input");
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, keys: string[]) {
  if (Object.keys(value).some((key) => !keys.includes(key)) || keys.some((key) => !(key in value))) throw new ReviewFailure("invalid_input");
}
function date(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export function validateFacts(value: unknown): Facts {
  const f = object(value);
  exact(f, ["productType", "category", "scope", "regions", "evidence", "foreignEligibility", "delivery", "deadlineKind", "deadlineOn", "eventStart", "eventEnd"]);
  const errors: Record<string, string> = {};
  const choices: Record<string, string[]> = {
    productType: ["", "event_program", "policy_reference", "living_guide"],
    category: ["", "policy", "program", "event", "youth_space", "living"],
    scope: ["nationwide", "specific", "unknown"], foreignEligibility: ["eligible", "ineligible", "unknown"],
    delivery: ["online", "offline", "hybrid", "unknown"], deadlineKind: ["", "fixed", "none", "closed"],
  };
  for (const [key, values] of Object.entries(choices)) if (typeof f[key] !== "string" || !values.includes(f[key] as string)) errors[key] = "선택지에서 값을 골라 주세요.";
  for (const key of ["evidence", "deadlineOn", "eventStart", "eventEnd"]) if (typeof f[key] !== "string") errors[key] = "입력한 값을 확인해 주세요.";
  if (typeof f.evidence === "string" && f.evidence.length > 500) errors.evidence = "근거는 500자 이내로 입력해 주세요.";
  if (!Array.isArray(f.regions) || f.regions.length > 17 || f.regions.some((r) => typeof r !== "string" || !/^(11|26|27|28|29|30|31|36|41|42|43|44|45|46|47|48|50)$/.test(r))) errors.regions = "대상 지역을 선택해 주세요.";
  if (f.scope === "specific" && Array.isArray(f.regions) && f.regions.length === 0) errors.regions = "특정 지역이라면 지역을 하나 이상 선택해 주세요.";
  if (f.scope !== "specific" && Array.isArray(f.regions) && f.regions.length) errors.regions = "전국 또는 확인 필요일 때 특정 지역을 선택할 수 없습니다.";
  const deadlineCategory = f.category === "policy" || f.category === "program";
  if (deadlineCategory && f.deadlineKind === "fixed" && (typeof f.deadlineOn !== "string" || !date(f.deadlineOn))) errors.deadlineOn = "유효한 신청 마감일을 입력해 주세요.";
  if ((!deadlineCategory || f.deadlineKind !== "fixed") && f.deadlineOn !== "") errors.deadlineOn = "마감일이 있는 정책·프로그램에만 날짜를 입력해 주세요.";
  if (!deadlineCategory && f.deadlineKind !== "") errors.deadlineKind = "이 카테고리는 신청 마감 입력 대상이 아닙니다.";
  if (f.category === "event") {
    for (const key of ["eventStart", "eventEnd"]) if (f[key] !== "" && (typeof f[key] !== "string" || !date(f[key] as string))) errors[key] = "유효한 개최일을 입력해 주세요.";
    if (Boolean(f.eventStart) !== Boolean(f.eventEnd)) errors.eventEnd = "시작일과 종료일을 함께 입력하거나 모두 확인 필요로 남겨 주세요.";
    if (typeof f.eventStart === "string" && typeof f.eventEnd === "string" && f.eventStart > f.eventEnd) errors.eventEnd = "종료일은 시작일보다 빠를 수 없습니다.";
  } else if (f.eventStart !== "" || f.eventEnd !== "") errors.eventStart = "행사 카테고리에만 개최 기간을 입력해 주세요.";
  if (Object.keys(errors).length) throw new ReviewFailure("invalid_input", errors);
  return { ...(f as Facts), regions: [...new Set(f.regions as string[])] };
}
export function validateContent(value: unknown): CandidateContent {
  const c = object(value);
  const errors: Record<string, string> = {};
  const limits = { titleKo: 300, titleJa: 300, summaryKo: 1000, summaryJa: 1000, contentKo: 200000, contentJa: 200000 };
  exact(c, Object.keys(limits));
  for (const [key, limit] of Object.entries(limits)) {
    if (typeof c[key] !== "string" || !(c[key] as string).trim()) errors[key] = "내용을 입력해 주세요.";
    else if ((c[key] as string).trim().length > limit) errors[key] = `${limit.toLocaleString("ko-KR")}자 이내로 입력해 주세요.`;
  }
  if (Object.keys(errors).length) throw new ReviewFailure("invalid_input", errors);
  return Object.fromEntries(Object.keys(limits).map((key) => [key, (c[key] as string).trim()])) as CandidateContent;
}
export function validateCommand(kind: ReviewKind, value: unknown): ReviewCommand {
  const v = object(value);
  if (typeof v.revision !== "string" || !/^[0-9a-f]{64}$/.test(v.revision) || typeof v.version !== "string" || !v.version || v.version.length > 128) throw new ReviewFailure("invalid_input");
  const preconditions = { revision: v.revision, version: v.version };
  if (kind === "facts" && v.action === "save_facts") {
    exact(v, ["action", "revision", "version", "facts", ...(v.confirmRestored === true ? ["confirmRestored"] : [])]);
    return { ...preconditions, action: "save_facts", facts: validateFacts(v.facts), ...(v.confirmRestored === true ? { confirmRestored: true as const } : {}) };
  }
  if (kind === "candidates" && v.action === "save_candidate") {
    exact(v, ["action", "revision", "version", "content", ...(Object.hasOwn(v, "imageSelection") ? ["imageSelection"] : [])]);
    let imageSelection;
    if (Object.hasOwn(v, "imageSelection")) {
      const i = object(v.imageSelection); exact(i, ["mode", "url"]);
      if (!["source", "override", "none"].includes(String(i.mode)) ||
          (i.mode === "override" ? !sourceImageUrl(i.url) : i.url !== null))
        throw new ReviewFailure("invalid_input", { imageUrl: "사용 가능한 HTTPS 이미지 URL을 입력해 주세요." });
      imageSelection = { mode: i.mode as "source" | "override" | "none", url: i.mode === "override" ? sourceImageUrl(i.url) : null };
    }
    return { ...preconditions, action: "save_candidate", content: validateContent(v.content), ...(imageSelection ? { imageSelection } : {}) };
  }
  if (kind === "candidates" && v.action === "review_change") {
    const edited = v.disposition === "edited";
    exact(v, ["action", "revision", "version", "disposition", "note", ...(edited ? ["content"] : [])]);
    if (!["no_impact", "edited"].includes(String(v.disposition)) || typeof v.note !== "string" || !v.note.trim() || v.note.trim().length > 4000) throw new ReviewFailure("invalid_input");
    return { ...preconditions, action: "review_change", disposition: edited ? "edited" : "no_impact", note: v.note.trim(), ...(edited ? { content: validateContent(v.content) } : {}) };
  }
  if (kind === "candidates" && v.action === "publish") {
    exact(v, ["action", "revision", "version"]);
    return { ...preconditions, action: "publish" };
  }
  if ((kind === "facts" && v.action === "exclude") || (kind === "candidates" && v.action === "reject")) {
    exact(v, ["action", "revision", "version", "note"]);
    const max = v.action === "exclude" ? 500 : 4000;
    if (typeof v.note !== "string" || !v.note.trim() || v.note.trim().length > max) throw new ReviewFailure("invalid_input", { note: `사유를 1~${max}자로 입력해 주세요.` });
    return { ...preconditions, action: v.action, note: v.note.trim() };
  }
  throw new ReviewFailure("invalid_input");
}
