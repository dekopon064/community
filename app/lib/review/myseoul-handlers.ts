import { privateResponse } from "../auth/http";
import { isSameOriginPost } from "../auth/urls";
import { ReviewFailure } from "./contracts";
import { failure } from "./handlers";
import { myseoulCommand } from "./myseoul-contract";
import type { MySeoulReviewStore } from "./myseoul-store";
type Dependencies = { authorize: () => Promise<{ userId: string }>; store: () => MySeoulReviewStore };

export async function myseoulRequest(request: Request, id: string, deps: Dependencies) {
  try {
    const { userId } = await deps.authorize();
    if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(id)) throw new ReviewFailure("invalid_input");
    if (request.method === "GET") return privateResponse(Response.json({ mode: "database", item: await deps.store().get(id) }));
    if (request.method !== "POST") throw new ReviewFailure("invalid_input");
    if (!isSameOriginPost(request)) return privateResponse(Response.json({ code: "wrong_origin" }, { status: 403 }));
    if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json" || Number(request.headers.get("content-length")) > 200000) throw new ReviewFailure("invalid_input");
    const reader = request.body?.getReader(); if (!reader) throw new ReviewFailure("invalid_input");
    const chunks: Uint8Array[] = []; let length = 0;
    while (true) { const { value, done } = await reader.read(); if (done) break;
      length += value.length; if (length > 200000) { await reader.cancel(); throw new ReviewFailure("invalid_input"); } chunks.push(value); }
    const bytes = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let input: unknown; try { input = JSON.parse(new TextDecoder().decode(bytes)); } catch { throw new ReviewFailure("invalid_input"); }
    const command = myseoulCommand(input);
    return privateResponse(Response.json({ mode: "database", item: await deps.store().execute(id, command, userId) }));
  } catch (e) { return failure(e); }
}
