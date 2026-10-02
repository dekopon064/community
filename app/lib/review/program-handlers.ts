import { privateResponse } from "../auth/http";
import { isSameOriginPost } from "../auth/urls";
import { ReviewFailure } from "./contracts";
import { failure } from "./handlers";
import { programCommand } from "./program-contract";
import type { ProgramReviewStore } from "./program-store";
type Dependencies = { authorize: () => Promise<{ userId: string }>; store: () => ProgramReviewStore };

export async function programRequest(request: Request, id: string | null, deps: Dependencies) {
  try {
    // Required before configuration, client creation, and every DB operation.
    const { userId } = await deps.authorize();
    if (id !== null && !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(id)) throw new ReviewFailure("invalid_input");
    if (request.method === "GET") {
      if (id) return privateResponse(Response.json({ mode: "database", item: await deps.store().get(id) }));
      const offset = new URL(request.url).searchParams.get("offset") ?? "0";
      if (!/^\d{1,6}$/.test(offset)) throw new ReviewFailure("invalid_input");
      const items = await deps.store().list(Number(offset));
      return privateResponse(Response.json({ mode: "database", items, hasMore: items.length === 25 }));
    }
    if (!id || request.method !== "POST") throw new ReviewFailure("invalid_input");
    if (!isSameOriginPost(request)) return privateResponse(Response.json({ code: "wrong_origin" }, { status: 403 }));
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || Number(request.headers.get("content-length")) > 200000) throw new ReviewFailure("invalid_input");
    const reader = request.body?.getReader(); if (!reader) throw new ReviewFailure("invalid_input");
    const chunks: Uint8Array[] = []; let length = 0;
    while (true) { const { value, done } = await reader.read(); if (done) break;
      length += value.length; if (length > 200000) { await reader.cancel(); throw new ReviewFailure("invalid_input"); } chunks.push(value); }
    const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let input: unknown; try { input = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new ReviewFailure("invalid_input"); }
    const command = programCommand(input);
    return privateResponse(Response.json({ mode: "database", item: await deps.store().execute(id, command, userId) }));
  } catch (e) { return failure(e); }
}
