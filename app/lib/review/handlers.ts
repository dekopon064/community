import { AdminAccessError } from "../auth/admin-policy";
import { privateResponse } from "../auth/http";
import { isSameOriginPost } from "../auth/urls";
import { ReviewFailure } from "./contracts";
import type { ReviewKind, ReviewStore } from "./contracts";
import { validateCommand } from "./validation";

type Dependencies = { authorize: () => Promise<{ userId: string }>; store: () => ReviewStore };
function failure(error: unknown) {
  if (error instanceof AdminAccessError) {
    const status = error.status === "signed_out" ? 401 : error.status === "forbidden" ? 403 : 503;
    return privateResponse(Response.json({ code: error.status }, { status }));
  }
  const e = error instanceof ReviewFailure ? error : new ReviewFailure("unavailable");
  const status = e.code === "invalid_input" ? 422 : e.code === "not_found" ? 404 : ["conflict", "already_processed"].includes(e.code) ? 409 : 503;
  return privateResponse(Response.json({ code: e.code, fields: e.fields }, { status }));
}
export function reviewKind(value: string | null): ReviewKind {
  if (value === "facts" || value === "candidates") return value;
  throw new ReviewFailure("invalid_input");
}
export async function listReviews(request: Request, deps: Dependencies) {
  try {
    await deps.authorize();
    const kind = reviewKind(new URL(request.url).searchParams.get("kind"));
    const rawOffset = new URL(request.url).searchParams.get("offset") ?? "0";
    if (!/^\d{1,6}$/.test(rawOffset)) throw new ReviewFailure("invalid_input");
    const store = deps.store();
    const items = await store.list(kind, Number(rawOffset));
    return privateResponse(Response.json({ mode: store.mode, items, hasMore: items.length === 25 }));
  } catch (error) { return failure(error); }
}
export async function reviewDetail(request: Request, rawKind: string, id: string, deps: Dependencies) {
  try {
    // Even GET performs server authorization before store selection or data reads.
    const { userId } = await deps.authorize();
    const kind = reviewKind(rawKind);
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id)) throw new ReviewFailure("invalid_input");
    if (request.method === "GET") { const store = deps.store(); return privateResponse(Response.json({ mode: store.mode, item: await store.get(kind, id) })); }
    if (!isSameOriginPost(request)) return privateResponse(Response.json({ code: "wrong_origin" }, { status: 403 }));
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") throw new ReviewFailure("invalid_input");
    const declaredLength = Number(request.headers.get("content-length"));
    if (declaredLength > 2 * 1024 * 1024) throw new ReviewFailure("invalid_input");
    // Bounded streaming read: do not buffer unbounded input before rejecting it.
    const reader = request.body?.getReader();
    if (!reader) throw new ReviewFailure("invalid_input");
    const chunks: Uint8Array[] = []; let length = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 2 * 1024 * 1024) { await reader.cancel(); throw new ReviewFailure("invalid_input"); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let body: unknown;
    try { body = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new ReviewFailure("invalid_input"); }
    const command = validateCommand(kind, body);
    const store = deps.store();
    const item = await store.execute(kind, id, command, userId);
    return privateResponse(Response.json({ mode: store.mode, item }));
  } catch (error) { return failure(error); }
}
