import { privateResponse } from "../auth/http";
import { isSameOriginPost } from "../auth/urls";
import { ReviewFailure } from "./contracts";
import { failure } from "./handlers";
import { dismissCommand, trashCommand } from "./trash";
import type { TrashStore } from "./trash";
type Dependencies = { authorize: () => Promise<{ userId: string }>; store: () => Pick<TrashStore, "list" | "execute"> & Partial<Pick<TrashStore, "preview" | "dismiss">> };
export async function trashRequest(request: Request, deps: Dependencies) {
  try {
    const { userId } = await deps.authorize();
    if (request.method === "GET") {
      if (new URL(request.url).searchParams.get("preview") === "dismiss") {
        const store = deps.store();
        if (!store.preview) throw new ReviewFailure("unavailable");
        return privateResponse(Response.json({ mode: "database", ...await store.preview() }));
      }
      const offset = new URL(request.url).searchParams.get("offset") ?? "0";
      if (!/^\d{1,6}$/.test(offset)) throw new ReviewFailure("invalid_input");
      const list = await deps.store().list(Number(offset));
      return privateResponse(Response.json({ mode: "database", ...list, hasMore: list.items.length === 25 }));
    }
    if (!isSameOriginPost(request)) return privateResponse(Response.json({ code: "wrong_origin" }, { status: 403 }));
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || Number(request.headers.get("content-length")) > 20000) throw new ReviewFailure("invalid_input");
    const reader = request.body?.getReader(); if (!reader) throw new ReviewFailure("invalid_input");
    const chunks: Uint8Array[] = []; let size = 0;
    while (true) { const { done, value } = await reader.read(); if (done) break; size += value.length; if (size > 20000) { await reader.cancel(); throw new ReviewFailure("invalid_input"); } chunks.push(value); }
    const bytes = new Uint8Array(size); let pos = 0; for (const c of chunks) { bytes.set(c, pos); pos += c.length; }
    let input: unknown; try { input = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new ReviewFailure("invalid_input"); }
    if (input && typeof input === "object" && "action" in input && ["dismiss", "empty"].includes(String(input.action))) {
      const command = dismissCommand(input), store = deps.store();
      if (!store.dismiss) throw new ReviewFailure("unavailable");
      return privateResponse(Response.json({ mode: "database", ...await store.dismiss(command, userId) }));
    }
    const command = trashCommand(input);
    return privateResponse(Response.json({ mode: "database", ...await deps.store().execute(command, userId) }));
  } catch (e) { return failure(e); }
}
