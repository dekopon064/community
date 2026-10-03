import { ReviewFailure } from "./contracts";
import type { ReviewStore, ReviewKind, ReviewItem, ReviewCommand, ListItem } from "./contracts";
import { databaseItem, databaseList } from "./database-dto";

export type RpcClient = { rpc: (name: string, args: Record<string, unknown>) => PromiseLike<{ data: unknown; error: { code?: string; message?: string } | null }> };
const errors: Record<string, "conflict" | "already_processed" | "invalid_input" | "not_found" | "publish_failed" | "program_input_changed" | "program_unavailable"> = {
  program_candidate_input_changed: "program_input_changed", program_candidate_unavailable: "program_unavailable",
  review_conflict: "conflict", review_already_processed: "already_processed", review_invalid_input: "invalid_input", review_not_found: "not_found", review_publish_failed: "publish_failed",
};
export class DatabaseReviewStore implements ReviewStore {
  readonly mode = "database" as const;
  private client: RpcClient;
  constructor(client: RpcClient) { this.client = client; }
  private async invoke(name: string, args: Record<string, unknown>) {
    try {
      const { data, error } = await this.client.rpc(name, args);
      if (error) throw new ReviewFailure(errors[error.message ?? ""] ?? "unavailable");
      if (data === null || data === undefined) throw new ReviewFailure("unavailable");
      return data;
    } catch (e) { if (e instanceof ReviewFailure) throw e; throw new ReviewFailure("unavailable"); }
  }
  async list(kind: ReviewKind, offset = 0): Promise<ListItem[]> {
    const data = await this.invoke("admin_review_list", { p_kind: kind, p_offset: offset, p_limit: 25 });
    return databaseList(data);
  }
  async get(kind: ReviewKind, id: string): Promise<ReviewItem> {
    return this.item(await this.invoke("admin_review_detail", { p_kind: kind, p_id: id }), kind, id);
  }
  private item(data: unknown, kind: ReviewKind, id: string): ReviewItem {
    return databaseItem(data, kind, id);
  }
  async execute(kind: ReviewKind, id: string, command: ReviewCommand, actor: string): Promise<ReviewItem> {
    if ((kind === "facts") !== ["save_facts", "exclude"].includes(command.action)) throw new ReviewFailure("invalid_input");
    const args: Record<string, unknown> = { p_id: id, p_revision: command.revision, p_version: command.version, p_actor: actor };
    const names = { save_facts: "admin_review_save_facts", exclude: "admin_review_exclude", save_candidate: "admin_review_save_candidate", review_change: "admin_myseoul_review_change", publish: "admin_review_publish", reject: "admin_review_reject" };
    if (command.action === "save_facts") args.p_facts = command.facts;
    if (command.action === "save_candidate") { args.p_content = command.content; if (command.imageSelection) args.p_image = command.imageSelection; }
    if (command.action === "review_change") { args.p_disposition = command.disposition; args.p_content = command.content ?? null; }
    if ("note" in command) args.p_note = command.note;
    return this.item(await this.invoke(command.action === "save_candidate" && command.imageSelection ? "admin_myseoul_save_candidate_image" : command.action === "save_facts" && command.confirmRestored ? "admin_review_save_restored" : names[command.action], args), kind, id);
  }
}
