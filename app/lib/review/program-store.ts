import { filterInfo } from './content-filter-store';
import { ReviewFailure } from "./contracts";
import type { RpcClient } from "./database-store";
import { patchFields, programFacts, programReasonText, strings } from "./program-contract";
import type { ProgramCommand } from "./program-contract";

function obj(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ReviewFailure("unavailable");
  return value as Record<string, unknown>;
}
function str(x: unknown, max = 60000) { if (typeof x !== "string" || x.length > max) throw new ReviewFailure("unavailable"); return x; }
export function programItem(data: unknown, id: string) {
  try {
    const o = obj(data), source = obj(o.source), result = obj(o.result);
    if (o.id !== id || !/^[a-f0-9]{64}$/.test(str(o.revision)) || !/^[a-f0-9]{64}$/.test(str(o.version)) || o.schema !== "program-scope-v1-local" || o.profile !== "program_capital_v1_local") throw new ReviewFailure("unavailable");
    if (!Number.isSafeInteger(o.factsVersion) || (o.factsVersion as number) < 1 || source.name !== "seoul_reservation") throw new ReviewFailure("unavailable");
    const editable = strings(o.editableFields);
    if (editable.some((k) => !(patchFields as readonly string[]).includes(k)) || !["target", "non_target", "observe_only"].includes(str(result.disposition))) throw new ReviewFailure("unavailable");
    if (!["open", "resolved", "excluded"].includes(str(o.status)) || !["blocked", "queued", "claimed", "completed", "failed", "cancelled"].includes(str(o.aiStatus))) throw new ReviewFailure("unavailable");
    const reasons = strings(result.reasons);
    if (!["in_scope", "out_of_scope", "review_required", "not_currently_available"].includes(str(result.decision))) throw new ReviewFailure("unavailable");
    if (!Array.isArray(o.history) || o.history.length > 25) throw new ReviewFailure("unavailable");
    const history = o.history.map((x) => { const h = obj(x); return { action: str(h.action, 30), actor: str(h.actor, 36), at: str(h.at, 100), note: str(h.note, 4000), fields: strings(h.fields) }; });
    return { id, filterInfo: filterInfo(o.filterInfo, String(o.revision)), revision: str(o.revision), version: str(o.version), schema: str(o.schema), profile: str(o.profile),
      factsVersion: o.factsVersion, source: { name: str(source.name), title: str(source.title), url: source.url === null ? null : str(source.url), body: str(source.body) },
      facts: programFacts(o.facts), observedFacts: programFacts(o.observedFacts), status: str(o.status), aiStatus: str(o.aiStatus),
      result: { decision: str(result.decision), disposition: str(result.disposition), reasons },
      reasonGuidance: reasons.map((code) => ({ code, text: programReasonText[code] ?? "지원하지 않는 사유입니다. 원문과 계약을 확인하고 임의로 해소하지 마세요." })),
      restoredReviewPending: o.restoredReviewPending === true, editableFields: editable, history };
  } catch { throw new ReviewFailure("unavailable"); }
}
export class ProgramReviewStore {
  constructor(privateClient: RpcClient) { this.client = privateClient; }
  private client: RpcClient;
  private async invoke(name: string, args: Record<string, unknown>) {
    try {
      const { data, error } = await this.client.rpc(name, args);
      if (error) throw new ReviewFailure(error.code === "PT409" ? "conflict" : error.code === "PT422" ? "invalid_input" : error.code === "PT404" ? "not_found" : "unavailable");
      if (data === null || data === undefined) throw new ReviewFailure("unavailable");
      return data;
    } catch (e) { if (e instanceof ReviewFailure) throw e; throw new ReviewFailure("unavailable"); }
  }
  async list(offset: number) {
    const rows = await this.invoke("admin_program_list", { p_offset: offset, p_limit: 25 });
    if (!Array.isArray(rows) || rows.length > 25) throw new ReviewFailure("unavailable");
    return rows.map((row) => { const r = obj(row); return { id: str(r.id, 36), title: str(r.title), reasons: strings(r.reasons) }; });
  }
  async get(id: string) { return programItem(await this.invoke("admin_program_detail", { p_id: id }), id); }
  async execute(id: string, command: ProgramCommand, actor: string) {
    const args: Record<string, unknown> = { p_id: id, p_revision: command.revision, p_version: command.version, p_note: command.note, p_actor: actor };
    if (command.action === "save_facts") { args.p_patch = command.patch; args.p_resolve = command.resolve; }
    return programItem(await this.invoke(command.action === "save_facts" ? command.confirmRestored ? "admin_program_save_restored" : "admin_program_save" : "admin_program_exclude", args), id);
  }
}
