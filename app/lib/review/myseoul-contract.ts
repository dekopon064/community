import { ReviewFailure } from "./contracts";

export const myseoulSchema = "myseoul-program-facts-v1-local";
export const myseoulProfile = "myseoul-program-v1-local";
export const myseoulPatchFields = ["description", "target", "conditions", "application_actor", "delivery_mode", "activity_region", "venue", "activity_evidence", "residence_scope", "residence", "residence_evidence", "public_category", "purpose", "qualification_note", "periods", "session_evidence", "application_methods", "application_links", "fees", "source_status"] as const;
export type MySeoulField = typeof myseoulPatchFields[number];
type Endpoint = { value: string; precision: "day" | "minute" };
export type MySeoulPeriod = { raw: string; status: string; endpoints: Endpoint[]; origin: string; label: string };
export type MySeoulIssue = { code: string; field: string; evidence: string[] };
export type MySeoulFacts = Record<string, unknown>;
export type MySeoulCommand = { action: "save_facts"; revision: string; version: string; patch: Partial<Record<MySeoulField, unknown>> } | { action: "exclude"; revision: string; version: string; note: string };

export function myObject(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new ReviewFailure("invalid_input");
  return v as Record<string, unknown>;
}
export function myText(v: unknown, max = 60000): string {
  if (typeof v !== "string" || v.length > max || /<[/!A-Za-z][^>]*>/.test(v)) throw new ReviewFailure("invalid_input");
  return v;
}
export function myStrings(v: unknown, limit = 200): string[] {
  if (!Array.isArray(v) || v.length > limit) throw new ReviewFailure("invalid_input");
  return v.map(x => myText(x, 4000));
}
function exact(o: Record<string, unknown>, fields: string[]) {
  if (Object.keys(o).length !== fields.length || fields.some(k => !Object.hasOwn(o, k))) throw new ReviewFailure("invalid_input");
}
export function myseoulOfficialUrl(v: unknown) {
  const s = myText(v, 500);
  if (!/^https:\/\/global\.seoul\.go\.kr\/hmpg\/ecpr\/prgm\/prgmDetail\.do\?cntr_no=[A-F0-9]{32}&prgrm_no=[A-F0-9]{32}&lang=ko$/.test(s)) throw new ReviewFailure("invalid_input");
  return s;
}
const enums: Record<string, string[]> = {
  public_category: ["program", "event", "unknown"], application_actor: ["individual", "institution_only", "unknown"],
  delivery_mode: ["online", "offline", "mixed", "unknown", "course_unresolved"], activity_region: ["capital", "noncapital", "unknown"],
  residence_scope: ["nationwide", "includes_capital", "capital", "noncapital_only", "unknown"],
};
const arrays = new Set(["conditions", "activity_evidence", "residence_evidence", "session_evidence", "application_methods", "application_links", "source_status"]);
function fieldValue(k: string, v: unknown): unknown {
  if (k === "periods") {
    const o = myObject(v); exact(o, ["application", "operation"]);
    return Object.fromEntries(["application", "operation"].map(name => {
      if (!Array.isArray(o[name]) || o[name].length > 50) throw new ReviewFailure("invalid_input");
      return [name, o[name].map(raw => {
        const p = myObject(raw); exact(p, ["raw", "status", "endpoints", "origin", "label"]);
        const status = myText(p.status, 20), origin = myText(p.origin, 20);
        if (!["ok", "missing", "unparsed"].includes(status) || !["header", "body", "operator"].includes(origin) || !Array.isArray(p.endpoints) || p.endpoints.length > 50 || status === "ok" && ![1, 2].includes(p.endpoints.length)) throw new ReviewFailure("invalid_input");
        const endpoints = p.endpoints.map(raw => {
          const e = myObject(raw); exact(e, ["value", "precision"]);
          const value = myText(e.value, 100), precision = myText(e.precision, 10);
          if (!(precision === "day" && /^\d{4}-\d{2}-\d{2}$/.test(value) || precision === "minute" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+09:00$/.test(value))) throw new ReviewFailure("invalid_input");
          return { value, precision };
        });
        return { raw: myText(p.raw, 4000), status, endpoints, origin, label: myText(p.label, 100) };
      })];
    }));
  }
  if (k === "fees") {
    if (!Array.isArray(v) || v.length > 200) throw new ReviewFailure("invalid_input");
    return v.map(raw => { const o = myObject(raw); exact(o, ["component", "evidence"]); const component = myText(o.component, 20), evidence = myStrings(o.evidence);
      if (!["tuition", "admission", "materials", "extra_fee"].includes(component) || !evidence.length) throw new ReviewFailure("invalid_input");
      return { component, evidence };
    });
  }
  if (arrays.has(k)) {
    const values = myStrings(v);
    if (k === "application_links") for (const s of values) {
      let u: URL; try { u = new URL(s); } catch { throw new ReviewFailure("invalid_input"); }
      if (u.protocol !== "https:" || u.username || u.password || /(?:token|secret|password|api[_-]?key)=/i.test(s)) throw new ReviewFailure("invalid_input");
    }
    return values;
  }
  const s = myText(v);
  if (enums[k] && !enums[k].includes(s)) throw new ReviewFailure("invalid_input");
  return s;
}
export function myseoulFacts(raw: unknown): MySeoulFacts {
  const o = myObject(raw);
  if (o.schema_version !== myseoulSchema || o.parser_version !== "myseoul-html-v2-local" || o.revision_contract !== "myseoul-semantic-v2" || !/^[a-f0-9]{64}$/.test(myText(o.source_revision, 64))) throw new ReviewFailure("invalid_input");
  const out: MySeoulFacts = Object.fromEntries(myseoulPatchFields.map(k => [k, fieldValue(k, o[k])]));
  Object.assign(out, { schema_version: myseoulSchema, parser_version: o.parser_version, revision_contract: o.revision_contract, source_revision: o.source_revision, official_url: myseoulOfficialUrl(o.official_url), source_category: o.source_category === null ? null : myText(o.source_category, 500) });
  for (const k of ["age", "companion", "language", "meeting_evidence", "early_close_evidence", "capacity_raw", "missing", "scope_exclusions"]) out[k] = myStrings(o[k]);
  if (o.capacity_value !== null) throw new ReviewFailure("invalid_input");
  out.capacity_value = null;
  if (!Array.isArray(o.issues) || o.issues.length > 200) throw new ReviewFailure("invalid_input");
  out.issues = o.issues.map(raw => { const i = myObject(raw); exact(i, ["code", "field", "evidence"]); const code = myText(i.code, 100), field = myText(i.field, 100);
    if (!/^[a-z_]+(?::[a-z_]+)?$/.test(code) || !/^[a-z_]+$/.test(field)) throw new ReviewFailure("invalid_input");
    return { code, field, evidence: myStrings(i.evidence) };
  });
  // Preserve only known inert evidence fields; never raw HTML/payload.
  if (!Array.isArray(o.evidence) || o.evidence.length > 200 || !Array.isArray(o.conflicts) || o.conflicts.length > 200) throw new ReviewFailure("invalid_input");
  out.evidence = o.evidence.map(raw => { const e = myObject(raw); return { field: myText(e.field, 100), label: myText(e.label, 100), value: myText(e.value, 4000), origin: myText(e.origin, 20) }; });
  out.conflicts = o.conflicts.map(raw => { const c = myObject(raw); return { field: myText(c.field, 100), labels: myStrings(c.labels), header: myStrings(c.header), body: myStrings(c.body) }; });
  return out;
}
export function myseoulCommand(raw: unknown): MySeoulCommand {
  const o = myObject(raw), action = o.action;
  if (!["save_facts", "exclude"].includes(String(action))) throw new ReviewFailure("invalid_input");
  exact(o, action === "save_facts" ? ["action", "revision", "version", "patch"] : ["action", "revision", "version", "note"]);
  const revision = myText(o.revision, 64), version = myText(o.version, 64);
  if (!/^[a-f0-9]{64}$/.test(revision) || !/^[a-f0-9]{64}$/.test(version)) throw new ReviewFailure("invalid_input");
  if (action === "save_facts") {
    const patch = myObject(o.patch);
    if (!Object.keys(patch).length || Object.keys(patch).some(k => !(myseoulPatchFields as readonly string[]).includes(k))) throw new ReviewFailure("invalid_input");
    return { action, revision, version, patch: Object.fromEntries(Object.entries(patch).map(([k, v]) => {
      if (k !== 'periods') return [k, fieldValue(k, v)];
      const axes = myObject(v);
      if (!Object.keys(axes).length || Object.keys(axes).some(axis => !['application', 'operation'].includes(axis))) throw new ReviewFailure('invalid_input');
      const checked = fieldValue(k, { application: [], operation: [], ...axes }) as Record<string, unknown>;
      return [k, Object.fromEntries(Object.keys(axes).map(axis => [axis, checked[axis]]))];
    })) };
  }
  const note = myText(o.note, 4000).trim();
  if (!note) throw new ReviewFailure('invalid_input');
  return { action: 'exclude', revision, version, note };
}

const guidance: Record<string, string> = {
  description_missing: "공식 원문에서 프로그램 설명을 확인해 입력해 주세요.", target_missing: "명시된 참여 대상을 확인해 주세요.",
  application_actor_unknown: "개인이 신청 가능한지 원문 조건을 확인해 주세요.", delivery_mode_unknown: "실제 진행 방식과 장소를 확인해 주세요.", course_modes_unresolved: "과정별 온라인·현장 안내를 대조해 주세요.",
  activity_region_unknown: "실제 개최 장소와 주소를 확인해 주세요. 집결지나 운영기관 주소와 구분합니다.", online_residence_unknown: "온라인 참여자의 거주 지역 조건을 확인해 주세요.",
  category_unresolved: "주요 활동의 근거에 따라 프로그램 또는 행사를 확인해 주세요.", nationality_or_visa_unresolved: "명시된 체류·국적 자격을 보존하고 일본인 거주자의 해당 조건 충족 근거를 기록해 주세요.",
  application_period_unknown: "신청 시작일과 마감일을 확인해 입력해 주세요.", operation_period_unknown: "교육·행사의 날짜와 시작·종료 시각을 확인해 주세요. 집결 시각은 시작 시각과 구분합니다.",
  application_method_missing: "신청 방법을 확인해 주세요. 별도 신청 폼은 필수가 아닙니다.", fee_unknown: "수강료와 별도 비용을 확인해 주세요.", fee_components_unresolved: "복합 비용의 항목별 근거를 확인해 주세요. 금액을 임의 분할하지 않습니다.", application_state_unknown: "현재 신청 상태와 기간을 대조해 주세요.",
};
export function myseoulGuidance(code: string) {
  if (code.startsWith("source_change_conflict:")) return "새 원문과 이전 보완값이 다릅니다. 확인한 사실을 입력하고 저장해 주세요.";
  if (code.startsWith("source_fact_conflict:")) return `상단과 본문의 ${code.endsWith("application_method") ? "신청 방법" : code.endsWith("operation") ? "운영 일정" : code.endsWith("application") ? "신청 기간" : "해당 사실"}이 다릅니다. 원문을 대조하고 사용할 값을 입력해 주세요.`;
  return guidance[code] ?? "지원하지 않는 사유입니다. 원문과 계약을 확인하고 임의로 해소하지 마세요.";
}

// Must match myseoul_reason_fields in SQL. Unknown reasons stay read-only.
export function myseoulReasonFields(reason: string): string[] {
  const map: Record<string, string[]> = {
    description_missing: ['description'], target_missing: ['target','conditions','application_actor'],
    application_actor_unknown: ['application_actor','target','conditions'],
    delivery_mode_unknown: ['delivery_mode','activity_region','venue','activity_evidence'],
    course_modes_unresolved: ['delivery_mode','activity_region','venue','activity_evidence'],
    activity_region_unknown: ['delivery_mode','activity_region','venue','activity_evidence'],
    online_residence_unknown: ['residence_scope','residence','residence_evidence'],
    category_unresolved: ['public_category','purpose'], nationality_or_visa_unresolved: ['qualification_note'],
    application_period_unknown: ['periods','session_evidence'], operation_period_unknown: ['periods','session_evidence'],
    application_method_missing: ['application_methods','application_links'], fee_unknown: ['fees'], fee_components_unresolved: ['fees'],
    application_state_unknown: ['source_status','periods'],
    'source_fact_conflict:application_method': ['application_methods','application_links'],
    'source_fact_conflict:application': ['periods','session_evidence'], 'source_fact_conflict:operation': ['periods','session_evidence'],
    'source_fact_conflict:target': ['target','conditions'], 'source_fact_conflict:mode': ['delivery_mode','activity_evidence'],
    'source_fact_conflict:venue': ['venue','activity_region','activity_evidence'], 'source_fact_conflict:status': ['source_status','periods'],
    'source_fact_conflict:tuition': ['fees'], 'source_fact_conflict:admission': ['fees'],
    'source_fact_conflict:materials': ['fees'], 'source_fact_conflict:extra_fee': ['fees'],
  };
  if (["source_change_conflict:application", "source_change_conflict:operation"].includes(reason)) return ["periods"];
  if (reason.startsWith("source_change_conflict:")) { const field = reason.split(":")[1]; return (myseoulPatchFields as readonly string[]).includes(field) ? [field] : []; }
  return map[reason] ?? [];
}
