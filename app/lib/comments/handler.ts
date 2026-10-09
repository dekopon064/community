import type { SupabaseClient } from "@supabase/supabase-js";
import type { AdminAccess } from "../auth/admin-policy";
import { privateResponse } from "../auth/http";
import { verifiedAccount } from "../auth/profile";
import { isSameOriginPost } from "../auth/urls";
import { COMMENT_UUID, RESIDENT_CODE, commentPage, normalizeComment, validComment, validCursor } from "./contracts";

type Dependencies = {
  client: () => Promise<SupabaseClient | null>;
  admin: () => Promise<AdminAccess>;
  authorize: () => Promise<{ userId: string }>;
  service: () => Pick<SupabaseClient, "rpc">;
};
const reply = (data: unknown, status = 200) => privateResponse(Response.json(data, { status }));
const failure = (code?: string) => {
  const errors: Record<string, [string, number]> = { PT404: ["information_unavailable", 404], PT401: ["authentication_required", 401], PT403: ["forbidden", 403], PT409: ["request_conflict", 409], PT429: ["rate_limited", 429], PT428: ["identity_changed", 409], "22023": ["invalid_request", 400] };
  const [error, status] = errors[code ?? ""] ?? ["unavailable", 503];
  return reply({ error }, status);
};
export async function commentRequest(request: Request, dependencies: Dependencies): Promise<Response> {
  const url = new URL(request.url), read = request.method === "GET";
  if (!read && (request.method !== "POST" || !isSameOriginPost(request))) return reply({ error: "forbidden" }, 403);
  let input: Record<string, unknown>;
  if (read) {
    if ([...url.searchParams.keys()].some(k => !["id", "at", "beforeId", "requestId"].includes(k)) || [...url.searchParams.keys()].some(k => url.searchParams.getAll(k).length !== 1)) return reply({ error: "invalid_request" }, 400);
    input = Object.fromEntries(url.searchParams);
  } else {
    if (url.search || !/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")) return reply({ error: "invalid_request" }, 400);
    try {
      // Bound the actual stream, not only an optional Content-Length header.
      const reader = request.body?.getReader(); if (!reader) return reply({ error: "invalid_request" }, 400);
      const chunks: Uint8Array[] = []; let size = 0;
      for (;;) { const result = await reader.read(); if (result.done) break; size += result.value.byteLength; if (size > 8192) { await reader.cancel(); return reply({ error: "invalid_request" }, 413); } chunks.push(result.value); }
      const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      input = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
      if (!input || typeof input !== "object" || Array.isArray(input)) return reply({ error: "invalid_request" }, 400);
    } catch { return reply({ error: "invalid_request" }, 400); }
  }
  if (typeof input.id !== "string" || !COMMENT_UUID.test(input.id)) return reply({ error: "invalid_request" }, 400);
  const id = input.id.toLowerCase();
  const action = read ? (input.requestId ? "status" : "list") : input.action;
  const keys: Record<string, string[]> = { list: ["id", "at", "beforeId"], status: ["id", "requestId"], prepare: ["id", "action"], create: ["id", "action", "requestId", "body", "expectedCode"], remove: ["id", "action", "commentId"], hide: ["id", "action", "commentId"] };
  if (typeof action !== "string" || !Object.hasOwn(keys, action) || Object.keys(input).some(k => !keys[action].includes(k))) return reply({ error: "invalid_request" }, 400);
  if (action === "list" && ((input.at !== undefined || input.beforeId !== undefined) && !validCursor(input.at, input.beforeId))) return reply({ error: "invalid_request" }, 400);
  if (["status", "create"].includes(action) && (typeof input.requestId !== "string" || !COMMENT_UUID.test(input.requestId))) return reply({ error: "invalid_request" }, 400);
  if (["remove", "hide"].includes(action) && (typeof input.commentId !== "string" || !COMMENT_UUID.test(input.commentId))) return reply({ error: "invalid_request" }, 400);
  if (action === "create" && (!validComment(input.body) || typeof input.expectedCode !== "string" || !RESIDENT_CODE.test(input.expectedCode))) return reply({ error: "invalid_request" }, 400);
  try {
    const client = await dependencies.client();
    const account = await verifiedAccount(client);
    if (!client || account.status === "unavailable") return reply({ error: "unavailable" }, 503);
    if (action !== "list" && !account.user) return reply({ error: "authentication_required" }, 401);
    if (action === "list") {
      const { data, error } = await client.rpc("list_information_comments", { p_curation_id: id, p_before_at: input.at ?? null, p_before_id: input.beforeId ?? null });
      if (error) return failure(error.code);
      const access = account.user ? await dependencies.admin() : null;
      return reply(commentPage(data, !!account.user, access?.status === "admin" && access.userId === account.user?.id));
    }
    let rpcClient: Pick<SupabaseClient, "rpc"> = client;
    let name: string, args: Record<string, unknown> = { p_curation_id: id };
    if (action === "hide") {
      const actor = await dependencies.authorize();
      if (actor.userId !== account.user?.id) return reply({ error: "forbidden" }, 403);
      rpcClient = dependencies.service(); name = "admin_hide_information_comment";
      args = { ...args, p_comment_id: input.commentId, p_actor: actor.userId };
    } else if (action === "prepare") name = "prepare_comment_resident";
    else if (action === "create") { name = "create_information_comment"; args = { ...args, p_request_id: input.requestId, p_body: normalizeComment(input.body as string), p_expected_code: input.expectedCode }; }
    else if (action === "remove") { name = "remove_information_comment"; args = { ...args, p_comment_id: input.commentId }; }
    else { name = "information_comment_request_state"; args = { ...args, p_request_id: input.requestId }; }
    const { data, error } = await rpcClient.rpc(name, args);
    if (error) return failure(error.code);
    if (action === "prepare") {
      if (typeof data?.code !== "string" || !RESIDENT_CODE.test(data.code)) throw new Error("invalid_comment_response");
      return reply({ code: data.code });
    }
    if (action === "create" || action === "status") {
      if (action === "status" && data?.outcome === "absent") return reply({ outcome: "absent" });
      if (data?.outcome !== "accepted" || typeof data.commentId !== "string" || !COMMENT_UUID.test(data.commentId) || !["live", "deleted", "hidden"].includes(data.state)) throw new Error("invalid_comment_response");
      return reply({ outcome: "accepted", commentId: data.commentId, state: data.state });
    }
    if (data?.outcome !== (action === "remove" ? "deleted" : "hidden")) throw new Error("invalid_comment_response");
    return reply({ outcome: data.outcome });
  } catch (error) {
    // Do not expose SQL messages, profiles, or privileged adapter diagnostics.
    const status = (error as { status?: string })?.status;
    return status === "forbidden" || status === "signed_out" ? reply({ error: status === "signed_out" ? "authentication_required" : "forbidden" }, status === "signed_out" ? 401 : 403) : reply({ error: "unavailable" }, 503);
  }
}
