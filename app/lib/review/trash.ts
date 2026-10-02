import { ReviewFailure } from "./contracts";
import type { RpcClient } from "./database-store";
import { databaseItem } from "./database-dto";
import { programItem } from "./program-store";

export const quickReasons = { service_not_suitable: "서비스에 적합하지 않음", region_not_suitable: "대상 지역이 아님" } as const;
export type QuickReason = keyof typeof quickReasons;
export type TrashItem = { id: string; sourceItemId: string; revision: string; version: string; sourceName: string; title: string; reasonCode: QuickReason | "custom"; note: string; excludedAt: string; expiresAt: string; canRestore: boolean; blockReason: string | null };
export type TrashList = { serverNow: string; items: TrashItem[] };
export type TrashCommand =
  | { action: "exclude"; id: string; revision: string; version: string; requestId: string; reasonCode: QuickReason | "custom"; note: string }
  | { action: "restore"; episodeId: string; revision: string; version: string; requestId: string };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const digest = /^[a-f0-9]{64}$/;
function obj(v: unknown) { if (!v || typeof v !== "object" || Array.isArray(v)) throw new ReviewFailure("unavailable"); return v as Record<string, unknown>; }
function str(v: unknown, max = 60000) { if (typeof v !== "string" || v.length > max) throw new ReviewFailure("unavailable"); return v; }
function date(v: unknown) { const s = str(v, 100); if (!Number.isFinite(Date.parse(s))) throw new ReviewFailure("unavailable"); return s; }
export function trashCommand(input: unknown): TrashCommand {
  try {
    const v = obj(input);
    const keys = v.action === "exclude" ? ["action", "id", "revision", "version", "requestId", "reasonCode", "note"] : ["action", "episodeId", "revision", "version", "requestId"];
    if (!["exclude", "restore"].includes(String(v.action)) || Object.keys(v).length !== keys.length || Object.keys(v).some(k => !keys.includes(k)) || !uuid.test(str(v.requestId, 36)) || !digest.test(str(v.revision, 64)) || !digest.test(str(v.version, 64))) throw new ReviewFailure("invalid_input");
    const pre = { revision: String(v.revision), version: String(v.version), requestId: String(v.requestId) };
    if (v.action === "restore") {
      if (!uuid.test(str(v.episodeId, 36))) throw new ReviewFailure("invalid_input");
      return { ...pre, action: "restore", episodeId: String(v.episodeId) };
    }
    const note = str(v.note, 4000).trim();
    if (!uuid.test(str(v.id, 36)) || ![...Object.keys(quickReasons), "custom"].includes(String(v.reasonCode)) || (v.reasonCode === "custom" ? !note : note !== "")) throw new ReviewFailure("invalid_input");
    return { ...pre, action: "exclude", id: String(v.id), reasonCode: v.reasonCode as QuickReason | "custom", note };
  } catch { throw new ReviewFailure("invalid_input"); }
}
export function trashList(input: unknown): TrashList {
  const v = obj(input); const serverNow = date(v.serverNow);
  if (!Array.isArray(v.items) || v.items.length > 25) throw new ReviewFailure("unavailable");
  const items = v.items.map(value => {
    const e = obj(value);
    for (const k of ["id", "sourceItemId"]) if (!uuid.test(str(e[k], 36))) throw new ReviewFailure("unavailable");
    for (const k of ["revision", "version"]) if (!digest.test(str(e[k], 64))) throw new ReviewFailure("unavailable");
    if (typeof e.canRestore !== "boolean" || ![...Object.keys(quickReasons), "custom"].includes(str(e.reasonCode, 40))) throw new ReviewFailure("unavailable");
    const blockReason = e.blockReason === null ? null : str(e.blockReason, 40);
    if (blockReason !== null && !["source_missing", "source_changed", "processing_active", "already_published", "state_changed"].includes(blockReason) || e.canRestore !== (blockReason === null)) throw new ReviewFailure("unavailable");
    const excludedAt = date(e.excludedAt), expiresAt = date(e.expiresAt);
    if (Date.parse(expiresAt) - Date.parse(excludedAt) !== 72 * 3600000) throw new ReviewFailure("unavailable");
    return { id: String(e.id), sourceItemId: String(e.sourceItemId), revision: String(e.revision), version: String(e.version), sourceName: str(e.sourceName, 100), title: str(e.title), reasonCode: e.reasonCode as TrashItem["reasonCode"], note: str(e.note, 4000), excludedAt, expiresAt, canRestore: e.canRestore, blockReason };
  });
  return { serverNow, items };
}
const errorMap: Record<string, ConstructorParameters<typeof ReviewFailure>[0]> = {
  review_conflict: "conflict", review_already_processed: "already_processed", review_invalid_input: "invalid_input", review_not_found: "not_found",
  trash_expired: "trash_expired", trash_source_changed: "trash_source_changed", trash_processing_active: "trash_processing_active", trash_already_published: "trash_already_published",
};
export class TrashStore {
  private client: RpcClient;
  constructor(client: RpcClient) { this.client = client; }
  private async invoke(name: string, args: Record<string, unknown>) {
    try {
      const { data, error } = await this.client.rpc(name, args);
      if (error) throw new ReviewFailure(errorMap[error.message ?? ""] ?? (error.code === "PT409" ? "conflict" : error.code === "PT422" ? "invalid_input" : error.code === "PT404" ? "not_found" : "unavailable"));
      if (data == null) throw new ReviewFailure("unavailable"); return data;
    } catch (e) { if (e instanceof ReviewFailure) throw e; throw new ReviewFailure("unavailable"); }
  }
  async list(offset: number) { return trashList(await this.invoke("admin_review_trash", { p_offset: offset, p_limit: 25 })); }
  async execute(command: TrashCommand, actor: string) {
    const args: Record<string, unknown> = { p_revision: command.revision, p_version: command.version, p_actor: actor, p_request: command.requestId };
    if (command.action === "exclude") Object.assign(args, { p_id: command.id, p_reason: command.reasonCode, p_note: command.note });
    else args.p_episode = command.episodeId;
    const v = obj(await this.invoke(command.action === "exclude" ? "admin_review_exclude_reason" : "admin_review_restore", args));
    const raw = obj(v.item), source = obj(raw.source); const id = str(raw.id, 36);
    if (!uuid.test(str(v.episodeId, 36)) || !uuid.test(id) || command.action === "exclude" && id !== command.id) throw new ReviewFailure("unavailable");
    const item = source.name === "seoul_reservation" ? programItem(raw, id) : databaseItem(raw, "facts", id);
    if (command.action === "exclude") return { episodeId: String(v.episodeId), expiresAt: date(v.expiresAt), item };
    if (v.sourceItemId !== id || v.sourceName !== source.name) throw new ReviewFailure("unavailable");
    return { episodeId: String(v.episodeId), sourceItemId: id, sourceName: String(source.name), item };
  }
}
